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
