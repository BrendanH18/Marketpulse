"""Filtering semantics for composable saved-data reports."""

import math

import click
import pytest

from marketpulse.cli.report_filters import FILTER_OPTIONS, compile_filters


def matches(option, argument, values):
    predicate = compile_filters(("value", "other"), {option: (argument,)})
    return [value for value in values if predicate({"value": value, "other": None})]


def test_twenty_distinct_filter_operations():
    assert len(FILTER_OPTIONS) == len(set(FILTER_OPTIONS)) == 20


@pytest.mark.parametrize(
    ("option", "argument", "expected"),
    [
        ("ieq", "value=STRASSE", ["Straße", "STRASSE"]),
        ("ine", "value=STRASSE", ["other", None]),
        ("not_contains", "value=RAS", ["other", None]),
        ("not_prefix", "value=STR", ["other", None]),
        ("not_suffix", "value=SSE", ["other", None]),
        ("glob", "value=STR*", ["STRASSE"]),
    ],
)
def test_unicode_text_and_case_sensitive_globs(option, argument, expected):
    assert matches(option, argument, ["Straße", "STRASSE", "other", None]) == expected


def test_text_json_representation_and_equals_in_value():
    assert matches("ieq", "value=TRUE", [True, False]) == [True]
    assert matches("ieq", "value=", [None, "", 0]) == [None, ""]
    assert matches("ieq", "value=a=b", ["a=b", "ab"]) == ["a=b"]
    assert matches("glob", 'value=*"x":*', [{"x": 2}, {"y": 2}]) == [{"x": 2}]


@pytest.mark.parametrize(
    ("option", "argument", "expected"),
    [
        ("gt", "value=2", [10, "2.01"]),
        ("ge", "value=2", [2, 10, "2.01"]),
        ("lt", "value=2", [-1, 1, "1e-3"]),
        ("le", "value=2", [-1, 1, 2, "1e-3"]),
        ("between", "value=1,2", [1, 2]),
        ("outside", "value=1,2", [-1, 10, "2.01", "1e-3"]),
    ],
)
def test_finite_numeric_comparisons_exclude_boolean_and_missing(option, argument, expected):
    values = [-1, 1, 2, 10, "2.01", "1e-3", None, "", "nope", True, False, [], {}, math.inf, math.nan]
    assert matches(option, argument, values) == expected


def test_range_can_have_equal_bounds_and_large_precise_values():
    assert matches("between", "value=2,2", [1, 2, 3]) == [2]
    assert matches("outside", "value=2,2", [1, 2, 3]) == [1, 3]
    assert matches("gt", "value=9007199254740992", [9007199254740992, 9007199254740993]) == [9007199254740993]


def test_membership_is_typed_and_nested():
    values = [True, 1, 1.0, "1", None, [True], [1], {"x": True}, {"x": 1}]
    assert matches("in_values", "value=[1]", values) == [1, 1.0]
    assert matches("in_values", "value=[true]", values) == [True]
    assert matches("in_values", 'value=["1",null,[1],{"x":1}]', values) == ["1", None, [1], {"x": 1}]
    assert matches("not_in", "value=[1]", values) == [True, "1", None, [True], [1], {"x": True}, {"x": 1}]
    assert matches("in_values", "value=[]", values) == []
    assert matches("not_in", "value=[]", values) == values
    assert matches("in_values", 'value=[{"a":1,"b":2}]', [{"b": 2, "a": 1}]) == [{"b": 2, "a": 1}]


def test_empty_and_nonempty_distinguish_false_and_zero():
    values = [None, "", [], {}, 0, False, " ", [None], {"a": None}]
    assert matches("empty", "value", values) == values[:4]
    assert matches("nonempty", "value", values) == values[4:]


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("string", ["", "x", "2"]),
        ("number", [0, 2.5]),
        ("boolean", [True, False]),
        ("array", [[]]),
        ("object", [{}]),
        ("null", [None]),
    ],
)
def test_native_json_type_selection(kind, expected):
    assert matches("is_type", "value=" + kind, [None, "", "x", "2", 0, 2.5, True, False, [], {}]) == expected


@pytest.mark.parametrize(
    ("option", "expected"),
    [
        ("length", ["ab", [1, 2], {"a": 1, "b": 2}]),
        ("min_length", ["ab", "abc", [1, 2], {"a": 1, "b": 2}]),
        ("max_length", ["", "a", "ab", [], [1, 2], {}, {"a": 1, "b": 2}]),
    ],
)
def test_length_of_text_arrays_and_objects_only(option, expected):
    values = ["", "a", "ab", "abc", [], [1, 2], {}, {"a": 1, "b": 2}, None, 2, True]
    assert matches(option, "value=2", values) == expected


def test_repeated_filters_and_separate_fields_combine_with_and():
    predicate = compile_filters(
        ("value", "other"), {"gt": ("value=1", "other=5"), "lt": ("value=10",), "not_in": ("value=[3]",)}
    )
    rows = [{"value": value, "other": other} for value, other in [(0, 9), (2, 4), (2, 6), (3, 7), (10, 8)]]
    assert list(filter(predicate, rows)) == [{"value": 2, "other": 6}]
    assert compile_filters(("value",), {})({"value": None})


@pytest.mark.parametrize(
    ("option", "argument"),
    [
        ("ieq", "unknown=x"),
        ("ieq", "value"),
        ("empty", "value=x"),
        ("nonempty", "unknown"),
        ("gt", "value=NaN"),
        ("ge", "value=Infinity"),
        ("lt", "value=x"),
        ("le", "value="),
        ("between", "value=2,1"),
        ("between", "value=1"),
        ("between", "value=1,2,3"),
        ("outside", "value=1,NaN"),
        ("in_values", "value={}"),
        ("not_in", "value=invalid"),
        ("in_values", "value=[NaN]"),
        ("in_values", "value=[Infinity]"),
        ("in_values", "value=[1e999]"),
        ("is_type", "value=int"),
        ("length", "value=2.5"),
        ("min_length", "value=-1"),
        ("max_length", "value=NaN"),
        ("bogus", "value=x"),
    ],
)
def test_invalid_filter_is_rejected_when_compiled(option, argument):
    with pytest.raises(click.UsageError):
        compile_filters(("value",), {option: (argument,)})


def test_invalid_later_condition_is_not_hidden_by_earlier_nonmatch():
    with pytest.raises(click.UsageError, match="Unknown field"):
        compile_filters(("value",), {"ieq": ("value=none", "bogus=none")})
