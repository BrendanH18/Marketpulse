"""Income payment cadence by symbol, account and calendar year."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from ..ledger import transaction_currency
from ..models import Transaction, TxnType
from .base import App
from .report_dates import parse_date_argument

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


_INCOME_TYPES = (TxnType.DIVIDEND, TxnType.DRIP, TxnType.INTEREST)


def _income_amount(txn: Transaction) -> float:
    """The income the ledger records for one payment: a DRIP's reinvested value, otherwise its amount."""
    return txn.quantity * txn.price if txn.type is TxnType.DRIP else txn.amount


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    if name not in SOURCES:
        raise KeyError(name)
    active_accounts, transactions = app.store.activity_snapshot()
    accounts = {account.saved_id: account for account in active_accounts}
    groups: dict[tuple[int, int, str, str], list[Transaction]] = defaultdict(list)
    for txn in transactions:
        if txn.type not in _INCOME_TYPES or not isinstance(txn.date, str):
            continue
        day = parse_date_argument(txn.date)
        if day is None:
            continue
        groups[day.year, txn.account_id, txn.symbol, transaction_currency(txn, accounts)].append(txn)

    rows = []
    for (year, account_id, symbol, currency), entries in sorted(groups.items()):
        drips = sum(txn.type is TxnType.DRIP for txn in entries)
        months = sorted({int(txn.date[5:7]) for txn in entries})
        dates = [txn.date for txn in entries]
        rows.append(
            {
                "year": year,
                "account_id": account_id,
                "account": accounts[account_id].name,
                "symbol": symbol,
                "currency": currency,
                "payments": len(entries),
                "cash_payments": len(entries) - drips,
                "drip_payments": drips,
                # Rounded like the snapshots source, only to drop binary float noise (3 x 0.1), not to cents.
                "amount": round(math.fsum(_income_amount(txn) for txn in entries), 6),
                "months": months,
                "distinct_months": len(months),
                "first_date": min(dates),
                "last_date": max(dates),
            }
        )
    return rows
