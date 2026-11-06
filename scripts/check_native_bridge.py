"""Compile native models and check them against an actual offline Python payload."""

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from marketpulse.brokers import PROFILE_NAMES
from marketpulse.config import Config
from marketpulse.db import Store
from marketpulse.desktop import (
    BACKUP_REASON_LABELS,
    DemoMarket,
    activity_row,
    archived_accounts,
    demo_snapshot,
    demo_tax,
    snapshot,
    storage_info,
    tax_report,
    write_tax_csv,
)
from marketpulse.models import Account, AccountType, Alert, AssetClass, Transaction, TxnType
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
    asset_classes = Path(tmp) / "asset-classes.json"
    asset_classes.write_text(json.dumps([[c.value, c.label] for c in AssetClass]))
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
    # Every coded warning and tax issue, on a fictional ledger: the app's English must match the engine's.
    (Path(tmp) / "coded").mkdir()
    coded = Store(Path(tmp) / "coded" / "marketpulse.db")
    cash = coded.add_account(Account(name="Fictional Cash", track_cash=True))
    tfsa = coded.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
    gone = coded.add_account(Account(name="Fictional Old", track_cash=True))

    def add(account: Account, kind: TxnType, day: str, symbol: str = "", qty: float = 0, **kw: object) -> None:
        coded.add_transaction(
            Transaction(
                account_id=account.saved_id, type=kind, date=day, symbol=symbol, quantity=qty, currency="CAD", **kw
            )  # type: ignore[arg-type]
        )

    add(cash, TxnType.BUY, "2025-01-02", "XEQT.TO", 1234.5, price=30)
    add(cash, TxnType.SELL, "2025-01-03", "XEQT.TO", 2000, price=31)
    add(cash, TxnType.SPLIT, "2025-01-04", "VFV.TO", ratio=2)
    add(cash, TxnType.TRANSFER, "2025-01-05", "ZAG.TO", 1, target_account_id=tfsa.saved_id)
    add(cash, TxnType.BUY, "2025-01-06", "VCN.TO", 2, price=40)
    add(cash, TxnType.TRANSFER, "2025-01-07", "VCN.TO", 3, target_account_id=tfsa.saved_id)
    add(tfsa, TxnType.BUY, "2025-01-08", "AAPL", 1, price=100)
    add(tfsa, TxnType.TRANSFER, "2025-01-09", "AAPL", 1, target_account_id=cash.saved_id)
    add(cash, TxnType.BUY, "2025-01-10", "NOPRICE", 1, price=10)
    coded.add_transaction(
        Transaction(account_id=cash.saved_id, type=TxnType.DEPOSIT, date="2025-01-11", amount=50, currency="EUR")
    )
    add(gone, TxnType.BUY, "2025-01-12", "GONE", 1, price=5)
    coded.add_transaction(
        Transaction(account_id=gone.saved_id, type=TxnType.DEPOSIT, date="2025-01-13", amount=5, currency="EUR")
    )
    gone.archived = True
    coded.update_account(gone)
    coded_tracker = Tracker(coded, DemoMarket(store=coded), Config())
    coded_snapshot = Path(tmp) / "coded-snapshot.json"
    coded_snapshot.write_text(json.dumps(snapshot(coded_tracker), allow_nan=False))
    coded_tax = Path(tmp) / "coded-tax.json"
    coded_tax.write_text(json.dumps(tax_report(coded_tracker), allow_nan=False))
    coded.close()
    # A generic CSV with a row for each import reason the engine codes.
    bad_rows = Path(tmp) / "bad-rows.csv"
    bad_rows.write_text(
        "date,type,symbol,quantity,price,amount,fees,account\n"
        "2025-01-02,BUY,AAPL,1,2x,,,Fictional Cash\n"
        "2025-13-01,BUY,AAPL,1,10,,,Fictional Cash\n"
        "03-04-2025,BUY,AAPL,1,10,,,Fictional Cash\n"
        "2025-01-02,Mystery,AAPL,1,10,,,Fictional Cash\n"
        "2025-01-02,BUY,AAPL,0,10,,,Fictional Cash\n"
        "2025-01-02,DIVIDEND,,,,5,,Fictional Cash\n"
        "2025-01-02,DIVIDEND,AAPL,,,,,Fictional Cash\n"
        "2025-01-02,BUY,AAPL,1,10,,,Old Fictional\n"
        "2999-01-02,BUY,AAPL,1,10,,,Fictional Cash\n"
        "2025-01-02,SPLIT,AAPL,,,,,Fictional Cash\n"
        "2025-01-02,BUY,AAPL,1,10,,,Fictional Cash\n"
    )
    import_env = {**env, "MARKETPULSE_DATA": str(Path(tmp) / "bad-rows-data")}
    for args in (["accounts", "add", "Fictional Cash"], ["accounts", "add", "Old Fictional"]):
        subprocess.run(cli + args, env=import_env, capture_output=True, check=True)
    subprocess.run(
        cli + ["accounts", "edit", "--archive", "--", "Old Fictional"], env=import_env, capture_output=True, check=True
    )
    bad_preview = Path(tmp) / "bad-rows.json"
    bad_preview.write_bytes(
        subprocess.run(
            cli + ["desktop", "import", "--dry-run", "--", str(bad_rows)],
            env=import_env,
            capture_output=True,
            check=True,
        ).stdout
    )
    backup_labels = Path(tmp) / "backup-labels.json"
    backup_labels.write_text(json.dumps(BACKUP_REASON_LABELS))
    alerts = Path(tmp) / "alerts.json"
    alerts.write_text(
        json.dumps(
            [
                {**asdict(a), "description": a.describe()}
                for a in [
                    Alert("XEQT.TO", "above", 1234.5, id=1),
                    Alert("XEQT.TO", "below", 30, id=2),
                    Alert("AAPL", "up_pct", 2.5, id=3),
                    Alert("AAPL", "down_pct", 5, id=4),
                ]
            ]
        )
    )
    subprocess.run(
        [
            "swiftc",
            str(sources / "Models.swift"),
            str(sources / "DesktopModels.swift"),
            str(sources / "Localization.swift"),
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
            str(root / "tests/fixtures/asset_forms.json"),
            str(asset_classes),
            str(coded_snapshot),
            str(coded_tax),
            str(bad_preview),
            str(backup_labels),
            str(alerts),
            # Foundation reads these: the expectations are English, whatever this Mac's region.
            "-AppleLanguages",
            "(en)",
            "-AppleLocale",
            "en_US",
        ],
        check=True,
    )
