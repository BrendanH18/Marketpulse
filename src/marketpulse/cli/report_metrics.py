"""Pure descriptive summaries of saved report cells, without engine calculations."""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, Context, Decimal, DecimalException, Inexact, Underflow, localcontext
from typing import Any

import click

from .report_dates import date_of

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
# Added under #143. OPERATIONS stays the original forty.
EXPANSION_OPERATIONS = (
    "date-min",
    "date-max",
    "date-count",
    "date-span",
    "number-variance",
    "number-stdev",
    "number-q1",
    "number-q3",
    "value-counts",
    "repeated-values",
)
ALL_OPERATIONS = OPERATIONS + EXPANSION_OPERATIONS


def _typed_key(value: Any) -> tuple:
    """Hash JSON by typed value, matching 1 with 1.0 while separating true from 1."""
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (int, float)):
        return ("number", value)
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, list):
        return ("array", tuple(_typed_key(item) for item in value))
    return ("object", tuple((key, _typed_key(item)) for key, item in sorted(value.items())))


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


SIGNIFICANT = 28
# Adjusted exponents of the default decimal context, which bounds the other numeric summaries too.
EXPONENT_LIMIT = 999_999


def _integers(numbers: list[Decimal]) -> tuple[list[int], int]:
    """The numbers as exact integers on one decimal grid: ``number == integer * 10 ** exponent``."""
    exponent = min((int(number.as_tuple().exponent) for number in numbers if number), default=0)
    integers = []
    for number in numbers:
        sign, digits, power = number.as_tuple()
        # int() of a Decimal is exact at any size; int() of a digit string stops at 4,300 digits.
        magnitude = int(Decimal((0, digits, 0))) * 10 ** (int(power) - exponent) if number else 0
        integers.append(-magnitude if sign else magnitude)
    return integers, exponent


def _decimal(integer: int, exponent: int) -> Decimal:
    """``integer * 10 ** exponent`` built exactly, without the caller's decimal context."""
    result = Decimal((integer < 0, Decimal(abs(integer)).as_tuple().digits, exponent))
    if result and not -EXPONENT_LIMIT <= result.adjusted() <= EXPONENT_LIMIT:
        raise click.ClickException("Summary arithmetic exceeds the supported decimal range.")
    return result


def _order(numerator: int, denominator: int) -> int:
    """floor(log10(numerator / denominator)) for positive integers."""
    order = Decimal(numerator).adjusted() - Decimal(denominator).adjusted()
    reached = numerator >= denominator * 10**order if order >= 0 else numerator * 10**-order >= denominator
    return order if reached else order - 1


def _rounded(numerator: int, denominator: int, exponent: int, *, root: bool = False) -> Decimal:
    """The ratio (or its square root) times ``10 ** exponent``, to 28 significant digits, half even.

    Integer arithmetic keeps a single rounding of the exact value.
    """
    if not numerator:
        return Decimal(0)
    order = _order(numerator, denominator)
    if root:
        order //= 2
    shift = SIGNIFICANT - 1 - order
    scale = 2 * shift if root else shift
    if scale >= 0:
        numerator *= 10**scale
    else:
        denominator *= 10**-scale
    if root:
        result = math.isqrt(numerator // denominator)
        # Compare the root with result + 1/2 by squaring both: 4 * ratio against (2 * result + 1) ** 2.
        excess = 4 * numerator - denominator * (2 * result + 1) ** 2
    else:
        result, remainder = divmod(numerator, denominator)
        excess = 2 * remainder - denominator
    if excess > 0 or excess == 0 and result % 2:
        result += 1
    return _decimal(result, exponent - shift)


def _spread_summary(operation: str, numbers: list[Decimal]) -> str | None:
    """Population variance and deviation, and inclusive quartiles, as decimal text.

    Quartiles interpolate linearly between the closest ranks and are exact. Variance and
    deviation are the exact values rounded once to 28 significant digits (half even). The
    same 10,000-digit working limit as the other numeric summaries applies, and results
    beyond the supported exponent range fail with a CLI error.
    """
    if not numbers:
        return None
    _precision(numbers)
    count = len(numbers)
    integers, exponent = _integers(numbers)
    if operation in ("number-q1", "number-q3"):
        lower, quarters = divmod((count - 1) * (1 if operation == "number-q1" else 3), 4)
        order = sorted(range(count), key=integers.__getitem__)
        if not quarters:
            return _decimal_text(numbers[order[lower]])
        below, above = integers[order[lower]], integers[order[lower + 1]]
        # (4 * below + quarters * (above - below)) / 4, written as hundredths to stay exact.
        return _decimal_text(_decimal(25 * (4 * below + quarters * (above - below)), exponent - 2))
    total = sum(integers)
    # count * sum(x^2) - sum(x)^2 is count^2 times the variance on the integer grid, exactly.
    spread = count * sum(integer * integer for integer in integers) - total * total
    if operation == "number-stdev":
        return _decimal_text(_rounded(spread, count * count, exponent, root=True))
    return _decimal_text(_rounded(spread, count * count, 2 * exponent))


def summarize_values(operation: str, values: list[Any]) -> Any:
    """Summarize cells in source order, preserving typed JSON values.

    Numeric aggregates accept finite numeric strings and numbers, excluding
    booleans. Results are decimal strings, with exact sums/ranges/medians up to
    10,000 working digits and means rounded to 28 significant digits (half even).
    Arithmetic uses Decimal's default exponent range, independent of callers.
    """
    if operation not in ALL_OPERATIONS:
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
    if operation.startswith("date-"):
        dates = [day for value in values if (day := date_of(value)) is not None]
        if operation == "date-count":
            return len(dates)
        if not dates:
            return None
        if operation == "date-span":
            return (max(dates) - min(dates)).days
        return (min if operation == "date-min" else max)(dates).isoformat()
    if operation in (
        "distinct",
        "duplicates",
        "distinct-values",
        "mode",
        "mode-count",
        "value-counts",
        "repeated-values",
    ):
        distinct: list[Any] = []
        counts: list[int] = []
        indices: dict[tuple, int] = {}
        for value in values:
            key = _typed_key(value)
            index = indices.get(key)
            if index is None:
                indices[key] = len(distinct)
                distinct.append(value)
                counts.append(1)
            else:
                counts[index] += 1
        if operation == "distinct":
            return len(distinct)
        if operation == "duplicates":
            return len(values) - len(distinct)
        if operation == "distinct-values":
            return distinct
        if operation == "mode-count":
            return max(counts, default=0)
        if operation == "value-counts":
            # A stable sort keeps first-encountered order among equally frequent values.
            return [[distinct[i], counts[i]] for i in sorted(range(len(distinct)), key=lambda i: -counts[i])]
        if operation == "repeated-values":
            return [value for value, occurrences in zip(distinct, counts, strict=True) if occurrences > 1]
        return distinct[counts.index(max(counts))] if distinct else None
    if operation in ("number-variance", "number-stdev", "number-q1", "number-q3"):
        return _spread_summary(operation, [number for value in values if (number := _number(value)) is not None])
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
