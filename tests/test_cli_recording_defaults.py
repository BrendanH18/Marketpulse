"""Plain recording commands print and save exactly what they did before #130 (items 1–20 are opt-in)."""

import json
from dataclasses import asdict
from datetime import date

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType

SCRIPT = [
    ["deposit", "5000", "-a", "Maple Cash", "-d", "2025-01-02", "-m", "seed"],
    ["buy", "XEQT.TO", "10", "40", "-a", "Maple Cash", "-d", "2025-01-06", "-f", "4.95", "-m", "first lot"],
    ["buy", "AAPL", "2", "150", "-a", "Maple Cash", "-d", "2025-01-07", "-c", "usd"],
    ["dividend", "xeqt.to", "12.5", "-a", "Maple Cash", "-d", "2025-01-31"],
    ["drip", "XEQT.TO", "0.5", "41", "-a", "Maple Cash", "-d", "2025-02-01"],
    ["interest", "3.21", "-a", "Maple Cash", "-d", "2025-02-02"],
    ["sell", "XEQT.TO", "4", "45", "-a", "Maple Cash", "-d", "2025-02-03", "-f", "1"],
    ["roc", "XEQT.TO", "5", "-a", "Maple Cash", "-d", "2025-02-04"],
    ["split", "XEQT.TO", "2", "-a", "Maple Cash", "-d", "2025-02-05"],
    ["fee", "9.99", "-a", "Maple Cash", "-d", "2025-02-06"],
    ["withdraw", "100", "-a", "Maple Cash", "-d", "2025-02-07"],
    ["transfer", "XEQT.TO", "2", "--from", "Maple Cash", "--to", "Maple TFSA", "-p", "42", "-d", "2025-02-10"],
    ["sell", "XEQT.TO", "10.5", "44", "-a", "Maple Cash", "-d", "2025-02-11"],
    ["buy", "XEQT.TO", "1", "-a", "Maple TFSA"],
    ["sell", "XEQT.TO", "abc", "-a", "Maple TFSA"],
    ["drip", "XEQT.TO", "1", "-a", "Maple TFSA"],
    ["split", "XEQT.TO", "x", "-a", "Maple TFSA"],
    ["sell", "XEQT.TO", "99", "40", "-a", "Maple TFSA"],
    ["roc", "VFV.TO", "3", "-a", "Maple Cash", "-d", "2025-02-12", "-c", "CAD"],
    ["transfer", "AAPL", "1", "--from", "Maple Cash", "--to", "Maple TFSA", "-d", "2025-02-13"],
    ["deposit", "250", "-a", "TFSA", "--request-id", "11111111-2222-3333-4444-555555555555"],
    ["buy", "XEQT.TO", "1", "40", "-a", "TFSA", "--request-id", "21111111-2222-3333-4444-555555555555"],
    ["buy", "XEQT.TO", "1", "40", "-a", "TFSA", "--request-id", "21111111-2222-3333-4444-555555555555"],
]

# Captured from the commands before any #130 change; a plain command must keep printing exactly this
# (today's date shown as "TODAY").
EXPECTED_OUTPUT = [
    (0, "✓ Deposit 5,000.00 CAD → Maple Cash on 2025-01-02\n"),
    (0, "✓ Bought 10 XEQT.TO @ 40.00 CAD in Maple Cash · now 10 @ avg 40.49\n"),
    (0, "✓ Bought 2 AAPL @ 150.00 USD in Maple Cash · now 2 @ avg 150.00\n"),
    (0, "✓ Dividend 12.50 CAD from XEQT.TO → Maple Cash on 2025-01-31\n"),
    (0, "✓ DRIP 0.5 XEQT.TO @ 41.00 CAD in Maple Cash\n"),
    (0, "✓ Interest 3.21 CAD → Maple Cash on 2025-02-02\n"),
    (0, "✓ Sold 4 XEQT.TO @ 45.00 CAD in Maple Cash — realized +16.92 CAD · now 6.5 @ avg 40.52\n"),
    (0, "✓ Return of capital 5.00 CAD on XEQT.TO in Maple Cash on 2025-02-04 · cost base now 258.37 CAD\n"),
    (0, "✓ Split XEQT.TO ×2 in Maple Cash\n"),
    (0, "✓ Fee 9.99 CAD → Maple Cash on 2025-02-06\n"),
    (0, "✓ Withdrawal 100.00 CAD → Maple Cash on 2025-02-07\n"),
    (0, "✓ Transferred 2 XEQT.TO Maple Cash → Maple TFSA\n"),
    (0, "✓ Sold 10.5 XEQT.TO @ 44.00 CAD in Maple Cash — realized +253.31 CAD · now 0.5 @ avg 19.87\n"),
    (0, "✓ Bought 1 XEQT.TO @ 40.00 CAD in Maple TFSA · now 3 @ avg 26.58\n"),
    (
        2,
        "Usage: main sell [OPTIONS] SYMBOL QUANTITY [PRICE]\nTry 'main sell --help' for help.\n\n"
        "Error: Invalid value for 'QUANTITY': 'abc' is not a valid float.\n",
    ),
    (
        2,
        "Usage: main drip [OPTIONS] SYMBOL QUANTITY PRICE\nTry 'main drip --help' for help.\n\n"
        "Error: Missing argument 'PRICE'.\n",
    ),
    (
        2,
        "Usage: main split [OPTIONS] SYMBOL RATIO\nTry 'main split --help' for help.\n\n"
        "Error: Invalid value for 'RATIO': 'x' is not a valid float.\n",
    ),
    (1, "Error: Cannot sell 99 XEQT.TO — only 3 held in this account.\n"),
    (
        0,
        "✓ Return of capital 3.00 CAD on VFV.TO in Maple Cash on 2025-02-12\n"
        "! Maple Cash holds no VFV.TO now; a return of capital only lowers the cost of shares held on its date\n",
    ),
    (
        0,
        "! no --price given: the tax report will ask for this transfer's market value\n"
        "✓ Transferred 1 AAPL Maple Cash → Maple TFSA\n",
    ),
    (0, "✓ Deposit 250.00 CAD → Maple TFSA on TODAY\n"),
    (0, "✓ Bought 1 XEQT.TO @ 40.00 CAD in Maple TFSA · now 4 @ avg 29.94\n"),
    (0, "✓ Transaction already recorded (#18).\n"),
]

# The rows those commands saved, by id (today's date shown as "TODAY").
EXPECTED_ROWS = [
    {
        "account_id": 1,
        "type": "DEPOSIT",
        "date": "2025-01-02",
        "symbol": "",
        "quantity": 0.0,
        "price": 0.0,
        "amount": 5000.0,
        "fees": 0.0,
        "currency": "CAD",
        "note": "seed",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 1,
    },
    {
        "account_id": 1,
        "type": "BUY",
        "date": "2025-01-06",
        "symbol": "XEQT.TO",
        "quantity": 10.0,
        "price": 40.0,
        "amount": 0.0,
        "fees": 4.95,
        "currency": "CAD",
        "note": "first lot",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 2,
    },
    {
        "account_id": 1,
        "type": "BUY",
        "date": "2025-01-07",
        "symbol": "AAPL",
        "quantity": 2.0,
        "price": 150.0,
        "amount": 0.0,
        "fees": 0.0,
        "currency": "USD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 3,
    },
    {
        "account_id": 1,
        "type": "DIVIDEND",
        "date": "2025-01-31",
        "symbol": "XEQT.TO",
        "quantity": 0.0,
        "price": 0.0,
        "amount": 12.5,
        "fees": 0.0,
        "currency": "CAD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 4,
    },
    {
        "account_id": 1,
        "type": "DRIP",
        "date": "2025-02-01",
        "symbol": "XEQT.TO",
        "quantity": 0.5,
        "price": 41.0,
        "amount": 0.0,
        "fees": 0.0,
        "currency": "CAD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 5,
    },
    {
        "account_id": 1,
        "type": "INTEREST",
        "date": "2025-02-02",
        "symbol": "",
        "quantity": 0.0,
        "price": 0.0,
        "amount": 3.21,
        "fees": 0.0,
        "currency": "CAD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 6,
    },
    {
        "account_id": 1,
        "type": "SELL",
        "date": "2025-02-03",
        "symbol": "XEQT.TO",
        "quantity": 4.0,
        "price": 45.0,
        "amount": 0.0,
        "fees": 1.0,
        "currency": "CAD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 7,
    },
    {
        "account_id": 1,
        "type": "ROC",
        "date": "2025-02-04",
        "symbol": "XEQT.TO",
        "quantity": 0.0,
        "price": 0.0,
        "amount": 5.0,
        "fees": 0.0,
        "currency": "CAD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 8,
    },
    {
        "account_id": 1,
        "type": "SPLIT",
        "date": "2025-02-05",
        "symbol": "XEQT.TO",
        "quantity": 0.0,
        "price": 0.0,
        "amount": 0.0,
        "fees": 0.0,
        "currency": "CAD",
        "note": "",
        "ratio": 2.0,
        "target_account_id": None,
        "id": 9,
    },
    {
        "account_id": 1,
        "type": "FEE",
        "date": "2025-02-06",
        "symbol": "",
        "quantity": 0.0,
        "price": 0.0,
        "amount": 9.99,
        "fees": 0.0,
        "currency": "CAD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 10,
    },
    {
        "account_id": 1,
        "type": "WITHDRAWAL",
        "date": "2025-02-07",
        "symbol": "",
        "quantity": 0.0,
        "price": 0.0,
        "amount": 100.0,
        "fees": 0.0,
        "currency": "CAD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 11,
    },
    {
        "account_id": 1,
        "type": "TRANSFER",
        "date": "2025-02-10",
        "symbol": "XEQT.TO",
        "quantity": 2.0,
        "price": 42.0,
        "amount": 0.0,
        "fees": 0.0,
        "currency": "CAD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": 2,
        "id": 12,
    },
    {
        "account_id": 1,
        "type": "SELL",
        "date": "2025-02-11",
        "symbol": "XEQT.TO",
        "quantity": 10.5,
        "price": 44.0,
        "amount": 0.0,
        "fees": 0.0,
        "currency": "CAD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 13,
    },
    {
        "account_id": 2,
        "type": "BUY",
        "date": "TODAY",
        "symbol": "XEQT.TO",
        "quantity": 1.0,
        "price": 40.0,
        "amount": 0.0,
        "fees": 0.0,
        "currency": "CAD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 14,
    },
    {
        "account_id": 1,
        "type": "ROC",
        "date": "2025-02-12",
        "symbol": "VFV.TO",
        "quantity": 0.0,
        "price": 0.0,
        "amount": 3.0,
        "fees": 0.0,
        "currency": "CAD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 15,
    },
    {
        "account_id": 1,
        "type": "TRANSFER",
        "date": "2025-02-13",
        "symbol": "AAPL",
        "quantity": 1.0,
        "price": 0.0,
        "amount": 0.0,
        "fees": 0.0,
        "currency": "USD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": 2,
        "id": 16,
    },
    {
        "account_id": 2,
        "type": "DEPOSIT",
        "date": "TODAY",
        "symbol": "",
        "quantity": 0.0,
        "price": 0.0,
        "amount": 250.0,
        "fees": 0.0,
        "currency": "CAD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 17,
    },
    {
        "account_id": 2,
        "type": "BUY",
        "date": "TODAY",
        "symbol": "XEQT.TO",
        "quantity": 1.0,
        "price": 40.0,
        "amount": 0.0,
        "fees": 0.0,
        "currency": "CAD",
        "note": "",
        "ratio": 0.0,
        "target_account_id": None,
        "id": 18,
    },
]

# Retry fingerprints of the two --request-id saves: new options must not change them.
EXPECTED_RECEIPTS = [
    {"fingerprint": "9be921f173d18ba4272dce071bb76183bc25d4abf1369339da62fb38cbdec2a6", "transaction_id": 17},
    {"fingerprint": "2a1a254414a7dd89977703ad92662ec5aa1da59548ba8c2072dd1fb9f884aeb5", "transaction_id": 18},
]


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "160")
    return lambda *args: CliRunner().invoke(main, list(args), catch_exceptions=False)


def test_plain_commands_print_and_save_exactly_as_before(cli, store):
    store.add_account(Account(name="Maple Cash", type=AccountType.NONREG, track_cash=True))
    store.add_account(Account(name="Maple TFSA", type=AccountType.TFSA))
    today = date.today().isoformat()
    for args, (code, output) in zip(SCRIPT, EXPECTED_OUTPUT, strict=True):
        result = cli(*args)
        assert (result.exit_code, result.output) == (code, output.replace("TODAY", today)), args
    rows = sorted((asdict(t) for t in store.transactions()), key=lambda r: r["id"])
    for row in rows:
        if row["date"] == today:
            row["date"] = "TODAY"
    assert rows == EXPECTED_ROWS
    receipts = [
        store.get_meta(f"transaction_request:{key}")
        for key in ("11111111-2222-3333-4444-555555555555", "21111111-2222-3333-4444-555555555555")
    ]
    assert [json.loads(r) for r in receipts] == EXPECTED_RECEIPTS
