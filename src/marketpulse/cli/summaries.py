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

from . import report_filters, report_metrics, reports
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
        if operation not in report_metrics.OPERATIONS:
            raise click.UsageError(f"Unknown summary operation '{operation}'. Use --describe to list operations.")
        if operation == "count":
            if colon:
                raise click.UsageError("The count operation takes no field; use NAME=count.")
        elif not colon or field not in schema:
            raise click.UsageError(f"Operation '{operation}' requires a field from: {', '.join(schema)}.")
        names.add(name)
        result.append(Metric(name, operation, field if colon else None))
    return result


def _summarize(rows: list[dict[str, Any]], groups: tuple[str, ...], metrics: list[Metric]) -> list[dict[str, Any]]:
    buckets: dict[tuple, list[dict[str, Any]]] = {} if groups else {(): []}
    for row in rows:
        key = tuple(report_metrics._typed_key(row[field]) for field in groups)
        buckets.setdefault(key, []).append(row)
    result = []
    for bucket in buckets.values():
        summary = {field: bucket[0][field] for field in groups}
        for metric in metrics:
            values = [row[metric.field] if metric.field is not None else None for row in bucket]
            summary[metric.name] = report_metrics.summarize_values(metric.operation, values)
        result.append(summary)
    return result


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
    for name, help_text in reversed(tuple(reports.FILTER_HELP.items())):
        spelling = "in" if name == "in_values" else name.replace("_", "-")
        command = click.option("--" + spelling, name, multiple=True, help=help_text)(command)
    return command


@main.command("summarize")
@_filter_options
@click.argument("source", type=click.Choice(sorted(reports.SOURCES)))
@click.option("--metric", multiple=True, help="Append NAME=OP[:FIELD]; repeat for multiple summaries.")
@click.option("--group-by", multiple=True, help="Group on source FIELD; repeat for a composite key.")
@click.option("--where", multiple=True, help="Keep exact source FIELD=VALUE text matches; repeat for AND.")
@click.option("--sort", multiple=True, help="Sort grouping fields or metric names; repeat for tie breakers.")
@click.option("--descending", is_flag=True, help="Sort in descending order, keeping missing values last.")
@click.option("--offset", type=click.IntRange(min=0), default=0, help="Skip N summary rows.")
@click.option("--limit", type=click.IntRange(min=1), help="Keep at most N summary rows.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "jsonl", "csv", "tsv", "markdown"]),
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
    metric: tuple[str, ...],
    group_by: tuple[str, ...],
    where: tuple[str, ...],
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

    Source filters run before grouping; group summaries run before sorting and pagination.
    Script output is raw and unmasked; configuration secrets remain redacted.
    """
    schema = reports.SOURCES[source]
    if describe:
        if any(
            (
                metric,
                group_by,
                where,
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
            json.dumps({"source": source, "fields": list(schema), "operations": report_metrics.OPERATIONS}) + "\n",
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
    exact = [reports._condition(value, schema) for value in where]
    matches = report_filters.compile_filters(schema, filters)
    if output is not None and os.path.lexists(output):
        raise click.UsageError("--output must name a new file; refusing to overwrite.")
    rows = [
        row
        for row in reports.load_source(source, app)
        if matches(row) and all(reports._text(row[field]) == value for field, value in exact)
    ]
    summaries = _summarize(rows, group_by, metrics)
    _sort(summaries, sort, {item.name for item in metrics if item.numeric}, descending)
    total = len(summaries)
    envelope = {"source": source, "total": total, "offset": offset, "limit": limit} if page_info else None
    reports._emit(reports._serialize(summaries[offset:][:limit], fields, output_format, envelope), output)
