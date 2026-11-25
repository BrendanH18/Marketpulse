"""Saved snapshots can be audited by calendar month without repricing the portfolio."""

import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.cli.base import App
from marketpulse.cli.report_snapshot_coverage import SOURCES, load_source
from marketpulse.db import Snapshot

SOURCE = "snapshot-month-coverage"


def test_monthly_snapshot_coverage_clips_edges_and_includes_empty_months(tracker, fake):
    app = App()
    app._tracker = tracker
    store = tracker.store
    store.upsert_snapshots(
        [
            Snapshot("2024-04-02", 120, 100, 100, "CAD", {}),
            Snapshot("2024-02-29", 119, 100, 100, "USD", {"backfilled": True}),
            Snapshot("2024-01-30", 100, 100, 100, "CAD", {"accounts": {"Fictional Archived": 100}}),
            Snapshot("2024-02-01", 102, 100, 100, "CAD", {"backfilled": 1}),
            Snapshot("2024-02-28", 118, 100, 100, "CAD", ["legacy detail"]),
            Snapshot("2024-04-03", 121, 100, 100, "CAD", {"backfilled": False}),
        ]
    )
    changes = store._conn.total_changes

    rows = load_source(SOURCE, app)

    assert rows == [
        {
            "snapshots": 1,
            "month": "2024-01",
            "first_date": "2024-01-30",
            "last_date": "2024-01-30",
            "expected_days": 2,
            "missing_days": 1,
            "currencies": ["CAD"],
            "backfilled_days": 0,
        },
        {
            "snapshots": 3,
            "month": "2024-02",
            "first_date": "2024-02-01",
            "last_date": "2024-02-29",
            "expected_days": 29,
            "missing_days": 26,
            "currencies": ["CAD", "USD"],
            "backfilled_days": 1,
        },
        {
            "snapshots": 0,
            "month": "2024-03",
            "first_date": None,
            "last_date": None,
            "expected_days": 31,
            "missing_days": 31,
            "currencies": [],
            "backfilled_days": 0,
        },
        {
            "snapshots": 2,
            "month": "2024-04",
            "first_date": "2024-04-02",
            "last_date": "2024-04-03",
            "expected_days": 3,
            "missing_days": 1,
            "currencies": ["CAD"],
            "backfilled_days": 0,
        },
    ]
    assert all(tuple(row) == SOURCES[SOURCE] for row in rows)
    assert store._conn.total_changes == changes
    assert not fake.calls


def test_gaps_preset_finds_a_fully_missing_month(tracker, monkeypatch):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    tracker.store.upsert_snapshots([Snapshot(day, 100, 90, 80, "CAD", {}) for day in ("2025-01-31", "2025-03-01")])

    result = CliRunner().invoke(main, ["report", SOURCE, "--preset", "gaps", "--fields", "month,missing_days"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [{"month": "2025-02", "missing_days": 28}]


def test_monthly_snapshot_coverage_for_empty_and_single_day_history(tracker):
    app = App()
    app._tracker = tracker
    assert load_source(SOURCE, app) == []

    tracker.store.upsert_snapshot(Snapshot("2024-12-31", 100, 90, 80, "CAD", {}))

    assert load_source(SOURCE, app) == [
        {
            "snapshots": 1,
            "month": "2024-12",
            "first_date": "2024-12-31",
            "last_date": "2024-12-31",
            "expected_days": 1,
            "missing_days": 0,
            "currencies": ["CAD"],
            "backfilled_days": 0,
        }
    ]


def test_monthly_snapshot_coverage_ignores_invalid_saved_dates(tracker):
    app = App()
    app._tracker = tracker
    tracker.store.upsert_snapshots(
        [
            Snapshot(day, 100, 90, 80, currency, detail)
            for day, currency, detail in [
                ("0000-01-01", "USD", {"backfilled": True}),
                ("2024-01-31", "CAD", {}),
                ("2024-02-01", "CAD", {}),
                ("2024-02-15x", "USD", {"backfilled": True}),
                ("2024-02-29", "CAD", {}),
                ("2024-02-30", "USD", {"backfilled": True}),
                ("2024-03-01", "CAD", {}),
                ("20240301", "USD", {"backfilled": True}),
                ("unknown", "USD", {"backfilled": True}),
            ]
        ]
    )

    rows = load_source(SOURCE, app)

    assert [(row["month"], row["snapshots"], row["missing_days"]) for row in rows] == [
        ("2024-01", 1, 0),
        ("2024-02", 2, 27),
        ("2024-03", 1, 0),
    ]
    assert all(row["currencies"] == ["CAD"] and row["backfilled_days"] == 0 for row in rows)


CHANGES = "snapshot-changes"


def test_snapshot_changes_compare_each_valid_snapshot_with_the_previous_one(tracker, fake):
    app = App()
    app._tracker = tracker
    store = tracker.store
    store.upsert_snapshots(
        [
            Snapshot("2024-01-01", 0.1, 0, 0.1, "CAD", {}),
            Snapshot("2024-01-02", 0.4, 0, 0.3, "CAD", {"backfilled": True}),
            Snapshot("2024-01-02x", 999, 0, 999, "CAD", {}),
            Snapshot("2024-01-05", 0.3, 0, 0.4, "CAD", {"backfilled": 1}),
            Snapshot("2024-01-06", 50, 40, 40, "USD", ["legacy detail"]),
            Snapshot("2024-02-30", 999, 0, 999, "USD", {}),
            Snapshot("2024-03-01", 60, 40, 45, "USD", {"backfilled": False}),
            Snapshot("20240302", 999, 0, 999, "USD", {}),
        ]
    )
    changes = store._conn.total_changes

    rows = load_source(CHANGES, app)

    assert all(tuple(row) == SOURCES[CHANGES] for row in rows)
    assert [tuple(row.values()) for row in rows] == [
        # 0.4 - 0.1 and 0.3 - 0.1 carry binary noise; rows keep six decimals, like the snapshots source.
        ("2024-01-02", "2024-01-01", 1, "CAD", True, 0.4, 0.1, 0.3, 300.0, 0.2, 0.1, True),
        ("2024-01-05", "2024-01-02", 3, "CAD", True, 0.3, 0.4, -0.1, -25.0, 0.1, -0.2, False),
        ("2024-01-06", "2024-01-05", 1, "USD", False, 50.0, 0.3, None, None, None, None, False),
        ("2024-03-01", "2024-01-06", 55, "USD", True, 60.0, 50.0, 10.0, 20.0, 5.0, 5.0, False),
    ]
    assert store._conn.total_changes == changes
    assert not fake.calls


def test_snapshot_changes_leave_percent_empty_after_zero_net_worth(tracker):
    app = App()
    app._tracker = tracker
    tracker.store.upsert_snapshots(
        [Snapshot("2024-01-01", 0, 0, 0, "CAD", {}), Snapshot("2024-01-02", 25, 20, 20, "CAD", {})]
    )

    assert load_source(CHANGES, app) == [
        {
            "date": "2024-01-02",
            "previous_date": "2024-01-01",
            "gap_days": 1,
            "currency": "CAD",
            "same_currency": True,
            "net_worth": 25.0,
            "previous_net_worth": 0.0,
            "change": 25.0,
            "change_pct": None,
            "contributions_change": 20.0,
            "market_change": 5.0,
            "backfilled": False,
        }
    ]


def test_snapshot_changes_need_two_valid_snapshots(tracker):
    app = App()
    app._tracker = tracker
    assert load_source(CHANGES, app) == []

    tracker.store.upsert_snapshots(
        [Snapshot("2024-01-01", 100, 90, 80, "CAD", {}), Snapshot("unknown", 120, 90, 80, "CAD", {})]
    )

    assert load_source(CHANGES, app) == []


@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        ("gains", [("2024-01-02", 10.0, 1), ("2024-01-09", 5.0, 1)]),
        ("losses", [("2024-01-05", -20.0, 3)]),
        ("gaps", [("2024-01-05", -20.0, 3)]),
    ],
)
def test_snapshot_changes_presets_through_report_and_summarize(tracker, fake, monkeypatch, preset, expected):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    store = tracker.store
    store.upsert_snapshots(
        [
            Snapshot("2024-01-01", 100, 90, 80, "CAD", {}),
            Snapshot("2024-01-02", 110, 90, 80, "CAD", {}),
            Snapshot("2024-01-05", 90, 90, 80, "CAD", {}),
            # A currency change leaves change null; numeric presets must skip it without failing.
            Snapshot("2024-01-06", 70, 60, 60, "USD", {}),
            Snapshot("2024-01-07", 70, 60, 60, "USD", {}),
            Snapshot("2024-01-08", 30, 60, 60, "CAD", {}),
            Snapshot("2024-01-09", 35, 60, 60, "CAD", {}),
        ]
    )
    changes = store._conn.total_changes
    runner = CliRunner()

    report = runner.invoke(main, ["report", CHANGES, "--preset", preset, "--fields", "date,change,gap_days"])
    summary = runner.invoke(main, ["summarize", CHANGES, "--preset", preset, "--metric", "rows=count"])

    assert report.exit_code == 0, report.output
    assert [tuple(row.values()) for row in json.loads(report.output)] == expected
    assert summary.exit_code == 0, summary.output
    assert json.loads(summary.output) == [{"rows": len(expected)}]
    assert store._conn.total_changes == changes
    assert not fake.calls
