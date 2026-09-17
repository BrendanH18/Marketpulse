"""Turn ledger state + quotes + FX into a priced portfolio view."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .ledger import Holding, LedgerState
from .models import Account, Asset, AssetClass, AssetKind, FxRates, Quote


@dataclass
class PositionView:
    account: Account
    symbol: str
    name: str
    kind: AssetKind
    asset_class: AssetClass
    quantity: float
    avg_cost: float
    book: float  # native currency
    currency: str
    first_date: str
    price: float | None = None  # native currency
    prev_close: float | None = None
    quote: Quote | None = None
    fx_rate: float | None = None  # base per native
    weight: float = 0.0  # % of net worth

    @property
    def priced(self) -> bool:
        return self.price is not None and self.fx_rate is not None

    @property
    def stale(self) -> bool:
        return bool(self.quote and self.quote.stale)

    @property
    def market_value(self) -> float | None:
        return None if self.price is None else self.quantity * self.price

    @property
    def day_change(self) -> float | None:
        if self.price is None or self.prev_close is None:
            return None
        return self.quantity * (self.price - self.prev_close)

    @property
    def day_change_pct(self) -> float | None:
        if self.price is None or not self.prev_close:
            return None
        return (self.price - self.prev_close) / self.prev_close * 100

    @property
    def gain(self) -> float | None:
        mv = self.market_value
        return None if mv is None else mv - self.book

    @property
    def gain_pct(self) -> float | None:
        g = self.gain
        return None if g is None or not self.book else g / self.book * 100

    def _base(self, v: float | None) -> float | None:
        return None if v is None or self.fx_rate is None else v * self.fx_rate

    @property
    def value_base(self) -> float | None:
        return self._base(self.market_value)

    @property
    def book_base(self) -> float | None:
        return self._base(self.book)

    @property
    def day_change_base(self) -> float | None:
        return self._base(self.day_change)

    @property
    def gain_base(self) -> float | None:
        return self._base(self.gain)


@dataclass
class CashView:
    account: Account
    currency: str
    amount: float
    amount_base: float | None


@dataclass
class Breakdown:
    key: str
    label: str
    value: float
    weight: float = 0.0
    day_change: float = 0.0
    book: float = 0.0

    @property
    def day_change_pct(self) -> float:
        prev = self.value - self.day_change
        return self.day_change / prev * 100 if prev else 0.0


@dataclass
class PortfolioView:
    base: str
    fx: FxRates
    positions: list[PositionView] = field(default_factory=list)
    cash: list[CashView] = field(default_factory=list)
    quotes: dict[str, Quote] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    net_worth: float = 0.0
    invested: float = 0.0  # cost base of priced positions
    cash_total: float = 0.0
    day_change: float = 0.0
    realized_total: float = 0.0
    realized_ytd: float = 0.0
    income_total: float = 0.0
    income_ytd: float = 0.0
    fees_total: float = 0.0
    excluded: list[str] = field(default_factory=list)
    by_account: list[Breakdown] = field(default_factory=list)
    by_class: list[Breakdown] = field(default_factory=list)
    by_currency: list[Breakdown] = field(default_factory=list)
    as_of: datetime = field(default_factory=datetime.now)

    @property
    def holdings_value(self) -> float:
        return self.net_worth - self.cash_total

    @property
    def unrealized(self) -> float:
        return self.holdings_value - self.invested

    @property
    def unrealized_pct(self) -> float:
        return self.unrealized / self.invested * 100 if self.invested else 0.0

    @property
    def day_change_pct(self) -> float:
        prev = self.net_worth - self.day_change
        return self.day_change / prev * 100 if prev else 0.0

    @property
    def stale(self) -> bool:
        return any(q.stale for q in self.quotes.values())

    @property
    def market_state(self) -> str:
        """Most 'open' state among exchange-traded (non-crypto) holdings."""
        states = {
            p.quote.market_state
            for p in self.positions
            if p.quote and p.quote.market_state and p.quote.instrument_type != "CRYPTOCURRENCY"
        }
        for s in ("REGULAR", "PRE", "POST", "CLOSED"):
            if s in states:
                return s
        return ""

    def movers(self, n: int = 5) -> list[PositionView]:
        priced = [p for p in self.positions if p.day_change_pct is not None and p.kind is AssetKind.MARKET]
        seen: dict[str, PositionView] = {}
        for p in sorted(priced, key=lambda p: abs(p.day_change_pct or 0), reverse=True):
            seen.setdefault(p.symbol, p)
        return list(seen.values())[:n]


def _price_holding(
    h: Holding, asset: Asset | None, quote: Quote | None, fx: FxRates, state: LedgerState, on: date
) -> tuple[float | None, float | None]:
    kind = asset.kind if asset else AssetKind.MARKET
    if kind is AssetKind.MARKET:
        if quote is None:
            return None, None
        price, prev = quote.price, quote.prev_close
        if quote.currency and h.currency and quote.currency != h.currency:
            # Ledger currency disagrees with the listing (e.g. a legacy guess):
            # express the live price in the ledger's currency.
            q_rate, h_rate = fx.rate(quote.currency), fx.rate(h.currency)
            if q_rate is None or not h_rate:
                return None, None
            factor = q_rate / h_rate
            price, prev = price * factor, prev * factor
        return price, prev
    if kind is AssetKind.FIXED_INCOME:
        today = asset.accrual_factor(on.isoformat())
        yesterday = asset.accrual_factor((on - timedelta(days=1)).isoformat())
        purchase = asset.accrual_factor(h.first_date) if h.first_date else 1.0
        unit = h.avg_cost / purchase if purchase else h.avg_cost
        return unit * today, unit * yesterday
    if kind is AssetKind.MANUAL:
        marked = state.valuations.get(h.symbol)
        price = marked[1] if marked else h.avg_cost
        return price, price
    return 1.0, 1.0  # CASH-like symbol


def build_view(
    state: LedgerState,
    accounts: dict[int, Account],
    assets: dict[str, Asset],
    quotes: dict[str, Quote],
    fx: FxRates,
    *,
    errors: dict[str, str] | None = None,
    on: date | None = None,
    account_id: int | None = None,
) -> PortfolioView:
    on = on or date.today()
    year = str(on.year)
    view = PortfolioView(base=fx.base, fx=fx, quotes=quotes, errors=dict(errors or {}))

    for h in state.open_holdings(account_id):
        acct = accounts.get(h.account_id) or Account(name=f"#{h.account_id}", id=h.account_id)
        asset = assets.get(h.symbol)
        quote = quotes.get(h.symbol)
        kind = asset.kind if asset else AssetKind.MARKET
        price, prev = _price_holding(h, asset, quote, fx, state, on)
        if asset and asset.asset_class:
            klass = asset.asset_class
        elif kind is AssetKind.FIXED_INCOME:
            klass = AssetClass.FIXED_INCOME
        elif kind is AssetKind.MANUAL:
            klass = AssetClass.ALTERNATIVE
        elif kind is AssetKind.CASH:
            klass = AssetClass.CASH
        else:
            klass = quote.asset_class if quote else AssetClass.OTHER
        name = (asset.name if asset and asset.name else "") or (quote.name if quote else "") or h.symbol
        view.positions.append(
            PositionView(
                account=acct,
                symbol=h.symbol,
                name=name,
                kind=kind,
                asset_class=klass,
                quantity=h.quantity,
                avg_cost=h.avg_cost,
                book=h.book,
                currency=h.currency,
                first_date=h.first_date,
                price=price,
                prev_close=prev,
                quote=quote,
                fx_rate=fx.rate(h.currency),
            )
        )

    acct_totals: dict[int, Breakdown] = {}
    class_totals: dict[str, Breakdown] = {}
    ccy_totals: dict[str, Breakdown] = {}

    def add(bucket: dict, key, label: str, value: float, day: float, book: float) -> None:
        b = bucket.get(key)
        if b is None:
            b = bucket[key] = Breakdown(key=str(key), label=label, value=0.0)
        b.value += value
        b.day_change += day
        b.book += book

    for p in view.positions:
        if not p.priced:
            view.excluded.append(p.symbol)
            continue
        value, book, day = p.value_base or 0.0, p.book_base or 0.0, p.day_change_base or 0.0
        view.net_worth += value
        view.invested += book
        view.day_change += day
        add(acct_totals, p.account.id, p.account.name, value, day, book)
        add(class_totals, p.asset_class.value, p.asset_class.label, value, day, book)
        add(ccy_totals, p.currency, p.currency, value, day, book)

    for (acct_id, ccy), amount in state.cash_balances(account_id).items():
        acct = accounts.get(acct_id)
        if acct is None or not acct.track_cash:
            continue
        amount_base = fx.convert(amount, ccy)
        view.cash.append(CashView(acct, ccy, amount, amount_base))
        if amount_base is None:
            view.excluded.append(f"{acct.name} cash ({ccy})")
            continue
        view.net_worth += amount_base
        view.cash_total += amount_base
        add(acct_totals, acct.id, acct.name, amount_base, 0.0, amount_base)
        add(class_totals, AssetClass.CASH.value, AssetClass.CASH.label, amount_base, 0.0, amount_base)
        add(ccy_totals, ccy, ccy, amount_base, 0.0, amount_base)

    def conv(amount: float, ccy: str) -> float:
        v = fx.convert(amount, ccy)
        return v if v is not None else 0.0

    in_scope = (lambda a: True) if account_id is None else (lambda a: a == account_id)
    for r in state.realized:
        if in_scope(r.account_id):
            g = conv(r.gain, r.currency)
            view.realized_total += g
            if r.date.startswith(year):
                view.realized_ytd += g
    for inc in state.income:
        if in_scope(inc.account_id):
            v = conv(inc.amount, inc.currency)
            view.income_total += v
            if inc.date.startswith(year):
                view.income_ytd += v
    view.fees_total = sum(conv(v, ccy) for ccy, v in state.fees.items())

    total = view.net_worth
    for p in view.positions:
        if p.value_base is not None and total:
            p.weight = p.value_base / total * 100
    for bucket, target in ((acct_totals, "by_account"), (class_totals, "by_class"), (ccy_totals, "by_currency")):
        rows = sorted(bucket.values(), key=lambda b: b.value, reverse=True)
        for b in rows:
            b.weight = b.value / total * 100 if total else 0.0
        setattr(view, target, rows)
    return view


def market_symbols(symbols: Iterable[str], assets: dict[str, Asset]) -> list[str]:
    """Symbols priced from the market: no asset row, or an asset of kind MARKET."""
    return sorted({s for s in symbols if s and (s not in assets or assets[s].kind is AssetKind.MARKET)})
