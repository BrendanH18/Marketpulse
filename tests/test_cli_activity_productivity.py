"""Calendar browsing, exclusions and scriptable paging on fictional offline rows."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, Transaction, TxnType


@pytest.fixture
def productivity(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    account = store.add_account(Account(name='Fictional, "Maple"'))
    hidden = store.add_account(Account(name="Archived secret", archived=True))
    specs = [
        ("2023-12-31", TxnType.BUY, "AAA", "winter seed"),
        ("2024-01-02", TxnType.BUY, "BBB", "Maple harvest"),
        ("2024-01-02", TxnType.DIVIDEND, "AAA", "winter income"),
        ("2024-02-03", TxnType.DEPOSIT, "", ""),
    ]
    for day, kind, symbol, note in specs:
        store.add_transaction(
            Transaction(account.saved_id, kind, day, symbol, quantity=1, price=10, amount=1, currency="CAD", note=note)
        )
    store.add_transaction(
        Transaction(
            hidden.saved_id,
            TxnType.BUY,
            "2024-01-02",
            "SECRET",
            quantity=1,
            price=10,
            currency="CAD",
            note="winter secret",
        )
    )
    store.add_transaction(
        Transaction(
            account.saved_id,
            TxnType.TRANSFER,
            "2024-01-02",
            "AAA",
            quantity=1,
            target_account_id=hidden.saved_id,
            currency="CAD",
            note="winter transfer",
        )
    )
    fake.offline = True
    calls = len(fake.calls)
    runner = CliRunner()

    def invoke(*args):
        result = runner.invoke(main, ["activity", *args], catch_exceptions=False)
        assert len(fake.calls) == calls
        return result

    return invoke


def records(invoke, *args):
    result = invoke("--json", *args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_repeated_exclusions_and_note_only_search_compose(productivity):
    assert [r["id"] for r in records(productivity, "--exclude-type", "buy")] == [4, 3]
    assert [r["id"] for r in records(productivity, "--exclude-type", "buy", "--exclude-type", "deposit")] == [3]
    assert [r["id"] for r in records(productivity, "--exclude-symbol", " aaa ")] == [4, 2]
    assert [r["id"] for r in records(productivity, "--exclude-symbol", "aaa", "--exclude-symbol", "bbb")] == [4]
    assert [r["id"] for r in records(productivity, "--note", "WINTER")] == [3, 1]
    assert [r["id"] for r in records(productivity, "--note", "maple")] == [2]  # not the account's name
    assert records(productivity, "--note", "winter", "--exclude-symbol", "AAA") == []
    assert productivity("--year", "2024", "--note", "WINTER", "--count").output == "1\n"


def test_calendar_filters_intersect_with_existing_ranges(productivity):
    assert [r["id"] for r in records(productivity, "--year", "2024")] == [4, 3, 2]
    assert [r["id"] for r in records(productivity, "--on", "2024-01-02")] == [3, 2]
    assert records(productivity, "--on", "2024-01-02", "--year", "2023") == []
    assert records(productivity, "--on", "2024-01-02", "--since", "2024-02-01") == []
    assert records(productivity, "--year", "2030") == []


def test_calendar_summaries_and_count_order_ignore_paging(productivity):
    assert records(productivity, "--summary", "year", "--offset", "100", "--limit", "1") == [
        {"group": "2023", "count": 1},
        {"group": "2024", "count": 3},
    ]
    days = records(productivity, "--summary", "day", "--summary-sort", "count")
    assert days == [
        {"group": "2024-01-02", "count": 2},
        {"group": "2023-12-31", "count": 1},
        {"group": "2024-02-03", "count": 1},
    ]
    assert records(productivity, "--summary", "year", "--summary-sort", "count")[0]["group"] == "2024"
    assert productivity("--summary", "day", "--summary-sort", "count").exit_code == 0


def test_csv_summaries_keep_schema_and_quote_account_names(productivity):
    result = productivity("--summary", "account", "--csv")
    assert result.exit_code == 0
    assert list(csv.DictReader(io.StringIO(result.output))) == [
        {"group": "1", "count": "4", "account": 'Fictional, "Maple"'},
    ]
    result = productivity("--summary", "year", "--csv", "--summary-sort", "count")
    assert list(csv.DictReader(io.StringIO(result.output))) == [
        {"group": "2024", "count": "3"},
        {"group": "2023", "count": "1"},
    ]
    empty = productivity("--summary", "day", "--csv", "--year", "2030")
    assert empty.output.splitlines() == ["group,count"]


def test_page_info_counts_filtered_visible_rows_and_handles_last_page(productivity):
    first = records(productivity, "--page-info", "--year", "2024", "--limit", "2")
    assert {k: v for k, v in first.items() if k != "items"} == {
        "total": 3,
        "offset": 0,
        "limit": 2,
        "returned": 2,
        "next_offset": 2,
    }
    assert [r["id"] for r in first["items"]] == [4, 3]
    last = records(productivity, "--page-info", "--year", "2024", "--limit", "2", "--offset", "2")
    assert [r["id"] for r in last["items"]] == [2]
    assert last["returned"] == 1 and last["next_offset"] is None
    empty = records(productivity, "--page-info", "--offset", "99")
    assert empty["items"] == [] and empty["next_offset"] is None and empty["total"] == 4
    all_rows = records(productivity, "--page-info", "--all", "--offset", "1", "--oldest-first")
    assert all_rows["limit"] is None and all_rows["next_offset"] is None
    assert [r["id"] for r in all_rows["items"]] == [2, 3, 4]
    assert "SECRET" not in json.dumps(first) and "Archived" not in json.dumps(first)


@pytest.mark.parametrize(
    "args",
    [
        ("--year", "0"),
        ("--year", "10000"),
        ("--on", "2024-02-30"),
        ("--exclude-type", "INVALID"),
        ("--page-info",),
        ("--page-info", "--json", "--summary", "year"),
        ("--page-info", "--json", "--csv"),
        ("--summary-sort", "count"),
    ],
)
def test_invalid_productivity_options(productivity, args):
    assert productivity(*args).exit_code == 2
