"""Shared maintenance cycle for the desktop app and unattended CLI runs."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from .services import Tracker
from .valuation import PortfolioView


@dataclass
class Cycle:
    view: PortfolioView
    report: dict


def run_cycle(tracker: Tracker, *, fresh: bool = False, notify: bool = True) -> Cycle:
    """Refresh valuation, record eligible snapshots, check alerts, and back up.

    Backup failures are visible but do not stop market refreshes. Stale or
    incomplete valuations are never saved as a daily performance snapshot.
    No trades, deposits, or other ledger entries are created by this cycle.
    """
    errors: list[str] = []
    try:
        tracker.store.auto_backup()
    except (OSError, sqlite3.Error) as e:
        errors.append(f"Backup failed: {e}")
    view = tracker.valuation(use_cache=not fresh)
    _, watch, watch_errors = tracker.watchlist_quotes(use_cache=not fresh)
    # Include alert-only symbols, even when neither held nor watched.
    active = tracker.store.alerts(active_only=True)
    quotes, alert_errors = (
        tracker.market.quotes([a.symbol for a in active], use_cache=not fresh) if active else ({}, {})
    )
    fired = tracker.check_alerts({**view.quotes, **watch, **quotes}, notify=notify)
    errors += [f"{s}: {e}" for s, e in {**view.errors, **watch_errors, **alert_errors}.items()]
    backups = tracker.store.backups()
    latest = tracker.store.latest_snapshot()
    report = {
        "last_run": datetime.now().isoformat(timespec="seconds"),
        "stale": view.stale or any(q.stale for q in [*watch.values(), *quotes.values()]),
        "snapshot_date": latest.date if latest and latest.currency == view.base else None,
        "backup": backups[0].name if backups else None,
        "fired": [a.describe() for a in fired],
        "errors": errors,
    }
    tracker.store.set_meta("automation_last_run", json.dumps(report, allow_nan=False))
    return Cycle(view, report)
