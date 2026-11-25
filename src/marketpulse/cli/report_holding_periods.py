"""Position episodes from first share to last share, per account and symbol."""

from __future__ import annotations

from typing import Any

from .base import App

GROUP = "ledger"
SOURCES = {
    "holding-periods": (
        "account_id",
        "account",
        "symbol",
        "episode",
        "status",
        "opened",
        "closed",
        "days_held",
        "increases",
        "decreases",
        "peak_quantity",
        "quantity",
    ),
}
DESCRIPTIONS = {
    "holding-periods": "Each period an active account held a symbol, from opening to closing, with days held.",
}
PRESETS = {
    "holding-periods": {
        "open": ("ieq", "status=open"),
        "closed": ("ieq", "status=closed"),
        "under-a-year": ("lt", "days_held=365"),
    },
}


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    if name not in SOURCES:
        raise KeyError(name)
    return []
