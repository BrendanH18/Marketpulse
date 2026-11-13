"""Validated predicates for saved-data reports; never fetch or mutate data."""

from __future__ import annotations

import json
import math
import re
import warnings
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from fnmatch import fnmatchcase, translate
from typing import Any

import click

from .report_dates import date_of, parse_date_argument

FILTER_OPTIONS = (
    "ieq",
    "ine",
    "not_contains",
    "not_prefix",
    "not_suffix",
    "gt",
    "ge",
    "lt",
    "le",
    "between",
    "outside",
    "in_values",
    "not_in",
    "empty",
    "nonempty",
    "is_type",
    "length",
    "min_length",
    "max_length",
    "glob",
)
# Added under #143; every one takes FIELD=VALUE.
EXPANSION_FILTERS = (
    "regex",
    "not_regex",
    "iglob",
    "not_glob",
    "contains_any",
    "contains_all",
    "date_from",
    "date_to",
    "has_item",
    "has_key",
)

Predicate = Callable[[dict[str, Any]], bool]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _typed_equal(left: Any, right: Any) -> bool:
    """JSON equality without Python's true == 1 shortcut, including nested values."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_typed_equal(a, b) for a, b in zip(left, right, strict=True))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_typed_equal(left[key], right[key]) for key in left)
    return left == right


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant: {value}")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Non-finite JSON number: {value}")
    return result


def _spelling(option: str) -> str:
    """The command-line spelling of a filter option."""
    return "in" if option == "in_values" else option.replace("_", "-")


def _json_argument(text: str, spelling: str, syntax: str) -> Any:
    try:
        return json.loads(text, parse_constant=_reject_constant, parse_float=_finite_float)
    except (ValueError, RecursionError) as exc:
        raise click.UsageError(f"--{spelling} requires FIELD={syntax} with finite JSON values.") from exc


def _expansion_condition(option: str, field: str, text: str) -> Predicate:
    spelling = _spelling(option)
    if option in ("regex", "not_regex"):
        try:
            with warnings.catch_warnings():
                # A valid pattern such as "[[" can warn about future syntax; the warning is not for users.
                warnings.simplefilter("ignore", FutureWarning)
                pattern = re.compile(text)
        except (re.error, RecursionError, OverflowError) as exc:
            raise click.UsageError(
                f"--{spelling} requires FIELD=PATTERN with a valid regular expression: {exc}."
            ) from exc
        wanted = option == "regex"
        return lambda row: (pattern.search(_text(row[field])) is not None) is wanted
    if option == "iglob":
        # Case is ignored per character, so ? still matches one character and [ß] only ß or ẞ.
        glob = re.compile(translate(text), re.IGNORECASE)
        return lambda row: glob.match(_text(row[field])) is not None
    if option == "not_glob":
        return lambda row: not fnmatchcase(_text(row[field]), text)
    if option in ("contains_any", "contains_all"):
        members = _json_argument(text, spelling, "JSON_ARRAY")
        if not isinstance(members, list) or not all(isinstance(member, str) for member in members):
            raise click.UsageError(f"--{spelling} requires FIELD=JSON_ARRAY of strings.")
        needles = [member.casefold() for member in members]
        combine = any if option == "contains_any" else all

        def text_members(row: dict[str, Any]) -> bool:
            actual = _text(row[field]).casefold()
            return combine(needle in actual for needle in needles)

        return text_members
    if option in ("date_from", "date_to"):
        bound = parse_date_argument(text)
        if bound is None:
            raise click.UsageError(f"--{spelling} requires FIELD=YYYY-MM-DD with a valid calendar date.")

        def date_match(row: dict[str, Any]) -> bool:
            actual = date_of(row[field])
            if actual is None:
                return False
            return actual >= bound if option == "date_from" else actual <= bound

        return date_match
    if option == "has_item":
        wanted_item = _json_argument(text, spelling, "JSON")
        return lambda row: isinstance(row[field], list) and any(_typed_equal(item, wanted_item) for item in row[field])
    return lambda row: isinstance(row[field], dict) and text in row[field]


def _condition(option: str, field: str, text: str) -> Predicate:
    if option in EXPANSION_FILTERS:
        return _expansion_condition(option, field, text)
    if option in ("ieq", "ine", "not_contains", "not_prefix", "not_suffix"):
        expected = text.casefold()

        def text_match(row: dict[str, Any]) -> bool:
            actual = _text(row[field]).casefold()
            if option == "ieq":
                return actual == expected
            if option == "ine":
                return actual != expected
            if option == "not_contains":
                return expected not in actual
            if option == "not_prefix":
                return not actual.startswith(expected)
            return not actual.endswith(expected)

        return text_match
    if option == "glob":
        return lambda row: fnmatchcase(_text(row[field]), text)
    if option in ("gt", "ge", "lt", "le", "between", "outside"):
        limits = text.split(",") if option in ("between", "outside") else [text]
        numbers = [_number(limit) for limit in limits]
        expected_length = 2 if option in ("between", "outside") else 1
        if len(numbers) != expected_length or any(number is None for number in numbers):
            syntax = "LOW,HIGH" if expected_length == 2 else "NUMBER"
            raise click.UsageError(f"--{option} requires FIELD={syntax} with finite numbers.")
        lower = numbers[0]
        assert lower is not None
        upper = numbers[-1]
        assert upper is not None
        if lower > upper:
            raise click.UsageError(f"--{option} requires LOW <= HIGH.")

        def numeric_match(row: dict[str, Any]) -> bool:
            actual = _number(row[field])
            if actual is None:
                return False
            if option == "gt":
                return actual > lower
            if option == "ge":
                return actual >= lower
            if option == "lt":
                return actual < lower
            if option == "le":
                return actual <= lower
            if option == "between":
                return lower <= actual <= upper
            return actual < lower or actual > upper

        return numeric_match
    if option in ("in_values", "not_in"):
        try:
            members = json.loads(text, parse_constant=_reject_constant, parse_float=_finite_float)
        except (ValueError, RecursionError) as exc:
            raise click.UsageError("Membership filters require FIELD=JSON_ARRAY with finite JSON values.") from exc
        if not isinstance(members, list):
            raise click.UsageError("Membership filters require FIELD=JSON_ARRAY.")

        def membership_match(row: dict[str, Any]) -> bool:
            matched = any(_typed_equal(row[field], member) for member in members)
            return matched if option == "in_values" else not matched

        return membership_match
    if option in ("empty", "nonempty"):

        def empty_match(row: dict[str, Any]) -> bool:
            value = row[field]
            empty = value is None or isinstance(value, (str, list, dict)) and len(value) == 0
            return empty if option == "empty" else not empty

        return empty_match
    if option == "is_type":
        types: dict[str, type | tuple[type, ...]] = {
            "string": str,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
            "null": type(None),
        }
        if text not in types:
            raise click.UsageError("--is-type requires FIELD=string|number|boolean|array|object|null.")
        expected_type = types[text]
        return lambda row: (
            isinstance(row[field], expected_type) and not (text == "number" and isinstance(row[field], bool))
        )
    if option in ("length", "min_length", "max_length"):
        try:
            length = int(text)
        except ValueError as exc:
            raise click.UsageError("Length filters require FIELD=N with a nonnegative integer.") from exc
        if length < 0:
            raise click.UsageError("Length filters require FIELD=N with a nonnegative integer.")

        def length_match(row: dict[str, Any]) -> bool:
            value = row[field]
            if not isinstance(value, (str, list, dict)):
                return False
            if option == "length":
                return len(value) == length
            if option == "min_length":
                return len(value) >= length
            return len(value) <= length

        return length_match
    raise click.UsageError(f"Unknown report filter '{option}'.")


def compile_filters(schema: tuple[str, ...], options: dict[str, tuple[str, ...]]) -> Predicate:
    """Validate every condition now and return their AND predicate for later rows.

    Numbers accept finite numeric strings as well as JSON numbers, but exclude
    booleans. Text predicates use the report's existing JSON-text convention.
    Date predicates read strings that start with a valid ``YYYY-MM-DD`` date.
    """
    predicates: list[Predicate] = []
    for option, values in options.items():
        if option not in FILTER_OPTIONS and option not in EXPANSION_FILTERS:
            raise click.UsageError(f"Unknown report filter '{option}'.")
        for value in values:
            if option in ("empty", "nonempty"):
                field, text = value, ""
            else:
                field, separator, text = value.partition("=")
                if not separator:
                    raise click.UsageError(f"--{_spelling(option)} requires FIELD=VALUE.")
            if field not in schema:
                raise click.UsageError(f"Unknown field '{field}'. Choose from: {', '.join(schema)}.")
            predicates.append(_condition(option, field, text))
    return lambda row: all(predicate(row) for predicate in predicates)
