"""Ledger replay engine.

Replays transactions in date order and derives holdings, cash, cost base
(Canadian average-cost ACB), realized gains, income and contributions. Pure
and deterministic: no I/O, no market data.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta

from .models import EPSILON, Account, Transaction, TxnType, guess_currency


@dataclass
class Holding:
    account_id: int
    symbol: str
    quantity: float = 0.0
    book: float = 0.0  # total adjusted cost base, in `currency`
    currency: str = ""
    first_date: str = ""

    @property
    def avg_cost(self) -> float:
        return self.book / self.quantity if self.quantity > EPSILON else 0.0


@dataclass
class RealizedGain:
    date: str
    account_id: int
    symbol: str
    quantity: float
    proceeds: float  # net of fees
    cost: float  # ACB of the shares sold
    currency: str
    txn_id: int | None = None

    @property
    def gain(self) -> float:
        return self.proceeds - self.cost


@dataclass
class IncomeEvent:
    date: str
    account_id: int
    symbol: str  # "" for account-level interest
    kind: TxnType  # DIVIDEND | DRIP | INTEREST
    amount: float
    currency: str


@dataclass
class CashFlow:
    """External money in (+) or out (-) of an account."""

    date: str
    account_id: int
    amount: float
    currency: str


@dataclass
class LedgerIssue:
    txn_id: int | None
    date: str
    message: str


@dataclass
class LedgerState:
    holdings: dict[tuple[int, str], Holding] = field(default_factory=dict)
    cash: dict[tuple[int, str], float] = field(default_factory=lambda: defaultdict(float))
    realized: list[RealizedGain] = field(default_factory=list)
    income: list[IncomeEvent] = field(default_factory=list)
    flows: list[CashFlow] = field(default_factory=list)
    fees: dict[str, float] = field(default_factory=lambda: defaultdict(float))  # ccy -> total fees paid
    issues: list[LedgerIssue] = field(default_factory=list)
    valuations: dict[str, tuple[str, float]] = field(default_factory=dict)  # symbol -> (date, price)

    def open_holdings(self, account_id: int | None = None) -> list[Holding]:
        return sorted(
            (
                h
                for h in self.holdings.values()
                if h.quantity > EPSILON and (account_id is None or h.account_id == account_id)
            ),
            key=lambda h: (h.account_id, h.symbol),
        )

    def symbols(self) -> list[str]:
        return sorted({h.symbol for h in self.open_holdings()})

    def cash_balances(self, account_id: int | None = None) -> dict[tuple[int, str], float]:
        return {k: v for k, v in self.cash.items() if abs(v) > 0.005 and (account_id is None or k[0] == account_id)}


def transaction_currency(txn: Transaction, accounts: dict[int, Account]) -> str:
    """The currency a transaction's prices and amounts are in.

    An explicit currency on the transaction wins. Otherwise a security's
    currency is guessed from its symbol (XEQT.TO -> CAD) and cash movements
    use the account's currency. Shared by the ledger and the tax engine so
    both always agree on what currency a row is in.
    """
    acct = accounts.get(txn.account_id)
    account_ccy = acct.currency if acct else "CAD"
    if txn.currency:
        return txn.currency
    return guess_currency(txn.symbol, account_ccy) if txn.symbol else account_ccy


def sort_key(txn: Transaction) -> tuple:
    # Same-day ordering: money in, then buys/splits, then sells, then money out,
    # so a deposit-then-buy entered on one day never looks like an oversell.
    order = {
        TxnType.DEPOSIT: 0,
        TxnType.BUY: 1,
        TxnType.DRIP: 1,
        TxnType.SPLIT: 2,
        TxnType.TRANSFER: 3,
        TxnType.ROC: 4,
        TxnType.DIVIDEND: 5,
        TxnType.INTEREST: 5,
        TxnType.VALUATION: 5,
        TxnType.SELL: 6,
        TxnType.FEE: 7,
        TxnType.WITHDRAWAL: 8,
    }
    return (txn.date, order[txn.type], txn.id or 0)


def _tracks_cash(accounts: dict[int, Account], account_id: int) -> bool:
    acct = accounts.get(account_id)
    return bool(acct and acct.track_cash)


def _holding(state: LedgerState, account_id: int, symbol: str, ccy: str) -> Holding:
    key = (account_id, symbol)
    h = state.holdings.get(key)
    if h is None:
        h = state.holdings[key] = Holding(account_id=account_id, symbol=symbol, currency=ccy)
    if not h.currency:
        h.currency = ccy
    return h


def _apply(state: LedgerState, txn: Transaction, accounts: dict[int, Account]) -> None:
    """Apply one transaction to `state` in place."""
    acct = txn.account_id
    t = txn.type
    ccy = transaction_currency(txn, accounts)
    cash_key = (acct, ccy)
    tracks_cash = _tracks_cash(accounts, acct)

    # `h` is the position a transaction acts on; lookups in the branches
    # below can come back empty, so it's typed as optional throughout.
    h: Holding | None
    if t in (TxnType.BUY, TxnType.DRIP):
        h = _holding(state, acct, txn.symbol, ccy)
        if h.quantity <= EPSILON:
            h.quantity, h.book, h.first_date = 0.0, 0.0, txn.date
        cost = txn.quantity * txn.price + txn.fees
        h.quantity += txn.quantity
        h.book += cost
        state.fees[ccy] += txn.fees
        if t is TxnType.DRIP:
            state.income.append(IncomeEvent(txn.date, acct, txn.symbol, t, txn.quantity * txn.price, ccy))
        elif tracks_cash:
            state.cash[cash_key] -= cost

    elif t is TxnType.SELL:
        h = state.holdings.get((acct, txn.symbol))
        held = h.quantity if h else 0.0
        if txn.quantity > held + EPSILON:
            state.issues.append(
                LedgerIssue(txn.id, txn.date, f"Sell of {txn.quantity:,.4f} {txn.symbol} exceeds {held:,.4f} held")
            )
        if h is None or held <= EPSILON:
            # Nothing to sell. (Also covers a sub-EPSILON "sell" of a
            # position that was never opened, which used to crash here.)
            return
        qty = min(txn.quantity, held)
        cost = h.avg_cost * qty
        proceeds = qty * txn.price - txn.fees
        state.realized.append(RealizedGain(txn.date, acct, txn.symbol, qty, proceeds, cost, h.currency, txn.id))
        h.quantity -= qty
        h.book -= cost
        if h.quantity <= EPSILON:
            h.quantity, h.book = 0.0, 0.0
        state.fees[h.currency] += txn.fees
        if tracks_cash:
            state.cash[(acct, h.currency)] += proceeds

    elif t is TxnType.SPLIT:
        h = state.holdings.get((acct, txn.symbol))
        if h:
            h.quantity *= txn.ratio

    elif t is TxnType.ROC:
        h = state.holdings.get((acct, txn.symbol))
        if h:
            excess = txn.amount - h.book
            h.book = max(h.book - txn.amount, 0.0)
            if excess > EPSILON:
                # ACB can't go negative: the excess is a deemed capital gain
                state.realized.append(RealizedGain(txn.date, acct, txn.symbol, 0.0, excess, 0.0, ccy, txn.id))
        if tracks_cash:
            state.cash[cash_key] += txn.amount

    elif t is TxnType.TRANSFER:
        h = state.holdings.get((acct, txn.symbol))
        if h is None or h.quantity <= EPSILON or txn.target_account_id is None:
            state.issues.append(LedgerIssue(txn.id, txn.date, f"Transfer of {txn.symbol} with nothing held"))
            return
        qty = min(txn.quantity, h.quantity)
        moved_book = h.avg_cost * qty
        h.quantity -= qty
        h.book -= moved_book
        dest = _holding(state, txn.target_account_id, txn.symbol, h.currency)
        if dest.quantity <= EPSILON:
            dest.first_date = txn.date
        dest.quantity += qty
        dest.book += moved_book

    elif t in (TxnType.DIVIDEND, TxnType.INTEREST):
        state.income.append(IncomeEvent(txn.date, acct, txn.symbol, t, txn.amount, ccy))
        if tracks_cash:
            state.cash[cash_key] += txn.amount

    elif t is TxnType.DEPOSIT:
        state.flows.append(CashFlow(txn.date, acct, txn.amount, ccy))
        if tracks_cash:
            state.cash[cash_key] += txn.amount

    elif t is TxnType.WITHDRAWAL:
        state.flows.append(CashFlow(txn.date, acct, -txn.amount, ccy))
        if tracks_cash:
            state.cash[cash_key] -= txn.amount

    elif t is TxnType.FEE:
        state.fees[ccy] += txn.amount
        if tracks_cash:
            state.cash[cash_key] -= txn.amount

    elif t is TxnType.VALUATION:
        state.valuations[txn.symbol] = (txn.date, txn.price)


def replay(
    transactions: list[Transaction],
    accounts: dict[int, Account] | None = None,
    *,
    until: str | None = None,
) -> LedgerState:
    """Replay the ledger (optionally only up to and including `until`)."""
    accounts = accounts or {}
    state = LedgerState()
    for txn in sorted(transactions, key=sort_key):
        if until and txn.date > until:
            break
        _apply(state, txn, accounts)
    return state


def replay_by_day(
    transactions: list[Transaction],
    accounts: dict[int, Account] | None,
    start: str,
    end: str,
) -> Iterator[tuple[str, LedgerState]]:
    """Yield `(iso_date, state)` for every calendar day from `start` to `end` inclusive.

    Equivalent to `replay(transactions, accounts, until=day)` for each day, but the
    ledger is sorted and walked once. The *same* `LedgerState` is mutated in place,
    so read what you need before advancing the iterator. Transactions dated before
    `start` are applied on the first day; those after `end` are never applied.
    """
    accounts = accounts or {}
    txns = sorted(transactions, key=sort_key)
    state = LedgerState()
    i = 0
    day, last = date.fromisoformat(start), date.fromisoformat(end)
    while day <= last:
        iso = day.isoformat()
        while i < len(txns) and txns[i].date <= iso:
            _apply(state, txns[i], accounts)
            i += 1
        yield iso, state
        day += timedelta(days=1)


# ── Contribution room ─────────────────────────────────────────────────────────


# TFSA annual dollar limits (CRA). Room accumulates from the year you turn 18
# (and no earlier than 2009); withdrawals are added back the following year.
TFSA_LIMITS = {
    2009: 5000,
    2010: 5000,
    2011: 5000,
    2012: 5000,
    2013: 5500,
    2014: 5500,
    2015: 10000,
    2016: 5500,
    2017: 5500,
    2018: 5500,
    2019: 6000,
    2020: 6000,
    2021: 6000,
    2022: 6000,
    2023: 6500,
    2024: 7000,
    2025: 7000,
    2026: 7000,
}
# FHSA (first home savings account), from 2023. Each year adds $8,000 of
# participation room. Unused room carries forward, but only up to $8,000, so
# the most you can ever put in within one year is $16,000. Contributions over
# the account's life are capped at $40,000.
FHSA_ANNUAL_LIMIT = 8000
FHSA_CARRYFORWARD_LIMIT = 8000
FHSA_LIFETIME_LIMIT = 40000


def tfsa_limit(year: int) -> int:
    # Future limits are indexed to inflation in $500 steps; assume flat until published.
    return TFSA_LIMITS.get(year, TFSA_LIMITS[max(TFSA_LIMITS)]) if year >= 2009 else 0


@dataclass
class RoomStatus:
    """Contribution room for one account type, and how it was derived.

    The columns always add up:
        remaining = starting_room + new_limits + withdrawals_added_back
                    - contributions - forfeited
    """

    account_type: str
    as_of_year: int
    starting_room: float
    contributions: float
    withdrawals_added_back: float
    new_limits: float
    remaining: float
    # Room that existed on paper but can't be used: FHSA room above the $8,000
    # carry-forward, or above what the $40,000 lifetime limit still allows.
    forfeited: float = 0.0


def contribution_room(
    account_type: str,
    as_of_year: int,
    starting_room: float,
    flows: list[CashFlow],
    account_ids: set[int],
    *,
    current_year: int | None = None,
) -> RoomStatus:
    """Remaining room given room known at Jan 1 of `as_of_year`.

    TFSA: adds each new year's limit and prior-year withdrawals.
    FHSA: see _fhsa_room (annual limit, capped carry-forward, lifetime limit).
    RRSP and others: room is user-supplied; only contributions are subtracted.
    """
    current_year = current_year or date.today().year
    mine = [f for f in flows if f.account_id in account_ids]
    relevant = [f for f in mine if int(f.date[:4]) >= as_of_year]
    contributions = sum(f.amount for f in relevant if f.amount > 0)
    if account_type == "FHSA":
        return _fhsa_room(as_of_year, starting_room, mine, current_year, contributions)
    withdrawals_back = 0.0
    new_limits = 0.0
    if account_type == "TFSA":
        withdrawals_back = sum(-f.amount for f in relevant if f.amount < 0 and int(f.date[:4]) < current_year)
        new_limits = sum(tfsa_limit(y) for y in range(as_of_year + 1, current_year + 1))
    remaining = starting_room + new_limits + withdrawals_back - contributions
    return RoomStatus(account_type, as_of_year, starting_room, contributions, withdrawals_back, new_limits, remaining)


def _fhsa_room(
    as_of_year: int, starting_room: float, flows: list[CashFlow], current_year: int, contributions: float
) -> RoomStatus:
    """FHSA participation room, walked forward one year at a time.

    `starting_room` is the participation room for `as_of_year` (it already
    includes any carry-forward into that year). Then, for each later year:

        carry_forward  = min(room last year - contributions last year, $8,000)
        room this year = $8,000 + carry_forward

    so unused room above $8,000 is forfeited, not banked. The result is
    finally capped by the lifetime limit: $40,000 minus everything ever
    contributed to these accounts (all recorded years, not just those since
    `as_of_year`).

    Not modelled: withdrawals never restore FHSA room (correct: they don't),
    RRSP-to-FHSA transfers (they use room but aren't deposits), and the
    account's 15-year / age-71 closing date.
    """
    by_year: dict[int, float] = defaultdict(float)
    for f in flows:
        if f.amount > 0:
            by_year[int(f.date[:4])] += f.amount

    room = starting_room
    new_limits = 0.0
    forfeited = 0.0
    for year in range(as_of_year, current_year):
        unused = max(room - by_year[year], 0.0)
        carry = min(unused, FHSA_CARRYFORWARD_LIMIT)
        forfeited += unused - carry
        # Over-contributing last year leaves room negative; that excess still
        # counts against this year's new room (and is taxed 1%/month by CRA).
        overage = min(room - by_year[year], 0.0)
        room = FHSA_ANNUAL_LIMIT + carry + overage
        new_limits += FHSA_ANNUAL_LIMIT
    remaining = room - by_year[current_year]

    lifetime_left = FHSA_LIFETIME_LIMIT - sum(by_year.values())
    if remaining > lifetime_left:
        # Annual room beyond what the lifetime limit allows can't be used.
        # (Negative means the lifetime limit itself has been exceeded.)
        forfeited += remaining - lifetime_left
        remaining = lifetime_left
    return RoomStatus("FHSA", as_of_year, starting_room, contributions, 0.0, new_limits, remaining, forfeited)
