"""Compile native models and check them against an actual offline Python payload."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

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
    # Exercise the actual receipt CLI on an isolated fictional ledger, with no quotes needed.
    request_id = str(uuid4())
    env = {**os.environ, "MARKETPULSE_DATA": str(Path(tmp) / "data"), "MARKETPULSE_CONFIG": str(Path(tmp) / "config.toml")}
    cli = [sys.executable, "-c", "from marketpulse.cli import main; main()"]
    subprocess.run(
        cli + ["deposit", "--request-id", request_id, "--currency", "CAD", "--", "12.5"],
        env=env,
        capture_output=True,
        check=True,
    )
    receipt = Path(tmp) / "receipt.json"
    receipt.write_bytes(
        subprocess.run(
            cli + ["desktop", "transaction-status", request_id], env=env, capture_output=True, check=True
        ).stdout
    )
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
    subprocess.run([str(binary), str(fixture), str(transactions), str(receipt)], check=True)
