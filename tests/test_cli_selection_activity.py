"""Recorded-value selection composes without quotes or disclosure of archived accounts."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.config import Config
from marketpulse.models import Account, AccountType, Transaction, TxnType


@pytest.fixture
def selection(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    first = store.add_account(Account(name="Fictional Maple", type=AccountType.TFSA))
    second = store.add_account(Account(name="Fictional Birch", type=AccountType.RRSP))
    hidden = store.add_account(Account(name="Fictional Hidden", archived=True))
    for owner, kind, day, amount, fees, ccy, target in [
        (first, TxnType.BUY, "2024-01-02", 0, 2, "CAD", None),
        (first, TxnType.DEPOSIT, "2024-04-03", 100, 0, "CAD", None),
        (second, TxnType.DEPOSIT, "2025-01-04", 200, 5, "USD", None),
        (first, TxnType.TRANSFER, "2025-07-05", 50, 0, "CAD", second),
        (hidden, TxnType.DEPOSIT, "2024-01-02", 100, 5, "CAD", None),
        (first, TxnType.TRANSFER, "2024-01-02", 100, 5, "CAD", hidden),
    ]:
        store.add_transaction(
            Transaction(
                owner.saved_id,
                kind,
                day,
                symbol="AAA" if kind.needs_symbol else "",
                quantity=1,
                price=123,
                amount=amount,
                fees=fees,
                currency=ccy,
                target_account_id=target.saved_id if target else None,
            )
        )
    fake.offline = True
    before = len(fake.calls)
    runner = CliRunner()

    def invoke(*args):
        result = runner.invoke(main, ["activity", *args], catch_exceptions=False)
        assert len(fake.calls) == before
        return result

    return invoke


def rows(invoke, *args):
    result = invoke("--json", *args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def ids(invoke, *args):
    return [row["id"] for row in rows(invoke, *args)]


def test_month_and_repeated_exclusions(selection):
    assert ids(selection, "--month", "1") == [3, 1]
    assert ids(selection, "--month", "1", "--year", "2024") == [1]
    assert ids(selection, "--exclude-currency", " usd ") == [4, 2, 1]
    assert ids(selection, "--exclude-currency", "USD", "--exclude-currency", "cAd") == []
    assert ids(selection, "--exclude-date", "2024-01-02", "--exclude-date", "2025-07-05") == [3, 2]
    assert ids(selection, "--month", "1", "--exclude-currency", "USD", "--exclude-date", "2024-01-02") == []


def test_amount_bounds_are_inclusive_raw_recorded_amounts(selection):
    assert ids(selection, "--min-amount", "100") == [3, 2]
    assert ids(selection, "--max-amount", "100") == [4, 2, 1]
    assert ids(selection, "--min-amount", "100", "--max-amount", "100") == [2]
    # BUY consideration is 123; its recorded amount remains zero.
    assert ids(selection, "--type", "BUY", "--max-amount", "0") == [1]
    assert selection("--min-amount", "0", "--count", "--offset", "99").output == "4\n"


def test_fee_bounds_and_presence(selection):
    assert ids(selection, "--min-fees", "2") == [3, 1]
    assert ids(selection, "--max-fees", "2") == [4, 2, 1]
    assert ids(selection, "--min-fees", "2", "--max-fees", "2") == [1]
    assert ids(selection, "--has-fees") == [3, 1]
    assert ids(selection, "--no-fees") == [4, 2]
    assert ids(selection, "--has-fees", "--max-fees", "0") == []
    assert ids(selection, "--no-fees", "--min-fees", "2") == []


def test_summaries_count_all_filtered_rows_before_paging(selection):
    assert rows(selection, "--summary", "quarter", "--limit", "1", "--offset", "99") == [
        {"group": "2024-Q1", "count": 1},
        {"group": "2024-Q2", "count": 1},
        {"group": "2025-Q1", "count": 1},
        {"group": "2025-Q3", "count": 1},
    ]
    assert rows(selection, "--summary", "account-type", "--summary-sort", "count") == [
        {"group": "TFSA", "count": 3},
        {"group": "RRSP", "count": 1},
    ]
    assert rows(selection, "--summary", "quarter", "--month", "1", "--has-fees") == [
        {"group": "2024-Q1", "count": 1},
        {"group": "2025-Q1", "count": 1},
    ]
    result = selection("--summary", "account-type", "--min-fees", "2", "--csv")
    assert list(csv.DictReader(io.StringIO(result.output))) == [
        {"group": "RRSP", "count": "1"},
        {"group": "TFSA", "count": "1"},
    ]
    assert rows(selection, "--summary", "quarter", "--month", "12") == []
    assert selection("--summary", "account-type", "--has-fees").exit_code == 0


def test_paged_csv_archive_guards_and_privacy(selection):
    result = selection("--has-fees", "--csv", "--limit", "1", "--offset", "1")
    assert [row["id"] for row in csv.DictReader(io.StringIO(result.output))] == ["1"]
    page = rows(selection, "--min-amount", "50", "--page-info", "--limit", "1")
    assert page["total"] == 3 and page["returned"] == 1 and page["next_offset"] == 1
    config = Config.load()
    config.privacy = True
    config.save()
    human = selection("--min-amount", "200", "--has-fees")
    assert human.exit_code == 0 and "200.00" not in human.output
    assert rows(selection, "--min-amount", "200")[0]["amount"] == 200
    assert "Hidden" not in selection("--has-fees").output


@pytest.mark.parametrize(
    "args",
    [
        ("--month", "0"),
        ("--month", "13"),
        ("--exclude-date", "2024-02-30"),
        ("--min-amount", "10", "--max-amount", "1"),
        ("--min-fees", "2", "--max-fees", "1"),
        *[
            (flag, value)
            for flag in ("--min-amount", "--max-amount", "--min-fees", "--max-fees")
            for value in ("nan", "inf", "-inf")
        ],
    ],
)
def test_invalid_selection_fails_before_opening_database(monkeypatch, args):
    def unexpected(*args, **kwargs):
        raise AssertionError("invalid input opened database")

    monkeypatch.setattr("marketpulse.services.Tracker.open", unexpected)
    result = CliRunner().invoke(main, ["activity", *args], catch_exceptions=False)
    assert result.exit_code == 2
