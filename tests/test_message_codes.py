"""Stable codes on the engine's messages, so the Mac app can word them in the user's language.

Every message keeps its English text byte for byte (the CLI and older apps show that); the
code and its values ride alongside it. All data here is fictional."""

import json

import pytest

from marketpulse import desktop
from marketpulse.analytics import DISPOSITION_NOTES, disposition_note
from marketpulse.brokers import skip_reasons
from marketpulse.desktop import BACKEND_STRINGS, BACKUP_REASON_LABELS, snapshot, tax_report
from marketpulse.ledger import LedgerIssue, replay
from marketpulse.models import Account, AccountType, AssetClass, CodedError, Transaction, TxnType, parse_date
from marketpulse.tax import Disposition, compute


def txn(id, kind, day, symbol="", qty=0.0, price=0.0, account=1, **kw):
    return Transaction(
        id=id, account_id=account, type=kind, date=day, symbol=symbol, quantity=qty, price=price, currency="CAD", **kw
    )


ACCOUNTS = {
    1: Account(name="Fictional Taxable", id=1),
    2: Account(name="Fictional TFSA", type=AccountType.TFSA, id=2),
    3: Account(name="Fictional Margin", type=AccountType.MARGIN, id=3),
}


def test_ledger_issues_carry_a_code_and_their_values():
    state = replay(
        [
            txn(1, TxnType.BUY, "2024-01-02", "XEQT.TO", 5, 30),
            txn(2, TxnType.SELL, "2024-02-01", "XEQT.TO", 1234.5, 31),
            txn(3, TxnType.SPLIT, "2024-03-01", "VFV.TO", ratio=2),
            txn(4, TxnType.TRANSFER, "2024-04-01", "ZAG.TO", 1, target_account_id=3),
            txn(5, TxnType.BUY, "2024-05-01", "VCN.TO", 2, 40),
            txn(6, TxnType.TRANSFER, "2024-06-01", "VCN.TO", 3, target_account_id=3),
        ],
        ACCOUNTS,
    )
    assert state.issues == [
        LedgerIssue(
            2,
            "2024-02-01",
            "Sell of 1,234.5000 XEQT.TO exceeds 5.0000 held",
            "sell_exceeds_held",
            {"symbol": "XEQT.TO", "quantity": 1234.5, "held": 5.0},
        ),
        LedgerIssue(3, "2024-03-01", "Split of VFV.TO with nothing held", "split_nothing_held", {"symbol": "VFV.TO"}),
        LedgerIssue(
            4, "2024-04-01", "Transfer of ZAG.TO with nothing held", "transfer_nothing_held", {"symbol": "ZAG.TO"}
        ),
        LedgerIssue(
            6,
            "2024-06-01",
            "Transfer of 3.0000 VCN.TO exceeds 2.0000 held",
            "transfer_exceeds_held",
            {"symbol": "VCN.TO", "quantity": 3.0, "held": 2.0},
        ),
    ]


def test_a_ledger_issue_without_a_code_still_builds():
    issue = LedgerIssue(None, "2024-01-01", "Something")
    assert (issue.code, issue.args) == ("", {})


def test_unpriced_registered_transfers_carry_a_code():
    report = compute(
        [
            txn(1, TxnType.BUY, "2024-01-02", "XEQT.TO", 10, 30),
            txn(2, TxnType.TRANSFER, "2024-02-01", "XEQT.TO", 4, target_account_id=2),
            txn(3, TxnType.BUY, "2024-01-03", "VFV.TO", 2, 100, account=2),
            txn(4, TxnType.TRANSFER, "2024-03-01", "VFV.TO", 2, account=2, target_account_id=1),
        ],
        ACCOUNTS,
        lambda day, ccy: 1.0,
        today="2025-01-01",
    )
    assert [(i.txn_id, i.code, i.args) for i in report.issues] == [
        (2, "transfer_to_registered_unpriced", {"symbol": "XEQT.TO"}),
        (4, "transfer_from_registered_unpriced", {"symbol": "VFV.TO"}),
    ]
    assert [i.message for i in report.issues] == [
        "Transfer of XEQT.TO into a registered account is a deemed sale at market value — "
        "add the price per unit to the transfer to include it in the tax report",
        "Transfer of VFV.TO out of a registered account enters your cost base at market value — "
        "add the price per unit to the transfer",
    ]


def test_snapshot_warning_items_match_the_english_warnings(tracker):
    store = tracker.store
    main = store.add_account(Account(name="Investing"))
    old = store.add_account(Account(name="Old RRSP", type=AccountType.RRSP))
    for t in [
        txn(None, TxnType.BUY, "2024-01-02", "AAPL", 2, 150, account=main.saved_id),
        txn(None, TxnType.BUY, "2024-01-03", "UNKNOWN", 1, 50, account=main.saved_id),
        txn(None, TxnType.SELL, "2024-01-04", "AAPL", 3, 150, account=main.saved_id),
        txn(None, TxnType.BUY, "2024-01-05", "AAPL", 1, 150, account=old.saved_id),
    ]:
        store.add_transaction(t)
    old.archived = True
    store.update_account(old)
    payload = snapshot(tracker)
    json.dumps(payload, allow_nan=False)
    items = payload["warning_items"]
    assert payload["warnings"] == [w["text"] for w in items]
    assert items == [
        {
            "code": "sell_exceeds_held",
            "args": {"symbol": "AAPL", "quantity": 3.0, "held": 2.0, "date": "2024-01-04"},
            "text": "2024-01-04: Sell of 3.0000 AAPL exceeds 2.0000 held",
        },
        {"code": "excluded_unpriced", "args": {"symbol": "UNKNOWN"}, "text": "Excluded from totals: UNKNOWN"},
        {
            "code": "archived_account_value",
            "args": {"account": "Old RRSP"},
            "text": "Archived account Old RRSP still holds investments or cash. They're left out of your totals, "
            "and daily snapshots are paused. Move or sell them, or unarchive the account.",
        },
    ]


def test_excluded_cash_and_archived_holdings_carry_codes(tracker, fake):
    store = tracker.store
    cash = store.add_account(Account(name="Euro Cash", track_cash=True))
    store.add_transaction(
        Transaction(account_id=cash.saved_id, type=TxnType.DEPOSIT, date="2024-01-02", amount=100, currency="EUR")
    )
    view = tracker.valuation(record=False)
    assert view.excluded == ["Euro Cash cash (EUR)"]
    assert view.excluded_items == [("unconverted_cash", {"account": "Euro Cash", "currency": "EUR"})]
    old = store.add_account(Account(name="Old Margin", track_cash=True))
    store.add_transaction(
        Transaction(account_id=old.saved_id, type=TxnType.DEPOSIT, date="2024-01-02", amount=5, currency="EUR")
    )
    store.add_transaction(txn(None, TxnType.BUY, "2024-01-03", "NOPRICE", 1, 1, account=old.saved_id))
    old.archived = True
    store.update_account(old)
    view = tracker.valuation(record=False)
    assert list(zip(view.excluded, view.excluded_items, strict=True)) == [
        ("NOPRICE in archived Old Margin", ("archived_holding", {"symbol": "NOPRICE", "account": "Old Margin"})),
        ("Euro Cash cash (EUR)", ("unconverted_cash", {"account": "Euro Cash", "currency": "EUR"})),
        ("Old Margin cash (EUR, archived)", ("archived_cash", {"account": "Old Margin", "currency": "EUR"})),
    ]


def test_tax_report_issues_carry_codes(tracker):
    store = tracker.store
    taxable = store.add_account(Account(name="Fictional Taxable"))
    tfsa = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
    store.add_transaction(txn(None, TxnType.BUY, "2024-01-02", "XEQT.TO", 10, 30, account=taxable.saved_id))
    store.add_transaction(
        txn(
            None,
            TxnType.TRANSFER,
            "2024-02-01",
            "XEQT.TO",
            4,
            account=taxable.saved_id,
            target_account_id=tfsa.saved_id,
        )
    )
    issues = tax_report(tracker)["issues"]
    assert issues == [
        {
            "date": "2024-02-01",
            "message": "Transfer of XEQT.TO into a registered account is a deemed sale at market value — "
            "add the price per unit to the transfer to include it in the tax report",
            "code": "transfer_to_registered_unpriced",
            "args": {"symbol": "XEQT.TO"},
        }
    ]


def test_coded_errors_keep_their_english_text():
    with pytest.raises(CodedError) as e:
        parse_date("2024-13-01")
    assert (str(e.value), e.value.code, e.value.details) == (
        "Invalid date '2024-13-01' — use YYYY-MM-DD.",
        "invalid_date",
        {"value": "2024-13-01"},
    )
    with pytest.raises(CodedError) as e:
        parse_date("03-04-2024")
    assert (str(e.value), e.value.code) == ("Ambiguous date '03-04-2024' — use YYYY-MM-DD.", "ambiguous_date")
    with pytest.raises(ValueError, match=r"^DIVIDEND needs a symbol\.$") as e:
        txn(1, TxnType.DIVIDEND, "2024-01-01", amount=5).validate()
    assert (e.value.code, e.value.details) == ("needs_symbol", {"type": "DIVIDEND"})  # type: ignore[attr-defined]


def test_backend_strings_list_the_engines_fixed_display_text():
    """Everything the bridge sends as fixed text the app shows."""
    strings = set(BACKEND_STRINGS)
    assert set(desktop.TAX_NOTES) <= strings
    assert {c.label for c in AssetClass} <= strings
    assert set(BACKUP_REASON_LABELS.values()) <= strings and set(skip_reasons()) <= strings
    assert "Generic CSV" in strings
    # Every tag a disposition can carry.
    tags = set()
    for complete in (True, False):
        for reason in ("", "registered", "superficial"):
            for window_open in (True, False):
                for kind in ("sale", "roc", "deemed"):
                    d = Disposition("2024-01-01", 1, "X", 1, 1, 1, "CAD", 1.0, 1, kind, complete)
                    d.denied_reason, d.denied, d.window_open = reason, 1.0, window_open
                    tags.add(disposition_note(d))
    assert tags - {""} == set(DISPOSITION_NOTES) <= strings


def test_import_reasons_carry_codes(store):
    import io

    from marketpulse.csvio import import_transactions

    main = store.add_account(Account(name="Fictional Cash"))
    old = store.add_account(Account(name="Old Fictional"))
    old.archived = True
    store.update_account(old)
    text = (
        "date,type,symbol,quantity,price,amount,account\n"
        "2025-01-02,BUY,AAPL,1,10,,Nobody\n"
        "2025-01-02,BUY,AAPL,1,10,,Old Fictional\n"
        "2025-01-02,DIVIDEND,AAPL,,,,Fictional Cash\n"
        "03-04-2025,BUY,AAPL,1,10,,Fictional Cash\n"
        "2999-01-02,BUY,AAPL,1,10,,Fictional Cash\n"
    )
    result = import_transactions(store, io.StringIO(text), default_account=main, create_accounts=False, dry_run=True)
    assert [(i.reason, i.code, i.args) for i in result.issues] == [
        ("unknown account 'Nobody'", "unknown_account", {"account": "Nobody"}),
        ("account 'Old Fictional' is archived", "archived_account", {"account": "Old Fictional"}),
        ("DIVIDEND row has no amount", "no_amount", {"type": "DIVIDEND"}),
        ("Ambiguous date '03-04-2025' — use YYYY-MM-DD.", "ambiguous_date", {"value": "03-04-2025"}),
        ("Date cannot be in the future.", "future_date", {}),
    ]
    no_default = import_transactions(
        store, io.StringIO("date,type,symbol,quantity,price\n2025-01-02,BUY,AAPL,1,10\n"), dry_run=True
    )
    assert [(i.reason, i.code) for i in no_default.issues] == [("no account", "no_account")]


def test_broker_reasons_carry_codes(store):
    from pathlib import Path

    from marketpulse.csvio import import_transactions

    questrade = Path(__file__).parent / "fixtures" / "brokers" / "questrade.csv"
    result = import_transactions(store, questrade, dry_run=True)
    codes = {(i.code, i.reason) for i in result.issues}
    assert (
        "negative_amount",
        "negative amount on a DIVIDEND (a reversal or correction?); record it by hand",
    ) in codes
    assert all(code for code, _ in codes)
    skipped = [i for i in result.issues if i.code == "not_imported"]
    assert skipped and all(i.reason in skip_reasons() and i.args == {"value": i.value} for i in skipped)
