"""Render the README preview from the real TUI using isolated, fictional data.

Run with `uv run --locked python scripts/render_preview.py` (dev dependencies required).
Uses the test suite's fake transport; no market requests or real portfolio reads.
"""

from __future__ import annotations

import asyncio
import math
import os
import runpy
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from marketpulse.config import Config
from marketpulse.db import Snapshot, Store
from marketpulse.market import MarketData
from marketpulse.models import Account, AccountType, Transaction, TxnType
from marketpulse.services import Tracker
from marketpulse.tui.app import MarketPulseApp

ROOT = Path(__file__).resolve().parents[1]


async def render() -> None:
    # The harness may disable terminal colors; the preview should show the actual palette.
    os.environ.pop("NO_COLOR", None)
    os.environ["TERM"] = "xterm-256color"
    os.environ["COLORTERM"] = "truecolor"
    fake_transport = runpy.run_path(str(ROOT / "tests" / "conftest.py"))["FakeTransport"]
    with tempfile.TemporaryDirectory(prefix="marketpulse-preview-") as directory:
        os.environ["MARKETPULSE_DATA"] = directory
        os.environ["MARKETPULSE_CONFIG"] = str(Path(directory) / "config.toml")
        fake = fake_transport()
        for symbol, price, previous, currency, name, instrument in [
            ("XEQT.TO", 40.25, 39.82, "CAD", "iShares Core Equity ETF", "ETF"),
            ("VFV.TO", 142.10, 140.96, "CAD", "Vanguard S&P 500 Index ETF", "ETF"),
            ("AAPL", 225.40, 227.12, "USD", "Apple Inc.", "EQUITY"),
            ("NVDA", 184.20, 181.80, "USD", "NVIDIA Corporation", "EQUITY"),
            ("USDCAD=X", 1.36, 1.355, "CAD", "USD/CAD", "CURRENCY"),
            ("^GSPC", 6450.25, 6418.42, "USD", "S&P 500", "INDEX"),
            ("^IXIC", 21820.30, 21692.15, "USD", "Nasdaq", "INDEX"),
            ("^GSPTSE", 28360.80, 28280.30, "CAD", "TSX", "INDEX"),
            ("BTC-USD", 98240.50, 96820.40, "USD", "Bitcoin", "CRYPTOCURRENCY"),
        ]:
            fake.set_quote(symbol, price, previous, currency, name, instrument)
        today = date.today()
        for symbol, price in [("XEQT.TO", 40.25), ("VFV.TO", 142.10), ("AAPL", 225.40), ("NVDA", 184.20)]:
            fake.set_history(
                symbol,
                {
                    (today - timedelta(days=90 - i)).isoformat(): price * (0.85 + i / 600 + math.sin(i / 7) * 0.02)
                    for i in range(91)
                },
                "CAD" if symbol.endswith(".TO") else "USD",
            )
        store = Store(Path(directory) / "preview.db")
        try:
            tfsa = store.add_account(Account(name="Demo TFSA", type=AccountType.TFSA))
            rrsp = store.add_account(Account(name="Demo RRSP", type=AccountType.RRSP))
            taxable = store.add_account(Account(name="Demo Taxable", type=AccountType.NONREG))
            for account, symbol, quantity, price, currency in [
                (tfsa, "XEQT.TO", 800, 30, "CAD"),
                (rrsp, "VFV.TO", 200, 110, "CAD"),
                (taxable, "AAPL", 50, 175, "USD"),
                (taxable, "NVDA", 30, 130, "USD"),
            ]:
                store.add_transaction(
                    Transaction(
                        account_id=account.saved_id,
                        type=TxnType.BUY,
                        date="2024-01-03",
                        symbol=symbol,
                        quantity=quantity,
                        price=price,
                        currency=currency,
                    )
                )
            store.add_transaction(
                Transaction(
                    account_id=tfsa.saved_id,
                    type=TxnType.DIVIDEND,
                    date=today.replace(day=1).isoformat(),
                    symbol="XEQT.TO",
                    amount=182.40,
                    currency="CAD",
                )
            )
            store.add_watch(["XEQT.TO", "VFV.TO", "AAPL", "NVDA", "BTC-USD"])
            for i in range(91):
                store.upsert_snapshot(
                    Snapshot(
                        date=(today - timedelta(days=90 - i)).isoformat(),
                        net_worth=69500 + i * 145 + math.sin(i / 6) * 580,
                        book=63210,
                        contributions=63210,
                        currency="CAD",
                        detail={},
                    )
                )
            config = Config(theme="tokyo-night", market_strip=["^GSPC", "^IXIC", "^GSPTSE", "USDCAD=X", "BTC-USD"])
            tracker = Tracker(store, MarketData(transport=fake, store=store), config)
            with patch("marketpulse.alerts.notify", return_value=True):
                app = MarketPulseApp(config, tracker=tracker)
                async with app.run_test(size=(150, 43)) as pilot:
                    await app.workers.wait_for_complete()
                    await pilot.pause()
                    output = ROOT / "docs" / "assets" / "dashboard.svg"
                    output.parent.mkdir(parents=True, exist_ok=True)
                    svg = app.export_screenshot(title="MarketPulse · sample portfolio")
                    # Explicit dimensions also make standalone image rendering consistent.
                    _, _, width, height = ElementTree.fromstring(svg).attrib["viewBox"].split()
                    svg = svg.replace("<svg ", f'<svg width="{width}" height="{height}" ', 1)
                    output.write_text(svg, encoding="utf-8")
                    print(f"Rendered {output}")
        finally:
            store.close()


if __name__ == "__main__":
    asyncio.run(render())
