"""Composable, offline, machine-readable reports over saved data."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import click

from . import report_catalog, report_portfolio
from .base import App, pass_app
from .root import main

SOURCES = {**report_portfolio.SOURCES, **report_catalog.SOURCES}


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
    module = report_portfolio if source in report_portfolio.SOURCES else report_catalog
    return module.load_source(source, app)


def _serialize(rows: list[dict[str, Any]], fields: list[str], output_format: str, envelope: dict | None) -> str:
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
        writer = csv.writer(stream, delimiter="\t" if output_format == "tsv" else ",", lineterminator="\n")
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
        click.echo(text, nl=False)
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
    except OSError as exc:
        raise click.ClickException(f"Cannot write report: {exc}") from exc
    finally:
        if temporary is not None:
            os.unlink(temporary)


@main.command("report")
@click.argument("source", type=click.Choice(sorted(SOURCES)))
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
    type=click.Choice(["json", "jsonl", "csv", "tsv", "markdown"]),
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
) -> None:
    """Query saved datasets offline. Script output is raw and unmasked; configuration secrets stay redacted.

    Filters combine with AND; processing is filter, unique, sort, pagination,
    projection, export. No quotes are fetched or snapshots recorded.
    """
    schema = SOURCES[source]
    selected = _fields(fields, schema) or list(schema)
    omitted = _fields(omit, schema)
    if fields is not None and omit is not None:
        raise click.UsageError("Choose --fields or --omit.")
    selected = [field for field in selected if field not in omitted]
    if not selected:
        raise click.UsageError("At least one output field is required.")
    conditions = [
        [_condition(value, schema) for value in values] for values in (where, not_values, contains, prefix, suffix)
    ]
    for field in (*present, *missing, *sort, *unique):
        if field not in schema:
            raise click.UsageError(f"Unknown field '{field}'. Choose from: {', '.join(schema)}.")
    if descending and not sort:
        raise click.UsageError("--descending requires --sort.")
    if page_info and (output_format != "json" or count):
        raise click.UsageError("--page-info requires JSON row output.")
    if count and (offset or limit is not None or fields is not None or omit is not None or output_format != "json"):
        raise click.UsageError("--count cannot combine with pagination, projection or alternate formats.")
    if describe:
        if any(
            (
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
    if output is not None and os.path.lexists(output):
        raise click.UsageError("--output must name a new file; refusing to overwrite.")
    rows = load_source(source, app)
    exact, excluded, substrings, prefixes, suffixes = conditions
    rows = [
        row
        for row in rows
        if all(_text(row[field]) == value for field, value in exact)
        and all(_text(row[field]) != value for field, value in excluded)
        and all(value.casefold() in _text(row[field]).casefold() for field, value in substrings)
        and all(_text(row[field]).casefold().startswith(value.casefold()) for field, value in prefixes)
        and all(_text(row[field]).casefold().endswith(value.casefold()) for field, value in suffixes)
        and all(row[field] is not None and row[field] != "" for field in present)
        and all(row[field] is None or row[field] == "" for field in missing)
    ]
    if unique:
        seen: set[tuple[str, ...]] = set()
        distinct = []
        for row in rows:
            key = tuple(json.dumps(row[field], sort_keys=True, ensure_ascii=False) for field in unique)
            if key not in seen:
                seen.add(key)
                distinct.append(row)
        rows = distinct
    for field in reversed(sort):
        # JSON schemas have fixed per-field types; nested values order by canonical JSON.
        rows.sort(
            key=lambda row: (
                0 if isinstance(row[field], (int, float)) else 1,
                row[field] if isinstance(row[field], (int, float)) else _text(row[field]),
            ),
            reverse=descending,
        )
        rows.sort(key=lambda row: row[field] is None or row[field] == "")
    total = len(rows)
    if count:
        _emit(str(total) + "\n", output)
        return
    rows = [{field: row[field] for field in selected} for row in rows[offset:][:limit]]
    envelope = {"source": source, "total": total, "offset": offset, "limit": limit} if page_info else None
    _emit(_serialize(rows, selected, output_format, envelope), output)
