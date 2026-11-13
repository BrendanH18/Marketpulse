"""Independent examples for the 40 saved-cell summary operations."""

import copy
import json
from decimal import ROUND_DOWN, Inexact, localcontext

import click
import pytest

from marketpulse.cli.report_metrics import OPERATIONS, summarize_values

VALUES = [
    None,
    "",
    [],
    {},
    False,
    True,
    0,
    1,
    1.0,
    "2.50",
    -3,
    "oops",
    [False],
    [0],
    {"x": True},
    {"x": 1},
    "a",
    "z",
    "a",
]
EXPECTED = {
    "count": 19,
    "present": 17,
    "missing": 2,
    "empty": 4,
    "nonempty": 15,
    "distinct": 17,
    "duplicates": 2,
    "first": None,
    "last": "a",
    "first-present": [],
    "last-present": "a",
    "mode": 1,
    "mode-count": 2,
    "values": VALUES,
    "distinct-values": VALUES[:8] + VALUES[9:18],
    "number-count": 5,
    "number-distinct": 4,
    "number-sum": "1.5",
    "number-min": "-3",
    "number-max": "2.5",
    "number-mean": "0.3",
    "number-median": "1",
    "number-range": "5.5",
    "positive-count": 3,
    "negative-count": 1,
    "zero-count": 1,
    "positive-sum": "4.5",
    "negative-sum": "-3",
    "absolute-sum": "7.5",
    "true-count": 1,
    "false-count": 1,
    "string-count": 6,
    "array-count": 3,
    "object-count": 3,
    "length-sum": 15,
    "length-min": 0,
    "length-max": 4,
    "length-mean": "1.25",
    "text-min": "",
    "text-max": "z",
}


@pytest.mark.parametrize("operation", EXPECTED)
def test_mixed_cells(operation):
    original = copy.deepcopy(VALUES)
    result = summarize_values(operation, VALUES)
    assert json.dumps(result) == json.dumps(EXPECTED[operation])
    assert json.dumps(VALUES) == json.dumps(original)


def test_complete_operation_catalog():
    assert len(OPERATIONS) == len(set(OPERATIONS)) == 40
    assert set(OPERATIONS) == set(EXPECTED)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_empty_input(operation):
    zeroes = {
        "count",
        "present",
        "missing",
        "empty",
        "nonempty",
        "distinct",
        "duplicates",
        "mode-count",
        "number-count",
        "number-distinct",
        "positive-count",
        "negative-count",
        "zero-count",
        "true-count",
        "false-count",
        "string-count",
        "array-count",
        "object-count",
        "length-sum",
    }
    expected = (
        0
        if operation in zeroes
        else "0"
        if operation.endswith("-sum")
        else []
        if operation in ("values", "distinct-values")
        else None
    )
    assert summarize_values(operation, []) == expected


def test_nested_typed_identity_and_mode_ties():
    values = [{"b": [True], "a": 1}, {"a": 1.0, "b": [True]}, {"a": True, "b": [1]}, [1], [True]]
    assert summarize_values("distinct", values) == 4
    assert summarize_values("duplicates", values) == 1
    assert summarize_values("mode", values) is values[0]
    assert summarize_values("mode-count", values) == 2
    assert json.dumps(summarize_values("distinct-values", values)) == json.dumps([values[i] for i in (0, 2, 3, 4)])


def test_decimal_precision_and_mean_rounding_are_local():
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        before = context.copy()
        assert summarize_values("number-sum", ["123456789012345678901234567890", "0.123456789"]) == (
            "1.23456789012345678901234567890123456789E+29"
        )
        assert summarize_values("number-mean", ["1", "0", "0"]) == "0.3333333333333333333333333333"
        assert summarize_values("number-median", ["1.01", "1.02"]) == "1.015"
        assert summarize_values("number-range", ["0.000001", "100000000000000000000"]) == (
            "99999999999999999999.999999"
        )
        assert summarize_values("number-count", ["bad", "NaN", "Infinity", float("inf"), True]) == 0
        assert context.prec == before.prec and context.rounding == before.rounding
        assert context.traps == before.traps and context.flags == before.flags


@pytest.mark.parametrize(
    "value,expected",
    [("0.000001", "0.000001"), ("0.0000001", "1E-7"), ("1e21", "1E+21"), ("-0.00", "0"), ("12.3400", "12.34")],
)
def test_decimal_output_notation(value, expected):
    assert summarize_values("number-min", [value]) == expected


def test_numeric_parsing_and_sign_counts():
    values = [" 2 ", "2.0", "+2e0", "-0", -0.0, "-1.5", False, True, "inf", "-Infinity", "nan", "bad", [], {}]
    assert summarize_values("number-count", values) == 6
    assert summarize_values("number-distinct", values) == 3
    assert summarize_values("positive-count", values) == 3
    assert summarize_values("negative-count", values) == 1
    assert summarize_values("zero-count", values) == 2
    assert summarize_values("number-sum", values) == "4.5"


def test_arithmetic_errors_are_clean():
    with pytest.raises(click.ClickException, match="10,000"):
        summarize_values("number-sum", ["1e10000", "0.1"])
    with pytest.raises(click.ClickException, match="decimal range"):
        summarize_values("number-sum", ["9e999999", "9e999999"])
    with pytest.raises(click.ClickException, match="decimal range"):
        summarize_values("number-sum", ["1e-1000100"])
    with pytest.raises(click.ClickException, match="decimal range"):
        summarize_values("number-mean", ["1e-1000026", 0])
    with pytest.raises(click.UsageError, match="Unknown summary"):
        summarize_values("invalid", [])
