"""The operation catalog agrees with the real `report` and `summarize` commands, checked both ways."""

import json
import os
import re
import shlex
from dataclasses import asdict

import click
import pytest
from click.testing import CliRunner

from marketpulse.cli import (
    main,
    report_derive,
    report_filters,
    report_formats,
    report_metrics,
    report_operations,
    report_output,
    reports,
)
from marketpulse.cli.base import App
from marketpulse.cli.report_operations import OPERATIONS
from marketpulse.db import Snapshot
from marketpulse.models import Account, Alert, Quote, Transaction, TxnType

COMMANDS = ("report", "summarize")
FAMILIES = {
    "projection",
    "filter",
    "sort",
    "page",
    "selection",
    "count",
    "format",
    "transform",
    "column",
    "window",
    "summary",
    "derive",
    "group",
}
# The shared catalog omits the schema, destination, help, and source-specific presets.
# On `summarize`, `--group-by` only sets up the groups that its operations work on.
HOUSEKEEPING = {
    "report": {"--describe", "--output", "--help", "--preset"},
    "summarize": {"--describe", "--output", "--help", "--group-by", "--preset"},
}
PREVIOUS_SOURCES = {
    "automation-runs": ("id", "ran_at"),
    "transaction-months": ("transactions", "month"),
    "account-symbols": ("transactions", "symbol"),
    "broker-transaction-codes": ("code", "profile"),
    "transaction-csv-columns": ("position", "column"),
}
AUDIT_SOURCES = {
    "transaction-currency-audit": ("transaction_id", "date"),
    "transfer-routes": ("transactions", "first_date"),
    "watchlist-quote-coverage": ("position", "symbol"),
    "alert-quote-coverage": ("alert_id", "symbol"),
    "snapshot-month-coverage": ("snapshots", "month"),
}
PRESET_SOURCES = {**PREVIOUS_SOURCES, **AUDIT_SOURCES}


def spelled(names):
    """Implementation names as the CLI spells them.

    Underscores become dashes; `in_values` and `round_values` are the options `--in` and `--round`.
    """
    return tuple({"in_values": "in", "round_values": "round"}.get(name, name.replace("_", "-")) for name in names)


# The documented order: each batch in turn and, inside it, each family block with its operations.
# A block the implementation keeps as an ordered list is read from there.
LAYOUT = (
    (136, "projection", ("fields", "omit")),
    (136, "filter", ("where", "not", "contains", "prefix", "suffix", "present", "missing")),
    (136, "sort", ("sort", "descending")),
    (136, "page", ("offset", "limit")),
    (136, "selection", ("unique",)),
    (136, "count", ("count",)),
    (136, "format", ("jsonl", "csv", "tsv", "markdown")),
    (136, "page", ("page-info",)),
    (138, "filter", spelled(report_filters.FILTER_OPTIONS)),
    (138, "transform", spelled(report_output.CELL_OPTIONS)),
    (138, "column", spelled(report_output.EXTRA_OPTIONS)),
    (138, "sort", ("sort-ci",)),
    (138, "window", ("reverse-rows", "tail", "every")),
    (140, "summary", report_metrics.OPERATIONS),
    (142, "derive", tuple(function.name for function in report_derive.FUNCTIONS[:50])),
    (143, "filter", spelled(report_filters.EXPANSION_FILTERS)),
    (143, "selection", ("duplicates", "singletons", "unique-last")),
    (143, "summary", report_metrics.EXPANSION_OPERATIONS),
    (143, "group", ("having", "totals")),
    (143, "format", report_formats.FORMATS),
    (153, "derive", tuple(function.name for function in report_derive.FUNCTIONS[50:])),
    (153, "summary", report_metrics.FURTHER_OPERATIONS),
)

# A fictional argument for every placeholder a syntax uses, so each entry can run on the catalog itself.
EXAMPLES = {
    "NAME": "result",
    "VALUE": "x",
    "TEXT": "x",
    "KEY": "x",
    "PATTERN": "x*",
    "N": "2",
    "NUMBER": "2",
    "LOW": "1",
    "HIGH": "2",
    "DIGITS": "2",
    "WIDTH": "10",
    "TYPE": "number",
    "JSON": '"x"',
    "JSON_ARRAY": '["x"]',
    "JSON_PAIR": '["x","y"]',
    "YYYY-MM-DD": "2024-01-31",
    "DATE": "2024-01-31",
    "FILTER": "ieq",
}
PLACEHOLDER = re.compile(r"FIELD,FIELD|YYYY-MM-DD|[A-Z]+(?:_[A-Z]+)*")


def options(command):
    """Every long option of a real command, with its Click parameter."""
    return {
        spelling: parameter
        for parameter in main.commands[command].params
        if isinstance(parameter, click.Option)
        for spelling in parameter.opts
        if spelling.startswith("--")
    }


def option_of(item):
    """The option an entry is written with: the first token of its syntax."""
    return item.syntax.split()[0]


def accepting(item):
    """The real commands that have an entry's option and, for `--format`, that choice."""
    option, _, choice = item.syntax.partition(" ")
    found = []
    for command in COMMANDS:
        parameter = options(command).get(option)
        if parameter is not None and (option != "--format" or choice in parameter.type.choices):
            found.append(command)
    return tuple(found)


def invocation(command, item, source="report-operations"):
    """An entry's syntax as arguments for one command, with what its option needs beside it."""
    option, _, argument = item.syntax.partition(" ")
    field, second_field = {
        "report-operations": ("issue", "family"),
        "report-fields": ("position", "source"),
        "command-parameters": ("position", "command"),
        **PRESET_SOURCES,
    }[source]
    examples = {**EXAMPLES, "FIELD": field, "FIELD,FIELD": f"{field},{second_field}"}
    arguments = [command, source, option]
    if argument:
        arguments.append(PLACEHOLDER.sub(lambda match: examples[match.group()], argument))
    if command == "summarize":
        # Every summary needs a metric; `result` is also the column that --having filters.
        if option != "--metric":
            arguments += ["--metric", "result=count"]
        # Grouping on the example field lets --sort and --totals run; lines output takes one column only.
        if item.syntax != "--format lines":
            arguments += ["--group-by", field]
    elif item.syntax == "--format lines":
        arguments += ["--fields", field]
    if option == "--descending":
        arguments += ["--sort", field]
    if source == "broker-transaction-codes" and option == "--decode-json":
        arguments += ["--encode-json", field]
    return arguments


def run(*arguments):
    """The output of a real CLI call that must succeed."""
    result = CliRunner().invoke(main, list(arguments))
    assert result.exit_code == 0, result.output
    return result.output


def test_catalog_holds_six_batches_of_distinct_operations():
    assert len(OPERATIONS) == 197
    assert [item.issue for item in OPERATIONS] == (
        [136] * 20 + [138] * 40 + [140] * 40 + [142] * 50 + [143] * 30 + [153] * 17
    )
    assert {item.family for item in OPERATIONS} == FAMILIES
    assert len({item.syntax for item in OPERATIONS}) == 197
    assert len({(item.family, item.operation) for item in OPERATIONS}) == 197


def test_catalog_follows_the_documented_layout():
    expected = [(issue, family, name) for issue, family, names in LAYOUT for name in names]
    assert [(item.issue, item.family, item.operation) for item in OPERATIONS] == expected


def test_every_operation_is_named_in_its_own_syntax():
    for item in OPERATIONS:
        option, _, argument = item.syntax.partition(" ")
        assert option.startswith("--"), item
        # The name is the option itself, or the format, summary operation or derive function it chooses.
        assert item.operation in (option[2:], *re.split("[=:]", argument)), item


def test_every_summary_is_one_plain_sentence():
    for item in OPERATIONS:
        summary = item.summary
        # Derive functions (#142) reuse their own descriptions, some of which start with "-1".
        assert (summary[0].isupper() or not summary[0].isalpha()) and summary.endswith("."), item
        # Plain in every export format: printable ASCII without Markdown code spans.
        assert summary.isascii() and summary.isprintable() and "`" not in summary, item
        # One sentence: nothing follows a period.
        assert ". " not in summary and summary == summary.strip(), item


def test_rows_number_the_catalog_in_the_source_schema():
    rows = report_operations.rows()
    assert [row["number"] for row in rows] == list(range(1, 198))
    assert all(tuple(row) == reports.SOURCES["report-operations"] for row in rows)
    assert all(type(row["commands"]) is list for row in rows)
    unnumbered = [{key: value for key, value in row.items() if key != "number"} for row in rows]
    assert unnumbered == [{**asdict(item), "commands": list(item.commands)} for item in OPERATIONS]


def test_each_entry_lists_exactly_the_commands_that_accept_it():
    listed = {item.syntax: item.commands for item in OPERATIONS}
    assert listed == {item.syntax: accepting(item) for item in OPERATIONS}


@pytest.mark.parametrize("command", COMMANDS)
def test_every_operation_of_a_command_is_cataloged(command):
    listed = [item for item in OPERATIONS if command in item.commands]
    assert {option_of(item) for item in listed} == set(options(command)) - HOUSEKEEPING[command]
    formats = options(command)["--format"]
    cataloged = {item.operation for item in listed if item.family == "format"}
    assert cataloged == set(formats.type.choices) - {formats.default}


@pytest.mark.parametrize("source", ["report-operations", "report-fields", "command-parameters", *PRESET_SOURCES])
def test_every_syntax_runs_on_each_command_that_lists_it(source, populated_store):
    failures = {}
    for item in OPERATIONS:
        for command in item.commands:
            result = CliRunner().invoke(main, invocation(command, item, source))
            if result.exit_code != 0:
                failures[command, item.syntax] = result.output or repr(result.exception)
    assert not failures


@pytest.mark.parametrize("sources", [PREVIOUS_SOURCES, AUDIT_SOURCES], ids=["previous", "audit"])
def test_exact_number_of_capabilities_in_each_batch(sources):
    assert set(sources) <= reports.SOURCES.keys()
    presets = [reports.SOURCE_PRESETS[source] for source in sources]
    assert all(len(group) == len(set(group.values())) == 3 for group in presets)
    assert len(sources) * len(OPERATIONS) + sum(map(len, presets)) == 1000


def test_all_preset_sources_are_covered_by_the_matrix():
    assert reports.SOURCE_PRESETS.keys() == PRESET_SOURCES.keys()


@pytest.fixture
def report_store(tracker, monkeypatch):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    store = tracker.store
    first = store.add_account(Account("Fictional First")).saved_id
    second = store.add_account(Account("Fictional Second")).saved_id
    store.add_transactions(
        [
            Transaction(first, TxnType.DEPOSIT, "2026-01-01", amount=100),
            Transaction(first, TxnType.BUY, "2026-01-02", "FRUIT.TO", 2, 10),
            Transaction(first, TxnType.WITHDRAWAL, "2026-02-02", amount=100),
            Transaction(first, TxnType.TRANSFER, "2026-02-03", "FRUIT.TO", 1, target_account_id=second),
            Transaction(second, TxnType.SELL, "2026-02-04", "FRUIT.TO", 1, 10),
            Transaction(first, TxnType.DIVIDEND, "2026-03-01", "BERRY.TO", amount=5),
        ]
    )
    store.record_automation_run({"last_run": "2026-01-02T12:00:00", "stale": False})
    store.record_automation_run({"last_run": "2026-01-03T12:00:00", "failed": True})
    store.record_automation_run({"last_run": "2026-01-04T12:00:00", "stale": True, "quote_errors": ["Offline"]})
    store.record_automation_run({"last_run": "2026-01-05T12:00:00", "stale": True, "quote_errors": []})
    return store


@pytest.fixture
def audit_store(tracker, monkeypatch):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    store = tracker.store
    first = store.add_account(Account("Fictional First")).saved_id
    second = store.add_account(Account("Fictional Second")).saved_id
    usd = store.add_account(Account("Fictional USD", currency="USD")).saved_id
    store.add_transactions(
        [
            Transaction(first, TxnType.DEPOSIT, "2024-01-01", amount=100, currency="CAD"),
            Transaction(first, TxnType.BUY, "2024-01-02", "FRUIT.TO", 4, 10),
            Transaction(first, TxnType.TRANSFER, "2024-01-03", "FRUIT.TO", 1, target_account_id=second),
            Transaction(first, TxnType.TRANSFER, "2024-01-04", "FRUIT.TO", 1, target_account_id=second),
            Transaction(first, TxnType.TRANSFER, "2024-01-04", "FRUIT.TO", 1, target_account_id=usd),
            Transaction(second, TxnType.BUY, "2024-01-05", "BERRY", 1, 10, currency="USD"),
        ]
    )
    store.add_watch(["FRUIT.TO", "BERRY", "MANGO"])
    store.cache_quotes([Quote("FRUIT.TO", 10, 9, fetched_at=1706745600), Quote("BERRY", 10, 9)])
    store.add_alert(Alert("FRUIT.TO", "above", 10, triggered_at="2024-02-01T00:00:00+00:00"))
    store.add_alert(Alert("MANGO", "below", 20, active=False))
    store.upsert_snapshots(
        [
            Snapshot("2024-01-30", 100, 100, 100, "CAD", {}),
            Snapshot("2024-01-31", 100, 100, 100, "CAD", {}),
            Snapshot("2024-02-01", 100, 100, 100, "CAD", {"backfilled": True}),
            Snapshot("2024-02-29", 100, 100, 100, "USD", {}),
        ]
    )
    return store


@pytest.fixture
def populated_store(source, request):
    return request.getfixturevalue("audit_store" if source in AUDIT_SOURCES else "report_store")


@pytest.mark.parametrize("source", PRESET_SOURCES)
def test_presets_are_discoverable_and_filter_both_commands(source, populated_store, fake):
    changes = populated_store._conn.total_changes
    report_presets = json.loads(run("report", source, "--describe"))["presets"]
    assert report_presets == json.loads(run("summarize", source, "--describe"))["presets"]
    assert set(report_presets) == reports.SOURCE_PRESETS[source].keys()
    unfiltered = int(run("report", source, "--count"))
    for name, filter_args in report_presets.items():
        named = run("report", source, "--preset", name)
        assert named == run("report", source, *shlex.split(filter_args))
        count = len(json.loads(named))
        assert 0 < count < unfiltered
        summary = run("summarize", source, "--preset", name, "--metric", "rows=count")
        assert json.loads(summary) == [{"rows": count}]
    assert not fake.calls
    assert populated_store._conn.total_changes == changes


def test_presets_combine_with_each_other_and_explicit_filters(report_store):
    assert run("report", "automation-runs", "--preset", "stale", "--preset", "quote-errors", "--count") == "1\n"
    assert run("report", "automation-runs", "--preset", "stale", "--in", "stale=[false]", "--count") == "0\n"
    summary = run(
        "summarize", "automation-runs", "--preset", "stale", "--gt", "quote_error_count=2", "--metric", "rows=count"
    )
    assert json.loads(summary) == [{"rows": 0}]


@pytest.mark.parametrize(
    ("source", "preset", "field", "expected"),
    [
        ("transaction-months", "deposits", "month", [(1, "2026-01")]),
        ("transaction-months", "withdrawals", "month", [(1, "2026-02")]),
        ("transaction-months", "transfers", "month", [(1, "2026-02"), (2, "2026-02")]),
        ("account-symbols", "buys", "symbol", [(1, "FRUIT.TO")]),
        ("account-symbols", "sales", "symbol", [(2, "FRUIT.TO")]),
        ("account-symbols", "dividends", "symbol", [(1, "BERRY.TO")]),
    ],
)
def test_activity_presets_select_the_expected_rows(source, preset, field, expected, report_store):
    rows = json.loads(run("report", source, "--preset", preset))
    assert [(row["account_id"], row[field]) for row in rows] == expected


@pytest.mark.parametrize(
    ("preset", "ids"),
    [("failed", [2]), ("stale", [4, 3]), ("quote-errors", [3])],
)
def test_automation_presets_select_the_expected_runs(preset, ids, report_store):
    assert json.loads(run("report", "automation-runs", "--preset", preset, "--fields", "id")) == [
        {"id": run_id} for run_id in ids
    ]


@pytest.mark.parametrize("source", PRESET_SOURCES)
def test_preset_sources_project_only_selected_fields(source, populated_store):
    field = PRESET_SOURCES[source][0]
    baseline = json.loads(run("report", source))
    assert baseline
    assert json.loads(run("report", source, "--fields", field)) == [{field: row[field]} for row in baseline]


@pytest.mark.parametrize("command", COMMANDS)
def test_preset_discovery_and_validation_need_no_source_data(command, monkeypatch):
    def forbidden(*args):
        pytest.fail("Describing or rejecting a preset should not open the tracker")

    monkeypatch.setattr(App, "tracker", property(forbidden))
    assert "failed" in json.loads(run(command, "automation-runs", "--describe"))["presets"]
    args = ["--metric", "rows=count"] if command == "summarize" else []
    for source, message in [
        ("automation-runs", "Choose from: failed, stale, quote-errors."),
        ("accounts", "Source 'accounts' has no presets."),
    ]:
        result = CliRunner().invoke(main, [command, source, "--preset", "missing", *args])
        assert result.exit_code == 2
        assert message in result.output
    result = CliRunner().invoke(main, [command, "automation-runs", "--describe", "--preset", "failed"])
    assert result.exit_code == 2
    assert "--describe cannot combine" in result.output


def test_report_emits_the_catalog_without_opening_saved_data():
    assert json.loads(run("report", "report-operations")) == report_operations.rows()
    assert run("report", "report-operations", "--count") == "197\n"
    assert not os.path.exists(os.environ["MARKETPULSE_DATA"])


def test_summarize_counts_each_batch():
    output = run("summarize", "report-operations", "--group-by", "issue", "--metric", "operations=count")
    assert json.loads(output) == [
        {"issue": 136, "operations": 20},
        {"issue": 138, "operations": 40},
        {"issue": 140, "operations": 40},
        {"issue": 142, "operations": 50},
        {"issue": 143, "operations": 30},
        {"issue": 153, "operations": 17},
    ]


def test_lines_format_prints_the_derive_functions():
    output = run(
        "report", "report-operations", "--where", "family=derive", "--fields", "operation", "--format", "lines"
    )
    assert output.splitlines() == [function.name for function in report_derive.FUNCTIONS]


def test_has_item_counts_the_operations_summarize_accepts():
    listed = sum("summarize" in item.commands for item in OPERATIONS)
    assert run("report", "report-operations", "--has-item", 'commands="summarize"', "--count") == f"{listed}\n"
