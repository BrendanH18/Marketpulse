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
- One pool per Yahoo symbol, unless you link symbols as identical property
  (`marketpulse tax link`): the same units listed under two symbols (a fund's
  CAD and USD lines, or a share cross-listed in Toronto and New York) then
  share one pool, and a purchase of either line counts for superficial losses.
  Linked units are treated as interchangeable one for one.
- ACB increases from non-cash distributions and T3 adjustments are entered manually.
- Superficial losses are computed with CRA's proportional formula; see
  `_superficial_denial` for the exact rule and its approximations.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import groupby
from math import prod

from .ledger import LedgerIssue, replay, sort_key, transaction_currency
from .models import EPSILON, Account, Asset, AssetClass, AssetKind, Transaction, TxnType

# (ISO date, currency) -> units of the base currency per 1 unit of `currency`
# on that date, or None if unknown. Must return 1.0 for the base currency.
FxLookup = Callable[[str, str], float | None]

# Linked symbols: {symbol: the pool symbol it shares an ACB pool with}. Symbols not in it are
# their own pool. See `pool_symbol`.
IdenticalProperty = Mapping[str, str]

# Called with (ISO date, open pools by pool symbol) once the last transaction of each ledger date
# has been applied. The pools are the engine's own: read them, never change them.
DayObserver = Callable[[str, dict[str, "AcbPool"]], None]

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
    # Superficial-loss working in sale-date units, kept for display (see _superficial_denial):
    acquired_in_window: float = 0.0  # units bought 30 days either side, any account
    held_after_window: float = 0.0  # units held (all accounts) at the end of day +30
    window_open: bool = False  # day +30 is still in the future: the figure can still change
    pool: str = ""  # the ACB pool the units came from: `symbol`, or the symbol it is linked to

    def __post_init__(self) -> None:
        self.pool = self.pool or self.symbol

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

    symbol: str  # the pool symbol: the security's own, or the one its identical lines link to
    # Units held per (account, symbol). The pool is shared, but quantities stay per account
    # and listing so a SPLIT or TRANSFER of one line in one account touches the right shares.
    holdings: dict[tuple[int, str], float] = field(default_factory=lambda: defaultdict(float))
    acb: float = 0.0  # total ACB of the pool, base currency
    # Set when a purchase or adjustment in the pool had no FX rate; cleared when the pool
    # is fully sold (a fresh pool starts clean).
    incomplete: bool = False
    # A superficial loss whose replacement shares haven't been bought yet in
    # a taxable account: added to the ACB of the next taxable purchase.
    pending_denied: float = 0.0
    pending_incomplete: bool = False  # the pending amount rests on a missing FX rate

    @property
    def quantity(self) -> float:
        return sum(q for q in self.holdings.values() if q > EPSILON)

    @property
    def acb_per_unit(self) -> float:
        q = self.quantity
        return self.acb / q if q > EPSILON else 0.0

    def held(self, account_id: int, symbol: str) -> float:
        return self.holdings.get((account_id, symbol), 0.0)

    def remove(self, account_id: int, symbol: str, quantity: float) -> float:
        """Take `quantity` units of `symbol` out of `account_id` at the pooled
        average cost and return the ACB that leaves with them."""
        total = self.quantity
        share = self.acb * (quantity / total) if total > EPSILON else 0.0
        self.holdings[(account_id, symbol)] -= quantity
        self.acb -= share
        if self.quantity <= EPSILON:
            # Fully sold: drop float dust and start the next pool fresh.
            self.holdings.clear()
            self.acb = 0.0
            self.incomplete = False
        return share


@dataclass
class TaxReport:
    dispositions: list[Disposition] = field(default_factory=list)
    pools: dict[str, AcbPool] = field(default_factory=dict)  # open pools after the replay, by pool symbol
    issues: list[LedgerIssue] = field(default_factory=list)


def is_taxable(account: Account | None) -> bool:
    """Gains in this account are reported. Unknown accounts are skipped, not guessed."""
    return account is not None and not account.type.registered


def pool_symbol(symbol: str, identical: IdenticalProperty | None) -> str:
    """The pool a symbol's units go into: the symbol it is linked to, or its own."""
    return identical.get(symbol, symbol) if identical else symbol


def compute(
    transactions: Sequence[Transaction],
    accounts: dict[int, Account],
    fx_on: FxLookup,
    *,
    today: str | None = None,
    on_day: DayObserver | None = None,
    identical: IdenticalProperty | None = None,
) -> TaxReport:
    """Replay the ledger through pooled ACB and return every taxable event.

    `today` (ISO date) only decides whether a superficial-loss window is still
    open; it defaults to the real date and is a parameter so tests are stable.
    `on_day`, if given, sees the pools at the end of every ledger date (see
    `foreign_property`); it only observes, so the report is the same with or without it.
    `identical` links symbols listing the same units into one pool (see `pool_symbol`).
    """
    today = today or date.today().isoformat()
    report = TaxReport()
    pools = report.pools
    ordered = sorted(transactions, key=sort_key)

    def key(symbol: str) -> str:
        return pool_symbol(symbol, identical)

    def pool(symbol: str) -> AcbPool:
        k = key(symbol)
        if k not in pools:
            pools[k] = AcbPool(k)
        return pools[k]

    def rate(txn: Transaction, ccy: str) -> float | None:
        return fx_on(txn.date, ccy)

    def acquire(p: AcbPool, account_id: int, symbol: str, quantity: float, cost: float, known: bool) -> None:
        """Add units of `symbol` to the pool at `cost` (base currency)."""
        p.holdings[(account_id, symbol)] += quantity
        p.acb += cost
        p.incomplete |= not known
        if p.pending_denied > EPSILON:
            # These are the replacement shares for an earlier superficial loss:
            # the denied loss becomes part of their cost.
            p.acb += p.pending_denied
            p.incomplete |= p.pending_incomplete
            p.pending_denied, p.pending_incomplete = 0.0, False

    p: AcbPool | None  # the pool a transaction acts on (lookups may find none)
    day = ""  # the ledger date being replayed
    for txn in ordered:
        if on_day is not None and day and txn.date != day:
            on_day(day, pools)
        day = txn.date
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
            acquire(
                pool(txn.symbol), txn.account_id, txn.symbol, txn.quantity, cost_native * (fx or 0.0), fx is not None
            )

        elif t is TxnType.SELL and taxable:
            p = pool(txn.symbol)
            qty = min(txn.quantity, p.held(txn.account_id, txn.symbol))
            if qty <= EPSILON:
                # Selling what isn't held is already reported by ledger.replay().
                continue
            fx = rate(txn, ccy)
            complete = fx is not None and not p.incomplete
            acb = p.remove(txn.account_id, txn.symbol, qty)
            proceeds = (qty * txn.price - txn.fees) * (fx or 0.0)
            d = Disposition(txn.date, txn.account_id, txn.symbol, qty, proceeds, acb, ccy, fx, txn.id, "sale", complete)
            d.pool = p.symbol
            report.dispositions.append(d)
            if d.gain < -EPSILON:
                taxable_fraction = _superficial_denial(d, ordered, accounts, today, key)
                if d.denied > EPSILON:
                    _attach_denied_loss(d, p, taxable_fraction)

        elif t is TxnType.SPLIT and taxable:
            # A split changes the unit count, never the cost: ACB per unit falls.
            p = pools.get(key(txn.symbol))
            if p and (txn.account_id, txn.symbol) in p.holdings:
                p.holdings[(txn.account_id, txn.symbol)] *= txn.ratio

        elif t is TxnType.ACB_INCREASE and taxable:
            p = pools.get(key(txn.symbol))
            if p is not None and p.held(txn.account_id, txn.symbol) > EPSILON:
                fx = rate(txn, ccy)
                p.incomplete |= fx is None
                p.acb += txn.amount * (fx or 0.0)

        elif t is TxnType.ROC and taxable:
            # Return of capital reduces ACB. If it would push ACB below zero,
            # ACB is set to zero and the excess is a capital gain that year.
            p = pools.get(key(txn.symbol))
            # Units of this listing must be held somewhere taxable: a linked line's units don't
            # make a return of capital on a line that isn't held reduce the shared cost base.
            if p is None or not any(q > EPSILON for (_, s), q in p.holdings.items() if s == txn.symbol):
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
                        pool=p.symbol,
                    )
                )

        elif t is TxnType.TRANSFER and txn.target_account_id is not None:
            _transfer(txn, ccy, taxable, accounts, pools.get(key(txn.symbol)), pool, acquire, fx_on, report)

    if on_day is not None and day:
        on_day(day, pools)
    report.pools = {s: p for s, p in pools.items() if p.quantity > EPSILON}
    if identical:
        report.issues += _staggered_linked_splits(ordered, key)
    return report


def _staggered_linked_splits(ordered: Sequence[Transaction], key: Callable[[str], str]) -> list[LedgerIssue]:
    """Flag one split recorded on different dates for linked lines.

    Superficial-loss checks treat a split row as the security splitting that day, so the same
    split on another day for the other line is counted again. Rows with the same ratio within
    the superficial-loss window are assumed to be one split recorded twice."""
    issues = []
    splits = [t for t in ordered if t.type is TxnType.SPLIT]
    for i, later in enumerate(splits):
        day = date.fromisoformat(later.date)
        for earlier in splits[:i]:
            if (
                earlier.symbol != later.symbol
                and key(earlier.symbol) == key(later.symbol)
                and earlier.ratio == later.ratio
                and earlier.date != later.date
                and (day - date.fromisoformat(earlier.date)).days <= SUPERFICIAL_WINDOW_DAYS
            ):
                issues.append(
                    LedgerIssue(
                        later.id,
                        later.date,
                        f"Split of {later.symbol} is dated {later.date}, but the split of linked {earlier.symbol} "
                        f"is dated {earlier.date}. Use the same date for both, or superficial-loss estimates "
                        "may count it twice",
                    )
                )
                break
    return issues


# ── In-kind transfers ─────────────────────────────────────────────────────────


def _transfer(
    txn: Transaction,
    ccy: str,
    src_taxable: bool,
    accounts: dict[int, Account],
    p: AcbPool | None,  # the symbol's pool, if it has one yet
    pool: Callable[[str], AcbPool],
    acquire: Callable[[AcbPool, int, str, float, float, bool], None],
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
    sym = txn.symbol
    if src_taxable and dst_taxable:
        if p is None:
            return
        qty = min(txn.quantity, p.held(txn.account_id, sym))
        p.holdings[(txn.account_id, sym)] -= qty
        p.holdings[(target, sym)] += qty
        return

    fx = fx_on(txn.date, ccy)
    priced = txn.price > 0
    if src_taxable and not dst_taxable:
        qty = min(txn.quantity, p.held(txn.account_id, sym)) if p else 0.0
        if p is None or qty <= EPSILON:
            return
        complete = fx is not None and not p.incomplete
        acb = p.remove(txn.account_id, sym, qty)
        if not priced:
            report.issues.append(
                LedgerIssue(
                    txn.id,
                    txn.date,
                    f"Transfer of {txn.symbol} into a registered account is a deemed sale at market value — "
                    "add the price per unit to the transfer to include it in the tax report",
                    "transfer_to_registered_unpriced",
                    {"symbol": txn.symbol},
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
            pool=p.symbol,
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
                    "transfer_from_registered_unpriced",
                    {"symbol": txn.symbol},
                )
            )
        # Unpriced: still add the units (so later sales aren't flagged as
        # oversells) but mark the pool incomplete, which keeps its sales out
        # of the yearly totals until the price is filled in.
        acquire(
            pool(sym),
            target,
            sym,
            txn.quantity,
            txn.quantity * txn.price * (fx or 0.0),
            priced and fx is not None,
        )


# ── Superficial losses ────────────────────────────────────────────────────────


def _superficial_denial(
    d: Disposition,
    ordered: Sequence[Transaction],
    accounts: dict[int, Account],
    today: str,
    key: Callable[[str], str],
) -> float:
    """Set the denied loss and return the taxable fraction of replacement purchases.

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

    "The same property" is every symbol in the sale's pool (`key` maps a symbol to its pool),
    so buying the other listing of identical units counts, one unit for one.

    Affiliated persons (a spouse, a corporation you control) are outside
    MarketPulse's view, so a clean result here isn't proof: the report says so.
    """
    sale_day = date.fromisoformat(d.date)
    lo = (sale_day - timedelta(days=SUPERFICIAL_WINDOW_DAYS)).isoformat()
    hi = (sale_day + timedelta(days=SUPERFICIAL_WINDOW_DAYS)).isoformat()
    cutoff = min(hi, today)
    pool = key(d.symbol)
    same = [t for t in ordered if key(t.symbol) == pool]

    # Count purchases in the units at the start of the window, then convert
    # to sale-date units. Multiply the scale once per split across holdings
    # (one account's units of one listing).
    scale = sale_scale = cutoff_scale = 1.0
    acquired = taxable = 0.0
    window = (t for t in same if lo <= t.date <= hi)
    for day, entries in groupby(window, key=lambda t: t.date):
        split_holdings: dict[float, Counter[tuple[int, str]]] = defaultdict(Counter)
        buys = []
        for t in entries:
            if t.type is TxnType.SPLIT:
                split_holdings[t.ratio][(t.account_id, t.symbol)] += 1
            elif t.type in (TxnType.BUY, TxnType.DRIP):
                buys.append(t)
        # Use the most occurrences in any one holding. One row per account and listing
        # describes one split, while repeated rows in a holding compound.
        splits = [(ratio, max(counts.values()), counts) for ratio, counts in split_holdings.items()]
        for t in buys:
            # Ledger replay applies a same-day split to purchases in that holding.
            # Purchases elsewhere are already in the new units for that split.
            held_as = (t.account_id, t.symbol)
            buy_scale = scale * prod(ratio ** (count - counts[held_as]) for ratio, count, counts in splits)
            quantity = t.quantity / buy_scale
            acquired += quantity
            if is_taxable(accounts.get(t.account_id)):
                taxable += quantity
        # On a split day, sells and end-of-day holdings use post-split units.
        scale *= prod(ratio**count for ratio, count, _ in splits)
        if day <= d.date:
            sale_scale = scale
        if day <= cutoff:
            cutoff_scale = scale

    # B: units held across every account at the end of day +30. The window
    # may still be open (sale less than 30 days ago), in which case today's
    # holdings are the best estimate and the row is marked provisional.
    held = sum(h.quantity for h in replay(same, accounts, until=cutoff).open_holdings())

    d.acquired_in_window = acquired * sale_scale
    d.held_after_window = held * (sale_scale / cutoff_scale)
    d.window_open = hi > today
    fraction = min(d.quantity, d.acquired_in_window, d.held_after_window) / d.quantity if d.quantity > EPSILON else 0.0
    if fraction > EPSILON:
        d.denied = -d.gain * fraction
        d.denied_reason = DENIED_SUPERFICIAL
    return taxable / acquired if d.acquired_in_window > EPSILON else 0.0


def _attach_denied_loss(d: Disposition, p: AcbPool, taxable_fraction: float) -> None:
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
    carried = d.denied * taxable_fraction
    if carried <= EPSILON:
        return
    # A sale missing an FX rate has a guessed loss, so the cost it adds is a guess too.
    if p.quantity > EPSILON:
        p.acb += carried
        p.incomplete |= not d.complete
    else:
        p.pending_denied += carried
        p.pending_incomplete |= not d.complete


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


# ── Specified foreign property (form T1135) ───────────────────────────────────
#
# A Canadian resident files form T1135 for any year in which the total *cost amount* of their
# specified foreign property was over $100,000 at any time. Under $250,000 all year, the
# simplified method is enough; at $250,000 or more at any point, the detailed one is needed.
# For shares and fund units the cost amount is the adjusted cost base, so the pools above
# already hold it: `foreign_property` watches them at the end of every ledger date.
#
# What counts is decided per symbol (`is_foreign_property`). Registered accounts never count;
# they are outside the pools to begin with. The thresholds are in Canadian dollars, so the
# Tracker hands `foreign_property` CAD rates whatever the base currency is.

T1135_THRESHOLD = 100_000.0  # file when the cost amount is over this at any time in the year
T1135_DETAILED_THRESHOLD = 250_000.0  # at or over this at any time: the detailed method

T1135_NOT_REQUIRED = "not_required"
T1135_SIMPLIFIED = "simplified"
T1135_DETAILED = "detailed"
T1135_UNDETERMINED = "undetermined"  # under the threshold, but an FX rate is missing
T1135_STATUS_LABELS = {
    T1135_NOT_REQUIRED: "T1135 not required (cost stayed at or under $100,000)",
    T1135_SIMPLIFIED: "T1135 likely required: simplified method (over $100,000, under $250,000 all year)",
    T1135_DETAILED: "T1135 likely required: detailed method (cost reached $250,000)",
    T1135_UNDETERMINED: "T1135 undetermined: an FX rate is missing, so the cost may be over $100,000",
}

# Yahoo suffixes of Canadian listings: TSX, TSX Venture, Cboe Canada (NEO) and the CSE.
CANADIAN_SUFFIXES = frozenset({"TO", "V", "NE", "CN"})
# Crypto and currency pairs (BTC-USD, ETH-CAD): not specified foreign property.
_PAIR = re.compile(r"-[A-Z]{3}$")
# Asset classes left out by default: crypto, and cash-like holdings such as money market funds.
_EXCLUDED_CLASSES = frozenset({AssetClass.CRYPTO, AssetClass.CASH})

FOREIGN_PROPERTY_NOTES = [
    "Estimate only, not tax advice: confirm with CRA's T1135 guide or a tax professional.",
    "Cost amount is your adjusted cost base in CAD, in non-registered accounts only.",
    "Foreign means listed outside Canada; `marketpulse asset foreign SYMBOL yes|no` corrects a symbol.",
]


def is_foreign_property(symbol: str, asset: Asset | None = None) -> bool:
    """Whether a symbol is specified foreign property, by where it is listed.

    An asset's `foreign_property` setting wins. Otherwise only market-priced symbols can be
    foreign: no Yahoo suffix (a US listing) or a non-Canadian one (.L, .DE, ...) is foreign,
    while .TO, .V, .NE and .CN listings are Canadian. That is why a Canadian-listed ETF holding
    US stocks doesn't count. Crypto, currency pairs, indices, cash-like, accrual-priced fixed-income and
    manually valued assets don't count unless set to.

    The listing is only a proxy for the issuer's residence: a US company's shares bought on
    the TSX are foreign property, and a Canadian company's bought in New York aren't. The
    per-asset setting is for those.
    """
    if asset is not None and asset.foreign_property is not None:
        return asset.foreign_property
    if asset is not None and (asset.kind is not AssetKind.MARKET or asset.asset_class in _EXCLUDED_CLASSES):
        return False
    sym = symbol.strip().upper()
    if not sym or sym.startswith("^") or "=" in sym or _PAIR.search(sym):
        return False
    _, dot, suffix = sym.rpartition(".")
    return not dot or suffix not in CANADIAN_SUFFIXES


@dataclass
class ForeignHolding:
    """One specified foreign property in one year. Amounts are cost amounts (ACB)."""

    symbol: str
    max_cost: float = 0.0  # the highest end-of-day cost during the year
    max_cost_date: str = ""  # the day it was first reached ("" if never held)
    year_end_cost: float = 0.0  # cost at the end of the year (or at `as_of` for the current year)
    gain: float = 0.0  # gain (loss) on the year's dispositions, as reported (complete ones only)
    dispositions: int = 0
    incomplete: bool = False  # an FX rate behind its cost or a disposition was missing


@dataclass
class ForeignPropertyYear:
    """Specified foreign property held in taxable accounts during one calendar year."""

    year: int
    as_of: str  # December 31, or today for a year still in progress
    currency: str = "CAD"  # the currency the amounts are in (the fx_on callback's)
    max_cost: float = 0.0  # the highest total end-of-day cost during the year
    max_cost_date: str = ""  # the day it was first reached ("" if nothing was held)
    year_end_cost: float = 0.0
    # True when an FX rate was missing: some cost is then left out, so totals may be too low.
    incomplete: bool = False
    holdings: list[ForeignHolding] = field(default_factory=list)

    @property
    def status(self) -> str:
        """Whether form T1135 looks required, and which method: one of the T1135_* values."""
        cost = round(self.max_cost, 2)  # to the cent, so float dust can't cross a threshold
        if cost >= T1135_DETAILED_THRESHOLD:
            return T1135_DETAILED
        if cost > T1135_THRESHOLD:
            return T1135_SIMPLIFIED
        return T1135_NOT_REQUIRED

    @property
    def label(self) -> str:
        """The assessment in words."""
        return T1135_STATUS_LABELS[self.assessment]

    @property
    def assessment(self) -> str:
        """`status`, or "undetermined" when it says not required but an FX rate is missing."""
        return T1135_UNDETERMINED if self.incomplete and self.status == T1135_NOT_REQUIRED else self.status

    @property
    def gain(self) -> float:
        return sum((h.gain for h in self.holdings), 0.0)


# End of one ledger date: {pool symbol: (cost, incomplete)} for every foreign pool still held.
_ForeignDay = tuple[str, dict[str, tuple[float, bool]]]


@dataclass
class _ForeignLedger:
    """One replay's worth of what `_foreign_year` needs for any year."""

    days: list[_ForeignDay]
    dispositions: list[Disposition]  # of foreign property, in replay order
    bought: dict[str, list[str]]  # dates of taxable purchases (and DRIPs), by pool symbol


def _foreign_replay(
    transactions: Sequence[Transaction],
    accounts: dict[int, Account],
    assets: dict[str, Asset],
    fx_on: FxLookup,
    today: str,
    identical: IdenticalProperty | None = None,
) -> _ForeignLedger:
    """Replay the ledger once, recording the foreign pools at the end of every ledger date.

    Identical lines share a pool, so they are one holding, named and judged by the pool symbol."""
    verdicts: dict[str, bool] = {}

    def foreign(symbol: str) -> bool:
        if symbol not in verdicts:
            verdicts[symbol] = is_foreign_property(symbol, assets.get(symbol.upper()))
        return verdicts[symbol]

    days: list[_ForeignDay] = []

    def observe(day: str, pools: dict[str, AcbPool]) -> None:
        held = {s: (p.acb, p.incomplete) for s, p in pools.items() if p.quantity > EPSILON and foreign(s)}
        days.append((day, held))

    report = compute(transactions, accounts, fx_on, today=today, on_day=observe, identical=identical)
    bought: dict[str, list[str]] = defaultdict(list)
    for t in transactions:
        if t.type in (TxnType.BUY, TxnType.DRIP) and is_taxable(accounts.get(t.account_id)):
            bought[pool_symbol(t.symbol, identical)].append(t.date)
    return _ForeignLedger(days, [d for d in report.dispositions if foreign(d.pool)], bought)


def _foreign_year(year: int, ledger: _ForeignLedger, today: str, currency: str) -> ForeignPropertyYear:
    days, dispositions = ledger.days, ledger.dispositions
    start, as_of = f"{year}-01-01", min(f"{year}-12-31", today)
    result = ForeignPropertyYear(year, as_of, currency)
    if start > as_of:
        return result  # a year that hasn't started: nothing has been held in it yet
    # What was held on January 1 is whatever the last earlier ledger date left behind.
    carried = [held for day, held in days if day < start][-1:]
    timeline = [(start, carried[0])] if carried else []
    timeline += [(day, held) for day, held in days if start <= day <= as_of]

    # A sale with an FX rate missing (on it, or on a purchase behind it) has a guessed gain, so
    # whether part of a loss was denied, and how much, is a guess too. A denied loss moves into
    # the replacement shares' cost: when the sale's loss was denied, or it could have been (a
    # taxable purchase within 30 days either side: what is still held at day 30 counts across
    # every account, so a taxable lot sold before then can still take part of it), the symbol's
    # cost and the gain on any later sale (in replay order) are incomplete from then on.
    # Conservatively, this lasts even if the pool is later sold out and reopened. A loss denied
    # on a move into a registered plan never enters taxable cost, so transfers don't count.
    def could_be_superficial(d: Disposition) -> bool:
        sold = date.fromisoformat(d.date)
        window = timedelta(days=SUPERFICIAL_WINDOW_DAYS)
        lo, hi = (sold - window).isoformat(), (sold + window).isoformat()
        return any(lo <= day <= hi for day in ledger.bought.get(d.pool, ()))

    guessed: dict[str, str] = {}  # by pool symbol
    unknown_gain: set[int] = set()  # dispositions (by position) whose gain rests on a guess
    for i, d in enumerate(dispositions):
        if d.pool in guessed:
            unknown_gain.add(i)
        elif not d.complete and (d.superficial or (d.kind == "sale" and could_be_superficial(d))):
            guessed[d.pool] = d.date
    holdings: dict[str, ForeignHolding] = {}
    for day, held in timeline:
        total = sum((cost for cost, _ in held.values()), 0.0)
        if total > result.max_cost + EPSILON:
            result.max_cost, result.max_cost_date = total, day
        for symbol, (cost, incomplete) in held.items():
            h = holdings.setdefault(symbol, ForeignHolding(symbol))
            if cost > h.max_cost + EPSILON or not h.max_cost_date:
                h.max_cost, h.max_cost_date = max(cost, h.max_cost), day
            h.incomplete |= incomplete or (symbol in guessed and guessed[symbol] <= day)
    final = timeline[-1][1] if timeline else {}
    for symbol, (cost, _) in final.items():
        holdings[symbol].year_end_cost = cost
    result.year_end_cost = sum((cost for cost, _ in final.values()), 0.0)
    for i, d in enumerate(dispositions):
        if start <= d.date <= as_of:
            h = holdings.setdefault(d.pool, ForeignHolding(d.pool))
            h.dispositions += 1
            if d.complete and i not in unknown_gain:
                h.gain += d.allowed_gain
            else:
                h.incomplete = True
    result.holdings = sorted(holdings.values(), key=lambda h: (-h.max_cost, h.symbol))
    result.incomplete = any(h.incomplete for h in result.holdings)
    return result


def foreign_property(
    transactions: Sequence[Transaction],
    accounts: dict[int, Account],
    assets: dict[str, Asset],
    fx_on: FxLookup,
    year: int,
    *,
    today: str | None = None,
    currency: str = "CAD",
    identical: IdenticalProperty | None = None,
) -> ForeignPropertyYear:
    """The cost of specified foreign property held during `year`, for form T1135.

    Replays the ledger through the same pooled ACB as `compute` (so registered accounts are
    left out and every purchase is converted at its own date's rate) and totals the foreign
    pools at the end of every day. `fx_on` must give rates in `currency`, which should be CAD
    because the T1135 thresholds are. A year still in progress runs to `today`.
    """
    today = today or date.today().isoformat()
    ledger = _foreign_replay(transactions, accounts, assets, fx_on, today, identical)
    return _foreign_year(year, ledger, today, currency)


def foreign_property_years(
    transactions: Sequence[Transaction],
    accounts: dict[int, Account],
    assets: dict[str, Asset],
    fx_on: FxLookup,
    *,
    today: str | None = None,
    currency: str = "CAD",
    identical: IdenticalProperty | None = None,
) -> list[ForeignPropertyYear]:
    """`foreign_property` for every year in which foreign property was held or sold, newest
    first, from a single replay. Years holding none are left out."""
    today = today or date.today().isoformat()
    ledger = _foreign_replay(transactions, accounts, assets, fx_on, today, identical)
    days, dispositions = ledger.days, ledger.dispositions
    seen = [day for day, held in days if held and day <= today] + [d.date for d in dispositions if d.date <= today]
    if not seen:
        return []
    first, last = int(min(seen)[:4]), int(today[:4])
    found = (_foreign_year(y, ledger, today, currency) for y in range(last, first - 1, -1))
    return [y for y in found if y.holdings]
