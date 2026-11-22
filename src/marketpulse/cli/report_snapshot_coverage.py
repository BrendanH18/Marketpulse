"""Calendar coverage of saved net-worth snapshots."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from itertools import groupby
from typing import TYPE_CHECKING, Any

from .base import App

if TYPE_CHECKING:
    from ..db import Snapshot

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
    "snapshot-month-coverage": "Saved snapshot counts, gaps, currencies and backfilled days by calendar month.",
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
    # Keep canonical dates so the store's ascending text order is chronological.
    snapshots: list[tuple[date, Snapshot]] = []
    for snapshot in app.store.snapshots():
        try:
            day = date.fromisoformat(snapshot.date)
        except (TypeError, ValueError):
            continue
        if day.isoformat() == snapshot.date:
            snapshots.append((day, snapshot))
    if not snapshots:
        return []
    history_first = snapshots[0][0]
    history_last = snapshots[-1][0]
    by_month = {
        month: [snapshot for _, snapshot in entries]
        for month, entries in groupby(snapshots, key=lambda pair: pair[0].replace(day=1))
    }
    rows = []
    first_day = history_first.replace(day=1)
    while True:
        month_snapshots = by_month.get(first_day, [])
        last_day = first_day.replace(day=monthrange(first_day.year, first_day.month)[1])
        expected_days = (min(last_day, history_last) - max(first_day, history_first)).days + 1
        rows.append(
            {
                "snapshots": len(month_snapshots),
                "month": first_day.isoformat()[:7],
                "first_date": month_snapshots[0].date if month_snapshots else None,
                "last_date": month_snapshots[-1].date if month_snapshots else None,
                "expected_days": expected_days,
                "missing_days": expected_days - len(month_snapshots),
                "currencies": sorted({snapshot.currency for snapshot in month_snapshots}),
                "backfilled_days": sum(
                    isinstance(snapshot.detail, dict) and snapshot.detail.get("backfilled") is True
                    for snapshot in month_snapshots
                ),
            }
        )
        if last_day >= history_last:
            break
        first_day = last_day + timedelta(days=1)
    return rows
