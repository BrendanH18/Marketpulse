import io
from pathlib import Path

import pytest

from marketpulse import brokers
from marketpulse.csvio import DuplicateRow, RowIssue, import_transactions, read_headers
from marketpulse.models import Account, AccountType, TxnType

FIXTURES = Path(__file__).parent / "fixtures" / "brokers"
QUESTRADE = FIXTURES / "questrade.csv"
WEALTHSIMPLE = FIXTURES / "wealthsimple.csv"
EXAMPLE = Path(__file__).parents[1] / "examples" / "transactions.csv"


def headers(path: Path) -> list[str]:
    return read_headers(path.read_text(encoding="utf-8-sig"))


def test_profiles_are_detected_from_the_header_row():
    assert brokers.detect(headers(QUESTRADE)).name == "questrade"
    assert brokers.detect(headers(WEALTHSIMPLE)).name == "wealthsimple"
    # MarketPulse's own export and any unrecognized file keep the generic importer.
    assert brokers.detect(headers(EXAMPLE)) is brokers.GENERIC
    assert brokers.detect(["Trade Date", "Action", "Symbol"]) is brokers.GENERIC
    assert brokers.PROFILE_NAMES == ["auto", "questrade", "wealthsimple", "generic"]


def test_a_named_profile_must_match_the_file(store):
    acct = store.add_account(Account(name="Main"))
    with pytest.raises(ValueError, match="doesn't look like a Questrade export"):
        import_transactions(store, WEALTHSIMPLE, default_account=acct, profile="questrade")
    with pytest.raises(ValueError, match="Unknown broker profile"):
        import_transactions(store, WEALTHSIMPLE, default_account=acct, profile="nope")
    assert store.transactions() == [] and store.backups() == []


def test_questrade_activity_export(store):
    result = import_transactions(store, QUESTRADE)
    assert (result.profile, result.profile_label) == ("questrade", "Questrade")
    assert (result.added, result.duplicates) == (8, 0)
    assert result.accounts_created == ["Questrade Individual TFSA 90001234", "Questrade Individual margin 90005678"]
    tfsa = store.get_account("Questrade Individual TFSA 90001234")
    margin = store.get_account("Questrade Individual margin 90005678")
    assert (tfsa.type, margin.type) == (AccountType.TFSA, AccountType.MARGIN)
    # The reversed dividend, the currency conversion and the transfer are reported, not guessed.
    assert [(i.line, i.field, i.value) for i in result.issues] == [
        (6, "amount", "-22.00"),
        (8, "type", "FX conversion"),
        (12, "type", "Transfers"),
    ]
    assert "reversal" in result.issues[0].reason
    by_type = {(t.type, t.account_id): t for t in store.transactions()}
    buy = by_type[(TxnType.BUY, tfsa.id)]
    assert (buy.date, buy.symbol, buy.quantity, buy.price, buy.fees, buy.currency) == (
        "2025-01-03",
        "XEQT.TO",
        100,
        30,
        4.95,
        "CAD",
    )
    sell = by_type[(TxnType.SELL, margin.id)]
    assert (sell.quantity, sell.price, sell.fees, sell.currency) == (2, 190, 4.95, "USD")
    assert by_type[(TxnType.DIVIDEND, tfsa.id)].amount == 22
    assert by_type[(TxnType.WITHDRAWAL, margin.id)].amount == 500
    assert by_type[(TxnType.FEE, margin.id)].amount == 25
    holdings = {(h.symbol, h.account_id): (h.quantity, round(h.book, 2)) for h in store.ledger().open_holdings()}
    assert holdings == {("XEQT.TO", tfsa.id): (100, 3004.95), ("AAPL", margin.id): (3, 542.97)}


QUESTRADE_HEADER = (
    "Transaction Date,Settlement Date,Action,Symbol,Description,Quantity,Price,Gross Amount,Commission,"
    "Net Amount,Currency,Account #,Activity Type,Account Type\n"
)


def test_questrade_reinvestment_is_a_purchase_with_the_dividend_paid_in_cash(store):
    tfsa = store.add_account(Account(name="Questrade Individual TFSA 90001234", type=AccountType.TFSA, track_cash=True))
    text = QUESTRADE_HEADER + (
        "2025-03-28,2025-03-28,DIV,XEQT.TO,DIST,0,0,0,0,22.00,CAD,90001234,Dividends,Individual TFSA\n"
        "2025-03-28,2025-03-28,REI,XEQT.TO,REINVEST,1,20.00,-20.00,0,-20.00,CAD,90001234,"
        "Dividend reinvestment,Individual TFSA\n"
    )
    result = import_transactions(store, io.StringIO(text))
    assert (result.added, result.issues) == (2, [])
    state = store.ledger()
    assert sum(e.amount for e in state.income) == 22  # counted once, not again on reinvestment
    assert state.cash_balances(tfsa.id) == {(tfsa.id, "CAD"): 2}
    assert state.open_holdings()[0].quantity == 1


def test_questrade_accounts_whose_numbers_end_alike_stay_apart(store):
    text = QUESTRADE_HEADER + (
        "2025-01-03,2025-01-06,Buy,XEQT.TO,ETF,1,30,-30,0,-30,CAD,90001234,Trades,Individual TFSA\n"
        "2025-01-03,2025-01-06,Buy,XEQT.TO,ETF,2,30,-60,0,-60,CAD,80001234,Trades,Individual TFSA\n"
    )
    result = import_transactions(store, io.StringIO(text))
    assert result.accounts_created == ["Questrade Individual TFSA 90001234", "Questrade Individual TFSA 80001234"]
    assert len({t.account_id for t in store.transactions()}) == 2


@pytest.mark.parametrize(
    ("ticker", "currency", "fx", "expected"),
    [
        ("XEQT", "CAD", "", "XEQT.TO"),
        ("RCI.B", "CAD", "", "RCI-B.TO"),  # share class
        ("REI.UN", "CAD", "", "REI-UN.TO"),  # trust units
        ("XEQT.TO", "CAD", "", "XEQT.TO"),  # already has an exchange
        ("BRK.B", "CAD", ", FX Rate: 1.4", "BRK.B"),  # converted US trade: left as written
        ("AAPL", "USD", "", "AAPL"),
    ],
)
def test_wealthsimple_tickers_become_yahoo_symbols(store, ticker, currency, fx, expected):
    acct = store.add_account(Account(name="WS", currency=currency))
    text = (
        "date,transaction,description,amount,balance,currency\n"
        f'2025-01-03,BUY,"{ticker} - Fictional: Bought 1.0000 shares (executed at 2025-01-03){fx}",-10,0,{currency}\n'
    )
    import_transactions(store, io.StringIO(text), default_account=acct)
    assert [t.symbol for t in store.transactions()] == [expected]


def test_wealthsimple_statement(store):
    acct = store.add_account(Account(name="WS TFSA", type=AccountType.TFSA))
    result = import_transactions(store, WEALTHSIMPLE, default_account=acct)
    assert result.profile == "wealthsimple"
    assert (result.added, result.accounts_created) == (7, [])
    assert [(i.line, i.field, i.value) for i in result.issues] == [(6, "type", "NRT"), (9, "type", "LOAN")]
    rows = [(t.type, t.symbol, t.quantity, round(t.price, 2), t.amount, t.currency) for t in store.transactions()]
    assert rows == [
        (TxnType.DEPOSIT, "", 0, 0, 5000, "CAD"),
        # A CAD trade without an FX conversion is a TSX listing.
        (TxnType.BUY, "XEQT.TO", 50, 30, 1500, "CAD"),
        # A converted US trade keeps its bare ticker; its price is what was paid in CAD.
        (TxnType.BUY, "AAPL", 2, 259.2, 518.4, "CAD"),
        (TxnType.DIVIDEND, "XEQT.TO", 0, 0, 11, "CAD"),
        (TxnType.SELL, "XEQT.TO", 10, 32, 320, "CAD"),
        (TxnType.INTEREST, "", 0, 0, 0.05, "CAD"),
        (TxnType.WITHDRAWAL, "", 0, 0, 200, "CAD"),
    ]


def test_wealthsimple_rows_whose_description_cant_be_read_are_skipped(store):
    acct = store.add_account(Account(name="WS"))
    text = (
        "date,transaction,description,amount,balance,currency\n"
        "2025-01-03,BUY,Bought something,-100.00,0,CAD\n"
        '2025-01-03,BUY,"XEQT - iShares: Bought some shares",-100.00,0,CAD\n'
        "2025-01-04,MYSTERY,Unknown,1.00,0,CAD\n"
    )
    result = import_transactions(store, io.StringIO(text), default_account=acct)
    assert result.added == 0
    assert [(i.line, i.field) for i in result.issues] == [(2, "symbol"), (3, "quantity"), (4, "type")]
    assert "MYSTERY" in result.issues[2].reason


@pytest.mark.parametrize("path", [QUESTRADE, WEALTHSIMPLE])
def test_broker_preview_is_the_import_and_reimporting_finds_duplicates(store, path):
    acct = store.add_account(Account(name="Default", type=AccountType.TFSA))
    preview = import_transactions(store, path, default_account=acct, dry_run=True)
    assert store.transactions() == []
    result = import_transactions(store, path, default_account=acct)
    result.backup = None
    assert preview == result
    again = import_transactions(store, path, default_account=acct)
    assert (again.added, again.duplicates) == (0, result.added)
    assert [d.line for d in again.duplicate_rows] == [
        line for line in range(2, 2 + result.added + len(result.issues)) if line not in {i.line for i in result.issues}
    ]


def test_generic_import_reports_the_field_and_value_of_each_bad_row(store):
    acct = store.add_account(Account(name="Main"))
    text = (
        "date,type,symbol,quantity,price,fees\n"
        "2024-01-05,BUY,AAPL,10,150,1\n"
        "2024-01-06,BUY,AAPL,1,2x,1\n"
        "2024-13-01,BUY,AAPL,1,150,\n"
        "2024-01-07,Mystery,AAPL,1,150,\n"
        "2024-01-08,BUY,AAPL,0,150,\n"
        "2024-01-09,DIVIDEND,,,,\n"
        "2024-01-10,BUY,AAPL,1,150,lots\n"
    )
    result = import_transactions(store, io.StringIO(text), default_account=acct)
    assert result.added == 1
    assert result.issues == [
        RowIssue(3, "price", "2x", "expected a number like 1234.56"),
        RowIssue(4, "date", "2024-13-01", "Invalid date '2024-13-01' — use YYYY-MM-DD."),
        RowIssue(5, "type", "Mystery", "unrecognized type 'Mystery'"),
        RowIssue(6, "quantity", "0", "Quantity must be positive."),
        RowIssue(7, "symbol", "", "DIVIDEND needs a symbol."),
        RowIssue(8, "fees", "lots", "expected a number like 1234.56"),
    ]
    assert result.skipped == [(i.line, i.reason) for i in result.issues]
    again = import_transactions(store, io.StringIO(text), default_account=acct)
    assert again.duplicate_rows == [DuplicateRow(2, "2024-01-05 BUY 10 AAPL @ 150 CAD · Main")]
