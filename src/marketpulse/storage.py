"""Persistent storage for portfolios using JSON."""
import json
import os
from pathlib import Path

from .models import Portfolio, Position, Transaction


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
        "schema": 2,
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
                "currency": pos.currency,
            }
            for ticker, pos in portfolio.positions.items()
        },
        "transactions": [
            {
                "ticker": txn.ticker,
                "action": txn.action,
                "shares": txn.shares,
                "price": txn.price,
                "date": txn.date,
                "fees": txn.fees,
                "currency": txn.currency,
                "note": txn.note,
            }
            for txn in portfolio.transactions
        ],
    }
    # Write atomically: a crash mid-write must not corrupt the portfolio file
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def load_portfolio(name: str) -> Portfolio | None:
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
            currency=pos.get("currency", ""),
        )
        for ticker, pos in data.get("positions", {}).items()
    }
    transactions = [
        Transaction(
            ticker=txn["ticker"],
            action=txn["action"],
            shares=txn["shares"],
            price=txn["price"],
            date=txn.get("date", ""),
            fees=txn.get("fees", 0.0),
            currency=txn.get("currency", ""),
            note=txn.get("note", ""),
        )
        for txn in data.get("transactions", [])
    ]
    if not transactions and positions:
        # Legacy (schema 1) file: synthesize an opening BUY per position so
        # replaying the ledger reproduces the current holdings. Written back
        # to disk only on the next natural save.
        transactions = [
            Transaction(
                ticker=pos.ticker,
                action="BUY",
                shares=pos.shares,
                price=pos.avg_cost,
                date=data.get("created_at", ""),
                currency=pos.currency,
                note="opening balance (migrated)",
            )
            for pos in positions.values()
        ]
    return Portfolio(
        name=data["name"],
        currency=data.get("currency", "CAD"),
        created_at=data.get("created_at", ""),
        watchlist=data.get("watchlist", []),
        positions=positions,
        transactions=transactions,
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
