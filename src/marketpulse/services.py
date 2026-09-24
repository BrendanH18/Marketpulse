"""Tracker: the single facade the CLI, TUI and menu bar talk to."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import alerts as alerts_mod
from . import fmt
from .analytics import (
    Performance,
    TaxYear,
    capital_gains,
    external_flows,
    income_forecast,
    performance,
)
from .config import Config
from .db import Snapshot, Store
from .ledger import RoomStatus, contribution_room, replay, replay_by_day, superficial_losses
from .market import MarketData, MarketError
from .models import (
    EPSILON,
    Account,
    AccountType,
    Alert,
    AssetClass,
    AssetKind,
    FxRates,
    Quote,
    Transaction,
    guess_currency,
)
from .themes import resolve_palette
from .valuation import PortfolioView, build_view, market_symbols


@dataclass
class StripItem:
    symbol: str
    label: str
    quote: Quote | None


STRIP_LABELS = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq",
    "^DJI": "Dow",
    "^GSPTSE": "TSX",
    "^RUT": "Russell",
    "^VIX": "VIX",
    "^TNX": "US 10Y",
    "USDCAD=X": "USD/CAD",
    "CADUSD=X": "CAD/USD",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ether",
    "GC=F": "Gold",
    "CL=F": "Oil",
}


class Tracker:
    def __init__(self, store: Store, market: MarketData, config: Config):
        self.store = store
        self.market = market
        self.config = config

    @classmethod
    def open(cls, config: Config | None = None) -> Tracker:
        store = Store.open_default()
        return cls(store, MarketData(store=store), config or Config.load())

    @property
    def base(self) -> str:
        return self.config.base_currency.upper()

    # ── symbols & currencies ──────────────────────────────────────────────────

    def resolve_currency(self, symbol: str, account: Account) -> tuple[str, Quote | None]:
        """Currency for a new trade: asset override, live listing, then a suffix guess."""
        if not symbol:
            return account.currency, None
        asset = self.store.assets().get(symbol.upper())
        if asset and asset.currency:
            return asset.currency, None
        if asset and asset.kind is not AssetKind.MARKET:
            return account.currency, None
        try:
            q = self.market.quote(symbol)
            return q.currency, q
        except MarketError:
            return guess_currency(symbol, account.currency), None

    def add_transaction(self, txn: Transaction) -> Transaction:
        if not txn.currency:
            acct = self.store.get_account(txn.account_id)
            if acct is None:
                raise ValueError("Unknown account.")
            txn.currency, _ = self.resolve_currency(txn.symbol, acct)
        txn.validate()
        if txn.type.value == "SELL":
            state = self.store.ledger()
            h = state.holdings.get((txn.account_id, txn.symbol))
            held = h.quantity if h else 0.0
            if txn.quantity > held + EPSILON:
                raise ValueError(
                    f"Cannot sell {fmt.qty(txn.quantity)} {txn.symbol} — only {fmt.qty(held)} held in this account."
                )
        return self.store.add_transaction(txn)

    # ── valuation ─────────────────────────────────────────────────────────────

    def valuation(self, *, use_cache: bool = True, record: bool = True, account_id: int | None = None) -> PortfolioView:
        state = self.store.ledger()
        accounts = self.store.account_map()
        assets = self.store.assets()
        symbols = market_symbols(state.symbols(), assets)
        quotes, errors = self.market.quotes(symbols, use_cache=use_cache) if symbols else ({}, {})
        currencies = {h.currency for h in state.open_holdings()} | {q.currency for q in quotes.values()}
        currencies |= {ccy for (_, ccy) in state.cash_balances()} | {r.currency for r in state.realized}
        currencies |= {i.currency for i in state.income}
        flows = external_flows(self.store.transactions(), accounts)
        currencies |= {c for _, _, c in flows}
        fx, fx_errors = self.market.fx_rates(currencies, self.base)
        errors.update({f"FX {k}": v for k, v in fx_errors.items()})
        view = build_view(state, accounts, assets, quotes, fx, errors=errors, account_id=account_id)
        if record and account_id is None and view.positions and not view.stale and not view.excluded:
            self.record_snapshot(view, fx, flows)
        return view

    def flows_base(self, fx: FxRates) -> list[tuple[str, float]]:
        """External flows converted at today's spot rate (a constant-FX view, used for XIRR).

        Snapshot `contributions` convert each flow at the rate on its own date instead,
        so `Performance.net_contributions` can differ slightly from the latest snapshot.
        """
        out = []
        for d, amount, ccy in external_flows(self.store.transactions(), self.store.account_map()):
            v = fx.convert(amount, ccy)
            if v is not None:
                out.append((d, v))
        return out

    def record_snapshot(
        self, view: PortfolioView, fx: FxRates, flows: list[tuple[str, float, str]] | None = None
    ) -> None:
        """Upsert today's snapshot.

        `contributions` is cumulative money in, each flow converted at the FX rate of
        its own day, so consecutive snapshots differ only by that day's real flows
        (which is what time-weighted returns strip out). We extend the most recent
        earlier snapshot with the flows since then at today's spot; only the very first
        snapshot converts the whole history at spot. Back-dated entries before that
        snapshot are picked up by `backfill`.
        """
        today = date.today().isoformat()
        if flows is None:
            flows = external_flows(self.store.transactions(), self.store.account_map())
        prev = self.store.latest_snapshot(before=today)
        if prev is not None and prev.currency == view.base:
            newer = [(a, c) for d, a, c in flows if d > prev.date]
            converted = [fx.convert(a, c) for a, c in newer]
            if any(v is None for v in converted):
                return  # a rate is missing: don't write a snapshot we know is wrong
            contributions = prev.contributions + sum(converted)
        else:
            contributions = sum(a for _, a in self.flows_base(fx))
        detail = {
            "accounts": {b.label: round(b.value, 2) for b in view.by_account},
            "classes": {b.key: round(b.value, 2) for b in view.by_class},
        }
        self.store.upsert_snapshot(
            Snapshot(
                date.today().isoformat(),
                view.net_worth,
                view.invested + view.cash_total,
                contributions,
                view.base,
                detail,
            )
        )

    def performance(self, view: PortfolioView) -> Performance:
        snaps = [(s.date, s.net_worth, s.contributions) for s in self.store.snapshots() if s.currency == view.base]
        return performance(view, self.flows_base(view.fx), snaps)

    # ── quotes for watchlist & market strip ───────────────────────────────────

    def watchlist_quotes(self, *, use_cache: bool = True) -> tuple[list[str], dict[str, Quote], dict[str, str]]:
        symbols = self.store.watchlist()
        quotes, errors = self.market.quotes(symbols, use_cache=use_cache) if symbols else ({}, {})
        return symbols, quotes, errors

    def market_strip(self, *, use_cache: bool = True) -> list[StripItem]:
        symbols = self.config.market_strip
        quotes, _ = self.market.quotes(symbols, use_cache=use_cache) if symbols else ({}, {})
        return [StripItem(s, STRIP_LABELS.get(s.upper(), s.upper()), quotes.get(s.upper())) for s in symbols]

    # ── alerts ────────────────────────────────────────────────────────────────

    def check_alerts(self, quotes: dict[str, Quote] | None = None, *, notify: bool = True) -> list[Alert]:
        active = self.store.alerts(active_only=True)
        if not active:
            return []
        if quotes is None or any(a.symbol not in quotes for a in active):
            fetched, _ = self.market.quotes([a.symbol for a in active])
            quotes = {**(quotes or {}), **fetched}
        fired, changed = alerts_mod.evaluate(active, quotes)
        for a in changed:
            self.store.update_alert(a)
        if notify:
            for a in fired:
                q = quotes[a.symbol]
                alerts_mod.notify(
                    "MarketPulse alert",
                    f"{q.symbol} {fmt.price(q.price)} {q.currency}  {fmt.arrow(q.change)} {fmt.pct(q.change_pct)}",
                    subtitle=a.note or a.describe(),
                )
        return fired

    # ── history backfill ──────────────────────────────────────────────────────

    def backfill(self, progress: Callable[[str], None] | None = None) -> int:
        """Rebuild daily net-worth snapshots from the ledger and historical closes."""
        txns = self.store.transactions()
        if not txns:
            return 0
        say = progress or (lambda _msg: None)
        accounts = self.store.account_map()
        assets = self.store.assets()
        base = self.base
        start = min(t.date for t in txns)

        market_syms = market_symbols((t.symbol for t in txns), assets)
        closes: dict[str, dict[str, float]] = {}
        listing_ccy: dict[str, str] = {}
        for i, sym in enumerate(market_syms, 1):
            say(f"prices {i}/{len(market_syms)}  {sym}")
            try:
                closes[sym], listing_ccy[sym] = self.market.daily_closes(sym, start)
            except MarketError:
                closes[sym] = {}

        full = replay(txns, accounts)
        ccys = {h.currency for h in full.holdings.values()} | set(listing_ccy.values())
        ccys |= {ccy for (_, ccy) in full.cash} | {c for _, _, c in external_flows(txns, accounts)}
        fx_hist: dict[str, dict[str, float]] = {}
        for ccy in sorted(c for c in ccys if c and c != base):
            say(f"fx {ccy}/{base}")
            try:
                fx_hist[ccy], _ = self.market.daily_closes(f"{ccy}{base}=X", start)
            except MarketError:
                fx_hist[ccy] = {}

        flows = external_flows(txns, accounts)  # sorted by date
        last_px: dict[str, float] = {}
        last_fx: dict[str, float] = {base: 1.0}
        snaps: list[Snapshot] = []
        contributions = 0.0
        pending = 0  # index of the first flow not yet converted
        say("replaying ledger")
        for iso, state in replay_by_day(txns, accounts, start, date.today().isoformat()):
            for sym, series in closes.items():
                if iso in series:
                    last_px[sym] = series[iso]
            for ccy, series in fx_hist.items():
                if iso in series:
                    last_fx[ccy] = series[iso]
            value = book = 0.0
            complete = True
            # Each flow converts at the rate in force on its own day; if that rate isn't
            # known yet the day is incomplete and the flow waits for the next rate.
            while pending < len(flows) and flows[pending][0] <= iso:
                _, amount, ccy = flows[pending]
                rate = last_fx.get(ccy)
                if rate is None:
                    complete = False
                    break
                contributions += amount * rate
                pending += 1
            for h in state.open_holdings():
                rate = last_fx.get(h.currency)
                asset = assets.get(h.symbol)
                kind = asset.kind if asset else AssetKind.MARKET
                if kind is AssetKind.MARKET:
                    px = last_px.get(h.symbol)
                    lc = listing_ccy.get(h.symbol, h.currency)
                    if px is not None and lc != h.currency:
                        lr = last_fx.get(lc)
                        px = px * lr / rate if lr is not None and rate else None
                elif kind is AssetKind.FIXED_INCOME:
                    purchase = asset.accrual_factor(h.first_date) if h.first_date else 1.0
                    px = h.avg_cost / purchase * asset.accrual_factor(iso) if purchase else h.avg_cost
                elif kind is AssetKind.MANUAL:
                    marked = state.valuations.get(h.symbol)
                    px = marked[1] if marked else h.avg_cost
                else:
                    px = 1.0
                if px is None or rate is None:
                    complete = False
                    continue
                value += h.quantity * px * rate
                book += h.book * rate
            for (acct_id, ccy), amount in state.cash_balances().items():
                acct = accounts.get(acct_id)
                rate = last_fx.get(ccy)
                if acct and acct.track_cash and rate is not None:
                    value += amount * rate
                    book += amount * rate
            if complete and (value > 0 or snaps):
                snaps.append(Snapshot(iso, value, book, contributions, base, {"backfilled": True}))
        self.store.upsert_snapshots(snaps)
        return len(snaps)

    # ── income, tax, room ─────────────────────────────────────────────────────

    def trailing_dividends(self, symbols: list[str]) -> dict[str, float]:
        out = {}
        for sym in symbols:
            try:
                out[sym] = sum(a for _, a in self.market.dividends(sym, "1y"))
            except MarketError:
                continue
        return out

    def income_forecast(self, view: PortfolioView):
        syms = sorted(
            {
                p.symbol
                for p in view.positions
                if p.kind is AssetKind.MARKET and p.asset_class in (AssetClass.EQUITY, AssetClass.ETF, AssetClass.FUND)
            }
        )
        return income_forecast(view, self.trailing_dividends(syms))

    def tax_years(self) -> tuple[list[TaxYear], list]:
        state = self.store.ledger()
        accounts = self.store.account_map()
        txns = self.store.transactions()
        warnings = superficial_losses(txns, state)
        flagged = {w.sale.txn_id for w in warnings if w.sale.txn_id is not None}
        base = self.base
        hist: dict[str, dict[str, float]] = {}
        taxable = [r for r in state.realized if (a := accounts.get(r.account_id)) and not a.type.registered]
        for ccy in sorted({r.currency for r in taxable if r.currency != base}):
            start = min(r.date for r in taxable if r.currency == ccy)
            start = (date.fromisoformat(start) - timedelta(days=7)).isoformat()
            try:
                hist[ccy], _ = self.market.daily_closes(f"{ccy}{base}=X", start)
            except MarketError:
                hist[ccy] = {}

        def fx_on(day: str, ccy: str) -> float | None:
            if not ccy or ccy == base:
                return 1.0
            series = hist.get(ccy) or {}
            prior = [d for d in series if d <= day]
            return series[max(prior)] if prior else None

        years = capital_gains(
            state, accounts, fx_on, inclusion_rate=self.config.capital_gains_inclusion, superficial_txn_ids=flagged
        )
        return years, warnings

    def room(self) -> list[tuple[RoomStatus, list[Account]]]:
        accounts = self.store.accounts()
        flows = self.store.ledger().flows
        out = []
        for acct_type, (year, amount) in sorted(self.store.rooms().items()):
            members = [a for a in accounts if a.type.value == acct_type]
            status = contribution_room(acct_type, year, amount, flows, {a.id for a in members})
            out.append((status, members))
        return out

    # ── menu bar / scripting payload ──────────────────────────────────────────

    def status_payload(self, view: PortfolioView | None = None, *, history_days: int = 30) -> dict:
        view = view or self.valuation()
        privacy = self.config.privacy
        watch_syms, wq, _ = self.watchlist_quotes()
        active_alerts = self.store.alerts()
        fired = self.check_alerts({**view.quotes, **wq}, notify=True)
        palette = resolve_palette(self.config.theme)

        display = self.config.menubar_display
        if display == "symbol" and self.config.menubar_symbol:
            sym = self.config.menubar_symbol.upper()
            q = wq.get(sym) or view.quotes.get(sym)
            if q is None:
                try:
                    q = self.market.quote(sym)
                except MarketError:
                    q = None
            title = f"{sym} {fmt.price(q.price)} {fmt.arrow(q.change)}{abs(q.change_pct):.2f}%" if q else sym
        elif display == "net_worth":
            title = fmt.compact(view.net_worth, view.base, privacy=privacy)
        elif display == "day_change":
            amount = fmt.money(view.day_change, view.base, privacy=privacy, sign=True, decimals=0)
            title = f"{fmt.arrow(view.day_change)} {amount}"
        else:
            title = f"{fmt.arrow(view.day_change)} {fmt.pct(view.day_change_pct)}"

        since = (date.today() - timedelta(days=history_days)).isoformat()
        history = [
            {"date": s.date, "value": round(s.net_worth, 2)}
            for s in self.store.snapshots(since)
            if s.currency == view.base
        ]

        def money(v: float | None) -> float | None:
            return None if v is None else round(v, 2)

        amap = self.store.account_map()
        return {
            "version": 1,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "title": title,
            "base": view.base,
            "privacy": privacy,
            "stale": view.stale,
            "market_state": view.market_state,
            "net_worth": money(view.net_worth),
            "day_change": money(view.day_change),
            "day_change_pct": round(view.day_change_pct, 4),
            "unrealized": money(view.unrealized),
            "unrealized_pct": round(view.unrealized_pct, 4),
            "income_ytd": money(view.income_ytd),
            "accounts": [
                {
                    "name": b.label,
                    "type": (a.type.value if (a := amap.get(int(b.key))) else AccountType.OTHER.value),
                    "value": money(b.value),
                    "day_change": money(b.day_change),
                    "day_change_pct": round(b.day_change_pct, 4),
                    "weight": round(b.weight, 2),
                }
                for b in view.by_account
            ],
            "movers": [
                {
                    "symbol": p.symbol,
                    "name": p.name,
                    "price": p.price,
                    "change_pct": round(p.day_change_pct or 0.0, 4),
                    "currency": p.currency,
                }
                for p in view.movers(5)
            ],
            "watchlist": [
                {
                    "symbol": s,
                    "name": wq[s].name,
                    "price": wq[s].price,
                    "change_pct": round(wq[s].change_pct, 4),
                    "currency": wq[s].currency,
                    "spark": [round(v, 4) for v in wq[s].intraday[-48:]],
                }
                for s in watch_syms
                if s in wq
            ],
            "history": history,
            "alerts": [
                {"symbol": a.symbol, "description": a.describe(), "triggered": bool(a.triggered_at)}
                for a in active_alerts
                if a.active
            ],
            "fired": [a.describe() for a in fired],
            "theme": {
                "name": palette.name,
                "dark": palette.dark,
                "accent": palette.accent,
                "up": palette.up,
                "down": palette.down,
                "background": palette.background,
                "foreground": palette.foreground,
                "muted": palette.muted,
            },
            "errors": sorted(set(view.errors.values()))[:5],
        }
