"""Output report transformations preserve source rows and validate before loading."""

import copy
import json

import click
import pytest

from marketpulse.cli.report_output import CELL_OPTIONS, EXTRA_OPTIONS, OutputPlan

SCHEMA = ("key", "value")


@pytest.mark.parametrize(
    ("option", "argument", "value", "expected"),
    [
        ("lower", "value", "ÉCOLE", "école"),
        ("upper", "value", "école", "ÉCOLE"),
        ("strip", "value", " \tCanada\n", "Canada"),
        ("lstrip", "value", " \tCanada\n", "Canada\n"),
        ("rstrip", "value", " \tCanada\n", " \tCanada"),
        ("replace", 'value=["CAD", "C$"]', "CAD 10 CAD", "C$ 10 C$"),
        ("fill", 'value={"status": "unknown"}', None, {"status": "unknown"}),
        ("fill", 'value="unknown"', "", ""),
        ("null_if", 'value="pending"', "pending", None),
        ("null_if", "value=1", True, True),
        ("null_if", "value=1", 1.0, None),
        ("null_if", 'value={"flag": true}', {"flag": 1}, {"flag": 1}),
        ("null_if", "value=[true]", [True], None),
        ("stringify", "value", None, ""),
        ("stringify", "value", "CAD", "CAD"),
        ("stringify", "value", {"z": 2, "a": [True]}, '{"a": [true], "z": 2}'),
        ("encode_json", "value", "CAD", '"CAD"'),
        ("encode_json", "value", None, "null"),
        ("decode_json", "value", '{"cad": [1, true, null]}', {"cad": [1, True, None]}),
        ("decode_json", "value", 3, 3),
        ("length_of", "value", "é🇨🇦", 3),
        ("length_of", "value", [1, False], 2),
        ("length_of", "value", {"a": 2}, 1),
        ("length_of", "value", 123, None),
        ("length_of", "value", None, None),
        ("round_values", "value=2", 12.345, 12.35),
        ("round_values", "value=0", 12.5, 12.0),
        ("round_values", "value=2", True, True),
        ("round_values", "value=2", "12.345", "12.345"),
        ("round_values", "value=15", 10**500, 10**500),
    ],
)
def test_cell_operation(option, argument, value, expected):
    original = {"key": "fictional", "value": value}
    before = copy.deepcopy(original)
    plan = OutputPlan(SCHEMA, {option: (argument,)})
    output = plan.apply([original])
    assert output == [{"key": "fictional", "value": expected}]
    assert original == before
    assert output[0] is not original
    assert plan.schema == SCHEMA


@pytest.mark.parametrize("operation", ["lower", "upper", "strip", "lstrip", "rstrip", "replace"])
def test_string_operations_preserve_other_json_types(operation):
    argument = 'value=["a", "b"]' if operation == "replace" else "value"
    values = [None, True, 12, [], {}, ["a"], {"a": 1}]
    rows = [{"key": "fictional", "value": value} for value in values]
    assert OutputPlan(SCHEMA, {operation: (argument,)}).apply(rows) == rows


def test_repeat_order_and_fixed_cell_pipeline():
    # The CLI's option order cannot change operation order; per-option repeats retain order.
    plan = OutputPlan(
        SCHEMA,
        {
            "replace": ('value=["a", "b"]', 'value=["b", "xy"]'),
            "strip": ("value",),
            "lower": ("value",),
            "length_of": ("value",),
            "encode_json": ("key",),
            "decode_json": ("key",),
        },
    )
    assert plan.apply([{"key": [True, {"x": 1}], "value": "  A  "}]) == [{"key": [True, {"x": 1}], "value": 2}]


def test_renames_are_simultaneous_and_column_order_is_predictable():
    plan = OutputPlan(
        SCHEMA,
        {
            "upper": ("key",),
            "rename": ("key=value", "value=key"),
            "constant": ('source="fictional"', 'details={"currency": "CAD"}'),
            "row_number": "row",
        },
    )
    assert plan.schema == ("value", "key", "source", "details", "row")
    assert plan.apply([{"key": "alpha", "value": 12}], start=9) == [
        {"value": "ALPHA", "key": 12, "source": "fictional", "details": {"currency": "CAD"}, "row": 10}
    ]
    assert plan.apply([]) == []


def test_constant_can_use_column_name_freed_by_rename():
    plan = OutputPlan(SCHEMA, {"rename": ("key=label",), "constant": ('key="saved"',)})
    assert plan.schema == ("label", "value", "key")
    assert plan.apply([{"key": "account", "value": 10}]) == [{"label": "account", "value": 10, "key": "saved"}]


@pytest.mark.parametrize(
    "options",
    [
        {"lower": ("unknown",)},
        {"rename": ("unknown=name",)},
        {"rename": ("key",)},
        {"rename": ("key=",)},
        {"rename": ("key=two words",)},
        {"rename": ("key=1name",)},
        {"rename": ("key=value",)},
        {"rename": ("key=name", "value=name")},
        {"rename": ("key=name", "key=other")},
        {"constant": ("missing",)},
        {"constant": ("key=1",)},
        {"constant": ("extra=1", "extra=2")},
        {"constant": ("extra",)},
        {"constant": ("=1",)},
        {"constant": ("extra=NaN",)},
        {"constant": ("extra=[1e999]",)},
        {"constant": ("extra={not json}",)},
        {"row_number": "key"},
        {"row_number": ""},
        {"constant": ("row=1",), "row_number": "row"},
        {"replace": ("value=[]",)},
        {"replace": ('value=["", "x"]',)},
        {"replace": ('value=["x", 1]',)},
        {"replace": ('value="x"',)},
        {"fill": ("value=Infinity",)},
        {"null_if": ('value={"x": -Infinity}',)},
        {"round_values": ("value=16",)},
        {"round_values": ("value=-1",)},
        {"round_values": ("value=1.5",)},
        {"round_values": ("value=",)},
    ],
)
def test_invalid_options_fail_during_construction(options):
    with pytest.raises(click.UsageError):
        OutputPlan(SCHEMA, options)


@pytest.mark.parametrize("value", ["invalid", "NaN", "Infinity", "-Infinity", "1e999", '{"a": [1e999]}'])
def test_invalid_json_decoding_identifies_field(value):
    plan = OutputPlan(SCHEMA, {"decode_json": ("value",)})
    with pytest.raises(click.ClickException, match="Cannot decode JSON in field 'value'"):
        plan.apply([{"key": "fictional", "value": value}])


def test_json_operations_round_trip_and_noop_plan():
    rows = [{"key": "fictional", "value": {"currency": "CAD", "note": "é,\n\t|", "nested": [True, 1.5, None]}}]
    encoded = OutputPlan(SCHEMA, {"encode_json": ("value",)}).apply(rows)
    assert json.loads(encoded[0]["value"]) == rows[0]["value"]
    assert OutputPlan(SCHEMA, {"decode_json": ("value",)}).apply(encoded) == rows
    assert OutputPlan(SCHEMA, {}).apply(rows) == rows


def test_sixteen_output_operations_are_unique():
    assert len(CELL_OPTIONS + EXTRA_OPTIONS) == len(set(CELL_OPTIONS + EXTRA_OPTIONS)) == 16
