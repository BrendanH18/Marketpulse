"""Data models for MarketPulse."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Quote:
    ticker: str
    name: str
    price: float
    prev_close: float
    day_high: float
    day_low: float
    volume: int
    market_cap: Optional[float]
    currency: str
    exchange: str
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None
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
class Position:
    ticker: str
    shares: float
    avg_cost: float  # per share, in portfolio currency
    note: str = ""

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

    def add_position(self, ticker: str, shares: float, avg_cost: float, note: str = "") -> tuple[Position, bool]:
        """Add a new position or blend into an existing one (averages the cost).

        Returns (position, blended) where blended is True if an existing
        position was averaged with the new lot.
        """
        ticker = ticker.upper()
        existing = self.positions.get(ticker)
        if existing:
            old_book = existing.shares * existing.avg_cost
            new_book = shares * avg_cost
            total_shares = existing.shares + shares
            new_avg = (old_book + new_book) / total_shares if total_shares else avg_cost
            pos = Position(ticker=ticker, shares=total_shares, avg_cost=new_avg, note=note or existing.note)
            self.positions[ticker] = pos
            return pos, True
        pos = Position(ticker=ticker, shares=shares, avg_cost=avg_cost, note=note)
        self.positions[ticker] = pos
        return pos, False
