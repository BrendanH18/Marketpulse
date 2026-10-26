"""Compile native models and check them against an actual offline Python payload."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from marketpulse.brokers import PROFILE_NAMES
from marketpulse.config import Config
from marketpulse.db import Store
from marketpulse.desktop import (
    DemoMarket,
    activity_row,
    archived_accounts,
    demo_snapshot,
    demo_tax,
    storage_info,
    tax_report,
    write_tax_csv,
)
from marketpulse.models import Account, AccountType, Transaction, TxnType
from marketpulse.services import Tracker

root = Path(__file__).resolve().parents[1]
sources = root / "macos/MarketPulseBar/Sources/MarketPulseBar"
if sys.platform != "darwin":
    raise SystemExit("Native bridge checks require macOS and the Swift Command Line Tools.")
with tempfile.TemporaryDirectory(prefix="marketpulse-bridge-") as tmp:
    binary = Path(tmp) / "bridge-check"
    fixture = Path(tmp) / "demo.json"
    fixture.write_text(json.dumps(demo_snapshot(), allow_nan=False))
    demo_tax_report = Path(tmp) / "demo-tax.json"
    demo_tax_report.write_text(json.dumps(demo_tax(), allow_nan=False))
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
    env = {
        **os.environ,
        "MARKETPULSE_DATA": str(Path(tmp) / "data"),
        "MARKETPULSE_CONFIG": str(Path(tmp) / "config.toml"),
    }
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
    # A broker import, previewed after a first import: profile, skipped fields and duplicates.
    import_env = {**env, "MARKETPULSE_DATA": str(Path(tmp) / "import-data")}
    questrade = str(root / "tests/fixtures/brokers/questrade.csv")
    subprocess.run(cli + ["desktop", "import", "--", questrade], env=import_env, capture_output=True, check=True)
    broker_preview = Path(tmp) / "broker-import.json"
    broker_preview.write_bytes(
        subprocess.run(
            cli + ["desktop", "import", "--dry-run", "--profile", "auto", "--", questrade],
            env=import_env,
            capture_output=True,
            check=True,
        ).stdout
    )
    profiles = Path(tmp) / "profiles.json"
    profiles.write_text(json.dumps(PROFILE_NAMES))
    # The real ledger's storage object (the CLI runs above may already have taken a daily backup).
    ledger = Store(Path(tmp) / "data" / "marketpulse.db")
    for reason in ("daily", "pre-restore"):
        ledger.backup(reason=reason)
    storage = Path(tmp) / "storage.json"
    storage.write_text(json.dumps(storage_info(ledger), allow_nan=False))
    # Settings › Data lists archived accounts so they can be unarchived.
    old = ledger.add_account(Account(name="Old RRSP", type=AccountType.RRSP))
    old.archived = True
    ledger.update_account(old)
    archived = Path(tmp) / "archived.json"
    archived.write_text(json.dumps(archived_accounts(ledger.account_map()), allow_nan=False))
    # The Tax workspace: a sale with no FX rate (no amounts), and one in an archived account (never named).
    taxable = ledger.add_account(Account(name="Fictional Taxable"))
    for kind, day, price in [(TxnType.BUY, "2025-01-10", 100), (TxnType.SELL, "2025-04-01", 120)]:
        ledger.add_transaction(
            Transaction(
                account_id=taxable.saved_id,
                type=kind,
                date=day,
                symbol="SAP.DE",
                quantity=2,
                price=price,
                currency="EUR",
            )
        )
    margin = ledger.add_account(Account(name="Old Margin", type=AccountType.MARGIN))
    for kind, day, price in [(TxnType.BUY, "2025-01-06", 15), (TxnType.SELL, "2025-05-01", 16)]:
        ledger.add_transaction(
            Transaction(
                account_id=margin.saved_id,
                type=kind,
                date=day,
                symbol="ZAG.TO",
                quantity=100,
                price=price,
                currency="CAD",
            )
        )
    margin.archived = True
    ledger.update_account(margin)
    offline = Tracker(ledger, DemoMarket(store=ledger), Config())  # no network: EUR has no rate
    ledger_tax = Path(tmp) / "tax.json"
    ledger_tax.write_text(json.dumps(tax_report(offline), allow_nan=False))
    export = Path(tmp) / "tax-export.json"
    export.write_text(json.dumps(write_tax_csv(offline, Path(tmp) / "gains.csv", 2025), allow_nan=False))
    ledger.close()
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
    subprocess.run(
        [
            str(binary),
            str(fixture),
            str(transactions),
            str(receipt),
            str(storage),
            str(archived),
            str(demo_tax_report),
            str(ledger_tax),
            str(export),
            str(root / "tests/fixtures/transaction_forms.json"),
            str(broker_preview),
            str(profiles),
        ],
        check=True,
    )
