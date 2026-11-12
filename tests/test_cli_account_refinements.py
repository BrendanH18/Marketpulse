"""Fictional, offline account-inventory refinements."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType


@pytest.fixture
def inventory(store, tracker, monkeypatch, fake):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))

    def forbidden(*args, **kwargs):
        raise AssertionError("Metadata selection must stay offline and read-only")

    monkeypatch.setattr(tracker, "valuation", forbidden)
    monkeypatch.setattr(store, "upsert_snapshot", forbidden)
    accounts = [
        store.add_account(Account("Fictional Épargne", AccountType.TFSA, institution="Example North")),
        store.add_account(Account("Fictional Retirement", AccountType.RRSP, institution="Example South")),
        store.add_account(Account("Fictional Taxable", AccountType.NONREG, currency="USD", institution="Sample Bank")),
        store.add_account(Account("Fictional Cash", AccountType.CASH, currency="EUR", institution="")),
        store.add_account(Account("Fictional Hidden", AccountType.TFSA, archived=True, institution="Example North")),
    ]
    runner = CliRunner()

    def invoke(*flags):
        result = runner.invoke(main, ["accounts", "list", *flags], catch_exceptions=False)
        assert fake.calls == []
        assert store.snapshots() == []
        return result

    return invoke, accounts


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (("--type", "tfsa", "--type", "rrsp"), [0, 1]),
        (("--currency", "cad", "--currency", " usd "), [0, 1, 2]),
        (("--institution", "example north", "--institution", "sample bank"), [0, 2]),
        (("--exclude-type", "tfsa", "--exclude-type", "cash"), [1, 2]),
        (("--exclude-currency", " cad ", "--exclude-currency", "EUR"), [2]),
        (("--exclude-institution", "example north", "--exclude-institution", "Example South"), [2, 3]),
        (("--exclude-search", "éPARGNE", "--exclude-search", "retire"), [2, 3]),
        (("--institution-search", "EXAMPLE"), [0, 1]),
    ],
)
def test_selection_and_human_output_are_offline(inventory, flags, expected):
    invoke, accounts = inventory
    result = invoke(*flags, "--json")
    assert result.exit_code == 0
    assert [row["id"] for row in json.loads(result.output)] == [accounts[i].id for i in expected]
    assert invoke(*flags).exit_code == 0


def test_explicit_account_union_intersects_filters_and_exclusions(inventory):
    invoke, accounts = inventory
    flags = ("--account", "Fictional Épargne", "--account", "rrsp", "--account", str(accounts[2].id))
    rows = json.loads(invoke(*flags, "--json").output)
    assert [row["id"] for row in rows] == [a.id for a in accounts[:3]]
    result = invoke(*flags, "--exclude-account", "rrsp", "--registered", "--json")
    assert [row["id"] for row in json.loads(result.output)] == [accounts[0].id]
    assert invoke(*flags).exit_code == 0
    assert invoke("--account", "missing").exit_code == 1
    assert invoke("--account", str(accounts[4].id)).exit_code == 1
    result = invoke("--archived", "--account", str(accounts[4].id), "--json")
    assert [row["id"] for row in json.loads(result.output)] == [accounts[4].id]


def test_refinements_filter_before_count_sort_and_page(inventory):
    invoke, accounts = inventory
    flags = ("--institution-search", "example", "--exclude-type", "NONREG")
    assert invoke(*flags, "--count").output.strip() == "2"
    result = invoke(*flags, "--sort", "name", "--descending", "--limit", "1", "--json", "--page-info")
    payload = json.loads(result.output)
    assert payload["total"] == 2
    assert payload["returned"] == 1
    assert payload["next_offset"] == 1
    assert payload["items"][0]["id"] == accounts[0].id
    result = invoke(*flags, "--csv", "--offset", "1")
    assert [row["id"] for row in csv.DictReader(io.StringIO(result.output))] == [str(accounts[1].id)]


def test_registration_summary_is_offline_and_counts_before_pagination(inventory):
    invoke, _ = inventory
    flags = ("--summary", "registered", "--limit", "1", "--offset", "20")
    expected = [{"group": "nonregistered", "count": 2}, {"group": "registered", "count": 2}]
    assert json.loads(invoke(*flags, "--json").output) == expected
    rows = list(csv.DictReader(io.StringIO(invoke(*flags, "--csv").output)))
    assert rows == [{"group": row["group"], "count": str(row["count"])} for row in expected]
    assert invoke(*flags).exit_code == 0
    result = invoke("--archived", "--summary", "registered", "--summary-sort", "count", "--json")
    assert json.loads(result.output)[0] == {"group": "registered", "count": 3}
    result = invoke("--exclude-currency", "CAD", "--summary", "registered", "--json")
    assert json.loads(result.output) == [{"group": "nonregistered", "count": 2}]


def test_empty_and_composed_selection(inventory):
    invoke, _ = inventory
    result = invoke("--type", "tfsa", "--type", "rrsp", "--institution-search", "south", "--count")
    assert result.output.strip() == "1"
    assert json.loads(invoke("--institution-search", "absent", "--json").output) == []
    assert "No accounts match" in invoke("--exclude-search", "fictional").output
