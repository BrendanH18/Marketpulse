"""Derived report fields: validated, pure functions of saved cells; never fetch or mutate data."""

from __future__ import annotations

import calendar
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Context, Decimal, DecimalException, localcontext
from typing import Any

import click

from .report_output import _equal, _json, _text


@dataclass(frozen=True)
class Function:
    name: str
    family: str  # date | number | text | value
    argument: str | None  # placeholder for the required argument, or None when there is none
    result: str  # integer | number | string | boolean | value
    description: str


# The documented order; `report derive-functions` and the capability inventory number these 1-50.
FUNCTIONS: tuple[Function, ...] = (
    Function("year", "date", None, "integer", "Calendar year."),
    Function("quarter", "date", None, "integer", "Calendar quarter, 1 to 4."),
    Function("month", "date", None, "integer", "Month number, 1 to 12."),
    Function("day", "date", None, "integer", "Day of the month, 1 to 31."),
    Function("weekday", "date", None, "integer", "ISO weekday, 1 for Monday to 7 for Sunday."),
    Function("day-of-year", "date", None, "integer", "Day of the year, 1 to 366."),
    Function("iso-week", "date", None, "integer", "ISO 8601 week number, 1 to 53."),
    Function("year-month", "date", None, "string", "Year and month as YYYY-MM."),
    Function("year-quarter", "date", None, "string", "Year and quarter as YYYY-Qn."),
    Function("year-week", "date", None, "string", "ISO week-numbering year and week as YYYY-Www."),
    Function("month-name", "date", None, "string", "English month name."),
    Function("weekday-name", "date", None, "string", "English weekday name."),
    Function("date", "date", None, "string", "Calendar date as YYYY-MM-DD, without any time."),
    Function("month-start", "date", None, "string", "First day of the month."),
    Function("month-end", "date", None, "string", "Last day of the month."),
    Function("quarter-start", "date", None, "string", "First day of the calendar quarter."),
    Function("quarter-end", "date", None, "string", "Last day of the calendar quarter."),
    Function("year-start", "date", None, "string", "January 1 of the year."),
    Function("year-end", "date", None, "string", "December 31 of the year."),
    Function("week-start", "date", None, "string", "Monday of the ISO week."),
    Function("is-weekend", "date", None, "boolean", "True on Saturday and Sunday."),
    Function("days-from", "date", "DATE", "integer", "Days from DATE to the field's date; negative when earlier."),
    Function("number", "number", None, "number", "The numeric value, parsing numeric text."),
    Function("abs", "number", None, "number", "Absolute value."),
    Function("negate", "number", None, "number", "Value with its sign reversed."),
    Function("sign", "number", None, "integer", "-1, 0 or 1."),
    Function("floor", "number", None, "number", "Largest whole number at or below the value."),
    Function("ceil", "number", None, "number", "Smallest whole number at or above the value."),
    Function("round", "number", "DIGITS", "number", "Value rounded half to even at 0 to 15 decimal places."),
    Function("bin", "number", "WIDTH", "number", "Lower edge of the value's WIDTH-sized bucket."),
    Function("add", "number", "NUMBER", "number", "Value plus NUMBER."),
    Function("multiply", "number", "NUMBER", "number", "Value times NUMBER."),
    Function("add-field", "number", "FIELD", "number", "Value plus another field."),
    Function("subtract-field", "number", "FIELD", "number", "Value minus another field."),
    Function("multiply-field", "number", "FIELD", "number", "Value times another field."),
    Function("divide-field", "number", "FIELD", "number", "Value divided by another, nonzero field."),
    Function("lower", "text", None, "string", "Lowercase text."),
    Function("upper", "text", None, "string", "Uppercase text."),
    Function("trim", "text", None, "string", "Text without leading or trailing whitespace."),
    Function("left", "text", "N", "string", "First N characters."),
    Function("before", "text", "TEXT", "string", "Text before the first TEXT; all of it when TEXT is absent."),
    Function("after-last", "text", "TEXT", "string", "Text after the last TEXT; empty when TEXT is absent."),
    Function("length", "value", None, "integer", "Length of text, an array or an object."),
    Function("text", "value", None, "string", "Report text: null is empty and nested values are JSON."),
    Function("type", "value", None, "string", "JSON type: string, number, boolean, array, object or null."),
    Function("is-missing", "value", None, "boolean", "True for null or empty text."),
    Function("coalesce", "value", "JSON", "value", "The value, or JSON when the value is null."),
    Function("equals", "value", "JSON", "boolean", "True when the value equals JSON, comparing JSON types."),
    Function("item", "value", "N", "value", "Array element N from 0; negative N counts from the end."),
    Function("key", "value", "NAME", "value", "Object member NAME."),
)
_BY_NAME = {function.name: function for function in FUNCTIONS}

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DATE = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})"
    r"(?:[T ]([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\.[0-9]+)?)?(?:Z|[+-]([0-9]{2}):([0-9]{2}))?)?"
)
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# Whole results below this magnitude are JSON integers; larger or fractional results are doubles.
_INTEGER_LIMIT = Decimal(10) ** 15


def _date(value: Any) -> date | None:
    """The calendar date of ISO date or date-time text, as written (no time zone conversion)."""
    if not isinstance(value, str):
        return None
    match = _DATE.fullmatch(value)
    if match is None:
        return None
    year, month, day, *clock = match.groups()
    if any(part is not None and int(part) > limit for part, limit in zip(clock, (23, 59, 59, 23, 59), strict=True)):
        return None
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _quarter(day: date) -> int:
    return (day.month - 1) // 3 + 1


def _quarter_start(day: date) -> date:
    return day.replace(month=3 * _quarter(day) - 2, day=1)


def _month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _year_week(day: date) -> str:
    iso_year, iso_week, _ = day.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


_DATE_PARTS: dict[str, Callable[[date], Any]] = {
    "year": lambda day: day.year,
    "quarter": _quarter,
    "month": lambda day: day.month,
    "day": lambda day: day.day,
    "weekday": lambda day: day.isoweekday(),
    "day-of-year": lambda day: day.toordinal() - day.replace(month=1, day=1).toordinal() + 1,
    "iso-week": lambda day: day.isocalendar()[1],
    "year-month": lambda day: f"{day.year:04d}-{day.month:02d}",
    "year-quarter": lambda day: f"{day.year:04d}-Q{_quarter(day)}",
    "year-week": _year_week,
    "month-name": lambda day: _MONTHS[day.month - 1],
    "weekday-name": lambda day: _WEEKDAYS[day.weekday()],
    "date": lambda day: day.isoformat(),
    "month-start": lambda day: day.replace(day=1).isoformat(),
    "month-end": lambda day: _month_end(day).isoformat(),
    "quarter-start": lambda day: _quarter_start(day).isoformat(),
    "quarter-end": lambda day: _month_end(_quarter_start(day).replace(month=3 * _quarter(day))).isoformat(),
    "year-start": lambda day: day.replace(month=1, day=1).isoformat(),
    "year-end": lambda day: day.replace(month=12, day=31).isoformat(),
    "week-start": lambda day: (day - timedelta(days=day.weekday())).isoformat(),
    "is-weekend": lambda day: day.weekday() >= 5,
}


def _number(value: Any) -> Decimal | None:
    """Finite numbers and numeric text, as in report filters and summaries; booleans are not numbers."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    # Invalid input must not leave Decimal flags in the caller's context.
    with localcontext(Context()):
        try:
            result = Decimal(str(value))
        except (DecimalException, ValueError):
            return None
    return result if result.is_finite() else None


def _json_number(value: Decimal) -> int | float | None:
    """A JSON number for a finite decimal result, or None when no finite double can hold it."""
    if value.copy_abs() < _INTEGER_LIMIT and value == value.to_integral_value():
        return int(value)
    result = float(value)
    return (result or 0) if math.isfinite(result) else None


def _rounded(value: Decimal, digits: int) -> Decimal:
    if int(value.as_tuple().exponent) >= -digits:
        return value
    # Enough working digits to keep every retained place, whatever the caller's context.
    with localcontext(Context(prec=max(28, value.adjusted() + digits + 3))):
        return value.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_EVEN)


def _bin(value: Decimal, width: Decimal) -> Decimal:
    """The largest multiple of width at or below value.

    The quotient is rounded toward minus infinity, never up into the next bucket, so its whole
    part is exact whenever it fits in the working digits.
    """
    with localcontext() as context:
        context.rounding = ROUND_FLOOR
        whole = (value / width).to_integral_value()
    return whole * width


_UNARY_NUMBERS: dict[str, Callable[[Decimal], Decimal | int]] = {
    "number": lambda value: value,
    "abs": lambda value: value.copy_abs(),
    "negate": lambda value: value.copy_negate(),
    "sign": lambda value: (value > 0) - (value < 0),
    "floor": lambda value: value.to_integral_value(rounding=ROUND_FLOOR),
    "ceil": lambda value: value.to_integral_value(rounding=ROUND_CEILING),
}
_BINARY_NUMBERS: dict[str, Callable[[Decimal, Decimal], Decimal | None]] = {
    "round": lambda value, digits: _rounded(value, int(digits)),
    "bin": _bin,
    "add": lambda value, other: value + other,
    "multiply": lambda value, other: value * other,
    "add-field": lambda value, other: value + other,
    "subtract-field": lambda value, other: value - other,
    "multiply-field": lambda value, other: value * other,
    "divide-field": lambda value, other: value / other if other else None,
}


def _arithmetic(compute: Callable[[], Decimal | int | None]) -> int | float | None:
    """Run decimal arithmetic at 28 digits, half even; unrepresentable results are None."""
    try:
        with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
            result = compute()
    except DecimalException:
        return None
    if result is None or isinstance(result, int):
        return result
    return _json_number(result)


def _type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "array" if isinstance(value, list) else "object"


_VALUES: dict[str, Callable[[Any], Any]] = {
    "lower": lambda value: value.lower() if isinstance(value, str) else None,
    "upper": lambda value: value.upper() if isinstance(value, str) else None,
    "trim": lambda value: value.strip() if isinstance(value, str) else None,
    "length": lambda value: len(value) if isinstance(value, (str, list, dict)) else None,
    "text": _text,
    "type": _type,
    "is-missing": lambda value: value is None or isinstance(value, str) and value == "",
}


def _usage(function: Function, problem: str) -> click.UsageError:
    return click.UsageError(f"--derive function '{function.name}' {problem}.")


def _whole(function: Function, argument: str, minimum: int | None) -> int:
    # Nine digits are more than any text or array holds, and keep int() far from its digit limit.
    if not re.fullmatch(r"-?[0-9]{1,9}", argument) or (minimum is not None and int(argument) < minimum):
        lowest = "-999999999" if minimum is None else str(minimum)
        raise _usage(function, f"requires a whole number N from {lowest} to 999999999")
    return int(argument)


def _compile(function: Function, field: str, argument: str | None, schema: tuple[str, ...]) -> Callable[[dict], Any]:
    """Validate one function call now and return its row evaluator."""
    name = function.name
    if name in _DATE_PARTS:
        part = _DATE_PARTS[name]

        def date_part(row: dict[str, Any]) -> Any:
            day = _date(row[field])
            return None if day is None else part(day)

        return date_part
    if name in _UNARY_NUMBERS:
        unary = _UNARY_NUMBERS[name]

        def unary_number(row: dict[str, Any]) -> int | float | None:
            value = _number(row[field])
            return None if value is None else _arithmetic(lambda: unary(value))

        return unary_number
    if name in _VALUES:
        transform = _VALUES[name]
        return lambda row: transform(row[field])

    assert argument is not None  # every remaining function requires one
    if name == "days-from":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", argument) or (origin := _date(argument)) is None:
            raise _usage(function, "requires a valid DATE as YYYY-MM-DD")

        def days_from(row: dict[str, Any]) -> int | None:
            day = _date(row[field])
            return None if day is None else (day - origin).days

        return days_from
    if name in _BINARY_NUMBERS:
        binary = _BINARY_NUMBERS[name]
        if function.argument == "FIELD":
            if argument not in schema:
                raise _usage(function, f"requires a second field from: {', '.join(schema)}")

            def two_fields(row: dict[str, Any]) -> int | float | None:
                value, other = _number(row[field]), _number(row[argument])
                return None if value is None or other is None else _arithmetic(lambda: binary(value, other))

            return two_fields
        if name == "round":
            if not re.fullmatch(r"0*[0-9]{1,2}", argument) or int(argument.lstrip("0") or "0") > 15:
                raise _usage(function, "requires DIGITS from 0 to 15")
            constant = Decimal(int(argument.lstrip("0") or "0"))
        else:
            parsed = _number(argument)
            if parsed is None or (name == "bin" and parsed <= 0):
                raise _usage(function, "requires a finite WIDTH above zero" if name == "bin" else "requires a NUMBER")
            constant = parsed

        def with_constant(row: dict[str, Any]) -> int | float | None:
            value = _number(row[field])
            return None if value is None else _arithmetic(lambda: binary(value, constant))

        return with_constant
    if name == "left":
        count = _whole(function, argument, 1)
        return lambda row: row[field][:count] if isinstance(row[field], str) else None
    if name in ("before", "after-last"):
        if not argument:
            raise _usage(function, "requires nonempty TEXT")
        if name == "before":
            return lambda row: row[field].partition(argument)[0] if isinstance(row[field], str) else None

        def after_last(row: dict[str, Any]) -> str | None:
            value = row[field]
            if not isinstance(value, str):
                return None
            _, separator, tail = value.rpartition(argument)
            return tail if separator else ""

        return after_last
    if name in ("coalesce", "equals"):
        try:
            constant_json = _json(argument)
        except (ValueError, RecursionError) as exc:
            raise _usage(function, f"requires finite JSON: {exc}") from exc
        if name == "coalesce":
            return lambda row: constant_json if row[field] is None else row[field]
        return lambda row: _equal(row[field], constant_json)
    if name == "item":
        index = _whole(function, argument, None)

        def item(row: dict[str, Any]) -> Any:
            value = row[field]
            return value[index] if isinstance(value, list) and -len(value) <= index < len(value) else None

        return item
    return lambda row: row[field].get(argument) if isinstance(row[field], dict) else None


class DerivePlan:
    """Compile ``--derive NAME=FUNCTION:FIELD[:ARGUMENT]`` before a source is loaded.

    Derived columns append to the source schema in argument order, and a later
    column may read an earlier one. ``apply`` returns new rows and leaves the
    loaded rows untouched. A function yields null for a cell it does not apply
    to; it never drops a row or fails on saved data.
    """

    def __init__(self, schema: tuple[str, ...], specifications: tuple[str, ...]) -> None:
        self._steps: list[tuple[str, Callable[[dict[str, Any]], Any]]] = []
        for specification in specifications:
            name, separator, expression = specification.partition("=")
            function_name, colon, call = expression.partition(":")
            if not separator or not colon or not _NAME.fullmatch(name):
                raise click.UsageError(
                    "--derive requires NAME=FUNCTION:FIELD[:ARGUMENT], with an ASCII identifier NAME."
                )
            if name in schema:
                raise click.UsageError(f"Derived field '{name}' duplicates an existing field.")
            function = _BY_NAME.get(function_name)
            if function is None:
                raise click.UsageError(
                    f"Unknown --derive function '{function_name}'. List them with `report derive-functions`."
                )
            field, has_argument, argument = call.partition(":")
            if field not in schema:
                raise click.UsageError(f"Unknown field '{field}'. Choose from: {', '.join(schema)}.")
            if function.argument is None and has_argument:
                raise _usage(function, "takes no argument")
            if function.argument is not None and not has_argument:
                raise _usage(function, f"requires FIELD:{function.argument}")
            self._steps.append((name, _compile(function, field, argument if has_argument else None, schema)))
            schema = (*schema, name)
        self.schema = schema

    def apply(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self._steps:
            return rows
        result = []
        for original in rows:
            row = dict(original)
            for name, compute in self._steps:
                row[name] = compute(row)
            result.append(row)
        return result
