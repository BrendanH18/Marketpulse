"""Saved snapshots can be audited by calendar month without repricing the portfolio."""

from marketpulse.cli.base import App
from marketpulse.cli.report_snapshot_coverage import SOURCES, load_source
from marketpulse.db import Snapshot

SOURCE = "snapshot-month-coverage"


def test_monthly_snapshot_coverage_clips_edges_and_omits_empty_months(tracker, fake):
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
