"""The 25 × 40 new report capabilities through the actual CLI pipeline."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main, reports

# name, input values, arguments ({f}=first source field), matching row indices,
# transformed values (None means retain the source values).
CASES = [
    ("ieq", ["Alpha", "alpha", "beta", None], ["--ieq", "{f}=ALPHA"], [0, 1], None),
    ("ine", ["Alpha", "alpha", "beta", None], ["--ine", "{f}=ALPHA"], [2, 3], None),
    ("not-contains", ["Alpha", "beta", None], ["--not-contains", "{f}=LP"], [1, 2], None),
    ("not-prefix", ["Alpha", "beta", None], ["--not-prefix", "{f}=AL"], [1, 2], None),
    ("not-suffix", ["Alpha", "beta", None], ["--not-suffix", "{f}=HA"], [1, 2], None),
    ("gt", [0, 1, 2, None], ["--gt", "{f}=1"], [2], None),
    ("ge", [0, 1, 2, None], ["--ge", "{f}=1"], [1, 2], None),
    ("lt", [0, 1, 2, None], ["--lt", "{f}=1"], [0], None),
    ("le", [0, 1, 2, None], ["--le", "{f}=1"], [0, 1], None),
    ("between", [0, 1, 2, None], ["--between", "{f}=1,2"], [1, 2], None),
    ("outside", [0, 1, 2, None], ["--outside", "{f}=1,2"], [0], None),
    ("in", [False, 0, [], None], ["--in", "{f}=[0,[]]"], [1, 2], None),
    ("not-in", [False, 0, [], None], ["--not-in", "{f}=[0,[]]"], [0, 3], None),
    ("empty", [None, "", [], {}, 0, False], ["--empty", "{f}"], [0, 1, 2, 3], None),
    ("nonempty", [None, "", [], {}, 0, False], ["--nonempty", "{f}"], [4, 5], None),
    ("is-type", [False, 0, [], None], ["--is-type", "{f}=number"], [1], None),
    ("length", ["ab", [0, 1], {"a": 0}, 2], ["--length", "{f}=2"], [0, 1], None),
    ("min-length", ["ab", [0, 1], {"a": 0}, 2], ["--min-length", "{f}=2"], [0, 1], None),
    ("max-length", ["ab", [0, 1], {"a": 0}, 2], ["--max-length", "{f}=1"], [2], None),
    ("glob", ["Alpha", "alpha", "Beta", None], ["--glob", "{f}=A*"], [0], None),
    ("lower", ["Alpha", "BETA", 2], ["--lower", "{f}"], [0, 1, 2], ["alpha", "beta", 2]),
    ("upper", ["Alpha", "beta", 2], ["--upper", "{f}"], [0, 1, 2], ["ALPHA", "BETA", 2]),
    ("strip", [" a ", " b\t", 2], ["--strip", "{f}"], [0, 1, 2], ["a", "b", 2]),
    ("lstrip", [" a ", " b\t", 2], ["--lstrip", "{f}"], [0, 1, 2], ["a ", "b\t", 2]),
    ("rstrip", [" a ", " b\t", 2], ["--rstrip", "{f}"], [0, 1, 2], [" a", " b", 2]),
    ("replace", ["banana", "band", None], ["--replace", '{f}=["an","X"]'], [0, 1, 2], ["bXXa", "bXd", None]),
    ("fill", [None, "", 0], ["--fill", "{f}=false"], [0, 1, 2], [False, "", 0]),
    ("null-if", [False, 0, "x"], ["--null-if", "{f}=0"], [0, 1, 2], [False, None, "x"]),
    ("stringify", [None, False, [1]], ["--stringify", "{f}"], [0, 1, 2], ["", "false", "[1]"]),
    ("encode-json", [None, "x", [1]], ["--encode-json", "{f}"], [0, 1, 2], ["null", '"x"', "[1]"]),
    ("decode-json", ["null", "false", "[1]"], ["--decode-json", "{f}"], [0, 1, 2], [None, False, [1]]),
    ("length-of", ["ab", [1], 0, None], ["--length-of", "{f}"], [0, 1, 2, 3], [2, 1, None, None]),
    ("round", [1.125, -1.125, False], ["--round", "{f}=2"], [0, 1, 2], [1.12, -1.12, False]),
    ("rename", ["a", "b"], ["--rename", "{f}=renamed_column"], [0, 1], None),
    ("constant", ["a", "b"], ["--constant", 'extra_column={"x":1}'], [0, 1], None),
    ("row-number", ["a", "b"], ["--row-number", "row_index"], [0, 1], None),
    ("sort-ci", ["beta", "Alpha", "alpha", None], ["--sort-ci", "{f}"], [1, 2, 0, 3], None),
    ("reverse-rows", ["a", "b", "c"], ["--reverse-rows"], [2, 1, 0], None),
    ("tail", ["a", "b", "c"], ["--tail", "2"], [1, 2], None),
    ("every", ["a", "b", "c"], ["--every", "2"], [0, 2], None),
]


@pytest.mark.parametrize("source", sorted(reports.SOURCES))
@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_new_dataset_operation_matrix(monkeypatch, source, case):
    name, values, arguments, indices, transformed = case
    schema = reports.SOURCES[source]
    first, second = schema[:2]
    data = [{**dict.fromkeys(schema), first: value, second: i} for i, value in enumerate(values)]
    original = json.dumps(data)
    monkeypatch.setattr(reports, "load_source", lambda *args: data)
    arguments = [arg.replace("{f}", first) for arg in arguments]
    result = CliRunner().invoke(main, ["report", source, *arguments])
    assert result.exit_code == 0, result.output
    expected = [dict(data[i]) for i in indices]
    if transformed is not None:
        for row, value in zip(expected, transformed, strict=True):
            row[first] = value
    if name == "rename":
        expected = [
            {("renamed_column" if key == first else key): value for key, value in row.items()} for row in expected
        ]
    elif name == "constant":
        expected = [{**row, "extra_column": {"x": 1}} for row in expected]
    elif name == "row-number":
        expected = [{**row, "row_index": i + 1} for i, row in enumerate(expected)]
    # JSON text comparisons protect bool/number distinctions in filter and transform results.
    assert json.dumps(json.loads(result.output), sort_keys=True) == json.dumps(expected, sort_keys=True)
    assert json.dumps(data) == original


def test_composed_operations_and_export(monkeypatch):
    data = [
        {"key": "b", "value": " keep "},
        {"key": "A", "value": " keep "},
        {"key": "c", "value": "skip"},
        {"key": "a", "value": " keep "},
        {"key": "D", "value": " keep "},
    ]
    monkeypatch.setattr(reports, "load_source", lambda *args: data)
    args = [
        "report",
        "config",
        "--ieq",
        "value= KEEP ",
        "--sort-ci",
        "key",
        "--descending",
        "--reverse-rows",
        "--tail",
        "3",
        "--every",
        "2",
        "--offset",
        "1",
        "--limit",
        "1",
        "--upper",
        "key",
        "--strip",
        "value",
        "--rename",
        "key=name",
        "--constant",
        "tag=true",
        "--row-number",
        "index",
        "--fields",
        "index,name,value,tag",
        "--page-info",
    ]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "source": "config",
        "total": 2,
        "offset": 1,
        "limit": 1,
        "rows": [{"index": 2, "name": "D", "value": "keep", "tag": True}],
    }
    result = CliRunner().invoke(main, args[:-1] + ["--format", "csv"])
    assert result.exit_code == 0, result.output
    assert list(csv.DictReader(io.StringIO(result.output))) == [
        {"index": "2", "name": "D", "value": "keep", "tag": "true"}
    ]


@pytest.mark.parametrize(
    "args",
    [
        ["--sort", "key", "--sort-ci", "value"],
        ["--sort-ci", "unknown"],
        ["--tail", "0"],
        ["--every", "0"],
        ["--count", "--lower", "key"],
        ["--count", "--row-number", "idx"],
        ["--fields", "key", "--rename", "key=renamed"],
        ["--describe", "--ieq", "key=x"],
        ["--describe", "--row-number", "idx"],
        ["--describe", "--every", "2"],
        ["--describe", "--reverse-rows"],
    ],
)
def test_new_pipeline_conflicts_before_loading(monkeypatch, args):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("invalid query loaded source"))
    result = CliRunner().invoke(main, ["report", "config", *args])
    assert result.exit_code == 2, result.output


def test_window_counts_empty_headers_and_numbers(monkeypatch):
    data = [{"key": str(i), "value": i} for i in range(7)]
    monkeypatch.setattr(reports, "load_source", lambda *args: data)
    result = CliRunner().invoke(main, ["report", "config", "--tail", "4", "--every", "2", "--count"])
    assert result.output == "2\n"
    result = CliRunner().invoke(
        main,
        ["report", "config", "--gt", "value=99", "--rename", "key=name", "--row-number", "index", "--format", "csv"],
    )
    assert result.exit_code == 0 and result.output.strip() == "name,value,index"
    result = CliRunner().invoke(main, ["report", "config", "--offset", "2", "--limit", "2", "--row-number", "index"])
    assert [row["index"] for row in json.loads(result.output)] == [3, 4]


def test_case_insensitive_numeric_sort_and_ties(monkeypatch):
    data = [
        {"key": "z", "value": 2},
        {"key": "A", "value": 10},
        {"key": "a", "value": "a"},
        {"key": "B", "value": "A"},
        {"key": "Z", "value": None},
    ]
    monkeypatch.setattr(reports, "load_source", lambda *args: data)
    result = CliRunner().invoke(main, ["report", "config", "--sort-ci", "value", "--sort-ci", "key", "--descending"])
    assert result.exit_code == 0, result.output
    assert [row["key"] for row in json.loads(result.output)] == ["A", "z", "B", "a", "Z"]


@pytest.mark.parametrize(
    ("source", "field", "value"),
    [("accounts", "type", "TFSA"), ("transactions", "type", "BUY"), ("assets", "kind", "manual")],
)
def test_null_if_saved_enum_values(tracker, monkeypatch, source, field, value):
    from marketpulse.cli.base import App
    from marketpulse.models import Account, AccountType, Asset, AssetKind, Transaction, TxnType

    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    account = tracker.store.add_account(Account("Fictional TFSA", type=AccountType.TFSA))
    tracker.store.add_transaction(Transaction(account.saved_id, TxnType.BUY, "2024-01-02", "FIC.TO", 2, 10))
    tracker.store.upsert_asset(Asset("FIC.TO", kind=AssetKind.MANUAL))
    result = CliRunner().invoke(main, ["report", source, "--null-if", f'{field}="{value}"', "--fields", field])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [{field: None}]
