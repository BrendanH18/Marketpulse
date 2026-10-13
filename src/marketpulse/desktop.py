"""Versioned native-app bridge. The existing menu bar JSON contract stays intact."""

from __future__ import annotations

import math
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from .analytics import income_by_month
from .automation import run_cycle
from .config import Config
from .db import Snapshot, Store
from .market import MarketData
from .models import Account, AccountType, Quote, Transaction, TxnType
from .services import Tracker


def snapshot(tracker: Tracker, *, fresh: bool = False) -> dict:
    cycle = run_cycle(tracker, fresh=fresh)
    view = cycle.view
    state = tracker.store.ledger()
    return {
        "version": 1,
        "demo": False,
        "status": tracker.status_payload(view, history_days=3650, evaluate_alerts=False),
        "accounts": [asdict(a) for a in tracker.store.accounts()],
        "positions": [
            {
                "id": f"{p.account.saved_id}:{p.symbol}",
                "account_id": p.account.saved_id,
                "account": p.account.name,
                "symbol": p.symbol,
                "name": p.name,
                "asset_class": p.asset_class.label,
                "quantity": p.quantity,
                "price": p.price,
                "currency": p.currency,
                "value": p.value_base,
                "book": p.book_base,
                "gain": p.gain_base,
                "gain_pct": p.gain_pct,
                "day_change_pct": p.day_change_pct,
                "weight": p.weight,
                "stale": p.stale,
            }
            for p in view.positions
        ],
        "activity": [asdict(t) for t in reversed(tracker.store.transactions())],
        "allocation": [asdict(b) for b in view.by_class],
        "income_months": [{"date": d, "value": v} for d, v in income_by_month(state, view.fx.convert)],
        "room": [asdict(r) for r, _ in tracker.room()],
        "alerts": [{**asdict(a), "description": a.describe()} for a in tracker.store.alerts()],
        "automation": cycle.report,
        "warnings": [
            *[f"{i.date}: {i.message}" for i in state.issues],
            *[f"Excluded from totals: {s}" for s in view.excluded],
        ],
    }


class DemoMarket(MarketData):
    """Fictional, offline quotes. Only used by the explicit read-only demo."""

    def quotes(self, symbols, *, use_cache=True):
        data = {
            "XEQT.TO": (34.82, 34.58, "CAD", "iShares Core Equity ETF Portfolio", "ETF"),
            "VFV.TO": (143.26, 142.20, "CAD", "Vanguard S&P 500 Index ETF", "ETF"),
            "AAPL": (228.40, 226.80, "USD", "Apple Inc.", "EQUITY"),
            "MSFT": (428.75, 425.60, "USD", "Microsoft Corporation", "EQUITY"),
            "NVDA": (138.20, 140.10, "USD", "NVIDIA Corporation", "EQUITY"),
            "USDCAD=X": (1.36, 1.36, "CAD", "USD/CAD", "CURRENCY"),
        }
        out = {}
        for sym in symbols:
            if sym in data:
                price, prev, ccy, name, kind = data[sym]
                out[sym] = Quote(
                    symbol=sym,
                    price=price,
                    prev_close=prev,
                    currency=ccy,
                    name=name,
                    instrument_type=kind,
                    intraday=[prev, prev * 1.003, prev * 0.998, price],
                    market_state="CLOSED",
                )
        return out, {s: "No demo quote" for s in symbols if s not in out}


def demo_snapshot() -> dict:
    """Never open the user's ledger, fetch quotes, or send notifications."""
    with TemporaryDirectory(prefix="marketpulse-demo-") as tmp:
        store = Store(Path(tmp) / "demo.db")
        try:
            tracker = Tracker(store, DemoMarket(store=store), Config(theme="tokyo-night", market_strip=[]))
            tfsa = store.add_account(Account(name="Everyday TFSA", type=AccountType.TFSA, institution="Wealthsimple"))
            rrsp = store.add_account(Account(name="Future RRSP", type=AccountType.RRSP, institution="Questrade"))
            taxable = store.add_account(Account(name="Personal investing", institution="Wealthsimple", track_cash=True))
            start = (date.today() - timedelta(days=180)).isoformat()
            for acct, sym, qty, price, ccy in [
                (tfsa, "XEQT.TO", 950, 29.10, "CAD"),
                (tfsa, "VFV.TO", 140, 124.30, "CAD"),
                (rrsp, "AAPL", 90, 196.20, "USD"),
                (rrsp, "MSFT", 55, 388.60, "USD"),
                (taxable, "NVDA", 65, 114.50, "USD"),
            ]:
                store.add_transaction(
                    Transaction(
                        account_id=acct.saved_id,
                        type=TxnType.BUY,
                        date=start,
                        symbol=sym,
                        quantity=qty,
                        price=price,
                        currency=ccy,
                    )
                )
            store.add_transaction(
                Transaction(account_id=taxable.saved_id, type=TxnType.DEPOSIT, amount=14000, currency="USD", date=start)
            )
            for days, amount in [(75, 92.40), (45, 103.15), (15, 112.80)]:
                store.add_transaction(
                    Transaction(
                        account_id=tfsa.saved_id,
                        type=TxnType.DIVIDEND,
                        date=(date.today() - timedelta(days=days)).isoformat(),
                        symbol="XEQT.TO",
                        amount=amount,
                        currency="CAD",
                    )
                )
            store.add_watch(["AAPL", "MSFT", "NVDA", "XEQT.TO"])
            store.set_room("TFSA", date.today().year, 18000)
            view = tracker.valuation(record=False)
            for i in range(180):
                value = view.net_worth * (0.82 + 0.18 * i / 180 + 0.011 * math.sin(i / 9))
                store.upsert_snapshot(
                    Snapshot(
                        (date.today() - timedelta(days=180 - i)).isoformat(),
                        value,
                        view.invested,
                        view.invested,
                        "CAD",
                        {"fictional": True},
                    )
                )
            # Same serializer, with notifications suppressed by having no demo alerts.
            payload = snapshot(tracker)
            payload["demo"] = True
            payload["automation"]["backup"] = None
            return payload
        finally:
            store.close()
