"""Calendar coverage of saved net-worth snapshots."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from itertools import groupby
from typing import Any

from .base import App

GROUP = "ledger"
SOURCES = {
    "snapshot-month-coverage": (
        "snapshots",
        "month",
        "first_date",
        "last_date",
        "expected_days",
        "missing_days",
        "currencies",
        "backfilled_days",
    ),
}
DESCRIPTIONS = {
    "snapshot-month-coverage": "Saved snapshot counts, gaps, currencies and backfilled days per populated month.",
}
PRESETS = {
    "snapshot-month-coverage": {
        "gaps": ("gt", "missing_days=0"),
        "backfilled": ("gt", "backfilled_days=0"),
        "mixed-currency": ("min_length", "currencies=2"),
    },
}


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    if name not in SOURCES:
        raise KeyError(name)
    snapshots = app.store.snapshots()
    if not snapshots:
        return []
    history_first = date.fromisoformat(snapshots[0].date)
    history_last = date.fromisoformat(snapshots[-1].date)
    rows = []
    # The store returns one snapshot per ISO date in ascending order.
    for month, entries in groupby(snapshots, key=lambda snapshot: snapshot.date[:7]):
        month_snapshots = list(entries)
        first_day = date.fromisoformat(f"{month}-01")
        last_day = first_day.replace(day=monthrange(first_day.year, first_day.month)[1])
        expected_days = (min(last_day, history_last) - max(first_day, history_first)).days + 1
        rows.append(
            {
                "snapshots": len(month_snapshots),
                "month": month,
                "first_date": month_snapshots[0].date,
                "last_date": month_snapshots[-1].date,
                "expected_days": expected_days,
                "missing_days": expected_days - len(month_snapshots),
                "currencies": sorted({snapshot.currency for snapshot in month_snapshots}),
                "backfilled_days": sum(
                    isinstance(snapshot.detail, dict) and snapshot.detail.get("backfilled") is True
                    for snapshot in month_snapshots
                ),
            }
        )
    return rows
