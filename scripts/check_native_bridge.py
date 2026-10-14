"""Compile native models and check them against an actual offline Python payload."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from marketpulse.desktop import activity_row, demo_snapshot
from marketpulse.models import Account, Transaction, TxnType

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
    target = {2: Account(name="RRSP", id=2)}
    for kind in TxnType:
        txn = Transaction(
            id=1, account_id=1, type=kind, symbol="AAPL", quantity=3, price=12, amount=7, currency="USD", ratio=2
        )
        if kind is TxnType.TRANSFER:
            txn.target_account_id = 2
        signed = txn.cash_direction * txn.gross_value if txn.cash_direction else txn.gross_value
        rows.append({"transaction": activity_row(txn, target), "expected_signed_value": signed})
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
