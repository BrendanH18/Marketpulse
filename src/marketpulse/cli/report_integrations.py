"""Offline catalogs of broker transaction mappings and MarketPulse CSV columns."""

from __future__ import annotations

from typing import Any

from .. import brokers
from ..models import TxnType
from .base import App

GROUP = "reference"
SOURCES: dict[str, tuple[str, ...]] = {
    "broker-transaction-codes": ("profile", "column", "code", "action", "outcome", "type", "reason"),
    "transaction-csv-columns": ("position", "column", "required", "aliases"),
}
DESCRIPTIONS: dict[str, str] = {
    "broker-transaction-codes": "Known Questrade activity and Wealthsimple transaction codes with their mappings.",
    "transaction-csv-columns": "Transaction export columns in order with their generic CSV import rules.",
}
PRESETS: dict[str, dict[str, tuple[str, str]]] = {
    "broker-transaction-codes": {
        "supported": ("in_values", 'outcome=["mapped"]'),
        "skipped": ("in_values", 'outcome=["skipped"]'),
        "trade-actions": ("nonempty", "action"),
    },
    "transaction-csv-columns": {
        "required": ("in_values", "required=[true]"),
        "optional": ("in_values", "required=[false]"),
        "account-routing": ("in_values", 'column=["account","target_account"]'),
    },
}


def _code_row(
    profile: str, column: str, code: str, mapping: TxnType | str, action: str | None = None
) -> dict[str, Any]:
    kind, reason = (mapping.value, None) if isinstance(mapping, TxnType) else (None, mapping)
    return {
        "profile": profile,
        "column": column,
        "code": code,
        "action": action,
        "outcome": "mapped" if kind is not None else "skipped",
        "type": kind,
        "reason": reason,
    }


def _broker_codes() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code, mapping in brokers._QUESTRADE_ACTIVITY.items():
        if mapping == brokers._TRADE:
            # Questrade uses both Activity Type and Action to distinguish purchases from sales.
            rows.extend(
                _code_row("questrade", "activity type", code, trade, action)
                for action, trade in brokers._QUESTRADE_TRADES.items()
            )
        else:
            rows.append(_code_row("questrade", "activity type", code, mapping))
    rows.extend(
        _code_row("wealthsimple", "transaction", code, mapping) for code, mapping in brokers._WEALTHSIMPLE_CODES.items()
    )
    return rows


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    if name == "broker-transaction-codes":
        return _broker_codes()
    if name == "transaction-csv-columns":
        from ..csvio import EXPORT_COLUMNS, GENERIC_REQUIRED_COLUMNS

        return [
            {
                "position": position,
                "column": column,
                "required": column in GENERIC_REQUIRED_COLUMNS,
                "aliases": list(brokers._ALIASES[column]),
            }
            for position, column in enumerate(EXPORT_COLUMNS, 1)
        ]
    raise KeyError(name)
