import io

import pytest

from marketpulse.csvio import export_transactions, import_transactions, parse_type
from marketpulse.db import Store
from marketpulse.models import Account, AccountType, Transaction, TxnType


def test_export_import_roundtrip(store, tmp_path):
    a = store.add_account(Account(name="Main"))
    b = store.add_account(Account(name="My TFSA", type=AccountType.TFSA))
    store.add_transaction(
        Transaction(
            account_id=a.id,
            type=TxnType.BUY,
            date="2024-01-01",
            symbol="AAPL",
            quantity=2,
            price=150,
            fees=1,
            currency="USD",
            note="core",
        )
    )
    store.add_transaction(
        Transaction(
            account_id=a.id, type=TxnType.TRANSFER, date="2024-02-01", symbol="AAPL", quantity=1, target_account_id=b.id
        )
    )
    store.add_transaction(
        Transaction(account_id=b.id, type=TxnType.DEPOSIT, date="2024-01-01", amount=7000, currency="CAD")
    )
    buf = io.StringIO()
    assert export_transactions(store, buf) == 3

    fresh = Store(tmp_path / "fresh.db")
    fresh.add_account(Account(name="My TFSA", type=AccountType.TFSA))  # transfer target must exist first
    result = import_transactions(fresh, io.StringIO(buf.getvalue()))
    assert result.added == 3 and result.accounts_created == ["Main"]
    holdings = {(h.symbol, fresh.get_account(h.account_id).name): h.quantity for h in fresh.ledger().open_holdings()}
    assert holdings == {("AAPL", "Main"): 1, ("AAPL", "My TFSA"): 1}
    again = import_transactions(fresh, io.StringIO(buf.getvalue()))
    assert again.added == 0 and again.duplicates == 3


def test_broker_style_headers(store):
    acct = store.add_account(Account(name="Main"))
    text = (
        "Trade Date,Action,Symbol,Quantity,Price,Commission,Currency,Description\n"
        '2024-01-05,Bought,AAPL,-10,"$150.00",4.95,USD,core\n'
        "2024-02-01,Sold,AAPL,5,160,4.95,USD,\n"
        "2024-03-01,Dividend,AAPL,,,,USD,\n"
        "2024-03-02,Mystery,AAPL,1,1,,USD,\n"
        "not a date,Buy,AAPL,1,1,,USD,\n"
        "31/01/2024 09:30,Buy,AAPL,2,150,,USD,US-style date with a time\n"
    )
    result = import_transactions(store, io.StringIO(text), default_account=acct)
    assert result.added == 3
    assert [line for line, _ in result.skipped] == [4, 5, 6]
    h = store.ledger().open_holdings()[0]
    assert h.quantity == 7 and h.currency == "USD"
    assert sorted(t.date for t in store.transactions()) == ["2024-01-05", "2024-01-31", "2024-02-01"]


def test_dry_run_and_required_columns(store):
    acct = store.add_account(Account(name="Main"))
    text = "date,type,symbol,quantity,price\n2024-01-01,BUY,XEQT.TO,1,30\n"
    assert import_transactions(store, io.StringIO(text), default_account=acct, dry_run=True).added == 1
    assert store.transactions() == []
    with pytest.raises(ValueError, match="missing required"):
        import_transactions(store, io.StringIO("symbol,qty\nA,1\n"), default_account=acct)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("BUY", TxnType.BUY),
        ("Sold", TxnType.SELL),
        ("Dividend reinvestment", TxnType.DRIP),
        ("CONT", TxnType.DEPOSIT),
        ("EFT out", TxnType.WITHDRAWAL),
        ("Distribution", TxnType.DIVIDEND),
        ("hmm", None),
    ],
)
def test_parse_type(raw, expected):
    assert parse_type(raw) == expected


def test_identical_partial_fills_are_kept(store):
    acct = store.add_account(Account(name="Main"))
    row = "2024-01-05,BUY,AAPL,5,150,USD\n"
    header = "date,type,symbol,quantity,price,currency\n"
    first = import_transactions(store, io.StringIO(header + row + row), default_account=acct)
    assert (first.added, first.duplicates) == (2, 0)
    again = import_transactions(store, io.StringIO(header + row + row), default_account=acct)
    assert (again.added, again.duplicates) == (0, 2)
    third = import_transactions(store, io.StringIO(header + row * 3), default_account=acct)
    assert (third.added, third.duplicates) == (1, 2)
    assert store.ledger().open_holdings()[0].quantity == 15
