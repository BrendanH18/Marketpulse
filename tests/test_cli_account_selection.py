"""Offline selection and grouped counts for fictional account metadata."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType


@pytest.fixture
def inventory(store, tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))

    def no_valuation(*args, **kwargs):
        raise AssertionError("Inventory selection must not price accounts")

    monkeypatch.setattr(tracker, "valuation", no_valuation)
    accounts = [
        store.add_account(
            Account(name="Fictional Savings", type=AccountType.TFSA, institution="Example", track_cash=True)
        ),
        store.add_account(Account(name="Fictional Retirement", type=AccountType.RRSP, institution="Example")),
        store.add_account(
            Account(name="Fictional Taxable", type=AccountType.NONREG, currency="USD", institution="   ")
        ),
        store.add_account(Account(name="Fictional Cash", type=AccountType.CASH, track_cash=True)),
        store.add_account(Account(name="Fictional Archived", type=AccountType.TFSA, archived=True)),
    ]
    runner = CliRunner()

    def invoke(*args):
        return runner.invoke(main, ["accounts", "list", *args], catch_exceptions=False)

    return invoke, accounts


@pytest.mark.parametrize(
    ("flags", "indexes"),
    [
        (("--registered",), [0, 1]),
        (("--nonregistered",), [2, 3]),
        (("--has-institution",), [0, 1]),
        (("--no-institution",), [2, 3]),
        (("--registered", "--has-institution", "--cash"), [0]),
    ],
)
def test_selection_filters(inventory, flags, indexes):
    invoke, accounts = inventory
    result = invoke(*flags, "--json")
    assert result.exit_code == 0
    assert [row["id"] for row in json.loads(result.output)] == [accounts[i].id for i in indexes]
    # Human output also takes the offline path.
    assert invoke(*flags).exit_code == 0


def test_exclusions_resolve_id_name_type_and_repeat(inventory):
    invoke, accounts = inventory
    result = invoke("--exclude-account", str(accounts[0].id), "--exclude-account", "rrsp", "--json")
    assert [row["id"] for row in json.loads(result.output)] == [accounts[2].id, accounts[3].id]
    result = invoke("--exclude-account", "fictional cash", "--count")
    assert result.output.strip() == "3"
    assert invoke("--exclude-account", "does not exist").exit_code == 1
    assert invoke("--exclude-account", str(accounts[4].id)).exit_code == 1
    result = invoke("--archived", "--exclude-account", str(accounts[4].id), "--json")
    assert len(json.loads(result.output)) == 4


def test_inclusive_ids_filter_before_pages(inventory):
    invoke, accounts = inventory
    result = invoke(
        "--min-id",
        str(accounts[1].id),
        "--max-id",
        str(accounts[3].id),
        "--offset",
        "1",
        "--limit",
        "1",
        "--json",
        "--page-info",
    )
    payload = json.loads(result.output)
    assert payload["total"] == 3
    assert payload["returned"] == 1
    assert payload["next_offset"] == 2
    assert payload["items"][0]["id"] == accounts[2].id
    assert invoke("--min-id", str(accounts[1].id)).exit_code == 0
    assert invoke("--max-id", str(accounts[3].id)).exit_code == 0


@pytest.mark.parametrize(
    ("group", "expected"),
    [
        (
            "type",
            [
                {"group": "CASH", "count": 1},
                {"group": "NONREG", "count": 1},
                {"group": "RRSP", "count": 1},
                {"group": "TFSA", "count": 1},
            ],
        ),
        ("currency", [{"group": "CAD", "count": 3}, {"group": "USD", "count": 1}]),
        ("institution", [{"group": "", "count": 2}, {"group": "Example", "count": 2}]),
        ("cash", [{"group": "tracked", "count": 2}, {"group": "untracked", "count": 2}]),
    ],
)
def test_summaries_use_all_matches_and_formats(inventory, group, expected):
    invoke, _ = inventory
    flags = ("--summary", group, "--limit", "1", "--offset", "100")
    assert json.loads(invoke(*flags, "--json").output) == expected
    rows = list(csv.DictReader(io.StringIO(invoke(*flags, "--csv").output)))
    assert rows == [{"group": row["group"], "count": str(row["count"])} for row in expected]
    assert invoke(*flags).exit_code == 0


def test_summary_sort_and_composition(inventory):
    invoke, _ = inventory
    result = invoke("--summary", "institution", "--summary-sort", "count", "--nonregistered", "--json")
    assert json.loads(result.output) == [{"group": "", "count": 2}]
    result = invoke("--archived", "--summary", "type", "--summary-sort", "count", "--json")
    assert json.loads(result.output) == [
        {"group": "TFSA", "count": 2},
        {"group": "CASH", "count": 1},
        {"group": "NONREG", "count": 1},
        {"group": "RRSP", "count": 1},
    ]
    assert json.loads(invoke("--search", "absent", "--summary", "type", "--json").output) == []


@pytest.mark.parametrize(
    "flags",
    [
        ("--min-id", "2", "--max-id", "1"),
        ("--min-id", "0"),
        ("--summary-sort", "count"),
        ("--summary", "type", "--count"),
        ("--summary", "type", "--json", "--page-info"),
        ("--summary", "type", "--json", "--csv"),
    ],
)
def test_invalid_combinations(inventory, flags):
    invoke, _ = inventory
    assert invoke(*flags).exit_code == 2
