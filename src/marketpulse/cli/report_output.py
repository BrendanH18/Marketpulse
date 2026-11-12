"""Validated, non-mutating output transformations for offline reports."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from typing import Any

import click

CELL_OPTIONS = (
    "lower",
    "upper",
    "strip",
    "lstrip",
    "rstrip",
    "replace",
    "fill",
    "null_if",
    "stringify",
    "encode_json",
    "decode_json",
    "length_of",
    "round_values",
)
EXTRA_OPTIONS = ("rename", "constant", "row_number")


def _json(value: str) -> Any:
    def reject_constant(token: str) -> Any:
        raise ValueError(f"non-finite number {token}")

    result = json.loads(value, parse_constant=reject_constant)

    def check(item: Any) -> None:
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("non-finite number")
        if isinstance(item, list):
            for child in item:
                check(child)
        elif isinstance(item, dict):
            for child in item.values():
                check(child)

    check(result)
    return result


def _equal(left: Any, right: Any) -> bool:
    """JSON equality with booleans distinct from numbers, including nested values."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right, strict=True))
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_equal(value, right[key]) for key, value in left.items())
    return left == right


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise click.UsageError(
            f"Invalid output column '{value}'; use letters, digits and underscores, "
            "starting with a letter or underscore."
        )
    return value


class OutputPlan:
    """Compile output options before a source is loaded.

    Cell operations always use original source names, in ``CELL_OPTIONS`` order.
    Repeated instances of one operation run in argument order. Aliases apply
    simultaneously, followed by constants and row numbering. ``apply`` accepts
    the already selected page; ``start`` is its zero-based offset in the query.
    """

    def __init__(self, schema: tuple[str, ...], options: dict[str, Any]) -> None:
        self._source_schema = schema
        self._operations: list[tuple[str, Callable[[Any], Any]]] = []
        self._aliases: dict[str, str] = {}
        self._constants: dict[str, Any] = {}
        self._row_number: str | None = options.get("row_number")

        for operation in CELL_OPTIONS:
            for specification in options.get(operation, ()):
                self._compile(operation, specification)
        for specification in options.get("rename", ()):
            field, value = self._pair(specification)
            if field in self._aliases:
                raise click.UsageError(f"Duplicate --rename for '{field}'.")
            self._aliases[field] = _name(value)

        columns = [self._aliases.get(field, field) for field in schema]
        if len(set(columns)) != len(columns):
            raise click.UsageError("--rename creates duplicate output columns.")
        for specification in options.get("constant", ()):
            field, separator, value = specification.partition("=")
            if not separator:
                raise click.UsageError("Use --constant NAME=JSON.")
            _name(field)
            if field in columns:
                raise click.UsageError(f"Output column '{field}' already exists.")
            self._constants[field] = self._parse_json(value, "constant")
            columns.append(field)
        if self._row_number is not None:
            _name(self._row_number)
            if self._row_number in columns:
                raise click.UsageError(f"Output column '{self._row_number}' already exists.")
            columns.append(self._row_number)
        self.schema = tuple(columns)

    def _field(self, field: str) -> str:
        if field not in self._source_schema:
            raise click.UsageError(f"Unknown field '{field}'. Choose from: {', '.join(self._source_schema)}.")
        return field

    def _pair(self, specification: str) -> tuple[str, str]:
        field, separator, value = specification.partition("=")
        if not separator:
            raise click.UsageError("Use FIELD=VALUE for output transformations.")
        return self._field(field), value

    @staticmethod
    def _parse_json(value: str, option: str) -> Any:
        try:
            return _json(value)
        except (ValueError, RecursionError) as exc:
            raise click.UsageError(f"--{option.replace('_', '-')} requires finite JSON: {exc}.") from exc

    def _compile(self, operation: str, specification: str) -> None:
        transform: Callable[[Any], Any]
        if operation in ("replace", "fill", "null_if", "round_values"):
            field, value = self._pair(specification)
        else:
            field, value = self._field(specification), ""
        if operation in ("lower", "upper", "strip", "lstrip", "rstrip"):
            method = getattr(str, operation)

            def string_method(item: Any) -> Any:
                return method(item) if isinstance(item, str) else item

            transform = string_method
        elif operation == "replace":
            replacement = self._parse_json(value, operation)
            if (
                not isinstance(replacement, list)
                or len(replacement) != 2
                or not all(isinstance(item, str) for item in replacement)
                or replacement[0] == ""
            ):
                raise click.UsageError('--replace requires FIELD=["nonempty old text", "new text"].')
            old, new = replacement

            def replace(item: Any) -> Any:
                return item.replace(old, new) if isinstance(item, str) else item

            transform = replace
        elif operation == "fill":
            replacement = self._parse_json(value, operation)

            def fill(item: Any) -> Any:
                return replacement if item is None else item

            transform = fill
        elif operation == "null_if":
            replacement = self._parse_json(value, operation)

            def null_if(item: Any) -> Any:
                return None if _equal(item, replacement) else item

            transform = null_if
        elif operation == "stringify":
            transform = _text
        elif operation == "encode_json":

            def encode(item: Any) -> str:
                return json.dumps(item, ensure_ascii=False, sort_keys=True, allow_nan=False)

            transform = encode
        elif operation == "decode_json":

            def decode(item: Any) -> Any:
                if not isinstance(item, str):
                    return item
                try:
                    return _json(item)
                except (ValueError, RecursionError) as exc:
                    raise click.ClickException(f"Cannot decode JSON in field '{field}': {exc}.") from exc

            transform = decode
        elif operation == "length_of":

            def length(item: Any) -> int | None:
                return len(item) if isinstance(item, (str, list, dict)) else None

            transform = length
        else:
            try:
                digits = int(value)
            except ValueError as exc:
                raise click.UsageError("--round requires FIELD=DIGITS, with DIGITS from 0 to 15.") from exc
            if not 0 <= digits <= 15:
                raise click.UsageError("--round requires DIGITS from 0 to 15.")

            def rounded(item: Any) -> Any:
                if isinstance(item, bool) or not isinstance(item, (int, float)):
                    return item
                if isinstance(item, float) and not math.isfinite(item):
                    return item
                return round(item, digits)

            transform = rounded
        self._operations.append((field, transform))

    def apply(self, rows: list[dict[str, Any]], start: int = 0) -> list[dict[str, Any]]:
        result = []
        for number, original in enumerate(rows, start=start + 1):
            row = dict(original)
            for field, transform in self._operations:
                row[field] = transform(row[field])
            row = {self._aliases.get(field, field): row[field] for field in self._source_schema}
            row.update(self._constants)
            if self._row_number is not None:
                row[self._row_number] = number
            result.append(row)
        return result
