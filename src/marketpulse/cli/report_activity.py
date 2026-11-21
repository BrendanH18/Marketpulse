"""Offline calendars and symbol histories from saved transactions."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..models import Transaction, TxnType
from .base import App

GROUP = "ledger"
SOURCES = {
    "transaction-months": (
        "account_id",
        "account",
        "month",
        "first_date",
        "last_date",
        "transactions",
        "types",
        "symbols",
    ),
    "account-symbols": ("account_id", "account", "symbol", "first_date", "last_date", "transactions", "types"),
}
DESCRIPTIONS = {
    "transaction-months": "Recorded activity and distinct symbols per active account and calendar month.",
    "account-symbols": "Recorded transaction types and history per active account and symbol.",
}
PRESETS = {
    "transaction-months": {
        "deposits": ("has_item", 'types="DEPOSIT"'),
        "withdrawals": ("has_item", 'types="WITHDRAWAL"'),
        "transfers": ("has_item", 'types="TRANSFER"'),
    },
    "account-symbols": {
        "buys": ("has_item", 'types="BUY"'),
        "sales": ("has_item", 'types="SELL"'),
        "dividends": ("has_item", 'types="DIVIDEND"'),
    },
}


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    if name not in SOURCES:
        raise KeyError(name)
    key_field = "month" if name == "transaction-months" else "symbol"
    active_accounts, transactions = app.store.activity_snapshot()
    accounts = {account.saved_id: account.name for account in active_accounts}
    groups: dict[tuple[int, str], list[Transaction]] = defaultdict(list)
    for txn in transactions:
        key = txn.date[:7] if key_field == "month" else txn.symbol
        if not key:
            continue
        groups[txn.account_id, key].append(txn)
        # Count visible transfers at both active ends.
        target = txn.target_account_id
        if txn.type is TxnType.TRANSFER and target is not None and target in accounts and target != txn.account_id:
            groups[target, key].append(txn)

    rows = []
    for (account_id, key), entries in sorted(groups.items()):
        row: dict[str, Any] = {
            "account_id": account_id,
            "account": accounts[account_id],
            key_field: key,
            "first_date": entries[0].date,
            "last_date": entries[-1].date,
            "transactions": len(entries),
            "types": sorted({txn.type.value for txn in entries}),
        }
        if key_field == "month":
            row["symbols"] = len({txn.symbol for txn in entries if txn.symbol})
        rows.append(row)
    return rows
