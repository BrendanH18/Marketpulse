"""Ledger maintenance for `undo` and `txn` (#130, items 21–30) on a fictional ledger."""

import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Transaction, TxnType


def add(store, acct, kind, day, symbol="", qty=0.0, price=0.0, **extra):
    return store.add_transaction(
        Transaction(
            account_id=acct.saved_id,
            type=kind,
            date=day,
            symbol=symbol,
            quantity=qty,
            price=price,
            currency="CAD",
            **extra,
        )
    )


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "160")
    return lambda *args, **kw: CliRunner().invoke(main, list(args), catch_exceptions=False, **kw)


@pytest.fixture
def ledger(store):
    """Ids 1–9: an entry in an account archived since, a cash-tracked taxable account with a
    deposit, buy, dividend and sale, a TFSA with two buys, plus two ledger issues (an oversold
    VFV.TO in the TFSA, a split of a symbol the taxable account never held)."""
    maple = store.add_account(Account(name="Maple Cash", type=AccountType.NONREG, track_cash=True))
    birch = store.add_account(Account(name="Birch TFSA", type=AccountType.TFSA))
    cedar = store.add_account(Account(name="Old Cedar", type=AccountType.MARGIN))
    add(store, cedar, TxnType.BUY, "2024-12-02", "ZAG.TO", 10, 15)  # 1
    add(store, maple, TxnType.DEPOSIT, "2025-01-02", amount=5000)  # 2
    add(store, maple, TxnType.BUY, "2025-01-03", "XEQT.TO", 50, 30, fees=5, note="first lot")  # 3
    add(store, birch, TxnType.BUY, "2025-01-06", "VFV.TO", 10, 100)  # 4
    add(store, birch, TxnType.SELL, "2025-02-03", "VFV.TO", 20, 105)  # 5: oversold
    add(store, maple, TxnType.DIVIDEND, "2025-03-31", "XEQT.TO", amount=25)  # 6
    add(store, maple, TxnType.SELL, "2025-04-01", "XEQT.TO", 20, 32)  # 7
    add(store, maple, TxnType.SPLIT, "2025-06-02", "ZCN.TO", ratio=2)  # 8: nothing held
    add(store, birch, TxnType.BUY, "2025-05-01", "VFV.TO", 5, 110, note="top-up")  # 9
    cedar.archived = True
    store.update_account(cedar)
    return store


def ids(store) -> list[int]:
    return sorted(t.saved_id for t in store.transactions())


def revision(store, txn_id: int) -> str:
    return next(t for t in store.transactions() if t.id == txn_id).revision(store.restore_id)


# ── defaults stay byte-for-byte the same ──────────────────────────────────────

SHOW_3 = (
    "Transaction #3                        \n                                      \n"
    " Field               Value            \n ──────────────────────────────────── \n"
    " account_id          1                \n type                BUY              \n"
    " date                2025-01-03       \n symbol              XEQT.TO          \n"
    " quantity            50.0             \n price               30.0             \n"
    " amount              0.0              \n fees                5.0              \n"
    " currency            CAD              \n note                first lot        \n"
    " ratio               0.0              \n target_account_id   —                \n"
    " id                  3                \n account             Maple Cash       \n"
    " target_account      —                \n revision            REVISION__REVISI \n"
    "                                      \n"
)
SHOW_3_JSON = (
    '{"account_id": 1, "type": "BUY", "date": "2025-01-03", "symbol": "XEQT.TO", "quantity": 50.0, '
    '"price": 30.0, "amount": 0.0, "fees": 5.0, "currency": "CAD", "note": "first lot", "ratio": 0.0, '
    '"target_account_id": null, "id": 3, "account": "Maple Cash", "target_account": null, '
    '"revision": "REVISION__REVISI"}\n'
)
UNDO_YES = (
    "                                                                                            \n"
    " ID   Date         Account      Type   Symbol   Qty    Price   Amount   Fees   Ccy   Note   \n"
    " ────────────────────────────────────────────────────────────────────────────────────────── \n"
    "  9   2025-05-01   Birch TFSA   BUY    VFV.TO     5   110.00   550.00      —   CAD   top-up \n"
    "                                                                                            \n"
    "✓ Deleted transaction #9.\n"
)
UNDO_DECLINED = (
    "                                                                                          \n"
    " ID   Date         Account      Type    Symbol   Qty   Price   Amount   Fees   Ccy   Note \n"
    " ──────────────────────────────────────────────────────────────────────────────────────── \n"
    "  8   2025-06-02   Maple Cash   SPLIT   ZCN.TO    ×2       —        —      —   CAD        \n"
    "                                                                                          \n"
    "Delete this transaction? [y/N]: n\n"
)
DELETE_6 = (
    "                                                                                              \n"
    " ID   Date         Account      Type       Symbol    Qty   Price   Amount   Fees   Ccy   Note \n"
    " ──────────────────────────────────────────────────────────────────────────────────────────── \n"
    "  6   2025-03-31   Maple Cash   DIVIDEND   XEQT.TO     —       —    25.00      —   CAD        \n"
    "                                                                                              \n"
    "✓ Deleted #6.\n"
)
CHECK = (
    "! 2 ledger issue(s).\n"
    "! #5 2025-02-03: Sell of 20.0000 VFV.TO exceeds 10.0000 held\n"
    "! #8 2025-06-02: Split of ZCN.TO with nothing held\n"
)
CHECK_JSON = (
    '{"ok": false, "issues": [{"txn_id": 5, "date": "2025-02-03", "message": "Sell of 20.0000 VFV.TO exceeds '
    '10.0000 held", "code": "sell_exceeds_held", "args": {"symbol": "VFV.TO", "quantity": 20.0, "held": 10.0}}, '
    '{"txn_id": 8, "date": "2025-06-02", "message": "Split of ZCN.TO with nothing held", "code": '
    '"split_nothing_held", "args": {"symbol": "ZCN.TO"}}]}\n'
)


def test_plain_show_and_check_are_unchanged(cli, ledger):
    rev = revision(ledger, 3)
    assert cli("txn", "show", "3").output == SHOW_3.replace("REVISION__REVISI", rev)
    assert cli("txn", "show", "--json", "3").output == SHOW_3_JSON.replace("REVISION__REVISI", rev)
    result = cli("txn", "check")
    assert (result.exit_code, result.output) == (1, CHECK)
    assert cli("txn", "check", "--json").output == CHECK_JSON


def test_plain_undo_and_delete_are_unchanged(cli, ledger):
    assert cli("undo", "-y").output == UNDO_YES
    assert cli("undo", input="n\n").output == UNDO_DECLINED
    assert cli("txn", "delete", "-y", "--", "6").output == DELETE_6
    assert ids(ledger) == [1, 2, 3, 4, 5, 7, 8]


# ── 21. undo --dry-run ─────────────────────────────────────────────────────────


def test_undo_dry_run_deletes_nothing(cli, ledger):
    result = cli("undo", "--dry-run")
    assert result.exit_code == 0
    assert "top-up" in result.output
    assert "Dry run: would delete transaction #9. Nothing was changed." in result.output
    assert "[y/N]" not in result.output
    assert ids(ledger) == list(range(1, 10))


def test_undo_dry_run_reports_the_refusal(cli, ledger):
    birch = ledger.get_account("Birch TFSA")
    add(ledger, birch, TxnType.BUY, "2025-01-05", "VFV.TO", 10, 95)  # 10: the oversold sale now adds up
    result = cli("undo", "--dry-run")
    assert result.exit_code == 1
    assert "Not deleted: transaction #5 on 2025-02-03 would no longer add up" in result.output
    assert ids(ledger) == list(range(1, 11))


# ── 22. undo -a / -s ───────────────────────────────────────────────────────────


def test_undo_latest_matching_account_or_symbol(cli, ledger):
    result = cli("undo", "-a", "maple cash", "-y")
    assert result.exit_code == 0 and "Deleted transaction #8." in result.output
    result = cli("undo", "--symbol", " xeqt.to ", "-y")
    assert result.exit_code == 0 and "Deleted transaction #7." in result.output
    assert cli("undo", "-a", "Birch TFSA", "-s", "VFV.TO", "-y").output.endswith("Deleted transaction #9.\n")
    assert ids(ledger) == [1, 2, 3, 4, 5, 6]


def test_undo_filters_refuse_archived_unknown_and_blank(cli, ledger):
    assert "No active account 'Old Cedar'" in cli("undo", "-a", "Old Cedar", "-y").output
    assert "No matching transaction to undo." in cli("undo", "-s", "ZAG.TO", "-y").output  # archived only
    assert cli("undo", "-s", " ", "-y").exit_code == 2
    assert ids(ledger) == list(range(1, 10))


# ── 23. undo --json ────────────────────────────────────────────────────────────


def test_undo_json_reports_the_deleted_entry(cli, ledger):
    result = cli("undo", "--json", "-y", "-s", "XEQT.TO")
    payload = json.loads(result.output)
    assert result.exit_code == 0
    assert payload["deleted"] is True and payload["ok"] is True and payload["dry_run"] is False
    assert payload["error"] is None
    assert payload["transaction"]["id"] == 7 and payload["transaction"]["account"] == "Maple Cash"
    assert ids(ledger) == [1, 2, 3, 4, 5, 6, 8, 9]


def test_undo_json_dry_run_and_refusal(cli, ledger):
    payload = json.loads(cli("undo", "--json", "--dry-run").output)
    assert (payload["dry_run"], payload["ok"], payload["deleted"]) == (True, True, False)
    birch = ledger.get_account("Birch TFSA")
    add(ledger, birch, TxnType.BUY, "2025-01-05", "VFV.TO", 10, 95)
    for args in (("--dry-run",), ("-y",)):
        result = cli("undo", "--json", *args)
        payload = json.loads(result.output)
        assert result.exit_code == 1 and payload["ok"] is False and payload["deleted"] is False
        assert "would no longer add up" in payload["error"]
    assert cli("undo", "--json").exit_code == 2  # can't prompt for confirmation
    assert ids(ledger) == list(range(1, 11))


# ── 24. txn show several ids ───────────────────────────────────────────────────


def test_txn_show_several_ids(cli, ledger):
    payload = json.loads(cli("txn", "show", "--json", "4", "3", "4").output)
    assert [row["id"] for row in payload] == [4, 3]
    text = cli("txn", "show", "3", "9").output
    assert text.index("Transaction #3") < text.index("Transaction #9")
    result = cli("txn", "show", "3", "99")
    assert result.exit_code == 1 and "No active transaction #99." in result.output
    assert "Transaction #3" not in result.output
    assert "No active transaction #1." in cli("txn", "show", "3", "1").output  # archived account


# ── 25. txn show --with-effect ─────────────────────────────────────────────────


def test_txn_show_with_effect_json(cli, ledger):
    payload = json.loads(cli("txn", "show", "--json", "--with-effect", "7").output)
    holding, cash = payload["effect"]
    assert holding["kind"] == "holding" and holding["symbol"] == "XEQT.TO" and holding["account"] == "Maple Cash"
    assert holding["before"] == {"quantity": 50.0, "book": pytest.approx(1505.0)}
    assert holding["after"] == {"quantity": 30.0, "book": pytest.approx(903.0)}
    assert cash["kind"] == "cash" and cash["currency"] == "CAD"
    assert cash["before"]["balance"] == pytest.approx(5000 - 1505 + 25)
    assert cash["after"]["balance"] == pytest.approx(5000 - 1505 + 25 + 640)
    plain = json.loads(cli("txn", "show", "--json", "7").output)
    assert "effect" not in plain


def test_txn_show_with_effect_table_and_no_effect(cli, ledger, tracker):
    text = cli("txn", "show", "--with-effect", "7", "8").output
    assert "Effect of #7" in text and "XEQT.TO units" in text and "Cash (CAD)" in text
    assert "$1,505.00" in text and "$903.00" in text
    assert "#8 changes no holding or tracked cash balance." in text
    tracker.config.privacy = True
    masked = cli("txn", "show", "--with-effect", "7").output
    assert "Effect of #7" in masked and "$903.00" not in masked and "••••" in masked


# ── 26. txn check --code ───────────────────────────────────────────────────────


def test_txn_check_code_filter(cli, ledger):
    result = cli("txn", "check", "--code", "SELL_EXCEEDS_HELD")
    assert result.exit_code == 1
    assert "1 ledger issue(s)." in result.output and "#5" in result.output and "#8" not in result.output
    payload = json.loads(cli("txn", "check", "--json", "--code", "split_nothing_held").output)
    assert [i["txn_id"] for i in payload["issues"]] == [8]
    result = cli("txn", "check", "--code", "transfer_nothing_held")
    assert (result.exit_code, result.output) == (0, "✓ No matching ledger issues.\n")
    assert cli("txn", "check", "--code", " ").exit_code == 2


# ── 27. txn check -a ───────────────────────────────────────────────────────────


def test_txn_check_account_filter(cli, ledger):
    payload = json.loads(cli("txn", "check", "--json", "-a", "Birch TFSA").output)
    assert [i["txn_id"] for i in payload["issues"]] == [5]
    result = cli("txn", "check", "-a", "maple cash", "--code", "sell_exceeds_held")
    assert (result.exit_code, result.output) == (0, "✓ No matching ledger issues.\n")
    assert "No active account 'Old Cedar'" in cli("txn", "check", "-a", "Old Cedar").output


# ── 28. txn edit --dry-run ─────────────────────────────────────────────────────


def test_txn_edit_dry_run_shows_the_diff(cli, ledger):
    before = [t.revision(ledger.restore_id) for t in ledger.transactions()]
    result = cli("txn", "edit", "--dry-run", "--quantity", "25", "--", "4")
    assert result.exit_code == 0
    assert "Transaction #4 (dry run)" in result.output
    assert "quantity" in result.output and "10.0" in result.output and "25.0" in result.output
    assert "price" not in result.output
    assert "Dry run: would update #4. Nothing was changed." in result.output
    moved = cli("txn", "edit", "--dry-run", "--account", "Maple Cash", "--", "4").output
    assert "account" in moved and "Birch TFSA" in moved and "Maple Cash" in moved
    result = cli("txn", "edit", "--dry-run", "--note", "renamed", "--", "3")
    assert "first lot" in result.output and "renamed" in result.output
    assert [t.revision(ledger.restore_id) for t in ledger.transactions()] == before


def test_txn_edit_dry_run_reports_refusals(cli, ledger):
    result = cli("txn", "edit", "--dry-run", "--quantity", "60", "--", "7")
    assert result.exit_code == 1 and "Not saved: on 2025-04-01, sell of" in result.output
    result = cli("txn", "edit", "--dry-run", "--quantity", "-1", "--", "7")
    assert result.exit_code == 1 and "Quantity must be positive." in result.output
    stale = cli("txn", "edit", "--dry-run", "--note", "x", "--revision", "0000000000000000", "--", "7")
    assert stale.exit_code == 1 and "has changed since it was loaded" in stale.output
    result = cli("txn", "edit", "--dry-run", "--", "7")
    assert result.exit_code == 0 and "No changes." in result.output
    assert next(t for t in ledger.transactions() if t.id == 7).quantity == 20


def test_txn_edit_dry_run_with_new_symbol_works_out_the_currency(cli, ledger, tracker):
    tracker.config.privacy = True
    result = cli("txn", "edit", "--dry-run", "--symbol", "AAPL", "--quantity", "3", "--", "4")
    assert result.exit_code == 0 and "AAPL" in result.output and "USD" in result.output
    assert "••••" in result.output and "10.0" not in result.output


# ── 29. txn delete several ids ─────────────────────────────────────────────────


def test_txn_delete_several_ids_together(cli, ledger):
    refused = cli("txn", "delete", "-y", "--", "3")
    assert refused.exit_code == 1 and ids(ledger) == list(range(1, 10))
    result = cli("txn", "delete", "-y", "--", "3", "7")  # the sale goes first, so the buy can follow
    assert result.exit_code == 0 and result.output.endswith("✓ Deleted #3, #7.\n")
    assert ids(ledger) == [1, 2, 4, 5, 6, 8, 9]


def test_txn_delete_several_ids_all_or_nothing(cli, ledger):
    result = cli("txn", "delete", "-y", "--", "3", "6")
    assert result.exit_code == 1
    assert "transaction #7 on 2025-04-01 would no longer add up" in result.output
    assert "Nothing was deleted." in result.output
    declined = cli("txn", "delete", "--", "6", "9", input="n\n")
    assert declined.output.count("Delete these 2 transactions? [y/N]") == 1
    assert ids(ledger) == list(range(1, 10))
    assert cli("txn", "delete", "-y", "--revision", "abc", "--", "6", "9").exit_code == 2
    assert "No transaction #42." in cli("txn", "delete", "-y", "--", "6", "42").output
    assert ids(ledger) == list(range(1, 10))


# ── 30. txn delete --dry-run ───────────────────────────────────────────────────


def test_txn_delete_dry_run(cli, ledger):
    result = cli("txn", "delete", "--dry-run", "--", "3")
    assert result.exit_code == 1 and "Not deleted: transaction #7" in result.output
    result = cli("txn", "delete", "--dry-run", "--", "3", "7")
    assert result.exit_code == 0 and "Dry run: would delete #3, #7. Nothing was changed." in result.output
    stale = cli("txn", "delete", "--dry-run", "--revision", "0000000000000000", "--", "6")
    assert stale.exit_code == 1 and "has changed since it was loaded" in stale.output
    assert ids(ledger) == list(range(1, 10))
