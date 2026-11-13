"""Pure descriptive summaries of saved report cells, without engine calculations."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, Decimal, DecimalException, Inexact, Underflow, localcontext
from typing import Any

import click

from .report_filters import _typed_equal

OPERATIONS = (
    "count",
    "present",
    "missing",
    "empty",
    "nonempty",
    "distinct",
    "duplicates",
    "first",
    "last",
    "first-present",
    "last-present",
    "mode",
    "mode-count",
    "values",
    "distinct-values",
    "number-count",
    "number-distinct",
    "number-sum",
    "number-min",
    "number-max",
    "number-mean",
    "number-median",
    "number-range",
    "positive-count",
    "negative-count",
    "zero-count",
    "positive-sum",
    "negative-sum",
    "absolute-sum",
    "true-count",
    "false-count",
    "string-count",
    "array-count",
    "object-count",
    "length-sum",
    "length-min",
    "length-max",
    "length-mean",
    "text-min",
    "text-max",
)


def _missing(value: Any) -> bool:
    return value is None or isinstance(value, str) and value == ""


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    # Invalid input must not leave Decimal flags in the caller's context.
    with localcontext(Context()):
        try:
            result = Decimal(str(value))
        except DecimalException:
            return None
    return result if result.is_finite() else None


def _decimal_text(value: Decimal) -> str:
    """Canonical finite text without context-sensitive normalize() rounding.

    Use ordinary notation for adjusted exponents -6 through 20, scientific
    notation outside that range, and remove insignificant trailing zeros.
    """
    if not value:
        return "0"
    sign, digits, exponent = value.as_tuple()
    exponent = int(exponent)
    while len(digits) > 1 and digits[-1] == 0:
        digits = digits[:-1]
        exponent += 1
    value = Decimal((sign, digits, exponent))
    return format(value, "f") if -6 <= value.adjusted() <= 20 else format(value, "E")


def _precision(numbers: list[Decimal]) -> int:
    """Enough digits for an exact sum, difference or even-sized median."""
    significant = [number for number in numbers if number]
    if not significant:
        return 28
    span = max(number.adjusted() for number in significant) - min(
        int(number.as_tuple().exponent) for number in significant
    )
    precision = max(28, span + len(str(len(numbers))) + 3)
    if precision > 10_000:
        raise click.ClickException("Summary arithmetic requires more than 10,000 decimal digits.")
    return precision


def _numeric_summary(operation: str, numbers: list[Decimal]) -> Any:
    if operation == "number-count":
        return len(numbers)
    if operation == "number-distinct":
        return len(set(numbers))
    if operation.endswith("-count"):
        return sum(
            number > 0
            if operation == "positive-count"
            else number < 0
            if operation == "negative-count"
            else number == 0
            for number in numbers
        )
    if operation in ("number-min", "number-max"):
        return _decimal_text((min if operation == "number-min" else max)(numbers)) if numbers else None
    if not numbers:
        return "0" if operation.endswith("-sum") else None
    try:
        with localcontext(Context(prec=_precision(numbers), rounding=ROUND_HALF_EVEN)) as context:
            context.traps[Inexact] = True
            if operation == "positive-sum":
                result = sum((number for number in numbers if number > 0), Decimal(0))
            elif operation == "negative-sum":
                result = sum((number for number in numbers if number < 0), Decimal(0))
            elif operation == "absolute-sum":
                result = sum((number.copy_abs() for number in numbers), Decimal(0))
            elif operation == "number-range":
                result = max(numbers) - min(numbers)
            elif operation == "number-median":
                ordered = sorted(numbers)
                middle = len(ordered) // 2
                result = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
            else:
                result = sum(numbers, Decimal(0))
            if operation == "number-mean":
                with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)) as mean_context:
                    mean_context.traps[Underflow] = True
                    result /= len(numbers)
    except DecimalException as exc:
        raise click.ClickException("Summary arithmetic exceeds the supported decimal range.") from exc
    return _decimal_text(result)


def summarize_values(operation: str, values: list[Any]) -> Any:
    """Summarize cells in source order, preserving typed JSON values.

    Numeric aggregates accept finite numeric strings and numbers, excluding
    booleans. Results are decimal strings, with exact sums/ranges/medians up to
    10,000 working digits and means rounded to 28 significant digits (half even).
    Arithmetic uses Decimal's default exponent range, independent of callers.
    """
    if operation not in OPERATIONS:
        raise click.UsageError(f"Unknown summary operation '{operation}'.")
    if operation == "count":
        return len(values)
    if operation in ("present", "missing"):
        missing = sum(_missing(value) for value in values)
        return missing if operation == "missing" else len(values) - missing
    if operation in ("empty", "nonempty"):
        empty = sum(value is None or isinstance(value, (str, list, dict)) and len(value) == 0 for value in values)
        return empty if operation == "empty" else len(values) - empty
    if operation in ("first", "last", "first-present", "last-present"):
        selected = [value for value in values if not _missing(value)] if operation.endswith("-present") else values
        return selected[0 if operation.startswith("first") else -1] if selected else None
    if operation == "values":
        return list(values)
    if operation in ("distinct", "duplicates", "distinct-values", "mode", "mode-count"):
        distinct: list[Any] = []
        counts: list[int] = []
        for value in values:
            for index, previous in enumerate(distinct):
                if _typed_equal(previous, value):
                    counts[index] += 1
                    break
            else:
                distinct.append(value)
                counts.append(1)
        if operation == "distinct":
            return len(distinct)
        if operation == "duplicates":
            return len(values) - len(distinct)
        if operation == "distinct-values":
            return distinct
        if operation == "mode-count":
            return max(counts, default=0)
        return distinct[counts.index(max(counts))] if distinct else None
    if operation.startswith("number-") or operation.startswith(("positive-", "negative-", "zero-", "absolute-")):
        return _numeric_summary(operation, [number for value in values if (number := _number(value)) is not None])
    if operation in ("true-count", "false-count"):
        return sum(value is (operation == "true-count") for value in values)
    if operation in ("string-count", "array-count", "object-count"):
        expected = {"string-count": str, "array-count": list, "object-count": dict}[operation]
        return sum(isinstance(value, expected) for value in values)
    if operation.startswith("length-"):
        lengths = [len(value) for value in values if isinstance(value, (str, list, dict))]
        if operation == "length-sum":
            return sum(lengths)
        if operation == "length-mean":
            return _numeric_summary("number-mean", [Decimal(length) for length in lengths])
        return (min if operation == "length-min" else max)(lengths) if lengths else None
    strings = [value for value in values if isinstance(value, str)]
    return (min if operation == "text-min" else max)(strings) if strings else None
