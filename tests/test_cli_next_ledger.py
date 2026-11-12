"""The next 25 offline ledger selectors and export controls, using fictional data."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Transaction, TxnType


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "200")
    return lambda *args: CliRunner().invoke(main, list(args), catch_exceptions=False)


@pytest.fixture
def ledger(store):
    maple = store.add_account(Account(name="Fictional Maple", type=AccountType.NONREG))
    birch = store.add_account(Account(name="Fictional Birch", type=AccountType.TFSA))
    old = store.add_account(Account(name="Fictional Archived", type=AccountType.RRSP))
    rows = [
        Transaction(maple.saved_id, TxnType.DEPOSIT, "2024-01-05", amount=1000, note="Seed funding"),
        Transaction(maple.saved_id, TxnType.BUY, "2024-01-06", "ALFA", quantity=2, price=10, fees=1, note="Winter lot"),
        Transaction(
            maple.saved_id,
            TxnType.BUY,
            "2024-02-04",
            "BETA",
            quantity=4,
            price=20,
            fees=3,
            note="Review later",
            currency="USD",
        ),
        Transaction(birch.saved_id, TxnType.DIVIDEND, "2025-01-06", "ALFA", amount=9),
        Transaction(
            maple.saved_id,
            TxnType.TRANSFER,
            "2025-01-07",
            "ALFA",
            quantity=1,
            price=11,
            target_account_id=birch.saved_id,
        ),
        Transaction(old.saved_id, TxnType.BUY, "2025-01-08", "OLD", quantity=1, price=99, fees=99),
        Transaction(
            maple.saved_id,
            TxnType.TRANSFER,
            "2025-01-09",
            "ALFA",
            quantity=1,
            target_account_id=old.saved_id,
        ),
        Transaction(birch.saved_id, TxnType.BUY, "2025-01-10", "ALFA", quantity=2, price=10, fees=1, note="  "),
    ]
    for row in rows:
        store.add_transaction(row)
    old.archived = True
    store.update_account(old)
    return rows


def records(cli, *args):
    result = cli("activity", "--json", *args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


@pytest.mark.parametrize(
    ("args", "ids"),
    [
        (("--min-quantity", "2"), [8, 3, 2]),
        (("--max-quantity", "2"), [8, 5, 4, 2, 1]),
        (("--min-price", "10"), [8, 5, 3, 2]),
        (("--max-price", "10"), [8, 4, 2, 1]),
        (("--exclude-note", "REVIEW"), [8, 5, 4, 2, 1]),
        (("--symbol-prefix", " aL"), [8, 5, 4, 2]),
        (("--account-search", "MAPLE"), [5, 3, 2, 1]),
        (("--id", "2", "--id", "4", "--id", "6", "--id", "7"), [4, 2]),
        (("--exclude-id", "1", "--exclude-id", "8"), [5, 4, 3, 2]),
        (("--has-target",), [5]),
        (("--weekend",), [3, 2]),
        (("--has-price",), [8, 5, 3, 2]),
        (("--has-quantity",), [8, 5, 3, 2]),
        (("--sort", "amount"), [1, 4, 8, 5, 3, 2]),
        (("--sort", "fees"), [3, 8, 2, 5, 4, 1]),
    ],
)
def test_fifteen_activity_capabilities(cli, ledger, fake, store, args, ids):
    before = store.transactions()
    assert [row["id"] for row in records(cli, *args)] == ids
    assert store.transactions() == before
    assert fake.calls == []


@pytest.mark.parametrize(
    ("args", "ids"),
    [
        (("--no-target",), [8, 4, 3, 2, 1]),
        (("--no-weekend",), [8, 5, 4, 1]),
        (("--no-price",), [4, 1]),
        (("--no-quantity",), [4, 1]),
        (("--sort", "fees", "--oldest-first"), [1, 4, 5, 2, 8, 3]),
        (("--min-quantity", "2", "--max-quantity", "2", "--max-price", "10"), [8, 2]),
        (("--has-target", "--account-search", "birch"), []),  # source account only
        (("--id", "2", "--id", "2", "--exclude-id", "2"), []),
    ],
)
def test_activity_combinations_and_opposite_flags(cli, ledger, args, ids):
    assert [row["id"] for row in records(cli, *args)] == ids


def test_activity_new_selection_precedes_summary_count_and_paging(cli, ledger):
    assert cli("activity", "--weekend", "--count").output == "2\n"
    assert json.loads(cli("activity", "--weekend", "--summary", "type", "--json").output) == [
        {"group": "BUY", "count": 2}
    ]
    result = records(cli, "--has-quantity", "--sort", "fees", "--limit", "2", "--offset", "1", "--page-info")
    assert result["total"] == 4
    assert result["next_offset"] == 3
    assert [row["id"] for row in result["items"]] == [8, 2]
    output = cli("activity", "--symbol-prefix", "AL", "--csv").output
    assert [int(row["id"]) for row in csv.DictReader(io.StringIO(output))] == [8, 5, 4, 2]


@pytest.mark.parametrize(
    "args",
    [
        ("--min-price", "nan"),
        ("--max-price", "inf"),
        ("--min-quantity", "-inf"),
        ("--max-quantity", "nan"),
        ("--min-price", "20", "--max-price", "10"),
        ("--min-quantity", "5", "--max-quantity", "1"),
        ("--id", "0"),
        ("--exclude-id", "-1"),
        ("--sort", "bogus"),
    ],
)
def test_activity_bad_options(cli, store, fake, args):
    assert cli("activity", *args).exit_code == 2
    assert store.accounts() == []
    assert store.transactions() == []
    assert fake.calls == []


@pytest.mark.parametrize(
    ("args", "indexes"),
    [
        (("--currency", " usd "), [3]),
        (("--note", "WINTER"), [2]),
        (("--has-note",), [1, 2, 3]),
        (("--exclude-type", "buy"), [1, 4, 5, 7]),
        (("--exclude-symbol", " alfa "), [1, 3, 6]),
        (("--exclude-account", "fictional maple"), [4, 6, 8]),
        (("--year", "2024"), [1, 2, 3]),
        (("--month", "2"), [3]),
        (("--limit", "2"), [1, 2]),
        (("--offset", "6"), [7, 8]),
    ],
)
def test_ten_export_capabilities(cli, ledger, fake, store, args, indexes):
    before = store.transactions()
    result = cli("export", "--jsonl", *args)
    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in result.output.splitlines()]
    assert [row["date"] for row in rows] == [ledger[i - 1].date for i in indexes]
    assert store.transactions() == before
    assert fake.calls == []


def test_export_combinations_file_and_reimport(cli, ledger, tmp_path):
    path = tmp_path / "fictional.csv"
    result = cli(
        "export",
        str(path),
        "--year",
        "2025",
        "--month",
        "1",
        "--exclude-account",
        "Fictional Archived",
        "--exclude-type",
        "transfer",
        "--no-note",
        "--limit",
        "1",
        "--offset",
        "1",
    )
    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(io.StringIO(path.read_text())))
    assert [(row["date"], row["account"]) for row in rows] == [("2025-01-10", "Fictional Birch")]
    report = json.loads(cli("import", str(path), "--dry-run", "--json").output)
    assert report["duplicates"] == 1 and report["added"] == 0 and report["issues"] == []
    assert cli("export", "--year", "2025", "--month", "1", "--count").output == "5\n"
    assert [row["date"] for row in csv.DictReader(io.StringIO(cli("export", "--offset", "0").output))] == [
        row.date for row in ledger
    ]


def test_export_repeatable_exclusions_and_empty_results(cli, ledger):
    assert cli("export", "--exclude-type", "buy", "--exclude-type", "transfer", "--count").output == "2\n"
    assert cli("export", "--exclude-symbol", "ALFA", "--exclude-symbol", "BETA", "--count").output == "2\n"
    assert (
        cli("export", "--exclude-account", "Fictional Maple", "--exclude-account", "Fictional Birch", "--count").output
        == "1\n"
    )
    assert cli("export", "--note", "unmatched", "--jsonl").output == ""
    assert cli("export", "--offset", "99", "--jsonl").output == ""
    assert len(cli("export", "--offset", "99").output.splitlines()) == 1  # CSV header retained


@pytest.mark.parametrize(
    "args",
    [
        ("--year", "0"),
        ("--year", "10000"),
        ("--month", "13"),
        ("--month", "0"),
        ("--limit", "0"),
        ("--offset", "-1"),
        ("--count", "--limit", "1"),
        ("--count", "--offset", "1"),
        ("--exclude-type", "bogus"),
    ],
)
def test_export_bad_options(cli, store, fake, args):
    assert cli("export", *args).exit_code == 2
    assert store.accounts() == [] and store.transactions() == [] and fake.calls == []


def test_export_unknown_excluded_account(cli, ledger):
    result = cli("export", "--exclude-account", "Missing")
    assert result.exit_code == 1 and "No account 'Missing'." in result.output


def test_activity_private_human_and_raw_script_output(cli, ledger, tracker):
    tracker.config.privacy = True
    output = cli("activity", "--min-price", "10", "--sort", "fees").output
    assert "•••" in output
    assert "3.00" not in output  # recorded fees remain masked; public unit prices stay visible
    assert records(cli, "--min-price", "20")[0]["price"] == 20
