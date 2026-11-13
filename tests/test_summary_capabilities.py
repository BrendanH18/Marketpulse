"""Independent expected results for all 1,000 dataset/summary combinations."""

import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main, reports
from marketpulse.cli.base import App
from marketpulse.db import Snapshot
from marketpulse.models import Account, Alert, Asset, Quote, Transaction, TxnType

# Operation, field values, expected result. These expectations do not call the
# aggregation implementation, so the matrix checks behavior, not registration.
CASES = [
    ("count", [None, "", False, 0], 4),
    ("present", [None, "", [], {}, False, 0], 4),
    ("missing", [None, "", [], {}, False, 0], 2),
    ("empty", [None, "", [], {}, False, 0], 4),
    ("nonempty", [None, "", [], {}, False, 0], 2),
    ("distinct", [False, 0, 0.0, [False], [0], {"x": False}, {"x": 0}], 6),
    ("duplicates", [False, 0, 0.0, [False], [0], {"x": False}, {"x": 0}], 1),
    ("first", [None, "a", "b"], None),
    ("last", ["a", "b", None], None),
    ("first-present", [None, "", False, "a"], False),
    ("last-present", ["a", 0, "", None], 0),
    ("mode", [False, 0, False, 0, 0.0], 0),
    ("mode-count", [False, 0, False, 0, 0.0], 3),
    ("values", [None, False, 0, "0"], [None, False, 0, "0"]),
    ("distinct-values", [False, 0, 0.0, [False], [0]], [False, 0, [False], [0]]),
    ("number-count", [False, None, "NaN", "Infinity", [], "2", 2, -1], 3),
    ("number-distinct", [False, "2", 2, "2.0", -1], 2),
    ("number-sum", [False, "bad", "0.1", 0.2, -1], "-0.7"),
    ("number-min", [False, "2", 10, -1], "-1"),
    ("number-max", [False, "2", 10, -1], "10"),
    ("number-mean", [False, "1", 2, 3], "2"),
    ("number-median", [False, 9, "1", 4, 2], "3"),
    ("number-range", [False, "2", 10, -1], "11"),
    ("positive-count", [False, "2", 0, -1, "bad"], 1),
    ("negative-count", [False, "2", 0, -1, "bad"], 1),
    ("zero-count", [False, True, "0", 0, -1], 2),
    ("positive-sum", [True, "2", 0, -1, "bad"], "2"),
    ("negative-sum", [True, "2", 0, -1, "-0.5"], "-1.5"),
    ("absolute-sum", [True, "2", 0, -1, "-0.5"], "3.5"),
    ("true-count", [True, 1, "true", False], 1),
    ("false-count", [False, 0, "false", True], 1),
    ("string-count", [None, "", "abc", [], 0], 2),
    ("array-count", [None, [], [1], {}, 0], 2),
    ("object-count", [None, {}, {"x": 1}, [], 0], 2),
    ("length-sum", [None, "ab", [1, 2, 3], {"x": 1}, False, 5], 6),
    ("length-min", [None, "ab", [1, 2, 3], {"x": 1}, False, 5], 1),
    ("length-max", [None, "ab", [1, 2, 3], {"x": 1}, False, 5], 3),
    ("length-mean", [None, "ab", [1, 2, 3], {"x": 1}, False, 5], "2"),
    ("text-min", [None, 0, "z", "Alpha", "alpha"], "Alpha"),
    ("text-max", [None, 0, "z", "Alpha", "alpha"], "z"),
]


@pytest.mark.parametrize("source", sorted(reports.SOURCES))
@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_thousand_summary_capabilities(monkeypatch, source, case):
    operation, values, expected = case
    schema = reports.SOURCES[source]
    field = schema[0]
    rows = [{**dict.fromkeys(schema), field: value} for value in values]
    before = json.dumps(rows)
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    specification = operation if operation == "count" else f"{operation}:{field}"
    result = CliRunner().invoke(main, ["summarize", source, "--metric", f"result={specification}"])
    assert result.exit_code == 0, result.output
    # Compare JSON rather than Python equality to protect boolean/number types.
    assert json.dumps(json.loads(result.output)) == json.dumps([{"result": expected}])
    assert json.dumps(rows) == before


def test_inventory_matches_documented_thousand():
    from marketpulse.cli import report_catalog, report_portfolio
    from marketpulse.cli.report_metrics import OPERATIONS

    # The documented thousand are the 25 original datasets; datasets added later extend the matrix.
    assert len({**report_portfolio.SOURCES, **report_catalog.SOURCES}) == 25
    assert len(CASES) == len(OPERATIONS) == 40
    assert {case[0] for case in CASES} == set(OPERATIONS)


@pytest.fixture
def fictional_summary_data(tracker, monkeypatch):
    store = tracker.store
    active = store.add_account(Account("Fictional Cash", track_cash=True))
    archived = store.add_account(Account("Archived Fictional", track_cash=True, archived=True))
    for account in (active, archived):
        for txn in (
            Transaction(account.saved_id, TxnType.DEPOSIT, "2024-01-01", amount=100, currency="CAD"),
            Transaction(account.saved_id, TxnType.BUY, "2024-01-02", "FIC.TO", 2, 10, currency="CAD"),
            Transaction(account.saved_id, TxnType.DIVIDEND, "2024-01-03", "FIC.TO", amount=5, currency="CAD"),
        ):
            store.add_transaction(txn)
    store.upsert_asset(Asset("FIC.TO", name="Fictional Fund"))
    store.upsert_snapshot(Snapshot("2024-01-03", 100, 100, 100, "CAD", {}))
    store.cache_quotes([Quote("FIC.TO", 12, 10, currency="CAD", fetched_at=1700000000)])
    store.add_alert(Alert("FIC.TO", "above", 15))
    store.add_watch(["FIC.TO", "FIC-B.TO"])
    store.set_targets({"equity": 75, "cash": 25})
    store.backup()
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    return store


@pytest.mark.parametrize(
    ("source", "expected_count"),
    [
        ("accounts", 1),
        ("transactions", 3),
        ("positions", 1),
        ("cash", 1),
        ("assets", 1),
        ("snapshots", 1),
        ("cached-quotes", 1),
        ("alerts", 1),
        ("watchlist", 2),
        ("targets", 2),
        ("realized", 0),
        ("payouts", 1),
        ("backups", 1),
    ],
)
def test_real_saved_sources_offline_without_writes(fictional_summary_data, fake, source, expected_count):
    store = fictional_summary_data
    changes = store._conn.total_changes
    snapshots, backups = store.snapshots(), store.backups()
    result = CliRunner().invoke(main, ["summarize", source, "--metric", "rows=count"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [{"rows": expected_count}]
    assert fake.calls == []
    assert store._conn.total_changes == changes
    assert store.snapshots() == snapshots
    assert store.backups() == backups


def test_real_grouped_transactions_hide_archived_accounts(fictional_summary_data):
    result = CliRunner().invoke(
        main,
        [
            "summarize",
            "transactions",
            "--group-by",
            "account",
            "--group-by",
            "currency",
            "--where",
            "type=BUY",
            "--metric",
            "rows=count",
            "--metric",
            "quantity=number-sum:quantity",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [{"account": "Fictional Cash", "currency": "CAD", "rows": 1, "quantity": "2"}]


def test_config_summaries_cannot_leak_keys_or_open_tracker(monkeypatch):
    from marketpulse.config import Config

    config = Config()
    config.quote_api_key = "fictional-secret-that-must-not-appear"
    monkeypatch.setattr(Config, "load", classmethod(lambda cls: config))
    monkeypatch.setattr(App, "tracker", property(lambda self: pytest.fail("opened tracker")))
    for source in ("config", "config-diff"):
        result = CliRunner().invoke(
            main, ["summarize", source, "--where", "key=quote_api_key", "--metric", "saved=values:value"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == [{"saved": ["(set)"]}]
        assert config.quote_api_key not in result.output
