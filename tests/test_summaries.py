"""Composition, validation and real-source proof for offline grouped summaries."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main, report_metrics, reports
from marketpulse.cli.base import App
from marketpulse.models import Account, AccountType, Transaction, TxnType


def invoke(*arguments):
    return CliRunner().invoke(main, ["summarize", *arguments])


def test_group_filter_sort_and_page(monkeypatch):
    rows = [
        {"key": "b", "value": "10"},
        {"key": "a", "value": "2"},
        {"key": "a", "value": "4"},
        {"key": "c", "value": None},
    ]
    original = json.dumps(rows)
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    result = invoke(
        "config",
        "--metric",
        "n=count",
        "--metric",
        "total=number-sum:value",
        "--group-by",
        "key",
        "--ge",
        "value=2",
        "--sort",
        "total",
        "--descending",
        "--offset",
        "1",
        "--limit",
        "1",
        "--page-info",
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "source": "config",
        "total": 2,
        "offset": 1,
        "limit": 1,
        "rows": [{"key": "a", "n": 2, "total": "6"}],
    }
    assert json.dumps(rows) == original


def test_exact_and_advanced_filters_combine_before_summaries(monkeypatch):
    rows = [{"key": "one", "value": 1}, {"key": "one", "value": 3}, {"key": "two", "value": 5}]
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    result = invoke("config", "--metric", "n=count", "--where", "key=one", "--gt", "value=2")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [{"n": 1}]


def test_nested_typed_group_keys_and_first_representation(monkeypatch):
    values = [False, 0, 0.0, [False], [0], [0.0], {"a": True}, {"a": 1}, {"a": 1.0}, None, ""]
    rows = [{"key": value, "value": i} for i, value in enumerate(values)]
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    result = invoke("config", "--metric", "n=count", "--group-by", "key")
    assert result.exit_code == 0, result.output
    assert (
        result.output
        == json.dumps(
            [
                {"key": False, "n": 1},
                {"key": 0, "n": 2},
                {"key": [False], "n": 1},
                {"key": [0], "n": 2},
                {"key": {"a": True}, "n": 1},
                {"key": {"a": 1}, "n": 2},
                {"key": None, "n": 1},
                {"key": "", "n": 1},
            ]
        )
        + "\n"
    )


def test_composite_group_order_and_multiple_metrics(monkeypatch):
    rows = [{"key": "a", "value": 2}, {"key": "a", "value": 3}, {"key": "a", "value": 2}]
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    result = invoke(
        "config",
        "--group-by",
        "key",
        "--group-by",
        "value",
        "--metric",
        "n=count",
        "--metric",
        "v=values:key",
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [
        {"key": "a", "value": 2, "n": 2, "v": ["a", "a"]},
        {"key": "a", "value": 3, "n": 1, "v": ["a"]},
    ]


def test_numeric_groups_agree_with_typed_distinctness(monkeypatch):
    # Decimal(str(float)) would incorrectly merge these distinct JSON numbers.
    values = [10**23, 1e23, 1, 1.0]
    monkeypatch.setattr(reports, "load_source", lambda *args: [{"key": value, "value": 0} for value in values])
    result = invoke("config", "--group-by", "key", "--metric", "n=count", "--metric", "d=distinct:key")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [
        {"key": 10**23, "n": 1, "d": 1},
        {"key": 1e23, "n": 1, "d": 1},
        {"key": 1, "n": 2, "d": 1},
    ]


@pytest.mark.parametrize("descending,expected", [(False, ["b", "a", "c"]), (True, ["a", "b", "c"])])
def test_decimal_metric_sort_missing_last(monkeypatch, descending, expected):
    rows = [{"key": "a", "value": "10"}, {"key": "b", "value": "2"}, {"key": "c", "value": None}]
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    result = invoke(
        "config",
        "--group-by",
        "key",
        "--metric",
        "mean=number-mean:value",
        "--sort",
        "mean",
        *(["--descending"] if descending else []),
    )
    assert result.exit_code == 0, result.output
    assert [row["key"] for row in json.loads(result.output)] == expected


def test_group_sort_retains_numeric_then_text_groups(monkeypatch):
    values = ["a", 2, None, 10, "z", ""]
    monkeypatch.setattr(reports, "load_source", lambda *args: [{"key": value, "value": 0} for value in values])
    result = invoke("config", "--group-by", "key", "--metric", "n=count", "--sort", "key", "--descending")
    assert result.exit_code == 0, result.output
    assert [row["key"] for row in json.loads(result.output)] == [10, 2, "z", "a", None, ""]


@pytest.mark.parametrize("grouped", [False, True])
@pytest.mark.parametrize("output_format", ["json", "jsonl", "csv", "tsv", "markdown"])
def test_empty_sources_have_stable_schema(monkeypatch, grouped, output_format):
    monkeypatch.setattr(reports, "load_source", lambda *args: [])
    result = invoke(
        "config",
        "--metric",
        "n=count",
        "--metric",
        "sum=number-sum:value",
        "--format",
        output_format,
        *(["--group-by", "key"] if grouped else []),
    )
    assert result.exit_code == 0, result.output
    if output_format == "json":
        assert json.loads(result.output) == ([] if grouped else [{"n": 0, "sum": "0"}])
    elif output_format == "jsonl":
        assert result.output == ("" if grouped else '{"n": 0, "sum": "0"}\n')
    elif output_format in ("csv", "tsv"):
        delimiter = "," if output_format == "csv" else "\t"
        parsed = list(csv.reader(io.StringIO(result.output), delimiter=delimiter))
        assert parsed == ([["key", "n", "sum"]] if grouped else [["n", "sum"], ["0", "0"]])
    else:
        assert "| n | sum |" in result.output


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--metric", "n"],
        ["--metric", "1n=count"],
        ["--metric", "n=unknown"],
        ["--metric", "n=count:value"],
        ["--metric", "n=number-sum"],
        ["--metric", "n=values:bogus"],
        ["--metric", "n=count", "--metric", "n=count"],
        ["--group-by", "key", "--metric", "key=count"],
        ["--metric", "n=count", "--group-by", "bogus"],
        ["--metric", "n=count", "--group-by", "key", "--group-by", "key"],
        ["--metric", "n=count", "--sort", "value"],
        ["--metric", "n=count", "--sort", "n", "--sort", "n"],
        ["--metric", "n=count", "--descending"],
        ["--metric", "n=count", "--page-info", "--format", "csv"],
        ["--metric", "n=count", "--where", "key"],
        ["--metric", "n=count", "--where", "bogus=x"],
        ["--metric", "n=count", "--gt", "value=nan"],
        ["--metric", "n=count", "--gt", "bogus=1"],
        ["--metric", "n=count", "--offset", "-1"],
        ["--metric", "n=count", "--limit", "0"],
        ["--describe", "--metric", "n=count"],
        ["--describe", "--where", "key=x"],
        ["--describe", "--group-by", "key"],
        ["--describe", "--sort", "key"],
        ["--describe", "--descending"],
        ["--describe", "--offset", "1"],
        ["--describe", "--limit", "1"],
        ["--describe", "--page-info"],
        ["--describe", "--format", "csv"],
        ["--describe", "--empty", "value"],
    ],
)
def test_invalid_query_does_not_load(monkeypatch, args):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("invalid query loaded source"))
    result = invoke("config", *args)
    assert result.exit_code == 2, result.output


def test_describe_without_source_access(monkeypatch):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("describe loaded source"))
    result = invoke("accounts", "--describe")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"] == "accounts"
    assert payload["fields"] == list(reports.SOURCES["accounts"])
    # The original forty come first; #143 appended ten more.
    assert payload["operations"][:40] == list(report_metrics.OPERATIONS)
    assert payload["operations"] == list(report_metrics.ALL_OPERATIONS) and len(payload["operations"]) == 50


def test_new_file_exports_and_no_overwrite(monkeypatch, tmp_path):
    rows = [{"key": "a|<b>\nx", "value": 2}, {"key": "b", "value": 4}]
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    output = tmp_path / "summary.csv"
    result = invoke("config", "--group-by", "key", "--metric", "n=count", "--format", "csv", "--output", str(output))
    assert result.exit_code == 0 and result.output == "", result.output
    assert list(csv.DictReader(io.StringIO(output.read_text()))) == [
        {"key": "a|<b>\nx", "n": "1"},
        {"key": "b", "n": "1"},
    ]
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("loaded despite existing output"))
    result = invoke("config", "--metric", "n=count", "--output", str(output))
    assert result.exit_code == 2 and "refusing to overwrite" in result.output
    assert output.read_text().startswith("key,n")


def test_markdown_escapes_source_values(monkeypatch):
    monkeypatch.setattr(reports, "load_source", lambda *args: [{"key": "<b>|\nx", "value": 2}])
    result = invoke("config", "--group-by", "key", "--metric", "n=count", "--format", "markdown")
    assert result.exit_code == 0, result.output
    assert "&lt;b&gt;&#124;<br>x" in result.output


def test_real_accounts_transactions_offline_and_read_only(tracker, fake, monkeypatch):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    active = tracker.store.add_account(Account("Fictional TFSA", type=AccountType.TFSA))
    hidden = tracker.store.add_account(Account("Fictional archived", type=AccountType.TFSA, archived=True))
    tracker.store.add_transaction(Transaction(active.saved_id, TxnType.BUY, "2024-01-02", "FIC.TO", 2, 10))
    tracker.store.add_transaction(Transaction(hidden.saved_id, TxnType.BUY, "2024-01-02", "HIDDEN.TO", 100, 50))
    before = tracker.store._conn.total_changes
    result = invoke(
        "transactions", "--group-by", "account", "--metric", "n=count", "--metric", "quantity=number-sum:quantity"
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [{"account": "Fictional TFSA", "n": 1, "quantity": "2"}]
    result = invoke("accounts", "--metric", "names=values:name")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [{"names": ["Fictional TFSA"]}]
    assert fake.calls == []
    assert tracker.store._conn.total_changes == before
