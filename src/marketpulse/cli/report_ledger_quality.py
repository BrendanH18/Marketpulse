"""Offline checks for likely duplicate transactions and how saved symbols are used."""

from __future__ import annotations

from typing import Any

from .base import App

GROUP = "ledger"
SOURCES = {
    "duplicate-transactions": (
        "transactions",
        "transaction_ids",
        "account_id",
        "account",
        "date",
        "type",
        "symbol",
        "quantity",
        "price",
        "amount",
        "fees",
        "currency",
        "target_account_id",
        "target_account",
        "notes_differ",
    ),
    "asset-usage": (
        "symbol",
        "usage",
        "has_asset",
        "kind",
        "name",
        "transactions",
        "accounts",
        "quantity",
        "watched",
        "alerts",
        "first_date",
        "last_date",
    ),
}
DESCRIPTIONS = {
    "duplicate-transactions": "Groups of identical transactions in active accounts that may have been recorded twice.",
    "asset-usage": "Each saved or referenced symbol with its transactions, holdings, watchlist entry and alerts.",
}
PRESETS = {
    "duplicate-transactions": {
        "same-note": ("in_values", "notes_differ=[false]"),
        "trades": ("in_values", "type=[BUY,SELL]"),
        "repeated": ("gt", "transactions=2"),
    },
    "asset-usage": {
        "held": ("ieq", "usage=held"),
        "watch-only": ("ieq", "usage=watched"),
        "unused": ("ieq", "usage=unused"),
    },
}


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    if name not in SOURCES:
        raise KeyError(name)
    return []
