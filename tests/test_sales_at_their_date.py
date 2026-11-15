"""New sales and imported rows are judged at their own date (issue #149). All data is fictional.

Before #149, `Tracker.add_transaction` compared a new sale with today's holdings and CSV imports
didn't check sales at all, so a sale dated before its shares were bought was accepted, and one of
shares held then but consolidated since was refused. Each test notes what happened before."""

import io

import pytest

from marketpulse.csvio import import_transactions
from marketpulse.models import Account, AccountType, Transaction, TxnType


def trade(acct, kind, day, qty, price=10.0, symbol="QAA", **kw):
    return Transaction(
        account_id=acct.saved_id, type=kind, date=day, symbol=symbol, quantity=qty, price=price, currency="CAD", **kw
    )


@pytest.fixture
def acct(store):
    return store.add_account(Account(name="Fictional Taxable"))


# ── recording by hand ─────────────────────────────────────────────────────────


def test_a_sale_dated_before_its_shares_were_bought_is_refused(tracker, store, acct):
    # Before: accepted, because 10 are held today; `txn check` then reported the oversell.
    store.add_transaction(trade(acct, TxnType.BUY, "2026-03-01", 10))
    with pytest.raises(ValueError, match=r"^Cannot sell 10 QAA — only 0 held in this account on 2026-02-01\.$"):
        tracker.add_transaction(trade(acct, TxnType.SELL, "2026-02-01", 10))
    assert len(store.transactions()) == 1 and store.ledger().issues == []


def test_a_backdated_sale_valid_at_its_date_is_accepted_after_a_consolidation(tracker, store, acct):
    # Before: refused with "only 1 held", today's quantity after the 1-for-10 consolidation.
    store.add_transaction(trade(acct, TxnType.BUY, "2026-01-01", 10, symbol="QAC"))
    store.add_transaction(trade(acct, TxnType.SPLIT, "2026-03-01", 0, 0, symbol="QAC", ratio=0.1))
    tracker.add_transaction(trade(acct, TxnType.SELL, "2026-02-01", 5, symbol="QAC"))
    state = store.ledger()
    assert state.issues == []
    assert state.holdings[(acct.saved_id, "QAC")].quantity == pytest.approx(0.5)


def test_a_backdated_sale_that_leaves_a_later_sale_short_is_refused(tracker, store, acct):
    # Before: refused, but as "only 0 held", though 10 were held on the sale's date.
    store.add_transaction(trade(acct, TxnType.BUY, "2026-01-01", 10, symbol="QAB"))
    later = store.add_transaction(trade(acct, TxnType.SELL, "2026-03-01", 10, symbol="QAB"))
    with pytest.raises(
        ValueError,
        match=rf"^Not recorded: transaction #{later.id} on 2026-03-01 would no longer add up "
        r"\(Sell of 10\.0000 QAB exceeds 5\.0000 held\)\. Change or delete that one first\.$",
    ):
        tracker.add_transaction(trade(acct, TxnType.SELL, "2026-02-01", 5, symbol="QAB"))
    assert len(store.transactions()) == 2


def test_a_backdated_sale_that_leaves_later_sales_valid_is_accepted(tracker, store, acct):
    # Accepted before too: the replay check only refuses what doesn't add up at some date.
    store.add_transaction(trade(acct, TxnType.BUY, "2026-01-01", 10))
    store.add_transaction(trade(acct, TxnType.SELL, "2026-03-01", 6))
    tracker.add_transaction(trade(acct, TxnType.SELL, "2026-02-01", 4))
    state = store.ledger()
    assert state.issues == [] and state.holdings[(acct.saved_id, "QAA")].quantity == 0


def test_same_day_sales_follow_the_days_purchases(tracker, store, acct):
    # Replay applies a day's buys before its sales, so a sale entered first still counts them.
    tracker.add_transaction(trade(acct, TxnType.BUY, "2026-02-01", 5))
    tracker.add_transaction(trade(acct, TxnType.SELL, "2026-02-01", 5))
    tracker.add_transaction(trade(acct, TxnType.BUY, "2026-02-01", 3))
    with pytest.raises(ValueError, match=r"^Cannot sell 4 QAA — only 3 held in this account on 2026-02-01\.$"):
        tracker.add_transaction(trade(acct, TxnType.SELL, "2026-02-01", 4))
    tracker.add_transaction(trade(acct, TxnType.SELL, "2026-02-01", 3))
    assert store.ledger().issues == []


def test_a_sale_after_a_transfer_counts_the_shares_moved_on_their_date(tracker, store, acct):
    tfsa = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
    store.add_transaction(trade(acct, TxnType.BUY, "2026-01-01", 10))
    store.add_transaction(trade(acct, TxnType.TRANSFER, "2026-02-01", 10, target_account_id=tfsa.saved_id))
    # Before: accepted, because the TFSA holds 10 today, though they arrived on February 1.
    with pytest.raises(ValueError, match=r"only 0 held in this account on 2026-01-15\.$"):
        tracker.add_transaction(trade(tfsa, TxnType.SELL, "2026-01-15", 10))
    # Before: refused as "only 0 held". It is refused because the transfer needs all 10.
    with pytest.raises(ValueError, match=r"would no longer add up \(Transfer of 10\.0000 QAA exceeds 9\.0000 held\)"):
        tracker.add_transaction(trade(acct, TxnType.SELL, "2026-01-15", 1))
    # Before: refused, because the taxable account holds none today.
    store.add_transaction(trade(acct, TxnType.BUY, "2026-01-10", 5))
    tracker.add_transaction(trade(acct, TxnType.SELL, "2026-01-15", 5))
    tracker.add_transaction(trade(tfsa, TxnType.SELL, "2026-02-02", 10))
    assert store.ledger().issues == []


def test_a_sale_after_a_split_counts_the_shares_held_on_its_date(tracker, store, acct):
    store.add_transaction(trade(acct, TxnType.BUY, "2026-01-01", 10))
    store.add_transaction(trade(acct, TxnType.SPLIT, "2026-02-01", 0, 0, ratio=2))
    with pytest.raises(ValueError, match=r"only 10 held in this account on 2026-01-15\.$"):
        tracker.add_transaction(trade(acct, TxnType.SELL, "2026-01-15", 20))
    tracker.add_transaction(trade(acct, TxnType.SELL, "2026-02-02", 20))
    assert store.ledger().issues == []


def test_problems_already_in_the_ledger_do_not_block_a_new_sale(tracker, store, acct):
    store.add_transaction(trade(acct, TxnType.BUY, "2026-03-01", 10))
    broken = store.add_transaction(trade(acct, TxnType.SELL, "2026-02-01", 5))
    store.add_transaction(trade(acct, TxnType.BUY, "2026-01-01", 2, symbol="QAD"))
    tracker.add_transaction(trade(acct, TxnType.SELL, "2026-04-01", 2, symbol="QAD"))
    assert [i.txn_id for i in store.ledger().issues] == [broken.id]


# ── importing a CSV ───────────────────────────────────────────────────────────

HEADER = "date,type,symbol,quantity,price,account\n"


def run_import(store, rows, **kw):
    """Preview, then import: the preview must report exactly what the import does."""
    text = HEADER + rows
    preview = import_transactions(store, io.StringIO(text), dry_run=True, **kw)
    result = import_transactions(store, io.StringIO(text), expect_fingerprint=preview.fingerprint, **kw)
    assert (preview.added, preview.skipped, preview.issues) == (result.added, result.skipped, result.issues)
    assert preview.accounts_created == result.accounts_created
    return result


def test_an_imported_sale_of_shares_bought_later_is_skipped(store, acct):
    # Before: imported, leaving the ledger with an oversell.
    result = run_import(
        store,
        "2026-03-01,BUY,QAA,10,10,Fictional Taxable\n"
        "2026-02-01,SELL,QAA,10,11,Fictional Taxable\n"
        "2026-03-02,SELL,QAA,4,12,Fictional Taxable\n",
    )
    assert result.added == 2
    assert result.skipped == [(3, "2026-02-01: Sell of 10.0000 QAA exceeds 0.0000 held")]
    [issue] = result.issues
    assert (issue.line, issue.field, issue.value, issue.code) == (3, "", "", "sell_exceeds_held")
    assert issue.args == {"symbol": "QAA", "quantity": 10.0, "held": 0.0, "date": "2026-02-01"}
    assert store.ledger().issues == []
    assert store.ledger().holdings[(acct.saved_id, "QAA")].quantity == 6


def test_rows_are_judged_in_date_order_not_file_order(store, acct):
    # A file listed newest first sells before it buys; by date, every row adds up.
    result = run_import(
        store,
        "2026-03-01,SELL,QAA,10,12,Fictional Taxable\n"
        "2026-02-01,SELL,QAA,5,11,Fictional Taxable\n"
        "2026-01-01,BUY,QAA,15,10,Fictional Taxable\n",
    )
    assert (result.added, result.skipped) == (3, [])
    assert store.ledger().issues == []


def test_the_later_of_two_competing_sales_is_skipped(store, acct):
    result = run_import(
        store,
        "2026-01-01,BUY,QAA,10,10,Fictional Taxable\n"
        "2026-03-01,SELL,QAA,10,12,Fictional Taxable\n"
        "2026-02-01,SELL,QAA,5,11,Fictional Taxable\n",
    )
    assert result.added == 2
    assert result.skipped == [(3, "2026-03-01: Sell of 10.0000 QAA exceeds 5.0000 held")]


def test_an_imported_sale_that_leaves_a_recorded_sale_short_is_skipped(store, acct):
    # Before: imported, and the sale already in the ledger became an oversell.
    store.add_transaction(trade(acct, TxnType.BUY, "2026-01-01", 10, symbol="QAB"))
    later = store.add_transaction(trade(acct, TxnType.SELL, "2026-03-01", 10, symbol="QAB"))
    result = run_import(store, "2026-02-01,SELL,QAB,5,11,Fictional Taxable\n")
    assert result.added == 0
    reason = f"transaction #{later.id} on 2026-03-01 would no longer add up (Sell of 10.0000 QAB exceeds 5.0000 held)"
    assert result.skipped == [(2, reason)]
    [issue] = result.issues
    assert issue.code == "breaks_later_entry"
    assert issue.args == {
        "symbol": "QAB",
        "quantity": 10.0,
        "held": 5.0,
        "date": "2026-03-01",
        "txn_id": str(later.id),
        "issue_code": "sell_exceeds_held",
    }
    assert store.ledger().issues == [] and len(store.transactions()) == 2


def test_imported_transfers_and_splits_are_checked_like_sales(store, acct):
    store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
    text = (
        "date,type,symbol,quantity,price,ratio,account,target_account\n"
        "2026-01-01,BUY,QAA,10,10,,Fictional Taxable,\n"
        "2026-02-01,SPLIT,QAA,,,2,Fictional Taxable,\n"
        "2026-02-02,TRANSFER,QAA,20,12,,Fictional Taxable,Fictional TFSA\n"
        "2026-01-15,TRANSFER,QAA,15,11,,Fictional Taxable,Fictional TFSA\n"
        "2026-01-10,SPLIT,QAE,,,2,Fictional Taxable,\n"
    )
    preview = import_transactions(store, io.StringIO(text), dry_run=True)
    result = import_transactions(store, io.StringIO(text))
    assert (preview.skipped, preview.added) == (result.skipped, result.added)
    assert result.added == 3
    assert result.skipped == [
        (5, "2026-01-15: Transfer of 15.0000 QAA exceeds 10.0000 held"),
        (6, "2026-01-10: Split of QAE with nothing held"),
    ]
    assert [i.code for i in result.issues] == ["transfer_exceeds_held", "split_nothing_held"]
    assert store.ledger().issues == []


def test_skipped_rows_keep_line_order_with_other_skip_reasons(store, acct):
    result = run_import(
        store,
        "2026-02-01,SELL,QAA,1,10,Fictional Taxable\n"
        "2026-02-01,Mystery,QAA,1,10,Fictional Taxable\n"
        "2026-03-01,BUY,QAA,1,10,Fictional Taxable\n",
    )
    assert [line for line, _ in result.skipped] == [2, 3] == [i.line for i in result.issues]
    assert [i.code for i in result.issues] == ["sell_exceeds_held", "unknown_type"]
    assert result.added == 1


def test_problems_already_in_the_ledger_do_not_block_an_import(store, acct):
    store.add_transaction(trade(acct, TxnType.BUY, "2026-03-01", 10))
    broken = store.add_transaction(trade(acct, TxnType.SELL, "2026-02-01", 5))
    result = run_import(
        store,
        "2026-04-01,SELL,QAA,1,12,Fictional Taxable\n2026-01-01,BUY,QAD,1,10,Fictional Taxable\n",
    )
    assert (result.added, result.skipped) == (2, [])
    assert [i.txn_id for i in store.ledger().issues] == [broken.id]


def test_an_account_created_only_for_a_skipped_sale_is_not_kept(store, acct):
    result = run_import(store, "2026-02-01,SELL,QAA,1,10,Fictional New Margin\n")
    assert result.added == 0 and result.accounts_created == []
    assert store.get_account("Fictional New Margin") is None


def test_a_reimport_of_a_file_whose_sale_was_skipped_skips_it_again(store, acct):
    rows = "2026-03-01,BUY,QAA,10,10,Fictional Taxable\n2026-02-01,SELL,QAA,10,11,Fictional Taxable\n"
    run_import(store, rows)
    again = run_import(store, rows)
    assert (again.added, again.duplicates, [line for line, _ in again.skipped]) == (0, 1, [3])


@pytest.fixture
def tfsa(store):
    return store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))


TRANSFER_HEADER = "date,type,symbol,quantity,price,account,target_account\n"


def test_a_transfer_in_later_in_the_file_covers_a_backdated_sale(store, acct, tfsa):
    # The 02-01 sale alone would leave the recorded 03-01 sale short; the 02-15 transfer in
    # makes up the difference. An unrelated short row mustn't change that.
    store.add_transaction(trade(acct, TxnType.BUY, "2026-01-01", 10))
    store.add_transaction(trade(acct, TxnType.SELL, "2026-03-01", 10))
    store.add_transaction(trade(tfsa, TxnType.BUY, "2026-01-01", 10))
    rows = (
        "2026-02-01,SELL,QAA,5,11,Fictional Taxable,\n"
        "2026-02-15,TRANSFER,QAA,5,12,Fictional TFSA,Fictional Taxable\n"
        "2026-02-01,SELL,QZZ,1,10,Fictional Taxable,\n"
    )
    text = TRANSFER_HEADER + rows
    preview = import_transactions(store, io.StringIO(text), dry_run=True)
    done = import_transactions(store, io.StringIO(text), expect_fingerprint=preview.fingerprint)
    assert (preview.added, preview.skipped) == (done.added, done.skipped)
    assert done.added == 2
    assert done.skipped == [(4, "2026-02-01: Sell of 1.0000 QZZ exceeds 0.0000 held")]
    assert store.ledger().issues == []


def test_a_sale_from_shares_a_skipped_transfer_would_have_brought_is_skipped_too(store, acct, tfsa):
    store.add_transaction(trade(acct, TxnType.BUY, "2026-01-01", 5))
    text = TRANSFER_HEADER + (
        "2026-02-01,TRANSFER,QAA,10,12,Fictional Taxable,Fictional TFSA\n2026-03-01,SELL,QAA,10,13,Fictional TFSA,\n"
    )
    done = import_transactions(store, io.StringIO(text))
    assert done.added == 0
    assert done.skipped == [
        (2, "2026-02-01: Transfer of 10.0000 QAA exceeds 5.0000 held"),
        (3, "2026-03-01: Sell of 10.0000 QAA exceeds 0.0000 held"),
    ]


def test_a_row_that_would_leave_another_row_of_the_file_short_names_its_line(store, acct, tfsa):
    store.add_transaction(trade(acct, TxnType.BUY, "2026-01-01", 10))
    store.add_transaction(trade(acct, TxnType.SELL, "2026-03-01", 10))
    store.add_transaction(trade(tfsa, TxnType.BUY, "2026-01-01", 5))
    text = TRANSFER_HEADER + (
        "2026-02-01,SELL,QAA,5,11,Fictional Taxable,\n"  # waits for the transfer, then breaks line 4
        "2026-02-15,TRANSFER,QAA,5,12,Fictional TFSA,Fictional Taxable\n"
        "2026-03-05,SELL,QAA,5,13,Fictional Taxable,\n"
    )
    preview = import_transactions(store, io.StringIO(text), dry_run=True)
    done = import_transactions(store, io.StringIO(text))
    assert (preview.added, preview.skipped, preview.issues) == (done.added, done.skipped, done.issues)
    assert done.added == 2
    assert done.skipped == [(2, "line 4 on 2026-03-05 would no longer add up (Sell of 5.0000 QAA exceeds 0.0000 held)")]
    [issue] = done.issues
    assert issue.code == "breaks_later_row"
    assert issue.args == {
        "symbol": "QAA",
        "quantity": 5.0,
        "held": 0.0,
        "date": "2026-03-05",
        "issue_code": "sell_exceeds_held",
        "line": "4",
    }
    assert store.ledger().issues == []


def test_two_backdated_sales_that_together_break_a_recorded_sale_are_both_skipped(store, acct):
    store.add_transaction(trade(acct, TxnType.BUY, "2026-01-01", 10))
    store.add_transaction(trade(acct, TxnType.SELL, "2026-03-01", 6))
    result = run_import(
        store, "2026-02-01,SELL,QAA,3,11,Fictional Taxable\n2026-02-02,SELL,QAA,3,11,Fictional Taxable\n"
    )
    assert result.added == 1 and [line for line, _ in result.skipped] == [3]
    assert store.ledger().issues == []
