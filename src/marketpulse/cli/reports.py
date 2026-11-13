"""Composable, offline, machine-readable reports over saved data."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

import click

from . import (
    report_catalog,
    report_derive,
    report_filters,
    report_formats,
    report_history,
    report_interface,
    report_ledger,
    report_output,
    report_portfolio,
    report_reference,
    report_system,
)
from .base import App, pass_app
from .root import main

# Each module owns its adapters: SOURCES (ordered field schemas), DESCRIPTIONS, GROUP and load_source.
SOURCE_MODULES = (
    report_portfolio,
    report_catalog,
    report_ledger,
    report_system,
    report_reference,
    report_history,
    report_interface,
)
SOURCES: dict[str, tuple[str, ...]] = {
    name: schema for module in SOURCE_MODULES for name, schema in module.SOURCES.items()
}
FORMATS = ("json", "jsonl", "csv", "tsv", "markdown", *report_formats.FORMATS)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _fields(value: str | None, schema: tuple[str, ...]) -> list[str]:
    if value is None:
        return []
    fields = [field.strip() for field in value.split(",")]
    if len(set(fields)) != len(fields) or any(field not in schema for field in fields):
        raise click.UsageError(f"Choose distinct fields from: {', '.join(schema)}.")
    return fields


def _condition(value: str, schema: tuple[str, ...]) -> tuple[str, str]:
    field, separator, text = value.partition("=")
    if not separator or field not in schema:
        raise click.UsageError(f"Use FIELD=VALUE with a field from: {', '.join(schema)}.")
    return field, text


def load_source(source: str, app: App) -> list[dict[str, Any]]:
    for module in SOURCE_MODULES:
        if source in module.SOURCES:
            return module.load_source(source, app)
    raise KeyError(source)


def _row_key(row: dict[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(json.dumps(row[field], sort_keys=True, ensure_ascii=False) for field in fields)


def _serialize(rows: list[dict[str, Any]], fields: list[str], output_format: str, envelope: dict | None) -> str:
    if output_format in report_formats.FORMATS:
        return report_formats.serialize(rows, fields, output_format)
    if output_format == "json":
        return (
            json.dumps(
                {**envelope, "rows": rows} if envelope is not None else rows, ensure_ascii=False, allow_nan=False
            )
            + "\n"
        )
    if output_format == "jsonl":
        return "".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows)
    if output_format in ("csv", "tsv"):
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, delimiter="\t" if output_format == "tsv" else ",", lineterminator="\r\n")
        writer.writerow(fields)
        writer.writerows([_text(row[field]) for field in fields] for row in rows)
        return stream.getvalue()

    def escape(value: Any) -> str:
        return (
            _text(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("|", "&#124;")
            .replace("\r", "&#13;")
            .replace("\n", "<br>")
        )

    return (
        "\n".join(
            [
                "| " + " | ".join(fields) + " |",
                "| " + " | ".join("---" for _ in fields) + " |",
                *("| " + " | ".join(escape(row[field]) for field in fields) + " |" for row in rows),
            ]
        )
        + "\n"
    )


def _emit(text: str, output: Path | None) -> None:
    if output is None:
        # Script output is raw: without color=True, Click drops escape sequences when stdout is a pipe.
        click.echo(text, nl=False, color=True)
        return
    # Publish a complete file without replacing an existing destination, including symlinks.
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=output.parent, delete=False
        ) as stream:
            temporary = stream.name
            stream.write(text)
        os.link(temporary, output)
    except (OSError, UnicodeEncodeError) as exc:
        raise click.ClickException(f"Cannot write report: {exc}") from exc
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)


# The option groups share a pipeline; their implementation modules do not open data sources.
FILTER_HELP = {
    "ieq": "Keep FIELD=TEXT equality matches, ignoring case.",
    "ine": "Exclude FIELD=TEXT equality matches, ignoring case.",
    "not_contains": "Exclude FIELD=TEXT substring matches, ignoring case.",
    "not_prefix": "Exclude FIELD=TEXT prefix matches, ignoring case.",
    "not_suffix": "Exclude FIELD=TEXT suffix matches, ignoring case.",
    "gt": "Keep numeric FIELD=VALUE strictly greater than VALUE.",
    "ge": "Keep numeric FIELD=VALUE greater than or equal to VALUE.",
    "lt": "Keep numeric FIELD=VALUE strictly less than VALUE.",
    "le": "Keep numeric FIELD=VALUE less than or equal to VALUE.",
    "between": "Keep numeric FIELD=LOW,HIGH inside inclusive bounds.",
    "outside": "Keep numeric FIELD=LOW,HIGH outside inclusive bounds.",
    "in_values": "Keep typed FIELD=JSON_ARRAY membership matches.",
    "not_in": "Exclude typed FIELD=JSON_ARRAY membership matches.",
    "empty": "Keep empty FIELD values (null, empty string, array or object).",
    "nonempty": "Keep nonempty FIELD values; zero and false are nonempty.",
    "is_type": "Keep FIELD=TYPE (string, number, boolean, array, object, null).",
    "length": "Keep string/array/object FIELD=N with exactly N elements.",
    "min_length": "Keep string/array/object FIELD=N with at least N elements.",
    "max_length": "Keep string/array/object FIELD=N with at most N elements.",
    "glob": "Keep case-sensitive FIELD=PATTERN shell wildcard matches.",
}
EXPANSION_FILTER_HELP = {
    "regex": "Keep FIELD=PATTERN regular expression matches anywhere in the text.",
    "not_regex": "Exclude FIELD=PATTERN regular expression matches.",
    "iglob": "Keep FIELD=PATTERN shell wildcard matches, ignoring case.",
    "not_glob": "Exclude case-sensitive FIELD=PATTERN shell wildcard matches.",
    "contains_any": "Keep FIELD=JSON_ARRAY rows containing any listed text, ignoring case.",
    "contains_all": "Keep FIELD=JSON_ARRAY rows containing every listed text, ignoring case.",
    "date_from": "Keep FIELD=YYYY-MM-DD dates on or after the day.",
    "date_to": "Keep FIELD=YYYY-MM-DD dates on or before the day.",
    "has_item": "Keep array FIELD=JSON values containing the typed item.",
    "has_key": "Keep object FIELD=KEY values containing the key.",
}
# Every FIELD=VALUE filter shared by `report` and `summarize`, in option order.
ROW_FILTER_HELP = {**FILTER_HELP, **EXPANSION_FILTER_HELP}
OUTPUT_HELP = {
    "lower": "Lowercase string FIELD for output.",
    "upper": "Uppercase string FIELD for output.",
    "strip": "Strip whitespace from both ends of string FIELD.",
    "lstrip": "Strip leading whitespace from string FIELD.",
    "rstrip": "Strip trailing whitespace from string FIELD.",
    "replace": 'Replace in string FIELD=["old","new"] (JSON array).',
    "fill": "Replace null FIELD=JSON values for output.",
    "null_if": "Replace typed FIELD=JSON matches with null for output.",
    "stringify": "Convert FIELD to report text for output (null becomes empty).",
    "encode_json": "Serialize FIELD to a JSON string for output.",
    "decode_json": "Parse JSON strings in FIELD for output; invalid JSON is an error.",
    "length_of": "Replace FIELD with its string/array/object length, otherwise null.",
    "round_values": "Round numeric FIELD=DIGITS (0–15) for output only.",
    "rename": "Rename output FIELD=NAME; aliases apply simultaneously.",
    "constant": "Append output NAME=JSON constant column.",
}


def _advanced_options(command):
    specs = {**ROW_FILTER_HELP, **OUTPUT_HELP}
    for name, help_text in reversed(tuple(specs.items())):
        spelling = {"in_values": "in", "round_values": "round"}.get(name, name.replace("_", "-"))
        command = click.option("--" + spelling, name, multiple=True, help=help_text)(command)
    command = click.option("--sort-ci", multiple=True, help="Sort by FIELD ignoring case; repeat for tie breakers.")(
        command
    )
    command = click.option("--reverse-rows", is_flag=True, help="Reverse rows after sorting.")(command)
    command = click.option("--tail", type=click.IntRange(min=1), help="Keep the last N rows before pagination.")(
        command
    )
    command = click.option(
        "--every", type=click.IntRange(min=1), default=1, help="Keep every Nth row before pagination."
    )(command)
    command = click.option("--row-number", help="Append a NAME column with 1-based positions before pagination.")(
        command
    )
    command = click.option(
        "--duplicates", multiple=True, help="Keep rows whose FIELD tuple occurs more than once; repeat for more keys."
    )(command)
    command = click.option(
        "--singletons", multiple=True, help="Keep rows whose FIELD tuple occurs exactly once; repeat for more keys."
    )(command)
    return click.option(
        "--unique-last", multiple=True, help="Keep the last row per FIELD tuple; repeat for more keys."
    )(command)


@main.command("report")
@_advanced_options
@click.argument("source", type=click.Choice(sorted(SOURCES)), metavar="SOURCE")
@click.option(
    "--derive",
    multiple=True,
    help="Add a computed NAME=FUNCTION:FIELD[:ARGUMENT] column; list functions with `report derive-functions`.",
)
@click.option("--fields", help="Comma-separated columns to retain, in order.")
@click.option("--omit", help="Comma-separated columns to remove.")
@click.option("--where", multiple=True, help="Keep FIELD=VALUE exact matches; repeat for AND.")
@click.option("--not", "not_values", multiple=True, help="Exclude FIELD=VALUE exact matches.")
@click.option("--contains", multiple=True, help="Keep FIELD=TEXT substring matches, ignoring case.")
@click.option("--prefix", multiple=True, help="Keep FIELD=TEXT prefix matches, ignoring case.")
@click.option("--suffix", multiple=True, help="Keep FIELD=TEXT suffix matches, ignoring case.")
@click.option("--present", multiple=True, help="Keep rows whose FIELD is neither null nor an empty string.")
@click.option("--missing", multiple=True, help="Keep rows whose FIELD is null or an empty string.")
@click.option("--sort", multiple=True, help="Order by FIELD; repeat for tie breakers. Missing values stay last.")
@click.option("--descending", is_flag=True, help="Reverse the requested sort order.")
@click.option("--offset", type=click.IntRange(min=0), default=0, help="Skip N matching rows.")
@click.option("--limit", type=click.IntRange(min=1), help="Keep at most N rows.")
@click.option("--unique", multiple=True, help="Keep the first row per FIELD tuple; repeat for more keys.")
@click.option("--count", is_flag=True, help="Print the matching distinct row count, before pagination.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(FORMATS),
    default="json",
    show_default=True,
)
@click.option("--page-info", is_flag=True, help="Wrap JSON in rows, total, offset and limit metadata.")
@click.option("--describe", is_flag=True, help="Print the source's field schema without loading data.")
@click.option(
    "--output",
    type=click.Path(path_type=Path, dir_okay=False),
    help="Write atomically to a new UTF-8 file; never overwrite.",
)
@pass_app
def report(
    app: App,
    source,
    derive,
    fields,
    omit,
    where,
    not_values,
    contains,
    prefix,
    suffix,
    present,
    missing,
    sort,
    descending,
    offset,
    limit,
    unique,
    count,
    output_format,
    page_info,
    describe,
    output,
    **advanced,
) -> None:
    """Query saved datasets offline. Script output is raw and unmasked; configuration secrets stay redacted.

    Filters combine with AND; processing is derived columns, filter, keyed selection, sort, row windows,
    pagination, output transformations, projection, export. No quotes are fetched or snapshots recorded.
    List the datasets with `marketpulse report sources`.
    """
    # Derived columns join the schema first, so every later option can name them like source fields.
    derived = report_derive.DerivePlan(SOURCES[source], derive)
    schema = derived.schema
    filter_options = {name: advanced[name] for name in ROW_FILTER_HELP}
    matches = report_filters.compile_filters(schema, filter_options)
    output_options = {name: advanced[name] for name in (*OUTPUT_HELP, "row_number")}
    output_plan = report_output.OutputPlan(schema, output_options)
    selected = _fields(fields, output_plan.schema) or list(output_plan.schema)
    omitted = _fields(omit, output_plan.schema)
    if fields is not None and omit is not None:
        raise click.UsageError("Choose --fields or --omit.")
    selected = [field for field in selected if field not in omitted]
    if not selected:
        raise click.UsageError("At least one output field is required.")
    conditions = [
        [_condition(value, schema) for value in values] for values in (where, not_values, contains, prefix, suffix)
    ]
    sort_ci = advanced["sort_ci"]
    duplicates, singletons, unique_last = advanced["duplicates"], advanced["singletons"], advanced["unique_last"]
    for field in (*present, *missing, *sort, *sort_ci, *unique, *duplicates, *singletons, *unique_last):
        if field not in schema:
            raise click.UsageError(f"Unknown field '{field}'. Choose from: {', '.join(schema)}.")
    if duplicates and singletons:
        raise click.UsageError("Choose --duplicates or --singletons.")
    if unique and unique_last:
        raise click.UsageError("Choose --unique or --unique-last.")
    if sort and sort_ci:
        raise click.UsageError("Choose --sort or --sort-ci.")
    if descending and not (sort or sort_ci):
        raise click.UsageError("--descending requires --sort or --sort-ci.")
    if count and any(output_options.values()):
        raise click.UsageError("--count cannot combine with output transformations.")
    if page_info and (output_format != "json" or count):
        raise click.UsageError("--page-info requires JSON row output.")
    if count and (offset or limit is not None or fields is not None or omit is not None or output_format != "json"):
        raise click.UsageError("--count cannot combine with pagination, projection or alternate formats.")
    advanced_active = any(value != 1 if name == "every" else bool(value) for name, value in advanced.items())
    if describe:
        if advanced_active or any(
            (
                derive,
                fields is not None,
                omit is not None,
                where,
                not_values,
                contains,
                prefix,
                suffix,
                present,
                missing,
                sort,
                descending,
                offset,
                limit is not None,
                unique,
                count,
                output_format != "json",
                page_info,
            )
        ):
            raise click.UsageError("--describe cannot combine with report operations.")
        _emit(json.dumps({"source": source, "fields": list(schema)}) + "\n", output)
        return
    report_formats.validate(output_format, selected)
    if output is not None and os.path.lexists(output):
        raise click.UsageError("--output must name a new file; refusing to overwrite.")
    rows = derived.apply(load_source(source, app))
    exact, excluded, substrings, prefixes, suffixes = conditions
    rows = [
        row
        for row in rows
        if matches(row)
        and all(_text(row[field]) == value for field, value in exact)
        and all(_text(row[field]) != value for field, value in excluded)
        and all(value.casefold() in _text(row[field]).casefold() for field, value in substrings)
        and all(_text(row[field]).casefold().startswith(value.casefold()) for field, value in prefixes)
        and all(_text(row[field]).casefold().endswith(value.casefold()) for field, value in suffixes)
        and all(row[field] is not None and row[field] != "" for field in present)
        and all(row[field] is None or row[field] == "" for field in missing)
    ]
    if duplicates or singletons:
        keyed = duplicates or singletons
        occurrences: dict[tuple[str, ...], int] = {}
        for row in rows:
            key = _row_key(row, keyed)
            occurrences[key] = occurrences.get(key, 0) + 1
        rows = [row for row in rows if (occurrences[_row_key(row, keyed)] > 1) is bool(duplicates)]
    if unique:
        seen: set[tuple[str, ...]] = set()
        distinct = []
        for row in rows:
            key = _row_key(row, unique)
            if key not in seen:
                seen.add(key)
                distinct.append(row)
        rows = distinct
    if unique_last:
        # Each key keeps its final row, and the kept rows stay in source order.
        final = {_row_key(row, unique_last): position for position, row in enumerate(rows)}
        rows = [row for position, row in enumerate(rows) if final[_row_key(row, unique_last)] == position]
    for field in reversed(sort or sort_ci):
        # Nested values order by canonical JSON; keep numeric and missing groups fixed in both directions.
        rows.sort(
            key=lambda row: (
                0 if isinstance(row[field], (int, float)) else 1,
                row[field]
                if isinstance(row[field], (int, float))
                else (_text(row[field]).casefold() if sort_ci else _text(row[field])),
            ),
            reverse=descending,
        )
        rows.sort(key=lambda row: (row[field] is None or row[field] == "", not isinstance(row[field], (int, float))))
    if advanced["reverse_rows"]:
        rows = rows[::-1]
    if advanced["tail"] is not None:
        rows = rows[-advanced["tail"] :]
    rows = rows[:: advanced["every"]]
    total = len(rows)
    if count:
        _emit(str(total) + "\n", output)
        return
    rows = output_plan.apply(rows[offset:][:limit], start=offset)
    rows = [{field: row[field] for field in selected} for row in rows]
    envelope = {"source": source, "total": total, "offset": offset, "limit": limit} if page_info else None
    _emit(_serialize(rows, selected, output_format, envelope), output)
