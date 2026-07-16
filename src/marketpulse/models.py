"""Data models for MarketPulse."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

TxnAction = Literal["BUY", "SELL"]

# Tolerance for float share arithmetic (fractional shares accumulate error)
_SHARE_EPSILON = 1e-9


def parse_tickers(raw: str) -> list[str]:
    """Split user input into upper-cased, de-duplicated tickers."""
    seen = set()
    return [t.upper() for t in raw.replace(",", " ").split() if not (t.upper() in seen or seen.add(t.upper()))]


def _today() -> str:
    return datetime.now().date().isoformat()


@dataclass
class Quote:
    ticker: str
    name: str
    price: float
    prev_close: float
    day_high: float
    day_low: float
    volume: int
    market_cap: float | None
    currency: str
    exchange: str
    week52_high: float | None = None
    week52_low: float | None = None
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def change(self) -> float:
        return self.price - self.prev_close

    @property
    def change_pct(self) -> float:
        if self.prev_close == 0:
            return 0.0
        return (self.change / self.prev_close) * 100

    @property
    def is_up(self) -> bool:
        return self.change >= 0


@dataclass
class Transaction:
    ticker: str
    action: TxnAction
    shares: float
    price: float  # per share, in the position's native currency
    date: str = field(default_factory=_today)  # ISO 8601
    fees: float = 0.0
    currency: str = ""  # "" = assume portfolio base currency
    note: str = ""

    @property
    def gross_value(self) -> float:
        return self.shares * self.price


@dataclass
class FxRates:
    """Spot FX rates for converting amounts into a base currency.

    rates maps currency -> base units per 1 unit of that currency.
    """

    base: str
    rates: dict[str, float] = field(default_factory=dict)

    def rate(self, currency: str) -> float | None:
        if not currency or currency == self.base:
            return 1.0
        return self.rates.get(currency)

    def convert(self, amount: float, currency: str) -> float | None:
        r = self.rate(currency)
        return None if r is None else amount * r


@dataclass
class Position:
    ticker: str
    shares: float
    avg_cost: float  # per share, in the position's native currency
    note: str = ""
    currency: str = ""  # "" = unknown/legacy; display falls back to live quote

    @property
    def book_value(self) -> float:
        return self.shares * self.avg_cost

    def market_value(self, current_price: float) -> float:
        return self.shares * current_price

    def gain_loss(self, current_price: float) -> float:
        return self.market_value(current_price) - self.book_value

    def gain_loss_pct(self, current_price: float) -> float:
        if self.book_value == 0:
            return 0.0
        return (self.gain_loss(current_price) / self.book_value) * 100


@dataclass
class Portfolio:
    name: str
    positions: dict[str, Position] = field(default_factory=dict)
    watchlist: list[str] = field(default_factory=list)
    currency: str = "CAD"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    transactions: list[Transaction] = field(default_factory=list)

    def buy(
        self,
        ticker: str,
        shares: float,
        price: float,
        *,
        fees: float = 0.0,
        date: str | None = None,
        currency: str = "",
        note: str = "",
    ) -> tuple[Position, bool]:
        """Record a buy: append a transaction and blend it into the position.

        Fees are folded into the average cost base (CRA-consistent).
        Returns (position, blended) where blended is True if an existing
        position was averaged with the new lot.
        """
        if shares <= 0:
            raise ValueError("Shares must be positive.")
        if price < 0:
            raise ValueError("Price cannot be negative.")
        ticker = ticker.upper()
        self.transactions.append(
            Transaction(
                ticker=ticker,
                action="BUY",
                shares=shares,
                price=price,
                date=date or _today(),
                fees=fees,
                currency=currency,
                note=note,
            )
        )
        new_book = shares * price + fees
        existing = self.positions.get(ticker)
        if existing:
            old_book = existing.shares * existing.avg_cost
            total_shares = existing.shares + shares
            new_avg = (old_book + new_book) / total_shares if total_shares else price
            pos = Position(
                ticker=ticker,
                shares=total_shares,
                avg_cost=new_avg,
                note=note or existing.note,
                currency=currency or existing.currency,
            )
            self.positions[ticker] = pos
            return pos, True
        pos = Position(
            ticker=ticker,
            shares=shares,
            avg_cost=new_book / shares,
            note=note,
            currency=currency,
        )
        self.positions[ticker] = pos
        return pos, False

    def sell(
        self,
        ticker: str,
        shares: float,
        price: float,
        *,
        fees: float = 0.0,
        date: str | None = None,
        note: str = "",
    ) -> tuple[float, Position | None]:
        """Record a sell using the average-cost method.

        Realized gain = shares * (price - avg_cost) - fees; avg cost is
        unchanged on the remaining shares. Selling all shares closes the
        position (the realized P&L stays in the ledger).
        Returns (realized_gain, remaining_position_or_None).
        Raises ValueError if the ticker isn't held or shares exceed the holding.
        """
        if shares <= 0:
            raise ValueError("Shares must be positive.")
        ticker = ticker.upper()
        existing = self.positions.get(ticker)
        if existing is None:
            raise ValueError(f"No position in {ticker}.")
        if shares > existing.shares + _SHARE_EPSILON:
            raise ValueError(f"Cannot sell {shares:,.4f} {ticker} — only {existing.shares:,.4f} held.")
        self.transactions.append(
            Transaction(
                ticker=ticker,
                action="SELL",
                shares=shares,
                price=price,
                date=date or _today(),
                fees=fees,
                currency=existing.currency,
                note=note,
            )
        )
        realized = shares * (price - existing.avg_cost) - fees
        remaining = existing.shares - shares
        if remaining <= _SHARE_EPSILON:
            del self.positions[ticker]
            return realized, None
        pos = Position(
            ticker=ticker,
            shares=remaining,
            avg_cost=existing.avg_cost,
            note=existing.note,
            currency=existing.currency,
        )
        self.positions[ticker] = pos
        return realized, pos

    def realized_pnl(self) -> dict[str, float]:
        """Replay the ledger and return realized P&L per currency.

        Uses the average-cost method per ticker. Transactions with no
        currency are attributed to the portfolio base currency.
        """
        holdings: dict[str, tuple[float, float]] = {}  # ticker -> (shares, avg_cost)
        realized: dict[str, float] = {}
        for txn in self.transactions:
            shares, avg = holdings.get(txn.ticker, (0.0, 0.0))
            if txn.action == "BUY":
                book = shares * avg + txn.gross_value + txn.fees
                shares += txn.shares
                holdings[txn.ticker] = (shares, book / shares if shares else 0.0)
            else:
                ccy = txn.currency or self.currency
                gain = txn.shares * (txn.price - avg) - txn.fees
                realized[ccy] = realized.get(ccy, 0.0) + gain
                holdings[txn.ticker] = (max(shares - txn.shares, 0.0), avg)
        return realized

    def add_position(self, ticker: str, shares: float, avg_cost: float, note: str = "") -> tuple[Position, bool]:
        """Add a lot at a given cost. Thin wrapper over buy() kept for the
        setup wizard and older call sites; records a BUY transaction."""
        return self.buy(ticker, shares, avg_cost, note=note)
