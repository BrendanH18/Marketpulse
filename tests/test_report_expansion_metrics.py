"""Independent expectations for the ten summary operations added under #143.

Expected values come from the issue's specification: by hand, or from exact
``fractions.Fraction``, ``statistics`` and ``datetime`` arithmetic. Nothing here
asks the implementation what the answer should be.
"""

import copy
import json
import math
import random
import statistics
from datetime import date
from decimal import ROUND_DOWN, Inexact, getcontext, localcontext
from fractions import Fraction

import click
import pytest
from click.testing import CliRunner

from marketpulse.cli import main, reports
from marketpulse.cli.report_metrics import ALL_OPERATIONS, EXPANSION_OPERATIONS, OPERATIONS, summarize_values

# Operations 34 to 43, in the order the specification numbers them.
EXPANSION = (
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
DATE_OPERATIONS = EXPANSION[:4]
SPREAD_OPERATIONS = EXPANSION[4:8]
# Sources that existed before #143; the schemas are all these tests need from them.
SOURCES = ("accounts", "transactions", "positions", "config", "commands")


def summarize(*arguments):
    return CliRunner().invoke(main, ["summarize", *arguments])


# Exact reference arithmetic, kept apart from decimal so it cannot share a rounding mistake.


def fraction_of(cell):
    """A finite number cell as an exact fraction; a float is read by its JSON text, like the other summaries."""
    return Fraction(repr(cell)) if isinstance(cell, float) else Fraction(cell)


def adjusted_exponent(value):
    """floor(log10(value)) of a positive fraction, settled by exact comparisons."""
    guess = math.floor((value.numerator.bit_length() - value.denominator.bit_length()) * math.log10(2))
    while value >= Fraction(10) ** (guess + 1):
        guess += 1
    while value < Fraction(10) ** guess:
        guess -= 1
    return guess


def round_significant(value, digits=28):
    """Round half to even at ``digits`` significant digits."""
    if value == 0:
        return Fraction(0)
    scale = Fraction(10) ** (adjusted_exponent(abs(value)) - digits + 1)
    # round() on a Fraction rounds half to even.
    return round(value / scale) * scale


def sqrt_significant(value, digits=28):
    """The square root of a nonnegative fraction, correctly rounded half to even."""
    if value == 0:
        return Fraction(0)
    scale = Fraction(10) ** (adjusted_exponent(value) // 2 - digits + 1)
    scaled = value / scale**2
    root = math.isqrt(scaled.numerator // scaled.denominator)
    assert 10 ** (digits - 1) <= root < 10**digits
    midpoint = Fraction(2 * root + 1, 2) ** 2
    if scaled > midpoint or (scaled == midpoint and root % 2 == 1):
        root += 1
    return root * scale


def decimal_text(value):
    """The specification's decimal string for an exact, terminating fraction."""
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    magnitude, exponent = abs(value), 0
    while magnitude.denominator != 1:
        magnitude *= 10
        exponent -= 1
        assert exponent > -5000, "not a terminating decimal"
    digits = magnitude.numerator
    while digits % 10 == 0:
        digits //= 10
        exponent += 1
    coefficient = str(digits)
    adjusted = len(coefficient) - 1 + exponent
    if -6 <= adjusted <= 20:
        if exponent >= 0:
            return sign + coefficient + "0" * exponent
        if len(coefficient) > -exponent:
            return sign + coefficient[:exponent] + "." + coefficient[exponent:]
        return sign + "0." + "0" * (-exponent - len(coefficient)) + coefficient
    mantissa = coefficient[0] + ("." + coefficient[1:] if len(coefficient) > 1 else "")
    return f"{sign}{mantissa}E{'+' if adjusted >= 0 else '-'}{abs(adjusted)}"


def population_variance(numbers):
    mean = sum(numbers) / len(numbers)
    return sum((number - mean) ** 2 for number in numbers) / len(numbers)


def quartiles(numbers):
    ordered = sorted(numbers)
    if len(ordered) == 1:
        # statistics.quantiles needed two data points before Python 3.13; one value is its own quartile.
        return ordered[0], ordered[0]
    first, _, third = statistics.quantiles(ordered, n=4, method="inclusive")
    return first, third


def test_reference_helpers_reproduce_hand_values():
    assert decimal_text(Fraction(11, 2)) == "5.5"
    assert decimal_text(Fraction(-125, 100)) == "-1.25"
    assert decimal_text(Fraction(12340, 1000)) == "12.34"
    assert decimal_text(Fraction(1, 10**6)) == "0.000001"
    assert decimal_text(Fraction(1, 10**7)) == "1E-7"
    assert decimal_text(Fraction(10**20)) == "100000000000000000000"
    assert decimal_text(Fraction(10**21)) == "1E+21"
    assert decimal_text(Fraction(15, 10) * 10**25) == "1.5E+25"
    assert decimal_text(round_significant(Fraction(2, 3))) == "0.6666666666666666666666666667"
    assert decimal_text(round_significant(Fraction(1, 3))) == "0.3333333333333333333333333333"
    # Ties go to the even digit, in either direction.
    assert round_significant(Fraction(25, 10), digits=1) == 2 and round_significant(Fraction(35, 10), digits=1) == 4
    assert decimal_text(sqrt_significant(Fraction(4))) == "2"
    assert decimal_text(sqrt_significant(Fraction(2))) == "1.414213562373095048801688724"
    assert sqrt_significant(Fraction(625, 100), digits=1) == 2 and sqrt_significant(Fraction(1225, 100), digits=1) == 4
    assert quartiles([Fraction(n) for n in (2, 4, 4, 4, 5, 5, 7, 9)]) == (4, Fraction(11, 2))


# The catalog.


def test_operation_catalog():
    assert EXPANSION_OPERATIONS == EXPANSION
    assert ALL_OPERATIONS == OPERATIONS + EXPANSION_OPERATIONS
    assert len(OPERATIONS) == 40 and len(EXPANSION_OPERATIONS) == 10
    assert len(ALL_OPERATIONS) == len(set(ALL_OPERATIONS)) == 50


@pytest.mark.parametrize("source", SOURCES)
def test_describe_lists_all_fifty_operations(monkeypatch, source):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("describe loaded source"))
    result = summarize(source, "--describe")
    assert result.exit_code == 0, result.output
    operations = json.loads(result.output)["operations"]
    assert operations == [*OPERATIONS, *EXPANSION]
    assert len(operations) == len(set(operations)) == 50


# Every operation on one list of mixed cells.

VALUES = [
    None,
    "",
    True,
    False,
    0,
    1,
    1.0,
    "1",
    "2.50",
    -3,
    "oops",
    "NaN",
    "Infinity",
    [1, 2],
    [1.0, 2],
    {"x": True},
    {"x": 1},
    "2024-03-05",
    "2024-03-05T16:30:00",
    "2023-12-31",
    "2024-02-30",
    "2024-03-05",
    None,
]
# Dates: 2024-03-05 three times (one as a timestamp) and 2023-12-31; 2024-02-30 is no date.
# Numbers: 0, 1, 1.0, "1", "2.50" and -3. Mean 5/12, variance 413/144; sorted -3, 0, 1, 1, 1, 2.5.
EXPECTED = {
    "date-min": "2023-12-31",
    "date-max": "2024-03-05",
    "date-count": 4,
    "date-span": 65,
    "number-variance": "2.868055555555555555555555556",
    "number-stdev": "1.693533452741797939697648019",
    "number-q1": "0.25",
    "number-q3": "1",
    # Twice-seen values first, each group in first-encountered order. The specification does not say
    # which spelling stands for equal numbers; the first one seen (1, not 1.0) is kept here.
    "value-counts": [
        [None, 2],
        [1, 2],
        [[1, 2], 2],
        ["2024-03-05", 2],
        ["", 1],
        [True, 1],
        [False, 1],
        [0, 1],
        ["1", 1],
        ["2.50", 1],
        [-3, 1],
        ["oops", 1],
        ["NaN", 1],
        ["Infinity", 1],
        [{"x": True}, 1],
        [{"x": 1}, 1],
        ["2024-03-05T16:30:00", 1],
        ["2023-12-31", 1],
        ["2024-02-30", 1],
    ],
    "repeated-values": [None, 1, [1, 2], "2024-03-05"],
}


def test_expected_table_covers_the_expansion():
    assert tuple(EXPECTED) == EXPANSION


@pytest.mark.parametrize("operation", EXPANSION)
def test_mixed_cells(operation):
    original = copy.deepcopy(VALUES)
    result = summarize_values(operation, VALUES)
    # JSON text keeps true apart from 1 and 1 apart from 1.0.
    assert json.dumps(result) == json.dumps(EXPECTED[operation])
    assert json.dumps(VALUES) == json.dumps(original)


def test_mixed_cells_agree_with_exact_arithmetic():
    numbers = [fraction_of(cell) for cell in (0, 1, 1.0, "1", "2.50", -3)]
    variance = population_variance(numbers)
    assert variance == Fraction(413, 144)
    assert EXPECTED["number-variance"] == decimal_text(round_significant(variance))
    assert EXPECTED["number-stdev"] == decimal_text(sqrt_significant(variance))
    assert (EXPECTED["number-q1"], EXPECTED["number-q3"]) == tuple(decimal_text(q) for q in quartiles(numbers))
    assert EXPECTED["date-span"] == (date(2024, 3, 5) - date(2023, 12, 31)).days


def test_specification_example():
    values = [2, 4, 4, 4, 5, 5, 7, 9]
    assert summarize_values("number-variance", values) == "4"
    assert summarize_values("number-stdev", values) == "2"
    assert summarize_values("number-q1", values) == "4"
    assert summarize_values("number-q3", values) == "5.5"


@pytest.mark.parametrize("operation", EXPANSION)
def test_empty_input(operation):
    expected = 0 if operation == "date-count" else [] if operation in ("value-counts", "repeated-values") else None
    result = summarize_values(operation, [])
    assert result == expected and type(result) is type(expected)


NOT_DATES = [
    None,
    True,
    False,
    0,
    20240305,
    2024.0305,
    "",
    "abc",
    "2024-02-30",
    "2024-3-5",
    "20240305",
    "2024-03-05x",
    ["2024-03-05"],
    {"date": "2024-03-05"},
]
NOT_NUMBERS = [
    None,
    True,
    False,
    "",
    "abc",
    "NaN",
    "nan",
    "Infinity",
    "-Infinity",
    "inf",
    "1,5",
    "2024-03-05",
    [1],
    {"a": 1},
    float("inf"),
    float("nan"),
]


@pytest.mark.parametrize("operation", DATE_OPERATIONS)
def test_no_date_like_values(operation):
    result = summarize_values(operation, NOT_DATES)
    assert result == (0 if operation == "date-count" else None)


@pytest.mark.parametrize("operation", SPREAD_OPERATIONS)
def test_no_finite_numbers(operation):
    assert summarize_values(operation, NOT_NUMBERS) is None


def test_no_repeated_values():
    values = [None, "", 0, False, "0", [0], {"a": 0}]
    assert summarize_values("repeated-values", values) == []
    assert json.dumps(summarize_values("value-counts", values)) == json.dumps([[value, 1] for value in values])


@pytest.mark.parametrize("operation", SPREAD_OPERATIONS)
def test_ineligible_cells_are_skipped_not_counted(operation):
    numbers = [2, 4, 4, 4, 5, 5, 7, 9]
    noisy = [True, numbers[0], None, *numbers[1:4], "NaN", "Infinity", "oops", [1], *numbers[4:], {"n": 3}, False, ""]
    assert summarize_values(operation, noisy) == summarize_values(operation, numbers)
    assert summarize_values(operation, noisy) == {"variance": "4", "stdev": "2", "q1": "4", "q3": "5.5"}[operation[7:]]


# Dates.


@pytest.mark.parametrize(
    "value",
    [
        "2024-03-05",
        "2024-03-05T10:00:00",
        "2024-03-05T23:59:59.999999+05:30",
        "2024-03-05 10:00",
        "2024-03-05T",
        "2024-03-05 ",
        "2024-03-05 anything at all",
        "2024-03-05T10:00\nsecond line",
        "2024-02-29",
        "2000-02-29",
        "0001-01-01",
        "9999-12-31",
    ],
)
def test_date_like_values(value):
    assert summarize_values("date-count", [value]) == 1
    assert summarize_values("date-min", [value]) == value[:10]
    assert summarize_values("date-max", [value]) == value[:10]
    assert summarize_values("date-span", [value]) == 0


@pytest.mark.parametrize(
    "value",
    [
        "2024-02-30",
        "2024-3-5",
        "20240305",
        "2024-03-05x",
        20240305,
        None,
        "2023-02-29",
        "1900-02-29",
        "2024-13-01",
        "2024-00-10",
        "2024-01-00",
        "2024-04-31",
        "2024-03-05Z",
        "2024-03-05t10:00",
        "2024-03-05\t10:00",
        "2024-03-05\n",
        " 2024-03-05",
        "+2024-03-05",
        "2024/03/05",
        "05-03-2024",
        "2024-W10-2",
        "２０２４-03-05",
        "2024-03-٠٥",
        True,
        2024.0305,
        ["2024-03-05"],
        {"date": "2024-03-05"},
    ],
)
def test_values_that_are_not_date_like(value):
    assert summarize_values("date-count", [value]) == 0
    assert summarize_values("date-min", [value]) is None
    assert summarize_values("date-max", [value]) is None
    assert summarize_values("date-span", [value]) is None


def test_year_zero_is_not_a_date():
    # The specification asks for "a real calendar date" without saying whether year 0000 is one.
    # The implementation follows Python's calendar, which starts at year 1, and skips it.
    assert summarize_values("date-count", ["0000-01-01", "0000-12-31"]) == 0
    assert summarize_values("date-min", ["0000-01-01", "0001-01-01"]) == "0001-01-01"


def test_timestamps_reduce_to_their_date():
    values = ["2024-03-05T23:59:59Z", "2024-03-04 00:00:00", "2024-03-06T00:00:00-08:00"]
    assert summarize_values("date-min", values) == "2024-03-04"
    assert summarize_values("date-max", values) == "2024-03-06"
    assert summarize_values("date-count", values) == 3
    assert summarize_values("date-span", values) == 2


def test_dates_out_of_order_and_repeated():
    values = ["2024-12-31", "2024-01-01T09:00", "2024-06-15", "2024-12-31", "2024-01-01"]
    assert summarize_values("date-min", values) == "2024-01-01"
    assert summarize_values("date-max", values) == "2024-12-31"
    # Every date-like value counts, not every distinct day.
    assert summarize_values("date-count", values) == 5
    assert summarize_values("date-span", values) == 365
    same = ["2024-03-05", "2024-03-05", "2024-03-05T10:00"]
    assert summarize_values("date-count", same) == 3
    assert summarize_values("date-span", same) == 0
    assert summarize_values("date-min", same) == summarize_values("date-max", same) == "2024-03-05"


def test_invalid_dates_do_not_move_the_range():
    values = ["2024-02-30", "2024-03-02", None, 5, "9999-99-99", "2024-03-01", "0000-00-00", "2024-03-01x"]
    assert summarize_values("date-min", values) == "2024-03-01"
    assert summarize_values("date-max", values) == "2024-03-02"
    assert summarize_values("date-count", values) == 2
    assert summarize_values("date-span", values) == 1


@pytest.mark.parametrize(
    "first,last,days",
    [
        ("2023-12-31", "2024-01-01", 1),
        ("1999-12-31", "2000-01-01", 1),
        ("2023-01-01", "2024-01-01", 365),
        ("2024-01-01", "2025-01-01", 366),
        ("2024-02-28", "2024-03-01", 2),
        ("2023-02-28", "2023-03-01", 1),
        ("2000-02-28", "2000-03-01", 2),
        ("1900-02-28", "1900-03-01", 1),
        ("2024-02-29", "2028-02-29", 1461),
        ("2024-02-29", "2024-02-29", 0),
        ("0001-01-01", "9999-12-31", 3652058),
    ],
)
def test_date_span_across_year_boundaries_and_leap_days(first, last, days):
    assert days == date.fromisoformat(last).toordinal() - date.fromisoformat(first).toordinal()
    for values in ([first, last], [last, first], [last + "T12:00:00", "bad", first + " 08:00", None]):
        result = summarize_values("date-span", values)
        assert result == days and type(result) is int


# Variance and deviation.

SPREAD = [
    ([2, 4, 4, 4, 5, 5, 7, 9], "4", "2"),
    ([3, 7, 7, 19], "36", "6"),
    ([0, 2], "1", "1"),
    # A single number and all-equal numbers have no spread.
    ([7], "0", "0"),
    (["-3.25"], "0", "0"),
    ([-0.0], "0", "0"),
    ([5, 5.0, "5.00", "5"], "0", "0"),
    ([1, 2, 3, 4], "1.25", "1.118033988749894848204586834"),
    ([-1, -2, -3, -4], "1.25", "1.118033988749894848204586834"),
    (["1", 2, "3.0", 4.0], "1.25", "1.118033988749894848204586834"),
    (["1250.50", "-320.25", "89.99", "0.01", "1250.50"], "441379.53004", "664.3640041724114962512886806"),
    ([0.1, 0.2, 0.3], "0.006666666666666666666666666667", "0.08164965809277260327324280249"),
    # 14/9 does not terminate.
    ([1, 2, 4], "1.555555555555555555555555556", "1.247219128924647128527916244"),
    # Float arithmetic loses these: the answer is 2/3 however large the offset.
    ([10**15 + 1, 10**15 + 2, 10**15 + 3], "0.6666666666666666666666666667", "0.8164965809277260327324280249"),
    ([10**30 + 1, 10**30 + 2, 10**30 + 3], "0.6666666666666666666666666667", "0.8164965809277260327324280249"),
    ([10**30 + 1, str(10**30 + 2), float(10**30 + 3)], "0.6666666666666666666666666667", None),
    (["0.1234567890123456789012345678901", "0.1234567890123456789012345678903"], "1E-62", "1E-31"),
    # Exact while it fits 28 digits: 1.0000000000001 squared has 27.
    (["0", "2.0000000000002"], "1.00000000000020000000000001", "1.0000000000001"),
    (["0", "2.469135780246913578024691356"], "1.524157875323883675049535154", "1.234567890123456789012345678"),
    # Exact variances of 29 digits, ...0025 and ...0075: half to even takes one down and the other up.
    (["0", "2.0000000000001"], "1.000000000000100000000000002", "1.00000000000005"),
    (["0", "0", "0", "4.0000000000002"], "3.000000000000300000000000008", "1.732050807568963896067824785"),
    # Notation switches outside adjusted exponents -6 to 20.
    ([0, "2e20"], "1E+40", "100000000000000000000"),
    ([0, "2e21"], "1E+42", "1E+21"),
    ([0, "2e25"], "1E+50", "1E+25"),
    ([0, "0.000002"], "1E-12", "0.000001"),
    ([0, "0.0000002"], "1E-14", "1E-7"),
    ([0, "2e-30"], "1E-60", "1E-30"),
]


@pytest.mark.parametrize("values,variance,deviation", SPREAD)
def test_variance_and_deviation(values, variance, deviation):
    exact = population_variance([fraction_of(cell) for cell in values])
    # The hand-written figures and the exact fraction arithmetic must agree before either judges the code.
    assert variance == decimal_text(round_significant(exact))
    assert deviation in (None, decimal_text(sqrt_significant(exact)))
    assert summarize_values("number-variance", values) == variance
    assert summarize_values("number-stdev", values) == decimal_text(sqrt_significant(exact))


def operand(rng):
    """A short fictional number cell: operands this small cannot land on a 29th-digit tie."""
    kind = rng.randrange(4)
    if kind == 0:
        return rng.randint(-1000, 1000)
    if kind == 1:
        return f"{rng.randint(-999, 999)}.{rng.randint(0, 9999):04d}"
    if kind == 2:
        return f"{rng.randint(-99, 99)}e{rng.randint(-3, 3)}"
    return rng.randint(-4000, 4000) / 8


def test_spread_matches_exact_fraction_arithmetic():
    rng = random.Random(143)
    for size in range(1, 13):
        for _ in range(20):
            cells = [operand(rng) for _ in range(size)]
            numbers = [fraction_of(cell) for cell in cells]
            variance = population_variance(numbers)
            first, third = quartiles(numbers)
            assert summarize_values("number-variance", cells) == decimal_text(round_significant(variance)), cells
            assert summarize_values("number-stdev", cells) == decimal_text(sqrt_significant(variance)), cells
            assert summarize_values("number-q1", cells) == decimal_text(first), cells
            assert summarize_values("number-q3", cells) == decimal_text(third), cells


# Two values deviate by exactly half their difference, so a difference of 28 digits or more whose last
# digit is odd puts the deviation exactly halfway between two 28-digit decimals.
ODD_TIES = [
    # 1.0000000000000000000000000015
    (["0", "2.000000000000000000000000003"], "1.000000000000000000000000002"),
    # 1500000000000000000000000001.5
    ([0, 3 * 10**27 + 3], "1.500000000000000000000000002E+27"),
    # 4200373054.4707307280871095495
    (["-8400746103.041461456174219099", "5.9"], "4200373054.47073072808710955"),
]
# 1.0000000000000000000000000025: the 28th digit is even, so half to even rounds down.
EVEN_TIE = (["0", "2.000000000000000000000000005"], "1.000000000000000000000000002")
# 4.00000000000000000000000000050000000000000000000000000001 is above the midpoint between 4 and
# 4.000000000000000000000000001, so no rounding rule gives 4.
ABOVE_MIDPOINT = (["0", "8.00000000000000000000000000100000000000000000000000000002"], "4.000000000000000000000000001")


def test_deviation_rounding_expectations_are_exact():
    # Kept apart from the expected failures below, so a slip in these figures cannot hide as one.
    for values, expected in (*ODD_TIES, EVEN_TIE, ABOVE_MIDPOINT):
        low, high = sorted(fraction_of(cell) for cell in values)
        variance = population_variance([low, high])
        assert variance == ((high - low) / 2) ** 2
        assert decimal_text(sqrt_significant(variance)) == expected
    assert (Fraction(ABOVE_MIDPOINT[0][1]) / 2) > Fraction("4.0000000000000000000000000005")


def test_deviation_tie_toward_an_even_digit():
    values, expected = EVEN_TIE
    assert summarize_values("number-stdev", values) == expected


@pytest.mark.parametrize("values,expected", ODD_TIES)
def test_deviation_tie_rounds_half_to_even(values, expected):
    assert summarize_values("number-stdev", values) == expected


def test_deviation_just_above_a_midpoint_rounds_up():
    values, expected = ABOVE_MIDPOINT
    assert summarize_values("number-stdev", values) == expected


EXTREME = ["1e500000", "9e999999"]


@pytest.mark.parametrize("value", EXTREME)
def test_extreme_magnitudes_are_finite_numbers(value):
    # The older summaries and the quartiles accept these single numbers.
    assert summarize_values("number-count", [value]) == 1
    assert summarize_values("number-min", [value]) == value.replace("e", "E+")
    assert summarize_values("number-q1", [value]) == summarize_values("number-q3", [value]) == value.replace("e", "E+")


@pytest.mark.parametrize("operation", ["number-variance", "number-stdev"])
@pytest.mark.parametrize("value", EXTREME)
def test_single_number_of_extreme_magnitude_has_no_spread(operation, value):
    assert summarize_values(operation, [value]) == "0"


def test_ambient_decimal_context_is_left_unchanged():
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        context.clear_flags()
        before = context.copy()
        assert summarize_values("number-variance", [1, 2, 4]) == "1.555555555555555555555555556"
        assert summarize_values("number-stdev", [1, 2, 3, 4]) == "1.118033988749894848204586834"
        assert summarize_values("number-variance", ["0", "2.0000000000001"]) == "1.000000000000100000000000002"
        assert summarize_values("number-q1", ["1.01", "1.02", "bad", "NaN", None]) == "1.0125"
        assert summarize_values("number-q3", ["1.01", "1.02", "Infinity", True]) == "1.0175"
        for operation in SPREAD_OPERATIONS:
            assert summarize_values(operation, ["bad", "NaN", "Infinity", float("inf"), True]) is None
            with pytest.raises(click.ClickException):
                summarize_values(operation, ["1e10000", "0.1"])
        # The deviation 1E-999999 is in range; the variance 1E-1999998 is not.
        assert summarize_values("number-stdev", ["1e-999999", "3e-999999"]) == "1E-999999"
        with pytest.raises(click.ClickException):
            summarize_values("number-variance", ["1e-999999", "3e-999999"])
        current = getcontext()
        assert current.prec == before.prec == 3 and current.rounding == before.rounding
        assert current.Emin == before.Emin and current.Emax == before.Emax
        assert current.traps == before.traps and current.flags == before.flags
    # The same holds in whatever context the process already had.
    before = getcontext().copy()
    for operation in SPREAD_OPERATIONS:
        summarize_values(operation, [1, 2, 4, "oops", "NaN", "0.1"])
    current = getcontext()
    assert current.prec == before.prec and current.rounding == before.rounding
    assert current.traps == before.traps and current.flags == before.flags


def test_arithmetic_beyond_the_limits_fails_cleanly():
    for operation in SPREAD_OPERATIONS:
        with pytest.raises(click.ClickException, match="10,000"):
            summarize_values(operation, ["1e10000", "0.1"])
    # The other numeric summaries already refuse results outside decimal's default exponent range;
    # these variances would be 1E-1999998 and 2.5E+1199999. Their deviations are in range and exact.
    for values, deviation in ((["1e-999999", "3e-999999"], "1E-999999"), (["1e600000", "2e600000"], "5E+599999")):
        with pytest.raises(click.ClickException, match="decimal range"):
            summarize_values("number-variance", values)
        assert summarize_values("number-stdev", values) == deviation
    with pytest.raises(click.UsageError, match="Unknown summary"):
        summarize_values("number-q2", [1, 2])


def test_digit_limit_is_measured_on_the_operands():
    # The specification refuses "arithmetic that would need more than 10,000 working digits" without
    # saying how the need is measured. The implementation measures the digits the operands span
    # together, which this pins down in both directions.
    wide = ["1e6000", "1"]
    # The exact variance is ((1E+6000 - 1) / 2) squared. Its intermediate needs about 12,000 digits,
    # and it is still answered, correctly.
    assert summarize_values("number-variance", wide) == "2.5E+11999"
    assert summarize_values("number-stdev", wide) == "5E+5999"
    # The first quartile of 0.1, 5 and 1E+10000 is 2.55 and needs three digits, but it is refused.
    with pytest.raises(click.ClickException, match="10,000"):
        summarize_values("number-q1", ["0.1", "5", "1e10000"])
    # Equal operands span nothing, however large they are.
    assert summarize_values("number-variance", ["1e10000", "1e10000"]) == "0"
    assert summarize_values("number-q3", ["1e10000", "1e10000"]) == "1E+10000"


# Quartiles.

QUARTILES = [
    ([7], "7", "7"),
    ([1, 2], "1.25", "1.75"),
    ([1, 2, 3], "1.5", "2.5"),
    ([1, 2, 3, 4], "1.75", "3.25"),
    ([1, 2, 3, 4, 5], "2", "4"),
    ([1, 2, 3, 4, 5, 6], "2.25", "4.75"),
    ([1, 2, 3, 4, 5, 6, 7], "2.5", "5.5"),
    ([2, 4, 4, 4, 5, 5, 7, 9], "4", "5.5"),
    (list(range(1, 10)), "3", "7"),
    (list(range(1, 14)), "4", "10"),
    # Unsorted input and duplicates.
    ([9, 2, 7, 4, 5, 4, 5, 4], "4", "5.5"),
    ([3, 1, 2], "1.5", "2.5"),
    ([5, 5, 5, 5], "5", "5"),
    ([1, 1, 2, 2], "1", "2"),
    # Decimals, negative numbers and mixed spellings.
    (["0.1", "0.2", "0.4"], "0.15", "0.3"),
    (["1.01", "1.02"], "1.0125", "1.0175"),
    ([0.1, 0.2, 0.3], "0.15", "0.25"),
    ([-5, -1, 0, 3], "-2", "0.75"),
    ([-4, -3, -2, -1], "-3.25", "-1.75"),
    ([-1, 1], "-0.5", "0.5"),
    ([10, "20", 30.0, "4e1"], "17.5", "32.5"),
    (["-0", "0.000"], "0", "0"),
    # Exact at any magnitude.
    ([10**15 + 1, 10**15 + 2, 10**15 + 3], "1000000000000001.5", "1000000000000002.5"),
    # 10**30 + 0.25 has an adjusted exponent of 30, so it is written in scientific notation.
    ([10**30, 10**30 + 1], "1." + "0" * 30 + "25E+30", "1." + "0" * 30 + "75E+30"),
    (["1e30", "3e30"], "1.5E+30", "2.5E+30"),
    (["1e-10", "3e-10"], "1.5E-10", "2.5E-10"),
    (["1e20", "3e20"], "15" + "0" * 19, "25" + "0" * 19),
    (["1e-6", "3e-6"], "0.0000015", "0.0000025"),
]


@pytest.mark.parametrize("values,first,third", QUARTILES)
def test_quartiles(values, first, third):
    numbers = [fraction_of(cell) for cell in values]
    # statistics.quantiles on fractions is the inclusive method, exactly.
    assert (first, third) == tuple(decimal_text(quartile) for quartile in quartiles(numbers))
    assert summarize_values("number-q1", values) == first
    assert summarize_values("number-q3", values) == third


def test_quartiles_far_apart_are_exact():
    values = ["1e20", "1e-20"]
    # 1E-20 + (1E+20 - 1E-20) / 4 and 1E-20 + 3 (1E+20 - 1E-20) / 4: 42 significant digits each.
    first = "25" + "0" * 18 + "." + "0" * 20 + "75"
    third = "75" + "0" * 18 + "." + "0" * 20 + "25"
    assert (first, third) == tuple(decimal_text(quartile) for quartile in quartiles([Fraction(v) for v in values]))
    assert summarize_values("number-q1", values) == first
    assert summarize_values("number-q3", values) == third


def test_quartiles_skip_ineligible_cells():
    values = [True, None, "x", 1, "2", 3.0, [4], {"v": 5}, "NaN", "Infinity", False]
    assert summarize_values("number-q1", values) == "1.5"
    assert summarize_values("number-q3", values) == "2.5"


# Value counts and repeated values.


def test_typed_distinctness():
    values = [
        False,
        0,
        0.0,
        True,
        1,
        1.0,
        "1",
        "1.0",
        None,
        "",
        [1],
        [1.0],
        [True],
        ["1"],
        {"a": 1, "b": [False]},
        {"b": [False], "a": 1.0},
        {"a": True, "b": [0]},
    ]
    original = copy.deepcopy(values)
    counts = summarize_values("value-counts", values)
    assert json.dumps(counts) == json.dumps(
        [
            [0, 2],
            [1, 2],
            [[1], 2],
            [{"a": 1, "b": [False]}, 2],
            [False, 1],
            [True, 1],
            ["1", 1],
            ["1.0", 1],
            [None, 1],
            ["", 1],
            [[True], 1],
            [["1"], 1],
            [{"a": True, "b": [0]}, 1],
        ]
    )
    assert json.dumps(summarize_values("repeated-values", values)) == json.dumps([0, 1, [1], {"a": 1, "b": [False]}])
    assert json.dumps(values) == json.dumps(original)
    assert all(type(pair) is list and len(pair) == 2 and type(pair[1]) is int for pair in counts)


def test_null_is_counted():
    assert summarize_values("value-counts", [None, "a", None]) == [[None, 2], ["a", 1]]
    assert summarize_values("repeated-values", [None, "a", None]) == [None]
    assert summarize_values("value-counts", [None]) == [[None, 1]]
    assert summarize_values("repeated-values", [None]) == []


def test_tie_order_and_sort_stability():
    values = ["b", "a", "b", "c", "a", "c", "d", "c", "e"]
    assert summarize_values("value-counts", values) == [["c", 3], ["b", 2], ["a", 2], ["d", 1], ["e", 1]]
    # First-encountered order, not the order in which values became repeated.
    assert summarize_values("repeated-values", ["b", "a", "a", "b", "c", "c", "c", "d"]) == ["b", "a", "c"]
    # Many equally frequent values keep their order on both sides of a more frequent one.
    spread = [*range(20), 7, *range(20, 40)]
    assert summarize_values("value-counts", spread) == [[7, 2], *([n, 1] for n in range(40) if n != 7)]
    assert summarize_values("repeated-values", spread) == [7]


def test_large_integers_stay_distinct_from_nearby_floats():
    # 1e23 as a float is 99999999999999991611392, not 10**23.
    values = [10**23, 1e23, 2**53 + 1, float(2**53), 10**23]
    assert summarize_values("value-counts", values) == [[10**23, 2], [1e23, 1], [2**53 + 1, 1], [float(2**53), 1]]
    assert summarize_values("repeated-values", values) == [10**23]


def test_counts_agree_with_the_older_distinct_operations():
    for values in (VALUES, [], ["x"], [None, None, 0, False, 0.0, "0"]):
        counts = summarize_values("value-counts", values)
        assert sum(count for _, count in counts) == len(values)
        assert len(counts) == summarize_values("distinct", values)
        assert json.dumps(sorted(json.dumps(value) for value, _ in counts)) == json.dumps(
            sorted(json.dumps(value) for value in summarize_values("distinct-values", values))
        )
        assert len(summarize_values("repeated-values", values)) == sum(count > 1 for _, count in counts)
        if values:
            assert json.dumps(counts[0]) == json.dumps(
                [summarize_values("mode", values), summarize_values("mode-count", values)]
            )


# Through the command line.

# Operation, field values, expected result: the same independent style as the older forty.
CASES = [
    ("date-min", [None, "2024-05-01", "2024-02-30", "2023-11-30T08:00:00", 20230101], "2023-11-30"),
    ("date-max", [None, "2024-05-01", "2024-13-01", "2023-11-30T08:00:00", "9999-99-99"], "2024-05-01"),
    ("date-count", ["2024-05-01", "2024-05-01", "2024-05-01 09:00", "2024-5-1", "", None, True], 3),
    ("date-span", ["2024-03-01", "bad", "2024-02-28", None], 2),
    ("number-variance", [False, "bad", 2, "4", 4.0, 4, 5, "5.0", 7, 9], "4"),
    ("number-stdev", [False, "bad", 2, "4", 4.0, 4, 5, "5.0", 7, 9], "2"),
    ("number-q1", [None, 9, "2", 7, 4, 5.0, "4", 5, 4], "4"),
    ("number-q3", [None, 9, "2", 7, 4, 5.0, "4", 5, 4], "5.5"),
    ("value-counts", [0, False, "0", 0.0, None, False, 0], [[0, 3], [False, 2], ["0", 1], [None, 1]]),
    ("repeated-values", [0, False, "0", 0.0, None, False, 0, [1], [1.0]], [0, False, [1]]),
]


def test_cases_cover_the_expansion():
    assert tuple(case[0] for case in CASES) == EXPANSION


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_expansion_operations_on_saved_sources(monkeypatch, source, case):
    operation, values, expected = case
    schema = reports.SOURCES[source]
    field = schema[0]
    rows = [{**dict.fromkeys(schema), field: value} for value in values]
    before = json.dumps(rows)
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    result = summarize(source, "--metric", f"result={operation}:{field}")
    assert result.exit_code == 0, result.output
    assert json.dumps(json.loads(result.output)) == json.dumps([{"result": expected}])
    assert json.dumps(rows) == before


def test_all_ten_results_in_one_summary(monkeypatch):
    rows = [{"key": "k", "value": value} for value in ("2024-01-31", 2, "2024-03-01T07:00", "4", 4, None, 4.0)]
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    # Metric names must be distinct identifiers, so each takes the last two letters of its operation.
    assert len({name[-2:] for name in EXPANSION}) == 10
    metrics = [part for name in EXPANSION for part in ("--metric", f"m_{name[-2:]}={name}:value")]
    result = summarize("config", *metrics)
    assert result.exit_code == 0, result.output
    # Numbers 2, 4, 4, 4: mean 3.5, variance 0.75, deviation half the root of 3.
    assert decimal_text(sqrt_significant(Fraction(3, 4))) == "0.8660254037844386467637231708"
    assert result.output == (
        '[{"m_in": "2024-01-31", "m_ax": "2024-03-01", "m_nt": 2, "m_an": 30, "m_ce": "0.75", '
        '"m_ev": "0.8660254037844386467637231708", "m_q1": "3.5", "m_q3": "4", '
        '"m_ts": [[4, 2], ["2024-01-31", 1], [2, 1], ["2024-03-01T07:00", 1], ["4", 1], [null, 1]], '
        '"m_es": [4]}]\n'
    )


def grouped_rows(groups):
    return [{"key": key, "value": value} for key, values in groups.items() for value in values]


DAY = "2024-03-01"
# Operation, the cells of each group, and the groups in ascending order of the result. A group named
# "none" has no eligible value, so its result is null and stays last in both directions.
SORTS = [
    # Decimal strings 9, 10 and 100 (as text: 10, 100, 9).
    ("number-stdev", {"a": [0, 20], "b": [0, 18], "c": [0, 200], "none": ["n/a"]}, ["b", "a", "c"]),
    # 9, 100 and 10000 (as text: 100, 10000, 9).
    ("number-variance", {"a": [0, 20], "b": [0, 6], "c": [0, 200], "none": [None]}, ["b", "a", "c"]),
    # 9, 10 and 101, then 9, 10 and 103.
    ("number-q1", {"a": [10, 10], "b": [9, 9], "c": [100, 104], "none": [True]}, ["b", "a", "c"]),
    ("number-q3", {"a": [10, 10], "b": [9, 9], "c": [100, 104], "none": [[]]}, ["b", "a", "c"]),
    # Spans of 10, 9 and 100 days.
    (
        "date-span",
        {
            "a": ["2024-03-01", "2024-03-11"],
            "b": ["2023-12-25", "2024-01-03"],
            "c": ["2024-01-15", "2024-04-24"],
            "none": ["n/a"],
        },
        ["b", "a", "c"],
    ),
    # Counts of 10, 9 and 2; a count is never null.
    ("date-count", {"a": [DAY] * 10, "b": [DAY] * 9, "c": [DAY] * 2}, ["c", "b", "a"]),
    # Text results.
    (
        "date-min",
        {"a": ["2024-03-01", "2024-03-11"], "b": ["2023-12-25"], "c": ["2024-01-15"], "none": [5]},
        ["b", "c", "a"],
    ),
    (
        "date-max",
        {"a": ["2024-03-01", "2024-03-11"], "b": ["2023-12-25"], "c": ["2024-01-15"], "none": [5]},
        ["b", "c", "a"],
    ),
    # As text: [["x", 1]], [[10, 1]], [[9, 1]].
    ("value-counts", {"a": [10], "b": [9], "c": ["x"]}, ["c", "a", "b"]),
    # As text: [10], [9], [].
    ("repeated-values", {"a": [10, 10], "b": [9, 9], "c": ["x", "y"]}, ["a", "b", "c"]),
]


def test_sorts_cover_the_expansion():
    assert len(SORTS) == 10 and {case[0] for case in SORTS} == set(EXPANSION)


@pytest.mark.parametrize("descending", [False, True])
@pytest.mark.parametrize("case", SORTS, ids=[case[0] for case in SORTS])
def test_sorting_by_each_kind_of_result(monkeypatch, case, descending):
    operation, groups, ascending = case
    monkeypatch.setattr(reports, "load_source", lambda *args: grouped_rows(groups))
    result = summarize(
        "config",
        "--group-by",
        "key",
        "--metric",
        f"result={operation}:value",
        "--sort",
        "result",
        *(["--descending"] if descending else []),
    )
    assert result.exit_code == 0, result.output
    missing = [key for key in groups if key == "none"]
    assert [row["key"] for row in json.loads(result.output)] == (ascending[::-1] if descending else ascending) + missing


def test_sorted_results_have_the_expected_values(monkeypatch):
    groups = {"a": [0, 20, "2024-03-01", "2024-03-11"], "b": [0, 18, "2023-12-25", "2024-01-03"], "none": [None]}
    monkeypatch.setattr(reports, "load_source", lambda *args: grouped_rows(groups))
    result = summarize(
        "config",
        "--group-by",
        "key",
        "--metric",
        "deviation=number-stdev:value",
        "--metric",
        "span=date-span:value",
        "--metric",
        "first=date-min:value",
        "--sort",
        "deviation",
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [
        {"key": "b", "deviation": "9", "span": 9, "first": "2023-12-25"},
        {"key": "a", "deviation": "10", "span": 10, "first": "2024-03-01"},
        {"key": "none", "deviation": None, "span": None, "first": None},
    ]


@pytest.mark.parametrize("operation", EXPANSION)
def test_each_operation_requires_a_field(monkeypatch, operation):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("invalid metric loaded source"))
    for specification in (operation, f"{operation}:", f"{operation}:bogus"):
        result = summarize("config", "--metric", f"n={specification}")
        assert result.exit_code == 2, result.output
        assert f"Operation '{operation}' requires a field from: key, value." in result.output


@pytest.mark.parametrize(
    "operation",
    ["date-range", "number-var", "number-q2", "value_counts", "DATE-MIN", "stdev", "date-min ", "repeated-value"],
)
def test_unknown_operations_fail_before_loading(monkeypatch, operation):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("unknown operation loaded source"))
    result = summarize("config", "--metric", f"n={operation}:value")
    assert result.exit_code == 2, result.output
    assert f"Unknown summary operation '{operation}'" in result.output
    with pytest.raises(click.UsageError, match="Unknown summary"):
        summarize_values(operation, [])


@pytest.mark.parametrize("operation", SPREAD_OPERATIONS)
def test_arithmetic_error_is_a_clean_cli_error(monkeypatch, tmp_path, operation):
    rows = [{"key": "a", "value": "1e10000"}, {"key": "a", "value": "0.1"}]
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    target = tmp_path / "summary.json"
    result = summarize("config", "--metric", f"n={operation}:value", "--output", str(target))
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert result.output == "Error: Summary arithmetic requires more than 10,000 decimal digits.\n"
    assert list(tmp_path.iterdir()) == []
