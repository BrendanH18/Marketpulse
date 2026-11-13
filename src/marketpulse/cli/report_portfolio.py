"""Read-only report sources backed by saved portfolio data and ledger replay."""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any

from ..models import EPSILON, Account, Alert, Asset, Transaction
from .allocation import _target_rows
from .base import App
from .data import BACKUP_FIELDS, _backup_metadata
from .positions import CASH_FIELDS, POSITION_FIELDS
from .quotes import QUOTE_FIELDS, _quote_json
from .realized import PAYOUT_FIELDS, REALIZED_FIELDS, _payout_row, _realized_row
from .snapshots import SNAPSHOT_FIELDS, _changes, _record

SOURCES: dict[str, tuple[str, ...]] = {
    "accounts": tuple(f.name for f in fields(Account)),
    "assets": tuple(f.name for f in fields(Asset)),
    "transactions": (*tuple(f.name for f in fields(Transaction)), "account"),
    "positions": tuple(POSITION_FIELDS),
    "cash": tuple(CASH_FIELDS),
    "snapshots": tuple(SNAPSHOT_FIELDS),
    "cached-quotes": tuple(QUOTE_FIELDS),
    "alerts": tuple(f.name for f in fields(Alert)),
    "watchlist": ("position", "symbol"),
    "targets": ("bucket", "label", "target"),
    "realized": tuple(REALIZED_FIELDS),
    "payouts": tuple(PAYOUT_FIELDS),
    "backups": tuple(BACKUP_FIELDS),
}

GROUP = "portfolio"
DESCRIPTIONS: dict[str, str] = {
    "accounts": "Active account metadata.",
    "assets": "Saved asset definitions.",
    "transactions": "Ledger transaction records for active accounts.",
    "positions": "Open ledger positions without market prices.",
    "cash": "Ledger cash balances without currency conversion.",
    "snapshots": "Previously recorded net-worth snapshots.",
    "cached-quotes": "Quotes already saved in the offline cache.",
    "alerts": "Saved alert definitions.",
    "watchlist": "Saved watched symbols.",
    "targets": "Saved allocation targets.",
    "realized": "Ledger-derived realized events.",
    "payouts": "Ledger-derived income events.",
    "backups": "Local backup inventory metadata.",
}


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    """Return raw script rows without pricing holdings, recording snapshots or contacting providers."""
    if name not in SOURCES:
        raise KeyError(name)
    store = app.store
    if name == "assets":
        return [asdict(a) for _, a in sorted(store.assets().items())]
    if name == "snapshots":
        snapshots = store.snapshots()
        changes = _changes(snapshots)
        return [_record(s, changes[s.date]) for s in snapshots]
    if name == "cached-quotes":
        return [_quote_json(symbol, quote, {}) for symbol, quote in store.all_cached_quotes().items()]
    if name == "alerts":
        return [asdict(a) for a in store.alerts()]
    if name == "watchlist":
        return [{"position": i, "symbol": symbol} for i, symbol in enumerate(store.watchlist(), 1)]
    if name == "targets":
        return _target_rows(store.targets())
    if name == "backups":
        return [_backup_metadata(path) for path in store.backups()]

    accounts = {a.saved_id: a for a in store.accounts()}
    if name == "accounts":
        return [asdict(a) for a in accounts.values()]
    if name == "transactions":
        rows = []
        for txn in store.transactions():
            if txn.account_id not in accounts:
                continue
            row = {**asdict(txn), "account": accounts[txn.account_id].name}
            # Do not expose an archived transfer destination through portfolio inspection.
            if txn.target_account_id is not None and txn.target_account_id not in accounts:
                row["target_account_id"] = None
            rows.append(row)
        return rows

    state = store.ledger()
    if name == "positions":
        return [
            {
                "account_id": h.account_id,
                "account": accounts[h.account_id].name,
                "symbol": h.symbol,
                "quantity": h.quantity,
                "book": h.book,
                "average_cost": h.avg_cost,
                "currency": h.currency,
                "first_date": h.first_date,
            }
            for h in state.open_holdings()
            if h.account_id in accounts
        ]
    if name == "cash":
        return [
            {
                "account_id": account_id,
                "account": accounts[account_id].name,
                "currency": currency,
                "balance": 0.0 if abs(balance) < EPSILON else balance,
            }
            for (account_id, currency), balance in sorted(state.cash.items())
            if account_id in accounts and accounts[account_id].track_cash
        ]
    if name == "realized":
        return [_realized_row(r, accounts) for r in state.realized if r.account_id in accounts]
    return [_payout_row(p, accounts) for p in state.income if p.account_id in accounts]
