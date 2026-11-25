"""Income payment cadence by symbol, account and calendar year."""

from __future__ import annotations

from typing import Any

from .base import App

GROUP = "ledger"
SOURCES = {
    "income-calendar": (
        "year",
        "account_id",
        "account",
        "symbol",
        "currency",
        "payments",
        "cash_payments",
        "drip_payments",
        "amount",
        "months",
        "distinct_months",
        "first_date",
        "last_date",
    ),
}
DESCRIPTIONS = {
    "income-calendar": "Dividend, reinvested dividend and interest payments by year, account, symbol and currency.",
}
PRESETS = {
    "income-calendar": {
        "monthly": ("gt", "distinct_months=11"),
        "reinvested": ("gt", "drip_payments=0"),
        "single-payment": ("in_values", "payments=[1]"),
    },
}


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    if name not in SOURCES:
        raise KeyError(name)
    return []
