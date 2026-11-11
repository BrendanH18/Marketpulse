"""Inventory exports and pagination use fictional metadata without pricing."""

import csv
import io
import json
from dataclasses import fields

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Asset, AssetClass, AssetKind


@pytest.fixture
def inventory_cli(store, tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.services.Tracker.valuation", lambda *a, **kw: pytest.fail("Unexpected pricing"))
    for account in [
        Account('Aster, "Demo"', AccountType.TFSA, "CAD"),
        Account("Birch", AccountType.RRSP, "USD"),
        Account("Cedar", AccountType.CASH, "CAD"),
        Account("Hidden", AccountType.TFSA, "CAD", archived=True),
    ]:
        store.add_account(account)
    for asset in [
        Asset("ART", AssetKind.MANUAL, "Painting, fictional\ncollection", currency="CAD"),
        Asset("BOND", AssetKind.FIXED_INCOME, "Demo deposit", asset_class=AssetClass.FIXED_INCOME, currency="CAD"),
        Asset("STOCK", AssetKind.MARKET, "Demo shares", currency="USD"),
    ]:
        store.upsert_asset(asset)
    runner = CliRunner()
    return lambda *args: runner.invoke(main, list(args), catch_exceptions=False)


def test_account_csv_metadata_quoting_and_archived_opt_in(inventory_cli, fake, store):
    result = inventory_cli("accounts", "list", "--csv")
    assert result.exit_code == 0
    reader = csv.DictReader(io.StringIO(result.output))
    assert reader.fieldnames == [f.name for f in fields(Account)]
    rows = list(reader)
    assert [r["name"] for r in rows] == ['Aster, "Demo"', "Birch", "Cedar"]
    archived = inventory_cli("accounts", "list", "--csv", "--archived")
    assert len(list(csv.DictReader(io.StringIO(archived.output)))) == 4
    assert fake.calls == [] and store.snapshots() == []


def test_account_count_before_page_and_filtered(inventory_cli, fake):
    result = inventory_cli("accounts", "list", "--count", "--currency", "CAD", "--offset", "99", "--limit", "1")
    assert result.output == "2\n" and result.exit_code == 0
    assert fake.calls == []


def test_account_limit_offset_and_page_metadata(inventory_cli, fake, store):
    result = inventory_cli(
        "accounts", "list", "--json", "--page-info", "--sort", "name", "--limit", "1", "--offset", "1"
    )
    payload = json.loads(result.output)
    assert {k: v for k, v in payload.items() if k != "items"} == {
        "total": 3,
        "offset": 1,
        "limit": 1,
        "returned": 1,
        "next_offset": 2,
    }
    assert payload["items"][0]["name"] == "Birch"
    tail = json.loads(inventory_cli("accounts", "list", "--json", "--page-info", "--offset", "2").output)
    assert tail["limit"] is None and tail["next_offset"] is None and tail["returned"] == 1
    empty = json.loads(inventory_cli("accounts", "list", "--json", "--page-info", "--offset", "99").output)
    assert empty["items"] == [] and empty["next_offset"] is None and empty["total"] == 3
    # Paging also implies offline table output, including an explicitly supplied zero offset.
    assert inventory_cli("accounts", "list", "--limit", "1").exit_code == 0
    assert inventory_cli("accounts", "list", "--offset", "0").exit_code == 0
    assert fake.calls == [] and store.snapshots() == []


def test_asset_csv_round_trip_and_empty_headers(inventory_cli, fake):
    result = inventory_cli("asset", "list", "--csv", "--symbol", " art ")
    assert result.exit_code == 0
    reader = csv.DictReader(io.StringIO(result.output))
    assert reader.fieldnames == [f.name for f in fields(Asset)]
    rows = list(reader)
    assert len(rows) == 1 and rows[0]["name"] == "Painting, fictional\ncollection"
    assert rows[0]["kind"] == "manual"
    empty = inventory_cli("asset", "list", "--csv", "--symbol", "missing")
    assert len(list(csv.DictReader(io.StringIO(empty.output)))) == 0
    assert fake.calls == []


def test_asset_unclassified_filter_and_count_before_paging(inventory_cli, fake):
    result = inventory_cli("asset", "list", "--count", "--unclassified", "--offset", "99", "--limit", "1")
    assert result.exit_code == 0 and result.output == "2\n"
    result = inventory_cli("asset", "list", "--json", "--unclassified", "--currency", "CAD")
    assert [a["symbol"] for a in json.loads(result.output)] == ["ART"]
    result = inventory_cli("asset", "list", "--json", "--unclassified", "--class", "fixed_income")
    assert json.loads(result.output) == []
    assert fake.calls == []


def test_asset_page_info_filtered_total_and_next_offset(inventory_cli, fake, store):
    payload = json.loads(
        inventory_cli("asset", "list", "--json", "--page-info", "--currency", "CAD", "--limit", "1").output
    )
    assert {k: v for k, v in payload.items() if k != "items"} == {
        "total": 2,
        "offset": 0,
        "limit": 1,
        "returned": 1,
        "next_offset": 1,
    }
    payload = json.loads(inventory_cli("asset", "list", "--json", "--page-info", "--offset", "99").output)
    assert payload["total"] == 3 and payload["items"] == [] and payload["next_offset"] is None
    assert fake.calls == [] and store.snapshots() == []


@pytest.mark.parametrize("group", ["accounts", "asset"])
@pytest.mark.parametrize(
    "args",
    [
        ["--csv", "--json"],
        ["--csv", "--count"],
        ["--count", "--json"],
        ["--page-info"],
        ["--page-info", "--csv"],
        ["--limit", "0"],
        ["--offset", "-1"],
    ],
)
def test_inventory_usage_errors(inventory_cli, group, args, fake):
    assert inventory_cli(group, "list", *args).exit_code == 2
    assert fake.calls == []
