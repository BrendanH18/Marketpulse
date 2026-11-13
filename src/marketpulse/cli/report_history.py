"""Read-only report sources for derived contribution room and saved snapshot breakdowns."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .base import App

GROUP = "ledger"
SOURCES: dict[str, tuple[str, ...]] = {
    "contribution-room": (
        "account_type",
        "as_of_year",
        "starting_room",
        "contributions",
        "withdrawals_added_back",
        "new_limits",
        "remaining",
        "forfeited",
        "accounts",
    ),
    "snapshot-classes": ("date", "asset_class", "value", "currency"),
}
DESCRIPTIONS: dict[str, str] = {
    "contribution-room": "Remaining contribution room the engine derives from saved baselines and recorded flows.",
    "snapshot-classes": "Asset-class breakdown saved with each net-worth snapshot.",
}


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    """Return raw script rows without pricing holdings, recording snapshots or contacting providers."""
    if name == "contribution-room":
        # The engine counts archived accounts' contributions, as CRA does, and lists only active members.
        return [{**asdict(status), "accounts": [a.name for a in members]} for status, members in app.tracker.room()]
    if name == "snapshot-classes":
        rows: list[dict[str, Any]] = []
        for snapshot in app.store.snapshots():
            # Backfilled and older snapshots have no breakdown, and the column can hold any JSON.
            classes = snapshot.detail.get("classes") if isinstance(snapshot.detail, dict) else None
            if isinstance(classes, dict):
                rows += [
                    {"date": snapshot.date, "asset_class": key, "value": classes[key], "currency": snapshot.currency}
                    for key in sorted(classes)
                ]
        return rows
    raise KeyError(name)
