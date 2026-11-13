"""Fictional saved data proves the contribution-room and snapshot-classes report sources (#143)."""

from __future__ import annotations

import json
import math
from dataclasses import asdict

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.cli.base import App
from marketpulse.cli.report_history import SOURCES, load_source
from marketpulse.db import Snapshot
from marketpulse.models import Account, AccountType, Transaction, TxnType


@pytest.fixture
def report_app(tracker, monkeypatch):
    """An active RRSP, an archived RRSP and an empty TFSA, with saved room and three snapshots."""
    store = tracker.store
    rrsp = store.add_account(Account("Fictional RRSP", AccountType.RRSP)).saved_id
    archived = store.add_account(Account("Fictional Archived", AccountType.RRSP, archived=True)).saved_id
    store.add_account(Account("Fictional Empty", AccountType.TFSA, currency="USD"))
    store.add_transaction(Transaction(rrsp, TxnType.DEPOSIT, "2024-01-15", amount=500, currency="CAD"))
    store.add_transaction(Transaction(archived, TxnType.DEPOSIT, "2024-01-05", amount=300, currency="CAD"))
    store.set_room("RRSP", 2024, 10000)
    store.set_room("RESP", 2023, 2500)
    store.upsert_snapshot(Snapshot("2024-03-06", 900.5, 800, 1000, "USD", {"classes": {"etf": 900.5}}))
    store.upsert_snapshot(
        Snapshot(
            "2024-03-05",
            1200,
            1000,
            1300,
            "CAD",
            {
                "accounts": {"Fictional RRSP": 700.25, "Fictional Archived": 499.75},
                "classes": {"equity": 589.75, "cash": 610.25},
            },
        )
    )
    store.upsert_snapshot(Snapshot("2024-03-04", 1100, 1000, 1300, "CAD", {"backfilled": True}))
    # Each CLI invocation builds its own App; every one of them gets this tracker.
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    return App()


# Worked out by hand from the fixture above, not by running the loader.
EXPECTED = {
    # RESP and RRSP room ignore the calendar. The archived RRSP's 300 deposit still uses room,
    # as the engine counts it; only its name stays out of `accounts`.
    "contribution-room": [
        {
            "account_type": "RESP",
            "as_of_year": 2023,
            "starting_room": 2500.0,
            "contributions": 0,
            "withdrawals_added_back": 0.0,
            "new_limits": 0.0,
            "remaining": 2500.0,
            "forfeited": 0.0,
            "accounts": [],
        },
        {
            "account_type": "RRSP",
            "as_of_year": 2024,
            "starting_room": 10000.0,
            "contributions": 800.0,
            "withdrawals_added_back": 0.0,
            "new_limits": 0.0,
            "remaining": 9200.0,
            "forfeited": 0.0,
            "accounts": ["Fictional RRSP"],
        },
    ],
    # In date order; the backfilled snapshot has no breakdown, and the account names are left out.
    "snapshot-classes": [
        {"date": "2024-03-05", "asset_class": "cash", "value": 610.25, "currency": "CAD"},
        {"date": "2024-03-05", "asset_class": "equity", "value": 589.75, "currency": "CAD"},
        {"date": "2024-03-06", "asset_class": "etf", "value": 900.5, "currency": "USD"},
    ],
}


def assert_native_json(value) -> None:
    """`json.dumps` would accept a tuple or a StrEnum silently, so check the exact types."""
    assert type(value) in (str, int, float, bool, type(None), list, dict), repr(value)
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, list):
        for item in value:
            assert_native_json(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            assert type(key) is str
            assert_native_json(item)


def run(*args: str):
    result = CliRunner().invoke(main, list(args))
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


@pytest.mark.parametrize("name", SOURCES)
def test_sources_have_stable_schemas_without_network_or_writes(name, report_app, fake):
    store = report_app.store
    changes = store._conn.total_changes
    snapshots = store.snapshots()
    backups = store.backups()
    rows = load_source(name, report_app)
    assert rows == EXPECTED[name]
    assert all(tuple(row) == SOURCES[name] for row in rows)
    assert_native_json(rows)
    assert fake.calls == []
    assert store._conn.total_changes == changes
    assert store.snapshots() == snapshots
    assert store.backups() == backups


@pytest.mark.parametrize("name", SOURCES)
def test_sources_never_name_the_archived_account(name, report_app):
    assert "Fictional Archived" not in json.dumps(load_source(name, report_app))


def test_contribution_room_is_the_engine_result(report_app):
    store = report_app.store
    # TFSA and FHSA room roll forward with the calendar, so compare with the engine, not fixed numbers.
    store.set_room("TFSA", 2023, 6500)
    store.set_room("FHSA", 2023, 8000)
    engine = report_app.tracker.room()
    rows = load_source("contribution-room", report_app)
    assert [row["account_type"] for row in rows] == ["FHSA", "RESP", "RRSP", "TFSA"]
    assert rows == [{**asdict(status), "accounts": [a.name for a in members]} for status, members in engine]
    assert rows[1:3] == EXPECTED["contribution-room"]
    assert rows[3]["accounts"] == ["Fictional Empty"]


def test_snapshot_classes_skip_details_without_a_breakdown(report_app):
    store = report_app.store
    for day, detail in (
        ("2024-03-07", {}),
        ("2024-03-08", {"classes": ["equity"]}),
        ("2024-03-09", {"classes": None}),
        ("2024-03-10", ["equity"]),
    ):
        store.upsert_snapshot(Snapshot(day, 1000, 1000, 1000, "CAD", detail))
    assert load_source("snapshot-classes", report_app) == EXPECTED["snapshot-classes"]


@pytest.mark.parametrize("name", SOURCES)
def test_report_and_summarize_serve_each_source_offline(name, report_app, fake):
    store = report_app.store
    changes = store._conn.total_changes
    assert run("report", name) == EXPECTED[name]
    assert run("summarize", name, "--metric", "rows=count") == [{"rows": len(EXPECTED[name])}]
    assert fake.calls == []
    assert store._conn.total_changes == changes


def test_report_operations_compose_over_these_sources(report_app):
    assert run("report", "snapshot-classes", "--sort", "value", "--descending", "--limit", "1") == [
        {"date": "2024-03-06", "asset_class": "etf", "value": 900.5, "currency": "USD"}
    ]
    assert run("summarize", "snapshot-classes", "--group-by", "currency", "--metric", "total=number-sum:value") == [
        {"currency": "CAD", "total": "1200"},
        {"currency": "USD", "total": "900.5"},
    ]
    assert run("summarize", "contribution-room", "--metric", "left=number-sum:remaining") == [{"left": "11700"}]
    assert run(
        "report", "contribution-room", "--has-item", 'accounts="Fictional RRSP"', "--fields", "account_type"
    ) == [{"account_type": "RRSP"}]


@pytest.mark.parametrize("name", SOURCES)
def test_empty_saved_data_returns_empty_rows(name, tracker):
    app = App()
    app._tracker = tracker
    assert load_source(name, app) == []


def test_unknown_source_is_rejected_before_opening_the_store(monkeypatch):
    app = App()
    monkeypatch.setattr(App, "store", property(lambda self: pytest.fail("must not open store")))
    monkeypatch.setattr(App, "tracker", property(lambda self: pytest.fail("must not open tracker")))
    with pytest.raises(KeyError, match="unknown"):
        load_source("unknown", app)
