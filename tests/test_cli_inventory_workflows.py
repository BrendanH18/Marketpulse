"""Fictional offline inventory reads and composable CLI metadata filters."""

import json
from dataclasses import asdict

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Asset, AssetClass, AssetKind, Transaction, TxnType


@pytest.fixture
def inventory_cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "160")
    runner = CliRunner()

    def invoke(*args):
        return runner.invoke(main, list(args), catch_exceptions=False)

    return invoke


@pytest.fixture
def inventory_accounts(store):
    return [
        store.add_account(Account("Fictional é TFSA", AccountType.TFSA, institution="Example Credit", track_cash=True)),
        store.add_account(Account("Fictional RRSP", AccountType.RRSP, institution="Example Credit")),
        store.add_account(Account("Second TFSA", AccountType.TFSA, institution="Sample Bank")),
        store.add_account(Account("Archived TFSA", AccountType.TFSA, institution="Example Credit", archived=True)),
    ]


@pytest.fixture
def inventory_assets(store):
    assets = [
        Asset(
            "FICTION-GIC",
            AssetKind.FIXED_INCOME,
            "Fictional dépôt",
            AssetClass.FIXED_INCOME,
            "CAD",
            rate=4.25,
            start_date="2024-01-01",
            maturity_date="2026-01-01",
        ),
        Asset("FICTION-HOUSE", AssetKind.MANUAL, "Fictional cottage", AssetClass.REAL_ESTATE, "CAD"),
        Asset("FICTION-USD", AssetKind.MANUAL, "Fictional art", AssetClass.ALTERNATIVE, "USD"),
        Asset("FICTION-EQUITY", AssetKind.MARKET, "Fictional shares", AssetClass.EQUITY, "USD"),
        Asset("UNCLASSIFIED"),
    ]
    for asset in assets:
        store.upsert_asset(asset)
    return assets


def test_account_metadata_reads_are_offline_and_do_not_create_snapshots(
    inventory_cli, inventory_accounts, store, fake, monkeypatch
):
    def forbidden_valuation(*args, **kwargs):
        pytest.fail("An offline inventory must not price holdings")

    monkeypatch.setattr("marketpulse.services.Tracker.valuation", forbidden_valuation)
    result = inventory_cli("accounts", "list", "--offline")
    assert result.exit_code == 0
    assert "Fictional é TFSA" in result.output and "tracked" in result.output
    assert "Archived TFSA" not in result.output and "Value" not in result.output
    result = inventory_cli("accounts", "list", "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == [asdict(a) for a in inventory_accounts[:3]]
    assert "é" in result.output
    assert fake.calls == [] and store.snapshots() == []


@pytest.mark.parametrize(
    ("args", "indices"),
    [
        (("--type", "tfsa"), [0, 2]),
        (("--institution", "EXAMPLE CREDIT"), [0, 1]),
        (("--search", "É tfsa"), [0]),
        (("--type", "TFSA", "--institution", "example credit", "--search", "fictional"), [0]),
        (("--institution", "Credit"), []),
        (("--type", "TFSA", "--search", "rrsp"), []),
    ],
)
def test_account_filters_compose(inventory_cli, inventory_accounts, args, indices, fake):
    result = inventory_cli("accounts", "list", "--json", *args)
    assert result.exit_code == 0
    assert [a["id"] for a in json.loads(result.output)] == [inventory_accounts[i].id for i in indices]
    assert fake.calls == []


def test_archived_accounts_require_explicit_inventory_opt_in(inventory_cli, inventory_accounts):
    result = inventory_cli("accounts", "list", "--archived", "--json", "--type", "tfsa")
    assert [a["id"] for a in json.loads(result.output)] == [inventory_accounts[i].id for i in (0, 2, 3)]
    assert json.loads(result.output)[-1]["archived"] is True
    assert "Archived TFSA (archived)" in inventory_cli("accounts", "list", "--archived", "--offline").output


def test_account_default_still_prices_holdings(inventory_cli, inventory_accounts, store, fake):
    store.add_transaction(
        Transaction(inventory_accounts[2].saved_id, TxnType.BUY, symbol="XEQT.TO", quantity=2, price=30, currency="CAD")
    )
    result = inventory_cli("accounts")
    assert result.exit_code == 0
    assert "Value" in result.output and "80.00" in result.output
    assert "Archived TFSA" not in result.output
    assert fake.calls


def test_empty_account_inventory_is_read_only(inventory_cli, store, fake):
    assert json.loads(inventory_cli("accounts", "list", "--json").output) == []
    assert "No accounts yet" in inventory_cli("accounts", "list", "--offline").output
    assert "No accounts match" in inventory_cli("accounts", "list", "--offline", "--type", "RRSP").output
    assert store.accounts(include_archived=True) == [] and fake.calls == []


def test_asset_json_preserves_all_metadata_and_unicode(inventory_cli, inventory_assets, fake, store):
    result = inventory_cli("asset", "list", "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == [asdict(a) for a in inventory_assets]
    assert "dépôt" in result.output
    assert fake.calls == [] and store.snapshots() == [] and store.accounts() == []


@pytest.mark.parametrize(
    ("args", "indices"),
    [
        (("--kind", "MANUAL"), [1, 2]),
        (("--class", "FIXED_INCOME"), [0]),
        (("--currency", "cad"), [0, 1]),
        (("--search", "DÉPÔT"), [0]),
        (("--search", "fiction-house"), [1]),
        (("--kind", "manual", "--class", "real_estate", "--currency", "cad", "--search", "cottage"), [1]),
        (("--kind", "manual", "--currency", "GBP"), []),
        (("--class", "equity", "--search", "UNCLASSIFIED"), []),
    ],
)
def test_asset_filters_compose(inventory_cli, inventory_assets, args, indices, fake):
    result = inventory_cli("asset", "list", "--json", *args)
    assert result.exit_code == 0
    assert [a["symbol"] for a in json.loads(result.output)] == [inventory_assets[i].symbol for i in indices]
    assert fake.calls == []


def test_asset_filtered_human_table_and_empty_results(inventory_cli, inventory_assets):
    result = inventory_cli("asset", "list", "--kind", "fixed_income", "--currency", "cad")
    assert "FICTION-GIC" in result.output and "4.25% annual" in result.output
    assert "FICTION-HOUSE" not in result.output
    assert "No assets match" in inventory_cli("asset", "list", "--search", "absent").output


def test_empty_asset_inventory_is_read_only(inventory_cli, store, fake):
    assert json.loads(inventory_cli("asset", "list", "--json").output) == []
    assert "No custom assets" in inventory_cli("asset", "list").output
    assert store.accounts(include_archived=True) == [] and fake.calls == []


@pytest.mark.parametrize(
    "args",
    [
        ("accounts", "list", "--type", "invalid"),
        ("asset", "list", "--kind", "invalid"),
        ("asset", "list", "--class", "invalid"),
    ],
)
def test_inventory_enum_filters_reject_unknown_values(inventory_cli, store, fake, args):
    result = inventory_cli(*args)
    assert result.exit_code == 2 and "Invalid value" in result.output
    assert store.accounts() == [] and fake.calls == []
