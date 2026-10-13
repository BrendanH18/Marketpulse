"""Compile native models and check them against an actual offline Python payload."""

import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from marketpulse.desktop import demo_snapshot
from marketpulse.models import Transaction, TxnType

root = Path(__file__).resolve().parents[1]
sources = root / "macos/MarketPulseBar/Sources/MarketPulseBar"
if sys.platform != "darwin":
    raise SystemExit("Native bridge checks require macOS and the Swift Command Line Tools.")
with tempfile.TemporaryDirectory(prefix="marketpulse-bridge-") as tmp:
    binary = Path(tmp) / "bridge-check"
    fixture = Path(tmp) / "demo.json"
    fixture.write_text(json.dumps(demo_snapshot(), allow_nan=False))
    transactions = Path(tmp) / "transactions.json"
    rows = []
    for kind in TxnType:
        txn = Transaction(id=1, account_id=1, type=kind, symbol="AAPL", quantity=3, price=12, amount=7, currency="USD")
        rows.append({"transaction": asdict(txn), "expected_value": txn.gross_value})
    transactions.write_text(json.dumps(rows, allow_nan=False))
    subprocess.run(
        [
            "swiftc",
            str(sources / "Models.swift"),
            str(sources / "DesktopModels.swift"),
            str(root / "scripts/check_native_bridge.swift"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    subprocess.run([str(binary), str(fixture), str(transactions)], check=True)
