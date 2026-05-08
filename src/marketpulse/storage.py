"""Persistent storage for portfolios using JSON."""
import json
import os
from pathlib import Path
from typing import Optional
from .models import Portfolio, Position


def _data_dir() -> Path:
    """Return the MarketPulse data directory, creating it if needed."""
    base = Path(os.environ.get("MARKETPULSE_DATA", Path.home() / ".marketpulse"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _portfolio_path(name: str) -> Path:
    return _data_dir() / f"{name}.json"


def save_portfolio(portfolio: Portfolio) -> None:
    path = _portfolio_path(portfolio.name)
    data = {
        "name": portfolio.name,
        "currency": portfolio.currency,
        "created_at": portfolio.created_at,
        "watchlist": portfolio.watchlist,
        "positions": {
            ticker: {
                "ticker": pos.ticker,
                "shares": pos.shares,
                "avg_cost": pos.avg_cost,
                "note": pos.note,
            }
            for ticker, pos in portfolio.positions.items()
        },
    }
    path.write_text(json.dumps(data, indent=2))


def load_portfolio(name: str) -> Optional[Portfolio]:
    path = _portfolio_path(name)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    positions = {
        ticker: Position(
            ticker=pos["ticker"],
            shares=pos["shares"],
            avg_cost=pos["avg_cost"],
            note=pos.get("note", ""),
        )
        for ticker, pos in data.get("positions", {}).items()
    }
    return Portfolio(
        name=data["name"],
        currency=data.get("currency", "CAD"),
        created_at=data.get("created_at", ""),
        watchlist=data.get("watchlist", []),
        positions=positions,
    )


def list_portfolios() -> list[str]:
    return [p.stem for p in _data_dir().glob("*.json")]


def delete_portfolio(name: str) -> bool:
    path = _portfolio_path(name)
    if path.exists():
        path.unlink()
        return True
    return False


def get_or_create_portfolio(name: str, currency: str = "CAD") -> Portfolio:
    p = load_portfolio(name)
    if p is None:
        p = Portfolio(name=name, currency=currency)
        save_portfolio(p)
    return p
