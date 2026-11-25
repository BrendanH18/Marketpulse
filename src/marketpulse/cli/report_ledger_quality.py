"""Offline checks for likely duplicate transactions and how saved symbols are used."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from ..ledger import LedgerState, replay, transaction_currency
from ..models import Account, Alert, Asset, Transaction
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
        "trades": ("in_values", 'type=["BUY","SELL"]'),
        "repeated": ("gt", "transactions=2"),
    },
    "asset-usage": {
        "held": ("ieq", "usage=held"),
        "watch-only": ("ieq", "usage=watched"),
        "unused": ("ieq", "usage=unused"),
    },
}


def _duplicates(accounts: dict[int, Account], transactions: list[Transaction]) -> list[dict[str, Any]]:
    """Group entries whose every saved field but the note matches; the note is often retyped on a re-entry."""
    groups: dict[tuple[Any, ...], list[Transaction]] = defaultdict(list)
    for txn in transactions:
        key = (
            txn.account_id,
            txn.date,
            txn.type,
            txn.symbol,
            txn.quantity,
            txn.price,
            txn.amount,
            txn.fees,
            transaction_currency(txn, accounts),  # an implied and an explicit CAD are the same entry
            txn.ratio,
            txn.target_account_id,
        )
        groups[key].append(txn)

    rows: list[dict[str, Any]] = []
    for entries in groups.values():
        if len(entries) < 2:
            continue
        first = entries[0]
        target_id = first.target_account_id
        target = accounts.get(target_id) if target_id is not None else None
        rows.append(
            {
                "transactions": len(entries),
                "transaction_ids": sorted(txn.saved_id for txn in entries),
                "account_id": first.account_id,
                "account": accounts[first.account_id].name,
                "date": first.date,
                "type": first.type.value,
                "symbol": first.symbol,
                "quantity": first.quantity,
                "price": first.price,
                "amount": first.amount,
                "fees": first.fees,
                "currency": transaction_currency(first, accounts),
                # Like the `transactions` dataset, an archived or removed target stays hidden.
                "target_account_id": target_id if target is not None else None,
                "target_account": target.name if target is not None else None,
                "notes_differ": len({txn.note.strip() for txn in entries}) > 1,
            }
        )
    rows.sort(key=lambda row: (row["date"], row["account_id"], row["transaction_ids"][0]))
    return rows


def _asset_usage(
    accounts: dict[int, Account],
    transactions: list[Transaction],
    ledger: LedgerState,
    saved_assets: dict[str, Asset],
    watchlist: list[str],
    saved_alerts: list[Alert],
) -> list[dict[str, Any]]:
    used: dict[str, list[Transaction]] = defaultdict(list)
    account_ids: dict[str, set[int]] = defaultdict(set)
    for txn in transactions:
        if not txn.symbol:
            continue
        used[txn.symbol].append(txn)
        # A transfer puts the symbol in both accounts, as in the `closed-positions` dataset.
        account_ids[txn.symbol].update(a for a in (txn.account_id, txn.target_account_id) if a in accounts)

    # The `holdings` dataset's replay: every account, so a position moved in from an archived account counts.
    quantity: dict[str, float] = defaultdict(float)
    for h in ledger.open_holdings():  # above EPSILON per account, so float noise is not held
        if h.account_id in accounts:
            quantity[h.symbol] += h.quantity
            account_ids[h.symbol].add(h.account_id)

    assets = {symbol.upper(): asset for symbol, asset in saved_assets.items()}
    watched = {symbol.strip().upper() for symbol in watchlist}
    alerts = Counter(alert.symbol.strip().upper() for alert in saved_alerts)
    symbols = {*assets, *used, *quantity, *watched, *alerts} - {""}

    rows = []
    for symbol in sorted(symbols):
        entries = used.get(symbol, [])
        asset = assets.get(symbol)
        held = quantity.get(symbol, 0.0)
        if held > 0:
            usage = "held"
        elif entries:
            usage = "traded"
        elif symbol in watched or alerts[symbol]:
            usage = "watched"
        else:
            usage = "unused"
        dates = [txn.date for txn in entries]
        rows.append(
            {
                "symbol": symbol,
                "usage": usage,
                "has_asset": asset is not None,
                "kind": asset.kind.value if asset is not None else None,
                "name": asset.name if asset is not None and asset.name.strip() else None,
                "transactions": len(entries),
                "accounts": sorted({accounts[account_id].name for account_id in account_ids.get(symbol, ())}),
                "quantity": held if math.isfinite(held) else None,
                "watched": symbol in watched,
                "alerts": alerts[symbol],
                "first_date": min(dates, default=None),
                "last_date": max(dates, default=None),
            }
        )
    return rows


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    """Read saved data only: no replay is written back, no quote is fetched and no snapshot is recorded."""
    if name not in SOURCES:
        raise KeyError(name)
    store = app.store
    if name == "duplicate-transactions":
        active_accounts, transactions = store.activity_snapshot()
        return _duplicates({account.saved_id: account for account in active_accounts}, transactions)
    # One snapshot for every read, so a restore in between can't pair two ledgers' rows.
    with store._read_snapshot():
        active_accounts = store.accounts()
        everyone = store.account_map()
        saved = store.transactions()
        saved_assets, watchlist, saved_alerts = store.assets(), store.watchlist(), store.alerts()
    accounts = {account.saved_id: account for account in active_accounts}
    transactions = [txn for txn in saved if txn.account_id in accounts]
    ledger = replay(saved, everyone)
    return _asset_usage(accounts, transactions, ledger, saved_assets, watchlist, saved_alerts)
