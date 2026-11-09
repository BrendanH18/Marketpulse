"""Create a new fictional Windows QA ledger; print its paths as JSON.

Each run creates a fresh temporary folder. Manual CAD assets keep the initial
snapshot offline. Follow docs/qa.md for the Windows app checklist.
"""

from __future__ import annotations

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

from marketpulse.config import Config
from marketpulse.db import Store
from marketpulse.models import Account, AccountType, Asset, AssetKind, Transaction, TxnType


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="marketpulse-windows-qa-"))
    data = root / "data"
    data.mkdir()
    config = root / "config.toml"
    Config(market_strip=[]).save(config)
    store = Store(data / "marketpulse.db")
    try:
        tfsa = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
        cash = store.add_account(Account(name="Fictional cash", track_cash=True))
        archived = store.add_account(Account(name="Archived QA account", type=AccountType.RRSP))
        for symbol in ("QA-FUND", "QA-OLD"):
            store.upsert_asset(Asset(symbol=symbol, kind=AssetKind.MANUAL, name="Fictional manual fund"))
        start = (date.today() - timedelta(days=30)).isoformat()
        rows = [
            Transaction(
                account_id=tfsa.saved_id, type=TxnType.BUY, symbol="QA-FUND", quantity=100, price=10, date=start
            ),
            Transaction(account_id=cash.saved_id, type=TxnType.DEPOSIT, amount=5000, date=start),
            Transaction(
                account_id=cash.saved_id, type=TxnType.BUY, symbol="QA-FUND", quantity=10, price=10, date=start
            ),
            Transaction(account_id=cash.saved_id, type=TxnType.SELL, symbol="QA-FUND", quantity=2, price=12),
            Transaction(account_id=tfsa.saved_id, type=TxnType.DIVIDEND, symbol="QA-FUND", amount=25),
            Transaction(account_id=cash.saved_id, type=TxnType.FEE, amount=3),
            Transaction(account_id=archived.saved_id, type=TxnType.BUY, symbol="QA-OLD", quantity=1, price=500),
        ]
        for row in rows:
            row.currency = "CAD"
            store.add_transaction(row)
        archived.archived = True
        store.update_account(archived)
    finally:
        store.close()
    csv_path = root / "sample-import.csv"
    csv_path.write_text(
        "date,account,type,symbol,quantity,price,currency,amount\n"
        f"{date.today()},Fictional TFSA,BUY,QA-FUND,2,10,CAD,\n"
        f"{date.today()},Archived QA account,BUY,QA-OLD,1,10,CAD,\n"
        "2024-13-40,Fictional TFSA,BUY,QA-FUND,1,10,CAD,\n",
        encoding="utf-8",
    )
    print(json.dumps({"root": str(root), "data": str(data), "config": str(config), "csv": str(csv_path)}))


if __name__ == "__main__":
    main()
