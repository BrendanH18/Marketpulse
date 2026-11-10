"""Offline ledger browsing and inspection on fictional records."""

import json
from dataclasses import asdict

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Transaction, TxnType


@pytest.fixture
def history_cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "200")
    runner = CliRunner()
    return lambda *args: runner.invoke(main, list(args), catch_exceptions=False)


@pytest.fixture
def history_rows(store):
    maple = store.add_account(Account(name="Fictional Maple", type=AccountType.TFSA))
    birch = store.add_account(Account(name="Fictional Birch"))
    rows = [
        Transaction(
            maple.saved_id,
            TxnType.BUY,
            "2024-01-02",
            "XEQT.TO",
            quantity=3,
            price=30,
            currency="CAD",
            note="Winter seed",
        ),
        Transaction(
            maple.saved_id, TxnType.DIVIDEND, "2024-01-03", "XEQT.TO", amount=7.25, currency="CAD", note="Winter income"
        ),
        Transaction(
            birch.saved_id, TxnType.BUY, "2024-01-03", "AAPL", quantity=2, price=150, currency="USD", note="Spring seed"
        ),
        Transaction(
            birch.saved_id, TxnType.DEPOSIT, "2024-02-01", amount=1234.56, currency="CAD", note="Spring savings"
        ),
    ]
    for row in rows:
        store.add_transaction(row)
    return rows


def _records(cli, *args):
    result = cli("activity", "--json", *args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_activity_date_boundaries_and_composed_filters(history_cli, history_rows, fake):
    calls = len(fake.calls)
    assert [r["id"] for r in _records(history_cli, "--since", "2024-01-03", "--until", "2024-01-03")] == [3, 2]
    assert [r["id"] for r in _records(history_cli, "--since", "2024-01-03")] == [4, 3, 2]
    assert [r["id"] for r in _records(history_cli, "--until", "2024-01-03")] == [3, 2, 1]
    result = _records(
        history_cli,
        "--since",
        "2024-01-02",
        "--until",
        "2024-01-03",
        "--type",
        "buy",
        "--type",
        "dividend",
        "--search",
        "WINTER",
        "--currency",
        "cad",
        "--account",
        "tfsa",
        "--symbol",
        "xeqt.to",
    )
    assert [r["id"] for r in result] == [2, 1]
    assert len(fake.calls) == calls


def test_activity_text_matches_symbol_note_and_account(history_cli, history_rows):
    assert [r["id"] for r in _records(history_cli, "--search", "aapl")] == [3]
    assert [r["id"] for r in _records(history_cli, "--search", "spring")] == [4, 3]
    assert [r["id"] for r in _records(history_cli, "--search", "mAPLe")] == [2, 1]
    assert [r["id"] for r in _records(history_cli, "--currency", "usd")] == [3]
    assert _records(history_cli, "--type", "SELL") == []
    assert "No matching transactions." in history_cli("activity", "--search", "no match").output


def test_activity_paging_is_after_filter_and_order_and_all_respects_offset(history_cli, history_rows):
    assert [r["id"] for r in _records(history_cli, "--search", "seed", "--limit", "1", "--offset", "1")] == [1]
    assert [r["id"] for r in _records(history_cli, "--oldest-first", "--limit", "1", "--offset", "1")] == [2]
    assert [r["id"] for r in _records(history_cli, "--all", "--limit", "1", "--offset", "1")] == [3, 2, 1]
    assert _records(history_cli, "--offset", "10") == []
    human = history_cli("activity", "--oldest-first", "--all").output
    assert human.index("Winter seed") < human.index("Winter income") < human.index("Spring seed")
    newest = history_cli("activity", "--all").output
    assert newest.index("Spring seed") < newest.index("Winter income") < newest.index("Winter seed")


@pytest.mark.parametrize(
    "args",
    [
        ("--since", "invalid"),
        ("--until", "2024-13-01"),
        ("--since", "2024-02-01", "--until", "2024-01-01"),
        ("--type", "nope"),
        ("--limit", "0"),
        ("--limit", "-1"),
        ("--offset", "-1"),
    ],
)
def test_activity_usage_errors_do_not_create_accounts(history_cli, store, fake, args):
    result = history_cli("activity", *args)
    assert result.exit_code == 2
    assert store.accounts() == [] and store.transactions() == [] and fake.calls == []


def test_empty_activity_and_missing_read_account_never_create_one(history_cli, store, fake):
    assert _records(history_cli) == []
    assert "No transactions yet." in history_cli("activity").output
    assert history_cli("activity", "--account", "missing", "--json").exit_code == 1
    assert history_cli("txn", "show", "1").exit_code == 1
    assert json.loads(history_cli("txn", "check", "--json").output) == {"ok": True, "issues": []}
    assert store.accounts() == [] and store.transactions() == [] and fake.calls == []


def test_activity_json_has_complete_unmasked_records_in_privacy_mode(history_cli, history_rows):
    history_cli("config", "set", "privacy", "true")
    result = _records(history_cli, "--oldest-first")
    assert result[0] == {
        **asdict(history_rows[0]),
        "account": "Fictional Maple",
        "target_account": None,
        "revision": result[0]["revision"],
    }
    assert result[3]["amount"] == 1234.56
    human = history_cli("activity").output
    assert "1,234.56" not in human and "••••" in human


def test_txn_show_includes_full_note_and_revision_usable_for_safe_edits(history_cli, history_rows, store, fake):
    row = history_rows[0]
    row.note = "Fictional complete note " * 4
    store.update_transaction(row)
    result = history_cli("txn", "show", str(row.id), "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["note"] == row.note and payload["quantity"] == 3
    assert payload["revision"] == store.transactions()[0].revision(store.restore_id)
    assert "Fictional complete note" in history_cli("txn", "show", str(row.id)).output
    assert (
        history_cli("txn", "edit", str(row.id), "--note", "Updated", "--revision", payload["revision"]).exit_code == 0
    )
    stale = history_cli("txn", "edit", str(row.id), "--note", "Stale", "--revision", payload["revision"])
    assert stale.exit_code == 1
    assert fake.calls == []


def test_txn_show_human_masks_financial_fields(history_cli, history_rows):
    history_cli("config", "set", "privacy", "true")
    human = history_cli("txn", "show", str(history_rows[3].id)).output
    assert "1234.56" not in human and "••••" in human
    assert json.loads(history_cli("txn", "show", str(history_rows[3].id), "--json").output)["amount"] == 1234.56


def test_archived_accounts_and_transfer_endpoints_stay_hidden(history_cli, history_rows, store):
    archived = store.add_account(Account(name="Hidden Fictional Cedar", archived=True))
    hidden = store.add_transaction(
        Transaction(archived.saved_id, TxnType.DEPOSIT, "2024-01-01", amount=3456, currency="CAD")
    )
    transfer = store.add_transaction(
        Transaction(
            history_rows[0].account_id,
            TxnType.TRANSFER,
            "2024-01-04",
            "XEQT.TO",
            quantity=1,
            target_account_id=archived.saved_id,
        )
    )
    assert [r["id"] for r in _records(history_cli, "--all")] == [4, 3, 2, 1]
    assert "Cedar" not in history_cli("activity", "--all").output
    assert _records(history_cli, "--search", "Cedar") == []
    assert history_cli("activity", "--account", str(archived.saved_id)).exit_code == 1
    for row in (hidden, transfer):
        result = history_cli("txn", "show", str(row.id), "--json")
        assert result.exit_code == 1 and "Cedar" not in result.output


def test_activity_search_and_account_filter_include_transfer_destination(history_cli, history_rows, store):
    source = history_rows[0].account_id
    target = history_rows[2].account_id
    transfer = store.add_transaction(
        Transaction(source, TxnType.TRANSFER, "2024-01-04", "XEQT.TO", quantity=1, target_account_id=target)
    )
    records = _records(history_cli, "--type", "TRANSFER", "--search", "Birch", "--account", str(target))
    assert [r["id"] for r in records] == [transfer.id]
    assert records[0]["account"] == "Fictional Maple"
    assert records[0]["target_account"] == "Fictional Birch"


@pytest.mark.parametrize("command", [("txn", "show", "1", "--json"), ("activity", "--json")])
def test_read_revision_stays_stale_when_restore_generation_changes_during_read(
    history_cli, history_rows, store, monkeypatch, command
):
    from marketpulse.db import RESTORE_ID_KEY

    original = store.transactions

    def restored_read(*args, **kwargs):
        store.set_meta(RESTORE_ID_KEY, "fictional-restore")
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "transactions", restored_read)
    result = history_cli(*command)
    assert result.exit_code == 0
    payload = json.loads(result.output)
    record = payload if isinstance(payload, dict) else next(r for r in payload if r["id"] == 1)
    row = next(t for t in original() if t.id == 1)
    assert record["revision"] == row.revision("")
    assert record["revision"] != row.revision(store.restore_id)


def test_txn_check_reports_existing_ledger_issues_and_exit_status(history_cli, store, fake):
    acct = store.add_account(Account(name="Fictional Elm"))
    row = store.add_transaction(
        Transaction(acct.saved_id, TxnType.SELL, "2024-01-01", "AAPL", quantity=17, price=123.45, currency="USD")
    )
    result = history_cli("txn", "check", "--json")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["issues"][0]["txn_id"] == row.id
    assert payload["issues"][0]["code"] == "sell_exceeds_held"
    human = history_cli("txn", "check")
    assert human.exit_code == 1 and "17.0000 AAPL" in human.output
    history_cli("config", "set", "privacy", "true")
    assert "17.0000" not in history_cli("txn", "check").output
    assert fake.calls == []


def test_txn_check_anonymizes_hidden_issues_without_claiming_consistency(history_cli, store):
    acct = store.add_account(Account(name="Fictional hidden account", archived=True))
    store.add_transaction(Transaction(acct.saved_id, TxnType.SELL, "2024-01-01", "SECRET", quantity=987, price=123.45))
    result = history_cli("txn", "check", "--json")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload == {
        "ok": False,
        "issues": [
            {
                "txn_id": None,
                "date": "",
                "message": "Issue in a hidden account.",
                "code": "hidden_account_issue",
                "args": {},
            }
        ],
    }
    assert "SECRET" not in history_cli("activity").output
