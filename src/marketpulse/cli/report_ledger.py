"""Read-only ledger rollups for the composable report command; active accounts only."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

from ..ledger import LedgerState, sort_key, transaction_currency
from ..models import EPSILON, Account, Transaction, TxnType
from .base import App

if TYPE_CHECKING:  # for annotations only; the real import stays lazy
    from ..db import Store

GROUP = "ledger"
SOURCES: dict[str, tuple[str, ...]] = {
    "holdings": ("symbol", "currency", "accounts", "quantity", "book", "first_date"),
    "closed-positions": ("account_id", "account", "symbol", "currency", "first_date", "last_date", "transactions"),
    "cash-flows": ("date", "account_id", "account", "amount", "currency"),
    "fees": ("transaction_id", "date", "account_id", "account", "type", "symbol", "fee", "currency"),
    "ledger-issues": ("transaction_id", "date", "account_id", "account", "code", "message", "details"),
    "symbols": (
        "symbol",
        "transactions",
        "first_date",
        "last_date",
        "held",
        "watched",
        "alerts",
        "asset_kind",
        "cached_quote",
    ),
    "currencies": ("currency", "base", "accounts", "transactions", "positions", "cash_balances", "cached_quotes"),
    "account-activity": (
        "account_id",
        "account",
        "type",
        "currency",
        "transactions",
        "first_date",
        "last_date",
        "open_positions",
        "symbols",
    ),
    "rooms": ("account_type", "as_of_year", "amount"),
}
DESCRIPTIONS: dict[str, str] = {
    "holdings": "Open ledger positions pooled by symbol and currency across active accounts.",
    "closed-positions": "Positions in active accounts whose ledger quantity has returned to zero.",
    "cash-flows": "Recorded deposits and withdrawals as signed external cash flows.",
    "fees": "Fees recorded on saved transactions in active accounts.",
    "ledger-issues": "Ledger replay warnings for transactions in active accounts.",
    "symbols": "Every symbol in visible saved data and where it is used.",
    "currencies": "Every currency in visible saved data and where it is used.",
    "account-activity": "Transaction counts, date ranges and open positions for each active account.",
    "rooms": "Saved contribution-room baselines by account type.",
}


def _finite(value: Any) -> Any:
    """JSON has no Infinity or NaN: an overflowed sum or a saved infinity is reported as null."""
    return None if isinstance(value, float) and not math.isfinite(value) else value


def _date_range(dates: list[str]) -> tuple[str | None, str | None]:
    """Earliest and latest of saved ISO dates, which order as text."""
    return (min(dates), max(dates)) if dates else (None, None)


def _holdings(state: LedgerState, accounts: dict[int, Account]) -> list[dict[str, Any]]:
    pooled: dict[tuple[str, str], dict[str, Any]] = {}
    for h in state.open_holdings():  # in account order, so the sums are reproducible
        if h.account_id not in accounts:
            continue
        row = pooled.setdefault(
            (h.symbol, h.currency),
            {
                "symbol": h.symbol,
                "currency": h.currency,
                "accounts": 0,
                "quantity": 0.0,
                "book": 0.0,
                "first_date": h.first_date,
            },
        )
        row["accounts"] += 1  # a ledger position is one account's stake in the symbol
        row["quantity"] += h.quantity
        row["book"] += h.book
        row["first_date"] = min(row["first_date"], h.first_date)
    return [
        {**row, "quantity": _finite(row["quantity"]), "book": _finite(row["book"])} for _, row in sorted(pooled.items())
    ]


def _closed_positions(
    state: LedgerState, accounts: dict[int, Account], transactions: list[Transaction]
) -> list[dict[str, Any]]:
    dates: dict[tuple[int, str], list[str]] = defaultdict(list)
    for txn in transactions:
        # A transfer is part of the position at both of its ends.
        for account_id in {txn.account_id, txn.target_account_id}:
            if account_id is not None:
                dates[(account_id, txn.symbol)].append(txn.date)
    rows = []
    for h in sorted(state.holdings.values(), key=lambda h: (h.account_id, h.symbol)):
        if h.quantity <= EPSILON and h.account_id in accounts:
            touched = dates.get((h.account_id, h.symbol), [])
            rows.append(
                {
                    "account_id": h.account_id,
                    "account": accounts[h.account_id].name,
                    "symbol": h.symbol,
                    "currency": h.currency,
                    "first_date": h.first_date,
                    "last_date": max(touched, default=None),
                    "transactions": len(touched),
                }
            )
    return rows


def _fees(state: LedgerState, accounts: dict[int, Account], transactions: list[Transaction]) -> list[dict[str, Any]]:
    rows = []
    for txn in sorted(transactions, key=sort_key):
        if txn.type is TxnType.FEE:
            fee = txn.amount
        elif txn.type in (TxnType.BUY, TxnType.DRIP, TxnType.SELL):
            fee = txn.fees
        else:
            continue  # the ledger ignores `fees` on every other type
        if fee <= 0:
            continue
        # The ledger charges a sale's fee in the currency of the position sold, whatever the sale says.
        sold = state.holdings.get((txn.account_id, txn.symbol)) if txn.type is TxnType.SELL else None
        rows.append(
            {
                "transaction_id": txn.id,
                "date": txn.date,
                "account_id": txn.account_id,
                "account": accounts[txn.account_id].name,
                "type": txn.type.value,
                "symbol": txn.symbol,
                "fee": _finite(fee),
                "currency": sold.currency if sold is not None else transaction_currency(txn, accounts),
            }
        )
    return rows


def _issues(state: LedgerState, accounts: dict[int, Account], transactions: list[Transaction]) -> list[dict[str, Any]]:
    owners = {txn.id: txn for txn in transactions}
    rows = []
    for issue in state.issues:
        txn = owners.get(issue.txn_id)
        if txn is None:  # raised by an archived account's transaction
            continue
        rows.append(
            {
                "transaction_id": issue.txn_id,
                "date": issue.date,
                "account_id": txn.account_id,
                "account": accounts[txn.account_id].name,
                "code": issue.code,
                "message": issue.message,
                "details": {key: _finite(value) for key, value in issue.args.items()},
            }
        )
    return rows


def _symbols(
    store: Store, state: LedgerState, accounts: dict[int, Account], transactions: list[Transaction]
) -> list[dict[str, Any]]:
    dates: dict[str, list[str]] = defaultdict(list)
    for txn in transactions:
        dates[txn.symbol].append(txn.date)
    # A position moved in from an archived account has no visible transaction, yet it is visible data.
    positions = [h for h in state.holdings.values() if h.account_id in accounts]
    held = {h.symbol for h in positions if h.quantity > EPSILON}
    assets = store.assets()
    watched = set(store.watchlist())
    alerts = Counter(alert.symbol for alert in store.alerts())
    cached = set(store.all_cached_quotes())
    symbols = {*dates, *(h.symbol for h in positions), *assets, *watched, *alerts, *cached} - {""}
    rows = []
    for symbol in sorted(symbols):
        first, last = _date_range(dates.get(symbol, []))
        rows.append(
            {
                "symbol": symbol,
                "transactions": len(dates.get(symbol, [])),
                "first_date": first,
                "last_date": last,
                "held": symbol in held,
                "watched": symbol in watched,
                "alerts": alerts[symbol],
                "asset_kind": assets[symbol].kind.value if symbol in assets else None,
                "cached_quote": symbol in cached,
            }
        )
    return rows


def _currencies(
    base: str, store: Store, state: LedgerState, accounts: dict[int, Account], transactions: list[Transaction]
) -> list[dict[str, Any]]:
    account_currencies = Counter(account.currency for account in accounts.values())
    transaction_currencies = Counter(transaction_currency(txn, accounts) for txn in transactions)
    position_currencies = Counter(h.currency for h in state.open_holdings() if h.account_id in accounts)
    # The balances the `cash` dataset lists: one per currency a cash-tracking active account has used.
    cash_currencies = Counter(
        currency for account_id, currency in state.cash if account_id in accounts and accounts[account_id].track_cash
    )
    quote_currencies = Counter(quote.currency for quote in store.all_cached_quotes().values())
    found = {
        base,  # listed even when nothing saved uses it yet
        *account_currencies,
        *transaction_currencies,
        *position_currencies,
        *cash_currencies,
        *quote_currencies,
    }
    return [
        {
            "currency": currency,
            "base": currency == base,
            "accounts": account_currencies[currency],
            "transactions": transaction_currencies[currency],
            "positions": position_currencies[currency],
            "cash_balances": cash_currencies[currency],
            "cached_quotes": quote_currencies[currency],
        }
        for currency in sorted(code for code in found if code)
    ]


def _account_activity(
    state: LedgerState, accounts: dict[int, Account], transactions: list[Transaction]
) -> list[dict[str, Any]]:
    own: dict[int, list[Transaction]] = {account_id: [] for account_id in accounts}
    for txn in transactions:
        own[txn.account_id].append(txn)
    open_positions = Counter(h.account_id for h in state.open_holdings())
    rows = []
    for account_id, account in accounts.items():
        first, last = _date_range([txn.date for txn in own[account_id]])
        rows.append(
            {
                "account_id": account_id,
                "account": account.name,
                "type": account.type.value,
                "currency": account.currency,
                "transactions": len(own[account_id]),
                "first_date": first,
                "last_date": last,
                "open_positions": open_positions[account_id],
                "symbols": len({txn.symbol for txn in own[account_id]} - {""}),
            }
        )
    return rows


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    """Return raw script rows without pricing holdings, recording snapshots or contacting providers."""
    if name not in SOURCES:
        raise KeyError(name)
    store = app.store
    if name == "rooms":
        # The baselines as saved; remaining room is the `room` command's calculation, not repeated here.
        return [
            {"account_type": account_type, "as_of_year": year, "amount": _finite(amount)}
            for account_type, (year, amount) in sorted(store.rooms().items())
        ]

    accounts = {a.saved_id: a for a in store.accounts()}
    state = store.ledger()  # the one replay; it covers archived accounts too, which every source filters out
    if name == "holdings":
        return _holdings(state, accounts)
    if name == "cash-flows":
        return [
            {
                "date": flow.date,
                "account_id": flow.account_id,
                "account": accounts[flow.account_id].name,
                "amount": _finite(flow.amount),
                "currency": flow.currency,
            }
            for flow in state.flows
            if flow.account_id in accounts
        ]

    # An archived account's transactions stay out of every row, count and date range, including its
    # transfers into an active account: those are not listed by the `transactions` dataset either.
    transactions = [txn for txn in store.transactions() if txn.account_id in accounts]
    if name == "closed-positions":
        return _closed_positions(state, accounts, transactions)
    if name == "fees":
        return _fees(state, accounts, transactions)
    if name == "ledger-issues":
        return _issues(state, accounts, transactions)
    if name == "symbols":
        return _symbols(store, state, accounts, transactions)
    if name == "currencies":
        # Upper-cased as `Tracker.base` reads it, so a hand-edited setting still matches saved codes.
        return _currencies(app.config.base_currency.upper(), store, state, accounts, transactions)
    return _account_activity(state, accounts, transactions)
