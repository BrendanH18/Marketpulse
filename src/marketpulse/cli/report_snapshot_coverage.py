"""Calendar coverage of saved net-worth snapshots."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from itertools import groupby, pairwise
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
    "snapshot-changes": (
        "date",
        "previous_date",
        "gap_days",
        "currency",
        "same_currency",
        "net_worth",
        "previous_net_worth",
        "change",
        "change_pct",
        "contributions_change",
        "market_change",
        "backfilled",
    ),
}
DESCRIPTIONS = {
    "snapshot-month-coverage": "Saved snapshot counts, gaps, currencies and backfilled days by calendar month.",
    "snapshot-changes": "Change in saved net worth and contributions since the previous saved snapshot.",
}
PRESETS = {
    "snapshot-month-coverage": {
        "gaps": ("gt", "missing_days=0"),
        "backfilled": ("gt", "backfilled_days=0"),
        "mixed-currency": ("min_length", "currencies=2"),
    },
    "snapshot-changes": {
        "gains": ("gt", "change=0"),
        "losses": ("lt", "change=0"),
        "gaps": ("gt", "gap_days=1"),
    },
}


def _valid_snapshots(app: App) -> list[tuple[date, Snapshot]]:
    """Saved snapshots whose date is a canonical ``YYYY-MM-DD``, in date order, with that date."""
    # Keep canonical dates so the store's ascending text order is chronological.
    snapshots: list[tuple[date, Snapshot]] = []
    for snapshot in app.store.snapshots():
        try:
            day = date.fromisoformat(snapshot.date)
        except (TypeError, ValueError):
            continue
        if day.isoformat() == snapshot.date:
            snapshots.append((day, snapshot))
    return snapshots


def _backfilled(snapshot: Snapshot) -> bool:
    return isinstance(snapshot.detail, dict) and snapshot.detail.get("backfilled") is True


def _month_coverage(snapshots: list[tuple[date, Snapshot]]) -> list[dict[str, Any]]:
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
                "backfilled_days": sum(_backfilled(snapshot) for snapshot in month_snapshots),
            }
        )
        if last_day >= history_last:
            break
        first_day = last_day + timedelta(days=1)
    return rows


def _changes(snapshots: list[tuple[date, Snapshot]]) -> list[dict[str, Any]]:
    rows = []
    for (previous_day, previous), (day, snapshot) in pairwise(snapshots):
        same_currency = snapshot.currency == previous.currency
        change = contributions_change = market_change = change_pct = None
        if same_currency:
            raw_change = snapshot.net_worth - previous.net_worth
            raw_contributions = snapshot.contributions - previous.contributions
            # Rounded like the snapshots source, only to drop binary float noise, not to cents.
            change = round(raw_change, 6)
            contributions_change = round(raw_contributions, 6)
            market_change = round(raw_change - raw_contributions, 6)
            if previous.net_worth:
                change_pct = round(raw_change / previous.net_worth * 100, 6)
        rows.append(
            {
                "date": snapshot.date,
                "previous_date": previous.date,
                "gap_days": (day - previous_day).days,
                "currency": snapshot.currency,
                "same_currency": same_currency,
                "net_worth": snapshot.net_worth,
                "previous_net_worth": previous.net_worth,
                "change": change,
                "change_pct": change_pct,
                "contributions_change": contributions_change,
                "market_change": market_change,
                "backfilled": _backfilled(snapshot),
            }
        )
    return rows


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    if name not in SOURCES:
        raise KeyError(name)
    snapshots = _valid_snapshots(app)
    if name == "snapshot-changes":
        return _changes(snapshots)
    return _month_coverage(snapshots)
