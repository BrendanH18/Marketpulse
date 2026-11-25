"""Position episodes from first share to last share, per account and symbol."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from ..ledger import LedgerState, _apply, sort_key
from ..models import EPSILON, TxnType
from .base import App
from .report_dates import date_of

if TYPE_CHECKING:  # for annotations only; the real import stays lazy
    from ..db import Store

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


def _finite(value: float) -> float | None:
    """JSON has no Infinity or NaN: an overflowed quantity is reported as null, as `holdings` does."""
    return value if math.isfinite(value) else None


def _days(opened: str, closed: str) -> int | None:
    start, end = date_of(opened), date_of(closed)
    return (end - start).days if start and end else None


def _episodes(store: Store) -> list[dict[str, Any]]:
    accounts = {a.saved_id: a for a in store.accounts()}
    everyone = store.account_map()  # replay sees archived accounts too, exactly as `Store.ledger` does
    state = LedgerState()
    episodes: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for txn in sorted(store.transactions(), key=sort_key):
        # A transfer changes two positions: the source account's and the target account's.
        keys = [(txn.account_id, txn.symbol)]
        if txn.type is TxnType.TRANSFER and txn.target_account_id is not None:
            keys.append((txn.target_account_id, txn.symbol))
        before = {key: _quantity(state, key) for key in keys}
        _apply(state, txn, everyone)  # the ledger's own arithmetic, so episodes can't drift from holdings
        for key in dict.fromkeys(keys):  # a transfer to its own account touches one position once
            if key[0] not in accounts:
                continue  # an archived account's own positions stay hidden
            old, new = before[key], _quantity(state, key)
            if old == new or (old <= EPSILON and new <= EPSILON):
                continue
            rows = episodes.setdefault(key, [])
            if old <= EPSILON:  # from nothing held to a position: a new episode opens
                rows.append(
                    {
                        "account_id": key[0],
                        "account": accounts[key[0]].name,
                        "symbol": key[1],
                        "episode": len(rows) + 1,
                        "status": "open",
                        "opened": txn.date,
                        "closed": None,
                        "days_held": None,
                        "increases": 0,
                        "decreases": 0,
                        "peak_quantity": 0.0,
                        "quantity": 0.0,
                    }
                )
            row = rows[-1]
            transfer = txn.type is TxnType.TRANSFER
            incoming = txn.type in (TxnType.BUY, TxnType.DRIP) or (transfer and key[0] == txn.target_account_id)
            outgoing = txn.type is TxnType.SELL or (transfer and key[0] == txn.account_id)
            if new > old and incoming:
                row["increases"] += 1
            elif new < old and outgoing:
                row["decreases"] += 1  # splits change the quantity but count as neither
            if new <= EPSILON:
                row.update(status="closed", closed=txn.date, days_held=_days(row["opened"], txn.date), quantity=0.0)
            else:
                row["quantity"] = new
                row["peak_quantity"] = max(row["peak_quantity"], new)
    return [
        {**row, "peak_quantity": _finite(row["peak_quantity"]), "quantity": _finite(row["quantity"])}
        for _, rows in sorted(episodes.items())
        for row in rows
    ]


def _quantity(state: LedgerState, key: tuple[int, str]) -> float:
    holding = state.holdings.get(key)
    return holding.quantity if holding else 0.0


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    """Replay the saved ledger once, without pricing, recording snapshots or contacting providers."""
    if name not in SOURCES:
        raise KeyError(name)
    return _episodes(app.store)
