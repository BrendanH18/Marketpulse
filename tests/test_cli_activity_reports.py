"""Offline activity reports use visible ledger rows, never market valuations."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, Transaction, TxnType


@pytest.fixture
def reports(store, tracker, monkeypatch, fake):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "160")
    maple = store.add_account(Account(name="Maple", type="TFSA"))
    birch = store.add_account(Account(name="Birch", type="CASH"))
    hidden = store.add_account(Account(name="Hidden", type="TFSA", archived=True))
    specs = [
        (maple, TxnType.BUY, "2024-01-02", "AAPL", "USD", 'Winter, "snow"\nsecond line'),
        (maple, TxnType.BUY, "2024-02-02", "XEQT.TO", "CAD", ""),
        (birch, TxnType.DEPOSIT, "2024-02-03", "", "CAD", "   "),
        (hidden, TxnType.BUY, "2024-01-02", "SECRET", "CAD", "Hidden note"),
    ]
    rows = [
        store.add_transaction(
            Transaction(
                account_id=a.saved_id,
                type=t,
                date=d,
                symbol=s,
                currency=c,
                note=n,
                quantity=1 if t == TxnType.BUY else 0,
                price=100,
                amount=1234,
            )
        )
        for a, t, d, s, c, n in specs
    ]
    rows.append(
        store.add_transaction(
            Transaction(
                account_id=maple.saved_id,
                target_account_id=hidden.saved_id,
                type=TxnType.TRANSFER,
                date="2024-02-04",
                symbol="AAPL",
                quantity=1,
                currency="USD",
            )
        )
    )
    fake.offline = True
    calls = len(fake.calls)
    runner = CliRunner()

    def invoke(*args):
        result = runner.invoke(main, ["activity", *args], catch_exceptions=False)
        assert len(fake.calls) == calls
        return result

    return invoke, rows


def test_csv_quotes_notes_and_obeys_visibility_order_and_paging(reports):
    invoke, txns = reports
    result = invoke("--csv", "--all", "--oldest-first")
    assert result.exit_code == 0
    rows = list(csv.DictReader(io.StringIO(result.output)))
    assert [int(r["id"]) for r in rows] == [t.id for t in txns[:3]]
    assert rows[0]["note"] == txns[0].note
    assert rows[0]["account"] == "Maple"
    assert rows[0]["revision"]
    assert "Hidden" not in result.output and "SECRET" not in result.output
    page = list(csv.DictReader(io.StringIO(invoke("--csv", "--offset", "1", "--limit", "1").output)))
    assert [int(r["id"]) for r in page] == [txns[1].id]
    empty = invoke("--csv", "--symbol", "MISSING")
    assert len(empty.output.splitlines()) == 1
    assert list(csv.DictReader(io.StringIO(empty.output))) == []


def test_count_filters_before_paging_and_does_not_create_accounts(reports, store):
    invoke, _ = reports
    assert invoke("--count", "--limit", "1", "--offset", "10").output == "3\n"
    assert invoke("--count", "--account", "Maple", "--currency", "usd", "--since", "2024-01-01").output == "1\n"
    assert invoke("--count", "--search", "missing").output == "0\n"
    before = len(store.accounts(include_archived=True))
    assert invoke("--count", "--account", "Missing").exit_code == 1
    assert len(store.accounts(include_archived=True)) == before


@pytest.mark.parametrize(
    "group,expected",
    [
        ("type", {"BUY": 2, "DEPOSIT": 1}),
        ("currency", {"CAD": 2, "USD": 1}),
        ("month", {"2024-01": 1, "2024-02": 2}),
        ("symbol", {"": 1, "AAPL": 1, "XEQT.TO": 1}),
    ],
)
def test_summary_groups_all_matching_visible_rows(reports, group, expected):
    invoke, _ = reports
    result = invoke("--summary", group, "--json", "--limit", "1", "--offset", "100")
    assert result.exit_code == 0
    assert {row["group"]: row["count"] for row in json.loads(result.output)} == expected
    human = invoke("--summary", group)
    assert human.exit_code == 0 and "Matching activity" in human.output
    assert json.loads(invoke("--summary", group, "--json", "--search", "missing").output) == []


def test_summary_account_identifies_account_and_obeys_filters(reports):
    invoke, rows = reports
    result = json.loads(invoke("--summary", "account", "--json").output)
    assert result == [
        {"group": str(rows[0].account_id), "count": 2, "account": "Maple"},
        {"group": str(rows[2].account_id), "count": 1, "account": "Birch"},
    ]
    assert json.loads(invoke("--summary", "symbol", "--json", "--currency", "usd").output) == [
        {"group": "AAPL", "count": 1}
    ]


def test_note_and_inclusive_id_filters_compose(reports):
    invoke, rows = reports
    assert invoke("--has-note", "--count").output == "1\n"
    assert invoke("--no-note", "--count").output == "2\n"
    assert invoke("--min-id", str(rows[1].id), "--max-id", str(rows[2].id), "--count").output == "2\n"
    assert invoke("--min-id", str(rows[0].id), "--max-id", str(rows[0].id), "--has-note", "--count").output == "1\n"
    assert invoke("--min-id", "999", "--json").output == "[]\n"


@pytest.mark.parametrize(
    "args",
    [
        ("--csv", "--json"),
        ("--count", "--json"),
        ("--count", "--csv"),
        ("--count", "--summary", "type"),
        ("--csv", "--summary", "type"),
        ("--min-id", "2", "--max-id", "1"),
        ("--min-id", "0"),
        ("--max-id", "-1"),
    ],
)
def test_invalid_report_options_are_usage_errors(reports, args):
    invoke, _ = reports
    assert invoke(*args).exit_code == 2


def test_report_machine_output_remains_unmasked_in_privacy(reports, tracker, monkeypatch):
    invoke, _ = reports
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    tracker.config.privacy = True
    rows = list(csv.DictReader(io.StringIO(invoke("--csv", "--oldest-first").output)))
    assert rows[0]["price"] == "100.0" or rows[0]["price"] == "100"
    assert invoke("--count").output == "3\n"
    assert "1234" not in invoke("--summary", "type").output
