"""Canadian capital gains engine: pooled ACB in your base currency.

Why this is separate from ledger.py
-----------------------------------
ledger.replay() tracks cost *per account*, which is what you want on screen
("what did I pay for the VFV in my Questrade margin account?"). The CRA
computes adjusted cost base differently, and the two only agree in simple
cases:

1. **ACB is pooled across all your taxable accounts.** Identical property is
   one pool no matter how many brokers hold it. If you own XEQT in two
   non-registered accounts, every sale uses the *combined* average cost.
   Registered accounts (TFSA, RRSP, FHSA, RESP, LIRA, RRIF) are outside the
   pool entirely: nothing inside them is ever reported.

2. **Each leg is converted at its own date's exchange rate.** For a US stock,
   each purchase's cost (price x quantity + commission) is converted to CAD
   at *that purchase's* FX rate, and the sale proceeds at the *sale date's*
   rate. The CAD gain therefore includes currency movement. Converting the
   USD gain at the sale-date rate (what MarketPulse 2.0 did) leaves that
   movement out.

This module replays the whole ledger once, keeping one `AcbPool` per symbol,
and produces a `Disposition` for every taxable event. It is pure: FX comes in
through the `fx_on` callback, so tests can hand it fixed rates and the
Tracker can hand it historical Yahoo rates.

Scope and known simplifications (tax figures are estimates; the README says
so and `marketpulse tax` prints it):
- One pool per Yahoo symbol. The same share listed under two symbols (a
  .TO and a .NE line, say) is treated as two properties.
- Phantom/reinvested distributions that raise ACB (box 42 / T3 adjustments)
  are not modelled unless you record them yourself.
- Superficial losses are computed with CRA's proportional formula; see
  `_superficial_denial` for the exact rule and its approximations.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from .ledger import LedgerIssue, replay, sort_key, transaction_currency
from .models import EPSILON, Account, Transaction, TxnType

# (ISO date, currency) -> units of the base currency per 1 unit of `currency`
# on that date, or None if unknown. Must return 1.0 for the base currency.
FxLookup = Callable[[str, str], float | None]

# CRA's superficial-loss window: 30 calendar days either side of the sale.
SUPERFICIAL_WINDOW_DAYS = 30

# Why part of a loss was denied (Disposition.denied_reason).
DENIED_SUPERFICIAL = "superficial"  # repurchased within 30 days and still held (s.54 "superficial loss")
DENIED_REGISTERED = "registered"  # moved in kind into a registered plan (s.40(2)(g)(iv)): loss is never allowed


@dataclass
class Disposition:
    """One taxable event, with every amount already in the base currency."""

    date: str
    account_id: int
    symbol: str
    quantity: float
    proceeds: float  # sale proceeds net of commission, base currency
    acb: float  # adjusted cost base of the units disposed of, base currency
    currency: str  # the security's trading currency (for reference)
    fx: float | None  # base per unit of `currency` on the disposition date
    txn_id: int | None = None
    # "sale"    an ordinary sell
    # "roc"     return of capital beyond ACB: the excess is a deemed gain
    # "deemed"  in-kind transfer to a registered plan: disposed of at market value
    kind: str = "sale"
    # False when an FX rate this figure depends on (the sale's, or any purchase
    # still in the pool) was unavailable. Incomplete rows are shown but left
    # out of yearly totals, so a missing rate never silently changes a number.
    complete: bool = True
    denied: float = 0.0  # part of a loss that is disallowed (>= 0), base currency
    denied_reason: str = ""  # DENIED_SUPERFICIAL | DENIED_REGISTERED | ""
    # Superficial-loss working, kept for display (see _superficial_denial):
    acquired_in_window: float = 0.0  # units bought 30 days either side, any account
    held_after_window: float = 0.0  # units held (all accounts) at the end of day +30
    window_open: bool = False  # day +30 is still in the future: the figure can still change

    @property
    def gain(self) -> float:
        """Economic gain (negative for a loss), before any denial."""
        return self.proceeds - self.acb

    @property
    def allowed_gain(self) -> float:
        """Gain as reported: a denied loss is added back, so it can't reduce tax."""
        return self.gain + self.denied

    @property
    def superficial(self) -> bool:
        return self.denied_reason == DENIED_SUPERFICIAL and self.denied > EPSILON


@dataclass
class AcbPool:
    """The pooled cost base of one security across every taxable account."""

    symbol: str
    # Units held per account. The pool is shared, but quantities stay per
    # account so a per-account SPLIT or TRANSFER touches the right shares.
    quantity_by_account: dict[int, float] = field(default_factory=lambda: defaultdict(float))
    acb: float = 0.0  # total ACB of the pool, base currency
    # Set when some purchase in the pool had no FX rate; cleared when the pool
    # is fully sold (a fresh pool starts clean).
    incomplete: bool = False
    # A superficial loss whose replacement shares haven't been bought yet in
    # a taxable account: added to the ACB of the next taxable purchase.
    pending_denied: float = 0.0

    @property
    def quantity(self) -> float:
        return sum(q for q in self.quantity_by_account.values() if q > EPSILON)

    @property
    def acb_per_unit(self) -> float:
        q = self.quantity
        return self.acb / q if q > EPSILON else 0.0

    def remove(self, account_id: int, quantity: float) -> float:
        """Take `quantity` units out of `account_id` at the pooled average
        cost and return the ACB that leaves with them."""
        total = self.quantity
        share = self.acb * (quantity / total) if total > EPSILON else 0.0
        self.quantity_by_account[account_id] -= quantity
        self.acb -= share
        if self.quantity <= EPSILON:
            # Fully sold: drop float dust and start the next pool fresh.
            self.quantity_by_account.clear()
            self.acb = 0.0
            self.incomplete = False
        return share


@dataclass
class TaxReport:
    dispositions: list[Disposition] = field(default_factory=list)
    pools: dict[str, AcbPool] = field(default_factory=dict)  # open pools after the replay, by symbol
    issues: list[LedgerIssue] = field(default_factory=list)


def is_taxable(account: Account | None) -> bool:
    """Gains in this account are reported. Unknown accounts are skipped, not guessed."""
    return account is not None and not account.type.registered


def compute(
    transactions: Sequence[Transaction],
    accounts: dict[int, Account],
    fx_on: FxLookup,
    *,
    today: str | None = None,
) -> TaxReport:
    """Replay the ledger through pooled ACB and return every taxable event.

    `today` (ISO date) only decides whether a superficial-loss window is still
    open; it defaults to the real date and is a parameter so tests are stable.
    """
    today = today or date.today().isoformat()
    report = TaxReport()
    pools = report.pools
    ordered = sorted(transactions, key=sort_key)

    def pool(symbol: str) -> AcbPool:
        if symbol not in pools:
            pools[symbol] = AcbPool(symbol)
        return pools[symbol]

    def rate(txn: Transaction, ccy: str) -> float | None:
        return fx_on(txn.date, ccy)

    def acquire(p: AcbPool, account_id: int, quantity: float, cost: float, known: bool) -> None:
        """Add units to the pool at `cost` (base currency)."""
        p.quantity_by_account[account_id] += quantity
        p.acb += cost
        p.incomplete |= not known
        if p.pending_denied > EPSILON:
            # These are the replacement shares for an earlier superficial loss:
            # the denied loss becomes part of their cost.
            p.acb += p.pending_denied
            p.pending_denied = 0.0

    for txn in ordered:
        acct = accounts.get(txn.account_id)
        taxable = is_taxable(acct)
        t = txn.type
        ccy = transaction_currency(txn, accounts)

        if t in (TxnType.BUY, TxnType.DRIP) and taxable:
            fx = rate(txn, ccy)
            # Commission is part of the cost of acquiring the shares. A DRIP
            # has no commission, and its value was taxed as a dividend, so it
            # enters the pool at quantity x price like any purchase.
            cost_native = txn.quantity * txn.price + txn.fees
            acquire(pool(txn.symbol), txn.account_id, txn.quantity, cost_native * (fx or 0.0), fx is not None)

        elif t is TxnType.SELL and taxable:
            p = pool(txn.symbol)
            held = p.quantity_by_account.get(txn.account_id, 0.0)
            qty = min(txn.quantity, held)
            if qty <= EPSILON:
                # Selling what isn't held is already reported by ledger.replay().
                continue
            fx = rate(txn, ccy)
            complete = fx is not None and not p.incomplete
            acb = p.remove(txn.account_id, qty)
            proceeds = (qty * txn.price - txn.fees) * (fx or 0.0)
            d = Disposition(txn.date, txn.account_id, txn.symbol, qty, proceeds, acb, ccy, fx, txn.id, "sale", complete)
            report.dispositions.append(d)
            if d.gain < -EPSILON:
                _superficial_denial(d, ordered, accounts, today)
                if d.denied > EPSILON:
                    _attach_denied_loss(d, p, ordered, accounts)

        elif t is TxnType.SPLIT and taxable:
            # A split changes the unit count, never the cost: ACB per unit falls.
            p = pools.get(txn.symbol)
            if p and txn.account_id in p.quantity_by_account:
                p.quantity_by_account[txn.account_id] *= txn.ratio

        elif t is TxnType.ROC and taxable:
            # Return of capital reduces ACB. If it would push ACB below zero,
            # ACB is set to zero and the excess is a capital gain that year.
            p = pools.get(txn.symbol)
            if p is None or p.quantity <= EPSILON:
                continue
            fx = rate(txn, ccy)
            # Without a rate the reduction is unknown, so everything this pool
            # reports from here on is too: flag it rather than guess.
            p.incomplete |= fx is None
            reduction = txn.amount * (fx or 0.0)
            excess = reduction - p.acb
            p.acb = max(p.acb - reduction, 0.0)
            if excess > EPSILON:
                report.dispositions.append(
                    Disposition(
                        txn.date,
                        txn.account_id,
                        txn.symbol,
                        0.0,
                        excess,
                        0.0,
                        ccy,
                        fx,
                        txn.id,
                        "roc",
                        fx is not None and not p.incomplete,
                    )
                )

        elif t is TxnType.TRANSFER and txn.target_account_id is not None:
            _transfer(txn, ccy, taxable, accounts, pools, pool, acquire, fx_on, report)

    report.pools = {s: p for s, p in pools.items() if p.quantity > EPSILON}
    return report


# ── In-kind transfers ─────────────────────────────────────────────────────────


def _transfer(
    txn: Transaction,
    ccy: str,
    src_taxable: bool,
    accounts: dict[int, Account],
    pools: dict[str, AcbPool],
    pool: Callable[[str], AcbPool],
    acquire: Callable[[AcbPool, int, float, float, bool], None],
    fx_on: FxLookup,
    report: TaxReport,
) -> None:
    """Move shares between accounts. What that means for tax depends on which
    side of the registered/taxable line each account is on:

    taxable -> taxable        Same owner, same pool: nothing happens.
    taxable -> registered     A *deemed disposition* at fair market value (a
                              "contribution in kind"). A gain is taxable; a
                              loss is denied outright and lost forever.
    registered -> taxable     The shares enter the pool at fair market value.
    registered -> registered  Outside the pool: nothing happens.

    Fair market value comes from the transfer's `price` (per unit, in the
    security's currency). Without it the tax effect can't be computed, so an
    issue is raised asking for it rather than guessing.
    """
    target = txn.target_account_id
    assert target is not None  # guaranteed by the caller
    dst_taxable = is_taxable(accounts.get(target))
    if src_taxable and dst_taxable:
        p = pools.get(txn.symbol)
        if p is None:
            return
        qty = min(txn.quantity, p.quantity_by_account.get(txn.account_id, 0.0))
        p.quantity_by_account[txn.account_id] -= qty
        p.quantity_by_account[target] += qty
        return

    fx = fx_on(txn.date, ccy)
    priced = txn.price > 0
    if src_taxable and not dst_taxable:
        p = pools.get(txn.symbol)
        qty = min(txn.quantity, p.quantity_by_account.get(txn.account_id, 0.0)) if p else 0.0
        if p is None or qty <= EPSILON:
            return
        complete = fx is not None and not p.incomplete
        acb = p.remove(txn.account_id, qty)
        if not priced:
            report.issues.append(
                LedgerIssue(
                    txn.id,
                    txn.date,
                    f"Transfer of {txn.symbol} into a registered account is a deemed sale at market value — "
                    "add the price per unit to the transfer to include it in the tax report",
                )
            )
            return
        d = Disposition(
            txn.date,
            txn.account_id,
            txn.symbol,
            qty,
            qty * txn.price * (fx or 0.0),
            acb,
            ccy,
            fx,
            txn.id,
            "deemed",
            complete,
        )
        if d.gain < -EPSILON:
            d.denied, d.denied_reason = -d.gain, DENIED_REGISTERED
        report.dispositions.append(d)

    elif dst_taxable and not src_taxable:
        if not priced:
            report.issues.append(
                LedgerIssue(
                    txn.id,
                    txn.date,
                    f"Transfer of {txn.symbol} out of a registered account enters your cost base at market value — "
                    "add the price per unit to the transfer",
                )
            )
        # Unpriced: still add the units (so later sales aren't flagged as
        # oversells) but mark the pool incomplete, which keeps its sales out
        # of the yearly totals until the price is filled in.
        acquire(
            pool(txn.symbol),
            target,
            txn.quantity,
            txn.quantity * txn.price * (fx or 0.0),
            priced and fx is not None,
        )


# ── Superficial losses ────────────────────────────────────────────────────────


def _superficial_denial(
    d: Disposition, ordered: Sequence[Transaction], accounts: dict[int, Account], today: str
) -> None:
    """Work out how much of a capital loss is a superficial loss.

    CRA's rule (Income Tax Act s.54, as applied in Folio S3-F4-C1 and the
    usual worked examples): a loss is superficial if you, or someone
    affiliated with you, acquire the same property in the 61-day window from
    30 days before to 30 days after the sale, *and* still hold it at the end
    of that window. When only some shares qualify, the denied part is

        loss x min(S, P, B) / S

    where S = units sold, P = units acquired in the window, and B = units
    held at the end of the window. Purchases count in *any* of your accounts,
    registered ones included. That's the classic trap: selling at a loss in
    a non-registered account and rebuying in your TFSA.

    Affiliated persons (a spouse, a corporation you control) are outside
    MarketPulse's view, so a clean result here isn't proof: the report says so.
    """
    sale_day = date.fromisoformat(d.date)
    lo = (sale_day - timedelta(days=SUPERFICIAL_WINDOW_DAYS)).isoformat()
    hi = (sale_day + timedelta(days=SUPERFICIAL_WINDOW_DAYS)).isoformat()
    same = [t for t in ordered if t.symbol == d.symbol]

    # P: acquisitions in the window. Only BUY and DRIP are acquisitions;
    # a transfer between your own accounts isn't.
    acquired = sum(t.quantity for t in same if t.type in (TxnType.BUY, TxnType.DRIP) and lo <= t.date <= hi)

    # B: units held across every account at the end of day +30. The window
    # may still be open (sale less than 30 days ago), in which case today's
    # holdings are the best estimate and the row is marked provisional.
    held = sum(h.quantity for h in replay(list(same), accounts, until=min(hi, today)).open_holdings())

    d.acquired_in_window = acquired
    d.held_after_window = held
    d.window_open = hi > today
    fraction = min(d.quantity, acquired, held) / d.quantity if d.quantity > EPSILON else 0.0
    if fraction > EPSILON:
        d.denied = -d.gain * fraction
        d.denied_reason = DENIED_SUPERFICIAL


def _attach_denied_loss(
    d: Disposition, p: AcbPool, ordered: Sequence[Transaction], accounts: dict[int, Account]
) -> None:
    """Add a denied superficial loss to the cost of the replacement shares.

    The denied loss isn't gone: it goes into the ACB of the substituted
    property, so you get it back when those shares are sold. Two refinements:

    - If some of the replacement shares were bought in a registered account,
      that share of the denied loss is lost for good (a registered plan has no
      ACB to add it to). Taxable and registered purchases in the window are
      pro-rated by quantity. That's an approximation: CRA ties the denial to
      specific substituted shares, which a pooled model can't identify.
    - If the pool still holds shares after the sale (the replacement was
      bought *before* it), the amount is added now. Otherwise it waits in
      `pending_denied` and is added to the next taxable purchase.
    """
    sale_day = date.fromisoformat(d.date)
    lo = (sale_day - timedelta(days=SUPERFICIAL_WINDOW_DAYS)).isoformat()
    hi = (sale_day + timedelta(days=SUPERFICIAL_WINDOW_DAYS)).isoformat()
    buys = [t for t in ordered if t.symbol == d.symbol and t.type in (TxnType.BUY, TxnType.DRIP) and lo <= t.date <= hi]
    total = sum(t.quantity for t in buys)
    in_taxable = sum(t.quantity for t in buys if is_taxable(accounts.get(t.account_id)))
    carried = d.denied * (in_taxable / total) if total > EPSILON else 0.0
    if carried <= EPSILON:
        return
    if p.quantity > EPSILON:
        p.acb += carried
    else:
        p.pending_denied += carried


# ── FX lookup from a daily series ─────────────────────────────────────────────


def fx_lookup(series: dict[str, dict[str, float]], base: str) -> FxLookup:
    """Build an FxLookup from daily closes: {currency: {iso_date: rate}}.

    Uses the most recent close on or before the requested day, so weekends
    and holidays take Friday's rate, the usual practice when no rate was
    published that day. (CRA prefers the Bank of Canada daily rate; Yahoo's
    close is typically within a few hundredths of a percent of it.)
    """
    base = base.upper()
    # Pre-sort each series once so every lookup is a binary search, not a scan.
    sorted_days = {ccy: sorted(closes) for ccy, closes in series.items()}

    def lookup(day: str, currency: str) -> float | None:
        if not currency or currency.upper() == base:
            return 1.0
        days = sorted_days.get(currency.upper())
        if not days:
            return None
        i = bisect_right(days, day)
        return series[currency.upper()][days[i - 1]] if i else None

    return lookup
