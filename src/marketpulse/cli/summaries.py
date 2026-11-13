"""Grouped descriptive summaries over existing, read-only report sources."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import click

from . import report_derive, report_filters, report_formats, report_metrics, reports
from .base import App, pass_app
from .root import main


@dataclass(frozen=True)
class Metric:
    name: str
    operation: str
    field: str | None

    @property
    def numeric(self) -> bool:
        return self.operation not in {
            "first",
            "last",
            "first-present",
            "last-present",
            "mode",
            "values",
            "distinct-values",
            "text-min",
            "text-max",
            "date-min",
            "date-max",
            "value-counts",
            "repeated-values",
        }


def _metrics(values: tuple[str, ...], schema: tuple[str, ...], groups: tuple[str, ...]) -> list[Metric]:
    result = []
    names = set(groups)
    for value in values:
        name, separator, expression = value.partition("=")
        operation, colon, field = expression.partition(":")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise click.UsageError("--metric requires NAME=OP[:FIELD], with an ASCII identifier NAME.")
        if name in names:
            raise click.UsageError(f"Metric name '{name}' duplicates a metric or grouping field.")
        if operation not in report_metrics.ALL_OPERATIONS:
            raise click.UsageError(f"Unknown summary operation '{operation}'. Use --describe to list operations.")
        if operation == "count":
            if colon:
                raise click.UsageError("The count operation takes no field; use NAME=count.")
        elif not colon or field not in schema:
            raise click.UsageError(f"Operation '{operation}' requires a field from: {', '.join(schema)}.")
        names.add(name)
        result.append(Metric(name, operation, field if colon else None))
    return result


def _measure(rows: list[dict[str, Any]], metrics: list[Metric]) -> dict[str, Any]:
    return {
        metric.name: report_metrics.summarize_values(
            metric.operation, [row[metric.field] if metric.field is not None else None for row in rows]
        )
        for metric in metrics
    }


def _summarize(rows: list[dict[str, Any]], groups: tuple[str, ...], metrics: list[Metric]) -> list[dict[str, Any]]:
    buckets: dict[tuple, list[dict[str, Any]]] = {} if groups else {(): []}
    for row in rows:
        key = tuple(report_metrics._typed_key(row[field]) for field in groups)
        buckets.setdefault(key, []).append(row)
    return [
        {**{field: bucket[0][field] for field in groups}, **_measure(bucket, metrics)} for bucket in buckets.values()
    ]


def _having(values: tuple[str, ...], fields: tuple[str, ...]) -> report_filters.Predicate:
    """Compile ``FILTER:NAME=VALUE`` conditions on summary columns, combined with AND."""
    spellings = {("in" if name == "in_values" else name.replace("_", "-")): name for name in reports.ROW_FILTER_HELP}
    predicates = []
    for value in values:
        spelling, separator, condition = value.partition(":")
        if not separator or spelling not in spellings:
            raise click.UsageError(f"--having requires FILTER:NAME=VALUE with a filter from: {', '.join(spellings)}.")
        try:
            predicates.append(report_filters.compile_filters(fields, {spellings[spelling]: (condition,)}))
        except click.UsageError as exc:
            raise click.UsageError(f"--having {value}: {exc.message}") from exc
    return lambda row: all(predicate(row) for predicate in predicates)


def _sort(rows: list[dict[str, Any]], fields: tuple[str, ...], numeric: set[str], descending: bool) -> None:
    for field in reversed(fields):

        def key(row: dict[str, Any], field: str = field) -> tuple:
            value = row[field]
            if value is None or value == "":
                return (2, "")
            if field in numeric or isinstance(value, (int, float)) and not isinstance(value, bool):
                return (0, Decimal(str(value)))
            return (1, reports._text(value))

        rows.sort(key=key, reverse=descending)
        # Keep numeric/text groups fixed in either direction, with missing values last.
        rows.sort(
            key=lambda row: (
                row[field] is None or row[field] == "",
                not (field in numeric or isinstance(row[field], (int, float)) and not isinstance(row[field], bool)),
            )
        )


def _filter_options(command):
    for name, help_text in reversed(tuple(reports.ROW_FILTER_HELP.items())):
        spelling = "in" if name == "in_values" else name.replace("_", "-")
        command = click.option("--" + spelling, name, multiple=True, help=help_text)(command)
    return command


@main.command("summarize")
@_filter_options
@click.argument("source", type=click.Choice(sorted(reports.SOURCES)), metavar="SOURCE")
@click.option(
    "--derive",
    multiple=True,
    help="Add a computed NAME=FUNCTION:FIELD[:ARGUMENT] source field; list functions with `report derive-functions`.",
)
@click.option("--metric", multiple=True, help="Append NAME=OP[:FIELD]; repeat for multiple summaries.")
@click.option("--group-by", multiple=True, help="Group on source FIELD; repeat for a composite key.")
@click.option("--where", multiple=True, help="Keep exact source FIELD=VALUE text matches; repeat for AND.")
@click.option("--having", multiple=True, help="Keep summary rows passing FILTER:NAME=VALUE; repeat for AND.")
@click.option("--totals", is_flag=True, help="Append a final row summarizing every filtered source row.")
@click.option("--sort", multiple=True, help="Sort grouping fields or metric names; repeat for tie breakers.")
@click.option("--descending", is_flag=True, help="Sort in descending order, keeping missing values last.")
@click.option("--offset", type=click.IntRange(min=0), default=0, help="Skip N summary rows.")
@click.option("--limit", type=click.IntRange(min=1), help="Keep at most N summary rows.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(reports.FORMATS),
    default="json",
    show_default=True,
)
@click.option("--page-info", is_flag=True, help="Wrap JSON in source, total, offset, limit and rows metadata.")
@click.option("--describe", is_flag=True, help="List source fields and operations without loading source data.")
@click.option("--output", type=click.Path(path_type=Path, dir_okay=False), help="Write atomically to a new UTF-8 file.")
@pass_app
def summarize(
    app: App,
    source: str,
    derive: tuple[str, ...],
    metric: tuple[str, ...],
    group_by: tuple[str, ...],
    where: tuple[str, ...],
    having: tuple[str, ...],
    totals: bool,
    sort: tuple[str, ...],
    descending: bool,
    offset: int,
    limit: int | None,
    output_format: str,
    page_info: bool,
    describe: bool,
    output: Path | None,
    **filters: tuple[str, ...],
) -> None:
    """Summarize saved rows offline, without fetching quotes or recording snapshots.

    Derived fields are computed first; source filters run before grouping; group summaries
    run before --having, sorting and pagination, and --totals closes the page.
    Script output is raw and unmasked; configuration secrets remain redacted.
    List the datasets with `marketpulse report sources`.
    """
    # Derived fields join the schema first, so filters, grouping and metrics can name them.
    derived = report_derive.DerivePlan(reports.SOURCES[source], derive)
    schema = derived.schema
    if describe:
        if any(
            (
                derive,
                metric,
                group_by,
                where,
                having,
                totals,
                sort,
                descending,
                offset,
                limit is not None,
                output_format != "json",
                page_info,
                any(filters.values()),
            )
        ):
            raise click.UsageError("--describe cannot combine with summary operations.")
        reports._emit(
            json.dumps({"source": source, "fields": list(schema), "operations": report_metrics.ALL_OPERATIONS}) + "\n",
            output,
        )
        return
    if not metric:
        raise click.UsageError("At least one --metric NAME=OP[:FIELD] is required (or use --describe).")
    if len(set(group_by)) != len(group_by) or any(field not in schema for field in group_by):
        raise click.UsageError(f"Choose distinct --group-by fields from: {', '.join(schema)}.")
    metrics = _metrics(metric, schema, group_by)
    fields = [*group_by, *(item.name for item in metrics)]
    if len(set(sort)) != len(sort) or any(field not in fields for field in sort):
        raise click.UsageError(f"Choose distinct --sort fields from: {', '.join(fields)}.")
    if descending and not sort:
        raise click.UsageError("--descending requires --sort.")
    if page_info and output_format != "json":
        raise click.UsageError("--page-info requires JSON output.")
    if totals and not group_by:
        raise click.UsageError("--totals requires --group-by.")
    report_formats.validate(output_format, fields)
    exact = [reports._condition(value, schema) for value in where]
    matches = report_filters.compile_filters(schema, filters)
    kept = _having(having, tuple(fields))
    if output is not None and os.path.lexists(output):
        raise click.UsageError("--output must name a new file; refusing to overwrite.")
    rows = [
        row
        for row in derived.apply(reports.load_source(source, app))
        if matches(row) and all(reports._text(row[field]) == value for field, value in exact)
    ]
    summaries = [summary for summary in _summarize(rows, group_by, metrics) if kept(summary)]
    _sort(summaries, sort, {item.name for item in metrics if item.numeric}, descending)
    total = len(summaries)
    page = summaries[offset:][:limit]
    if totals:
        # The closing row covers every filtered source row, whatever --having and pagination kept.
        page.append({**dict.fromkeys(group_by), **_measure(rows, metrics)})
    envelope = {"source": source, "total": total, "offset": offset, "limit": limit} if page_info else None
    reports._emit(reports._serialize(page, fields, output_format, envelope), output)
