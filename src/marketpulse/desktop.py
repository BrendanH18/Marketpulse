"""Versioned native-app bridge. The existing menu bar JSON contract stays intact."""

from __future__ import annotations

import math
import platform
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from . import __version__
from .analytics import income_by_month
from .automation import run_cycle
from .config import Config, config_path
from .db import Snapshot, Store
from .market import MarketData
from .models import Account, AccountType, Quote, Transaction, TxnType
from .services import Tracker


def snapshot(tracker: Tracker, *, fresh: bool = False) -> dict:
    cycle = run_cycle(tracker, fresh=fresh)
    view = cycle.view
    state = tracker.store.ledger()
    status = tracker.status_payload(view, history_days=None, evaluate_alerts=False)
    # Alerts were already evaluated by the cycle; report what it fired, as `status --json` does.
    status["fired"] = cycle.report["fired"]
    # Archived accounts never appear in the app (valuation already leaves out their
    # holdings); their own transactions are hidden too, though the ledger keeps them.
    amap = tracker.store.account_map()
    archived = {i for i, a in amap.items() if a.archived}
    return {
        "version": 1,
        "demo": False,
        "status": status,
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
        "activity": [
            activity_row(t, amap) for t in reversed(tracker.store.transactions()) if t.account_id not in archived
        ],
        "allocation": [asdict(b) for b in view.by_class],
        "income_months": [{"date": d, "value": v} for d, v in income_by_month(state, view.fx.convert)],
        "room": [asdict(r) for r, _ in tracker.room()],
        "alerts": [{**asdict(a), "description": a.describe()} for a in tracker.store.alerts()],
        "automation": cycle.report,
        # Which engine answered: the app shows it, and release builds check it matches the tag.
        "backend": {"version": __version__, "python": platform.python_version()},
        "storage": storage_info(tracker.store),
        "settings": settings_info(tracker),
        "warnings": [
            *[f"{i.date}: {i.message}" for i in state.issues],
            *[f"Excluded from totals: {s}" for s in view.excluded],
            *[archived_warning(name) for name in view.archived_with_value],
        ],
    }


def storage_info(store: Store) -> dict:
    """Where the ledger lives, whether it's brand new, and the backups the app can restore."""
    return {
        "data_dir": str(store.path.parent),
        # A brand-new ledger, so the app offers its welcome. Archived accounts count: their
        # owner has used MarketPulse before. Every transaction belongs to an account.
        "empty": not store.accounts(include_archived=True),
        "backup_dir": str(store.backup_dir),
        "backups": [row for p in store.backups() if (row := backup_row(store, p)) is not None],
    }


def settings_info(tracker: Tracker) -> dict:
    """The configuration the app's Settings window edits with `config set`."""
    config = tracker.config
    try:
        account = tracker.store.get_account(config.default_account) if config.default_account else None
    except (OverflowError, ValueError):  # an id too large for SQLite, or digits like "²" int() rejects
        account = None
    return {
        "base_currency": tracker.base,
        "privacy": config.privacy,
        # As written in the config (a name, id or account type), and the active account it picks.
        "default_account": config.default_account,
        "default_account_id": account.saved_id if account and not account.archived else None,
        "menubar_display": config.menubar_display,
        "menubar_symbol": config.menubar_symbol,
        "config_path": str(config_path()),
    }


def backup_row(store: Store, path: Path) -> dict | None:
    """A backup the app can offer to restore, newest first like `backup list`. None if it's
    gone since the folder was listed (another process may prune automatic backups)."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return None
    taken = store.backup_time(path)
    return {
        "name": path.name,
        "reason": store.backup_reason(path),
        "taken_at": taken.isoformat() if taken else None,
        "size": size,
    }


def archived_warning(name: str) -> str:
    return (
        f"Archived account {name} still holds investments or cash. They're left out of your totals, "
        "and daily snapshots are paused. Move or sell them, or unarchive the account."
    )


def activity_row(t: Transaction, accounts: dict[int, Account]) -> dict:
    """A ledger entry for the app; `value` is unsigned and `direction` gives its sign."""
    target = accounts.get(t.target_account_id) if t.target_account_id is not None else None
    return {
        **asdict(t),
        "value": t.gross_value,
        "direction": t.cash_direction,
        "target_account": target.name if target else "",
        # Sent back with an edit or delete (`txn edit --revision`), which is refused if the entry changed.
        "revision": t.revision,
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
            # The demo's folder is temporary; the app must never show it as the user's.
            payload["storage"] = {"data_dir": None, "empty": False, "backup_dir": None, "backups": []}
            payload["settings"]["config_path"] = None
            return payload
        finally:
            store.close()
