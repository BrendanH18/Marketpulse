"""Versioned native-app bridge. The existing menu bar JSON contract stays intact."""

from __future__ import annotations

import hashlib
import json
import math
import platform
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from . import __version__
from .analytics import disposition_note, income_by_month, rebalance
from .automation import run_cycle
from .config import Config, config_path
from .db import Snapshot, Store
from .market import MarketData, MarketError
from .models import Account, AccountType, Asset, AssetClass, AssetKind, Quote, Transaction, TxnType
from .services import Tracker
from .tax import Disposition


def snapshot(tracker: Tracker, *, fresh: bool = False) -> dict:
    # Read before anything the app shows: a restore during the snapshot then makes its activity
    # revisions stale, so nothing shown from the replaced ledger can be edited or deleted.
    generation = tracker.store.restore_id
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
    targets = tracker.store.targets()
    # What each manual asset's value rests on: the valuation pricing uses, else the latest purchase.
    valued: dict[str, str] = {}
    for t in tracker.store.transactions():
        if t.type is TxnType.BUY and t.date > valued.get(t.symbol, ""):
            valued[t.symbol] = t.date
    valued.update({symbol: day for symbol, (day, _) in state.valuations.items()})
    return {
        "version": 1,
        "demo": False,
        "status": status,
        # Each with the revision an edit, archive or unarchive sends back (`accounts edit --revision`).
        "accounts": [
            # `registered`: tax-sheltered, so an in-kind transfer across that line needs a market price.
            {**asdict(a), "registered": a.type.registered, "revision": a.revision(generation)}
            for a in tracker.store.accounts()
        ],
        "archived_accounts": archived_accounts(amap, generation),
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
            activity_row(t, amap, generation)
            for t in reversed(tracker.store.transactions())
            if t.account_id not in archived
        ],
        "allocation": [asdict(b) for b in view.by_class],
        # Asset-class targets (`allocation --target`) and how far the portfolio is from each, as
        # `marketpulse allocation` shows them. Suggestions only: MarketPulse never trades.
        "targets": [{"bucket": k, "weight": w} for k, w in targets.items()],
        "rebalance": [{**asdict(r), "drift": r.drift} for r in rebalance(view.by_class, targets, view.net_worth)]
        if targets
        else [],
        "assets": [asset_row(a, valued) for a in tracker.store.assets().values()],
        "income_months": [{"date": d, "value": v} for d, v in income_by_month(state, view.fx.convert)],
        "room": [asdict(r) for r, _ in tracker.room()],
        "alerts": [{**asdict(a), "description": a.describe()} for a in tracker.store.alerts()],
        "automation": cycle.report,
        # Which engine answered: the app shows it, and release builds check it matches the tag.
        "backend": {"version": __version__, "python": platform.python_version()},
        "storage": storage_info(tracker.store),
        "settings": settings_info(tracker),
        "ledger_revision": ledger_revision(tracker, generation),
        "warnings": [
            *[f"{i.date}: {i.message}" for i in state.issues],
            *[f"Excluded from totals: {s}" for s in view.excluded],
            *[archived_warning(name) for name in view.archived_with_value],
        ],
    }


def asset_row(a: Asset, valued: dict[str, str]) -> dict:
    """A symbol's saved details (`marketpulse asset list`): a GIC or bond valued by accrual, an
    asset valued by hand, or a market symbol whose asset class was overridden."""
    return {
        **asdict(a),
        "asset_class": a.asset_class.value if a.asset_class else None,
        "asset_class_label": a.asset_class.label if a.asset_class else None,
        "valued_on": valued.get(a.symbol) if a.kind is AssetKind.MANUAL else None,
    }


def ledger_revision(tracker: Tracker, generation: str = "") -> str:
    """Changes whenever anything a tax report reads does, archived accounts and their entries
    included (the snapshot leaves those out): the app reloads its Tax workspace only then.
    That includes the day: room rolls over on January 1, and superficial-loss windows close."""
    store = tracker.store
    parts = [
        date.today().isoformat(),
        *(t.revision(generation) for t in store.transactions()),
        *(a.revision(generation) for a in store.accounts(include_archived=True)),
        json.dumps(sorted(store.rooms().items())),
        tracker.base,
        repr(tracker.config.capital_gains_inclusion),
    ]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def write_tax_csv(tracker: Tracker, path: Path, year: int | None = None) -> dict:
    """Write the dispositions (one year's, or all) for an accountant; `marketpulse tax --csv`
    and the app's Export CSV. Returns how many were written, and the ledger issues that may
    have left sales out of the file (e.g. a transfer into a TFSA with no price)."""
    from .csvio import export_capital_gains

    years, report = tracker.tax_years()
    if year is not None and not any(y.year == year for y in years):
        raise ValueError(f"No capital gains or losses in {year}.")
    try:
        with path.open("w", newline="", encoding="utf-8") as f:
            n = export_capital_gains(years, tracker.store.account_map(), tracker.base, f, year=year)
    except OSError as e:
        raise ValueError(f"Couldn't write {path}: {e.strerror or e}") from e
    return {"exported": n, "issues": [{"date": i.date, "message": i.message} for i in report.issues]}


def archived_accounts(accounts: dict[int, Account], generation: str = "") -> list[dict]:
    """Only so Settings can offer to unarchive them; nothing else in the app shows these."""
    return [
        {"id": a.saved_id, "name": a.name, "type": a.type.value, "revision": a.revision(generation)}
        for a in accounts.values()
        if a.archived
    ]


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


TAX_NOTES = [
    "Estimates only, not tax advice. Check these figures against your T5008, T3 and T5 slips before you file.",
    "Purchases by a spouse or a corporation you control can also make a loss superficial; MarketPulse can't see those.",
]


def tax_report(tracker: Tracker) -> dict:
    """Capital gains for every year, as `marketpulse tax` computes them, for the app's Tax workspace.

    Amounts are in the base currency. A row missing an FX rate has no amounts (they aren't
    known) and is left out of every total, as in `marketpulse tax`. Every account counts,
    archived ones included, because CRA does; archived accounts are named only as archived.
    """
    years, report = tracker.tax_years()
    accounts = tracker.store.account_map()

    def amount(r: Disposition, value: float) -> float | None:
        return value if r.complete else None

    def account(account_id: int) -> dict:
        acct = accounts.get(account_id)
        return {
            "account_id": account_id,
            "account": acct.name if acct and not acct.archived else None,
            "account_type": acct.type.value if acct else None,
            "archived": bool(acct and acct.archived),
        }

    return {
        "version": 1,
        "demo": False,
        "base_currency": tracker.base,
        "inclusion_rate": tracker.config.capital_gains_inclusion,
        "years": [
            {
                "year": y.year,
                "proceeds": y.proceeds,
                "acb": y.cost,
                "denied": y.denied,
                "net_gain": y.net_gain,
                "taxable": y.taxable,
                "inclusion_rate": y.inclusion_rate,
                "dispositions": len(y.rows),
                "missing_fx": len(y.missing_fx),
                "superficial": sum(1 for r in y.rows if r.superficial),
                "securities": [
                    {
                        "symbol": s.symbol,
                        "dispositions": len(s.rows),
                        "quantity": s.quantity,
                        "proceeds": s.proceeds,
                        "acb": s.cost,
                        "denied": s.denied,
                        "net_gain": s.net_gain,
                        "missing_fx": s.missing_fx,
                    }
                    for s in y.by_symbol()
                ],
                "rows": [
                    {
                        "id": f"{r.date}:{r.txn_id}:{i}",
                        "date": r.date,
                        **account(r.account_id),
                        "symbol": r.symbol,
                        "quantity": r.quantity,
                        "currency": r.currency,
                        "fx": r.fx,
                        "kind": r.kind,
                        "complete": r.complete,
                        "proceeds": amount(r, r.proceeds),
                        "acb": amount(r, r.acb),
                        "gain": amount(r, r.gain),
                        "denied": amount(r, r.denied),
                        "allowed_gain": amount(r, r.allowed_gain),
                        "denied_reason": r.denied_reason,
                        "superficial": r.superficial,
                        "acquired_in_window": r.acquired_in_window,
                        "held_after_window": r.held_after_window,
                        "window_open": r.window_open,
                        "note": disposition_note(r),
                        "transaction_id": r.txn_id,
                    }
                    for i, r in enumerate(y.rows)
                ],
            }
            for y in years
        ],
        "issues": [{"date": i.date, "message": i.message} for i in report.issues],
        "room": [asdict(r) for r, _ in tracker.room()],
        "notes": TAX_NOTES,
    }


def archived_warning(name: str) -> str:
    return (
        f"Archived account {name} still holds investments or cash. They're left out of your totals, "
        "and daily snapshots are paused. Move or sell them, or unarchive the account."
    )


def activity_row(t: Transaction, accounts: dict[int, Account], generation: str = "") -> dict:
    """A ledger entry for the app; `value` is unsigned and `direction` gives its sign."""
    target = accounts.get(t.target_account_id) if t.target_account_id is not None else None
    return {
        **asdict(t),
        "value": t.gross_value,
        "direction": t.cash_direction,
        "target_account": target.name if target else "",
        # Sent back with an edit or delete (`txn edit --revision`), which is refused if the entry changed.
        "revision": t.revision(generation),
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

    def daily_closes(self, symbol: str, start: str) -> tuple[dict[str, float], str]:
        """A fictional, gently rising USD/CAD rate, so the demo's tax report has trade-date FX."""
        if symbol != "USDCAD=X":
            raise MarketError(f"No demo history for {symbol}")
        first = date.fromisoformat(start)
        days = max((date.today() - first).days, 1)
        return {
            (first + timedelta(days=i)).isoformat(): round(1.34 + 0.03 * i / days, 4) for i in range(days + 1)
        }, "CAD"


@contextmanager
def demo_tracker() -> Iterator[Tracker]:
    """A fictional portfolio in a temporary folder. Never opens the user's ledger, fetches
    quotes, or sends notifications; the folder is deleted afterwards."""
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
            # Taxable sales for the Tax workspace: a loss bought back within 30 days (superficial),
            # then a gain whose cost base carries the denied loss.
            for days, kind, qty, price in [
                (130, TxnType.SELL, 15, 104.80),
                (118, TxnType.BUY, 15, 107.40),
                (60, TxnType.SELL, 20, 131.40),
            ]:
                store.add_transaction(
                    Transaction(
                        account_id=taxable.saved_id,
                        type=kind,
                        date=(date.today() - timedelta(days=days)).isoformat(),
                        symbol="NVDA",
                        quantity=qty,
                        price=price,
                        fees=4.95,
                        currency="USD",
                    )
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
            # A GIC valued by accrual, and targets for the Allocation workspace.
            gic_start = date.today() - timedelta(days=200)
            store.upsert_asset(
                Asset(
                    symbol="GIC-DEMO",
                    kind=AssetKind.FIXED_INCOME,
                    name="Fictional 2-year GIC",
                    asset_class=AssetClass.FIXED_INCOME,
                    currency="CAD",
                    rate=4.1,
                    start_date=gic_start.isoformat(),
                    maturity_date=(gic_start + timedelta(days=730)).isoformat(),
                )
            )
            store.add_transaction(
                Transaction(
                    account_id=rrsp.saved_id,
                    type=TxnType.BUY,
                    date=gic_start.isoformat(),
                    symbol="GIC-DEMO",
                    quantity=1,
                    price=8000,
                    currency="CAD",
                )
            )
            store.set_targets({"etf": 55, "equity": 35, "fixed_income": 10})
            store.add_watch(["AAPL", "MSFT", "NVDA", "XEQT.TO"])
            store.set_room("TFSA", date.today().year, 18000)
            yield tracker
        finally:
            store.close()


def demo_snapshot() -> dict:
    """Never open the user's ledger, fetch quotes, or send notifications."""
    with demo_tracker() as tracker:
        store = tracker.store
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


def demo_tax() -> dict:
    """The demo portfolio's tax report, from the same fictional ledger as `demo_snapshot`."""
    with demo_tracker() as tracker:
        return {**tax_report(tracker), "demo": True}
