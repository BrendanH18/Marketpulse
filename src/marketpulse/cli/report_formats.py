"""Additional offline report export formats; serializers never open a data source."""

from __future__ import annotations

import html
import json
import math
from collections.abc import Iterable, Sequence
from typing import Any

import click

FORMATS = ("html", "text", "records", "lines", "json-columns")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    # NaN and Infinity are report text, not JSON: a text column shows what the cell holds.
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, list):
        return any(_non_finite(item) for item in value)
    if isinstance(value, dict):
        return any(_non_finite(item) for item in value.values())
    return False


def require_json_values(field: str, values: Iterable[Any]) -> None:
    """Refuse to write a NaN or infinity as JSON, which has neither, naming the field that holds it."""
    if any(_non_finite(value) for value in values):
        raise click.ClickException(
            f"Field '{field}' holds NaN or infinity, which JSON cannot represent. "
            "Choose a text format such as --format csv, or leave the field out."
        )


def _line(value: Any) -> str:
    """Report text on one line: backslashes, line breaks and tabs become escapes."""
    return _text(value).replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(output_format: str, fields: Sequence[str]) -> None:
    """Reject a format the selected columns cannot use, before a source is loaded."""
    if output_format == "lines" and len(fields) != 1:
        raise click.UsageError("--format lines requires exactly one output column.")


def _html(rows: list[dict[str, Any]], fields: Sequence[str]) -> str:
    def cell(value: Any) -> str:
        return html.escape(_text(value), quote=True).replace("\r", "&#13;").replace("\n", "<br>")

    lines = [
        "<table>",
        "<thead>",
        "<tr>" + "".join(f"<th>{cell(field)}</th>" for field in fields) + "</tr>",
        "</thead>",
        "<tbody>",
        *("<tr>" + "".join(f"<td>{cell(row[field])}</td>" for field in fields) + "</tr>" for row in rows),
        "</tbody>",
        "</table>",
    ]
    return "\n".join(lines) + "\n"


def _table(rows: list[dict[str, Any]], fields: Sequence[str]) -> str:
    cells = [[_line(row[field]) for field in fields] for row in rows]
    widths = [max([len(field), *(len(line[i]) for line in cells)]) for i, field in enumerate(fields)]
    lines = [
        "  ".join(field.ljust(width) for field, width in zip(fields, widths, strict=True)),
        "  ".join("-" * width for width in widths),
    ]
    for row, line in zip(rows, cells, strict=True):
        lines.append(
            "  ".join(
                text.rjust(width) if _number(row[field]) else text.ljust(width)
                for field, text, width in zip(fields, line, widths, strict=True)
            )
        )
    # Only the padding spaces go; a value's own trailing characters, such as a no-break space, stay.
    return "".join(line.rstrip(" ") + "\n" for line in lines)


def _records(rows: list[dict[str, Any]], fields: Sequence[str]) -> str:
    def line(field: str, text: str) -> str:
        return f"{field}: {text}\n" if text else f"{field}:\n"

    return "\n".join("".join(line(field, _line(row[field])) for field in fields) for row in rows)


def _lines(rows: list[dict[str, Any]], fields: Sequence[str]) -> str:
    (field,) = fields
    values = [_text(row[field]) for row in rows]
    if any("\n" in value or "\r" in value for value in values):
        raise click.ClickException("Cannot write a value containing a line break with --format lines.")
    return "".join(value + "\n" for value in values)


def serialize(rows: list[dict[str, Any]], fields: Sequence[str], output_format: str) -> str:
    """Render already selected rows; cell text follows the report convention.

    Strings are raw, null is empty and other values are canonical JSON, with a
    non-finite number as ``NaN``, ``Infinity`` or ``-Infinity``. ``html``
    is an escaped table fragment, ``text`` an aligned table with numbers on the
    right, ``records`` one ``field: value`` block per row, ``lines`` one raw
    value per line and ``json-columns`` one typed array per column.
    """
    if output_format == "html":
        return _html(rows, fields)
    if output_format == "text":
        return _table(rows, fields)
    if output_format == "records":
        return _records(rows, fields)
    if output_format == "lines":
        return _lines(rows, fields)
    if output_format == "json-columns":
        columns = {field: [row[field] for row in rows] for field in fields}
        for field, values in columns.items():
            require_json_values(field, values)
        return json.dumps(columns, ensure_ascii=False, allow_nan=False) + "\n"
    raise ValueError(f"Unknown report format: {output_format}")
