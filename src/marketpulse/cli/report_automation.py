"""Offline reporting over saved automation cycle history."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import App

if TYPE_CHECKING:
    from ..db import AutomationRun

GROUP = "system"
SOURCES: dict[str, tuple[str, ...]] = {
    "automation-runs": (
        "id",
        "ran_at",
        "failed",
        "retained_failure",
        "stale",
        "stale_count",
        "stale_since",
        "snapshot_date",
        "fired_count",
        "error_count",
        "quote_error_count",
    ),
}
DESCRIPTIONS = {
    "automation-runs": "Saved automation runs and the latest failure retained beyond the rolling history.",
}
PRESETS = {
    "automation-runs": {
        "failed": ("in_values", "failed=[true]"),
        "stale": ("in_values", "stale=[true]"),
        "quote-errors": ("gt", "quote_error_count=0"),
    },
}


def _count(items: Any) -> int | None:
    # A run that raised before finishing can lack these lists. Preserve that distinction from zero.
    return len(items) if isinstance(items, list) else None


def _row(run: AutomationRun, *, retained_failure: bool) -> dict[str, Any]:
    report = run.report
    return {
        "id": run.id,
        "ran_at": run.ran_at,
        "failed": run.failed,
        "retained_failure": retained_failure,
        "stale": report.get("stale"),
        "stale_count": report.get("stale_count"),
        "stale_since": report.get("stale_since"),
        "snapshot_date": report.get("snapshot_date"),
        "fired_count": _count(report.get("fired")),
        "error_count": _count(report.get("errors")),
        "quote_error_count": _count(report.get("quote_errors")),
    }


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    if name not in SOURCES:
        raise KeyError(name)
    runs, pruned_failure = app.store.automation_status()
    rows = [_row(run, retained_failure=False) for run in runs]
    if pruned_failure is not None:
        rows.append(_row(pruned_failure, retained_failure=True))
    return rows
