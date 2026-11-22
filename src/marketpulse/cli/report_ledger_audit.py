"""Offline diagnostics for saved transaction currencies and transfer routes."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..ledger import transaction_currency
from ..models import Account, Transaction, TxnType, guess_currency
from .base import App

GROUP = "ledger"
SOURCES = {
    "transaction-currency-audit": (
        "transaction_id",
        "account_id",
        "account",
        "date",
        "type",
        "symbol",
        "account_currency",
        "recorded_currency",
        "effective_currency",
        "currency_source",
        "differs_from_account",
    ),
    "transfer-routes": (
        "source_account_id",
        "source_account",
        "target_account_id",
        "target_account",
        "transactions",
        "first_date",
        "last_date",
        "currencies",
        "symbols",
        "same_account_currency",
    ),
}
DESCRIPTIONS = {
    "transaction-currency-audit": "Recorded and resolved input currencies for transactions from active accounts.",
    "transfer-routes": "Transfer counts, dates, currencies and symbols by directed pair of active accounts.",
}
PRESETS = {
    "transaction-currency-audit": {
        "explicit": ("ieq", "currency_source=explicit"),
        "inferred": ("ine", "currency_source=explicit"),
        "cross-currency": ("in_values", "differs_from_account=[true]"),
    },
    "transfer-routes": {
        "same-currency": ("in_values", "same_account_currency=[true]"),
        "cross-currency": ("in_values", "same_account_currency=[false]"),
        "repeat": ("gt", "transactions=1"),
    },
}


def _currency_audit(accounts: dict[int, Account], transactions: list[Transaction]) -> list[dict[str, Any]]:
    rows = []
    for txn in transactions:
        account = accounts[txn.account_id]
        effective_currency = transaction_currency(txn, accounts)
        if txn.currency:
            source = "explicit"
        elif txn.symbol and guess_currency(txn.symbol, ""):
            source = "symbol"
        else:
            source = "account"
        rows.append(
            {
                "transaction_id": txn.saved_id,
                "account_id": txn.account_id,
                "account": account.name,
                "date": txn.date,
                "type": txn.type.value,
                "symbol": txn.symbol,
                "account_currency": account.currency,
                "recorded_currency": txn.currency or None,
                "effective_currency": effective_currency,
                "currency_source": source,
                "differs_from_account": effective_currency != account.currency,
            }
        )
    return rows


def _transfer_routes(accounts: dict[int, Account], transactions: list[Transaction]) -> list[dict[str, Any]]:
    routes: dict[tuple[int, int], list[Transaction]] = defaultdict(list)
    for txn in transactions:
        target = txn.target_account_id
        if txn.type is TxnType.TRANSFER and target is not None and target in accounts and target != txn.account_id:
            routes[txn.account_id, target].append(txn)

    rows = []
    for (source_id, target_id), entries in sorted(routes.items()):
        source, target_account = accounts[source_id], accounts[target_id]
        rows.append(
            {
                "source_account_id": source_id,
                "source_account": source.name,
                "target_account_id": target_id,
                "target_account": target_account.name,
                "transactions": len(entries),
                "first_date": entries[0].date,
                "last_date": entries[-1].date,
                "currencies": sorted({transaction_currency(txn, accounts) for txn in entries}),
                "symbols": sorted({txn.symbol for txn in entries if txn.symbol}),
                "same_account_currency": source.currency == target_account.currency,
            }
        )
    return rows


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    if name not in SOURCES:
        raise KeyError(name)
    active_accounts, transactions = app.store.activity_snapshot()
    accounts = {account.saved_id: account for account in active_accounts}
    if name == "transaction-currency-audit":
        return _currency_audit(accounts, transactions)
    return _transfer_routes(accounts, transactions)
