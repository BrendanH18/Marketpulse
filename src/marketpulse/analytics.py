"""Performance, allocation, income and tax analytics. Pure functions."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise

from .ledger import LedgerState
from .models import EPSILON, Account, Transaction, TxnType, guess_currency
from .valuation import Breakdown, PortfolioView

# ── Money in / money out ──────────────────────────────────────────────────────


def external_flows(transactions: Sequence[Transaction], accounts: dict[int, Account]) -> list[tuple[str, float, str]]:
    """Money you put into (+) or took out of (-) your investments: (date, amount, currency).

    Accounts with recorded deposits/withdrawals (or cash tracking) use those.
    Otherwise the account is treated as fully invested: buys are money in,
    sell proceeds and cash distributions are money out.
    """
    cash_based = {t.account_id for t in transactions if t.type in (TxnType.DEPOSIT, TxnType.WITHDRAWAL)}
    cash_based |= {a.id for a in accounts.values() if a.track_cash}
    flows = []
    for t in sorted(transactions, key=lambda t: (t.date, t.id or 0)):
        acct = accounts.get(t.account_id)
        ccy = t.currency or (
            guess_currency(t.symbol, acct.currency if acct else "CAD")
            if t.symbol
            else (acct.currency if acct else "CAD")
        )
        if t.account_id in cash_based:
            if t.type is TxnType.DEPOSIT:
                flows.append((t.date, t.amount, ccy))
            elif t.type is TxnType.WITHDRAWAL:
                flows.append((t.date, -t.amount, ccy))
        elif t.type is TxnType.BUY:
            flows.append((t.date, t.quantity * t.price + t.fees, ccy))
        elif t.type is TxnType.SELL:
            flows.append((t.date, -(t.quantity * t.price - t.fees), ccy))
        elif t.type in (TxnType.DIVIDEND, TxnType.INTEREST, TxnType.ROC):
            flows.append((t.date, -t.amount, ccy))
    return flows


# ── Returns ───────────────────────────────────────────────────────────────────


def xirr(cashflows: Sequence[tuple[str, float]]) -> float | None:
    """Annualized money-weighted return (%). Investor convention: money you
    put in is negative, money you get back (incl. terminal value) positive."""
    flows = sorted((d, a) for d, a in cashflows if abs(a) > EPSILON)
    if not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return None
    d0 = date.fromisoformat(flows[0][0])
    times = [(date.fromisoformat(d) - d0).days / 365.0 for d, _ in flows]
    if times[-1] <= 0:
        return None

    def npv(rate: float) -> float:
        return sum(a / (1.0 + rate) ** t for (_, a), t in zip(flows, times, strict=True))

    lo, hi = -0.9999, 100.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    mid = 0.0
    for _ in range(300):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9 or hi - lo < 1e-12:
            break
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return mid * 100


def twr_index(points: Sequence[tuple[str, float, float]]) -> list[tuple[str, float]]:
    """Growth-of-1 index from (date, value, cumulative_contributions) points.

    Each period's return strips out that period's net contribution, assumed
    to arrive at the end of the period (daily snapshots make this precise).
    """
    if not points:
        return []
    index = [(points[0][0], 1.0)]
    level = 1.0
    for (_, v0, c0), (d1, v1, c1) in pairwise(points):
        if v0 > EPSILON:
            r = (v1 - (c1 - c0)) / v0 - 1.0
            if math.isfinite(r) and r > -1.0:
                level *= 1.0 + r
        index.append((d1, level))
    return index


def annualize(total_pct: float, days: int) -> float | None:
    if days < 365:
        return None
    return ((1 + total_pct / 100) ** (365.0 / days) - 1) * 100


def max_drawdown(values: Sequence[float]) -> float:
    """Worst peak-to-trough decline, as a negative percent."""
    peak = -math.inf
    worst = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, (v - peak) / peak * 100)
    return worst


def volatility(values: Sequence[float], periods_per_year: float = 365.0) -> float | None:
    rets = [b / a - 1 for a, b in pairwise(values) if a > 0]
    if len(rets) < 10:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(periods_per_year) * 100


def period_return(values: Sequence[float]) -> float | None:
    vals = [v for v in values if v is not None]
    if len(vals) < 2 or not vals[0]:
        return None
    return (vals[-1] / vals[0] - 1) * 100


@dataclass
class Performance:
    since: str = ""
    days: int = 0
    net_contributions: float = 0.0
    total_gain: float = 0.0  # net worth - net contributions
    xirr_pct: float | None = None
    twr_pct: float | None = None
    twr_annual_pct: float | None = None
    max_drawdown_pct: float | None = None
    volatility_pct: float | None = None
    index: list[tuple[str, float]] = field(default_factory=list)


def performance(
    view: PortfolioView,
    flows_base: Sequence[tuple[str, float]],
    snapshots: Sequence[tuple[str, float, float]],
    today: date | None = None,
) -> Performance:
    today = today or date.today()
    perf = Performance()
    if flows_base:
        perf.since = min(d for d, _ in flows_base)
        perf.days = (today - date.fromisoformat(perf.since)).days
    perf.net_contributions = sum(a for _, a in flows_base)
    perf.total_gain = view.net_worth - perf.net_contributions
    investor = [(d, -a) for d, a in flows_base] + [(today.isoformat(), view.net_worth)]
    if perf.days >= 30:
        perf.xirr_pct = xirr(investor)
    idx = twr_index(snapshots)
    if len(idx) >= 2:
        perf.index = idx
        perf.twr_pct = (idx[-1][1] - 1) * 100
        span = (date.fromisoformat(idx[-1][0]) - date.fromisoformat(idx[0][0])).days
        perf.twr_annual_pct = annualize(perf.twr_pct, span)
        levels = [v for _, v in idx]
        perf.max_drawdown_pct = max_drawdown(levels)
        perf.volatility_pct = volatility(levels)
    return perf


# ── Allocation ────────────────────────────────────────────────────────────────


@dataclass
class RebalanceRow:
    bucket: str
    label: str
    value: float
    weight: float
    target: float
    delta: float  # + buy / - sell, base currency

    @property
    def drift(self) -> float:
        return self.weight - self.target


def rebalance(breakdown: Sequence[Breakdown], targets: dict[str, float], total: float) -> list[RebalanceRow]:
    rows = {b.key: b for b in breakdown}
    keys = list(dict.fromkeys([*targets, *rows]))
    out = []
    for key in keys:
        b = rows.get(key)
        value = b.value if b else 0.0
        target = targets.get(key, 0.0)
        out.append(
            RebalanceRow(
                bucket=key,
                label=b.label if b else key.replace("_", " ").title(),
                value=value,
                weight=value / total * 100 if total else 0.0,
                target=target,
                delta=target / 100 * total - value,
            )
        )
    return sorted(out, key=lambda r: abs(r.delta), reverse=True)


# ── Income ────────────────────────────────────────────────────────────────────


def income_by_month(
    state: LedgerState, convert: Callable[[float, str], float | None], months: int = 12, today: date | None = None
) -> list[tuple[str, float]]:
    today = today or date.today()
    labels = []
    y, m = today.year, today.month
    for _ in range(months):
        labels.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    labels.reverse()
    totals: dict[str, float] = defaultdict(float)
    for inc in state.income:
        key = inc.date[:7]
        if key in totals or key in labels:
            totals[key] += convert(inc.amount, inc.currency) or 0.0
    return [(label, totals.get(label, 0.0)) for label in labels]


def income_by_symbol(
    state: LedgerState, convert: Callable[[float, str], float | None], year: int | None = None
) -> list[tuple[str, float]]:
    totals: dict[str, float] = defaultdict(float)
    for inc in state.income:
        if year is None or inc.date.startswith(str(year)):
            totals[inc.symbol or "Interest"] += convert(inc.amount, inc.currency) or 0.0
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)


@dataclass
class IncomeForecast:
    symbol: str
    name: str
    quantity: float
    per_share_ttm: float
    currency: str
    annual: float  # native
    annual_base: float | None
    yield_pct: float | None
    yield_on_cost_pct: float | None


def income_forecast(view: PortfolioView, per_share_ttm: dict[str, float]) -> list[IncomeForecast]:
    """Forward 12-month income assuming trailing distributions repeat."""
    grouped: dict[str, list] = defaultdict(list)
    for p in view.positions:
        if per_share_ttm.get(p.symbol):
            grouped[p.symbol].append(p)
    rows = []
    for sym, positions in grouped.items():
        qty = sum(p.quantity for p in positions)
        book = sum(p.book for p in positions)
        dps = per_share_ttm[sym]
        first = positions[0]
        annual = qty * dps
        rows.append(
            IncomeForecast(
                symbol=sym,
                name=first.name,
                quantity=qty,
                per_share_ttm=dps,
                currency=first.currency,
                annual=annual,
                annual_base=view.fx.convert(annual, first.currency),
                yield_pct=dps / first.price * 100 if first.price else None,
                yield_on_cost_pct=annual / book * 100 if book else None,
            )
        )
    return sorted(rows, key=lambda r: r.annual_base or 0.0, reverse=True)


# ── Canadian capital gains ────────────────────────────────────────────────────


@dataclass
class GainRow:
    date: str
    account: str
    symbol: str
    quantity: float
    proceeds: float
    cost: float
    currency: str
    fx: float | None
    superficial: bool = False

    @property
    def gain(self) -> float:
        return self.proceeds - self.cost

    @property
    def gain_base(self) -> float | None:
        return None if self.fx is None else self.gain * self.fx


@dataclass
class TaxYear:
    year: int
    rows: list[GainRow] = field(default_factory=list)
    inclusion_rate: float = 0.5

    @property
    def proceeds(self) -> float:
        return sum(r.proceeds * r.fx for r in self.rows if r.fx is not None)

    @property
    def cost(self) -> float:
        return sum(r.cost * r.fx for r in self.rows if r.fx is not None)

    @property
    def net_gain(self) -> float:
        return sum(r.gain_base for r in self.rows if r.gain_base is not None and not (r.superficial and r.gain < 0))

    @property
    def taxable(self) -> float:
        return max(self.net_gain, 0.0) * self.inclusion_rate

    @property
    def missing_fx(self) -> list[GainRow]:
        return [r for r in self.rows if r.fx is None]


def capital_gains(
    state: LedgerState,
    accounts: dict[int, Account],
    fx_on: Callable[[str, str], float | None],
    *,
    inclusion_rate: float = 0.5,
    superficial_txn_ids: set[int] | None = None,
) -> list[TaxYear]:
    """Realized gains in taxable accounts grouped by year, converted at each
    trade date's FX rate (as CRA requires). Superficial losses are listed but
    denied in the net figure."""
    superficial_txn_ids = superficial_txn_ids or set()
    years: dict[int, TaxYear] = {}
    for r in state.realized:
        acct = accounts.get(r.account_id)
        if acct is None or acct.type.registered:
            continue
        y = int(r.date[:4])
        ty = years.setdefault(y, TaxYear(year=y, inclusion_rate=inclusion_rate))
        ty.rows.append(
            GainRow(
                date=r.date,
                account=acct.name,
                symbol=r.symbol,
                quantity=r.quantity,
                proceeds=r.proceeds,
                cost=r.cost,
                currency=r.currency,
                fx=fx_on(r.date, r.currency),
                superficial=r.txn_id in superficial_txn_ids,
            )
        )
    return [years[y] for y in sorted(years, reverse=True)]
