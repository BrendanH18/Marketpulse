"""Offline details, selection and ordering on fictional inventory metadata."""

import json
from dataclasses import asdict

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Asset, AssetKind


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "160")
    monkeypatch.setattr("marketpulse.services.Tracker.valuation", lambda *a, **kw: pytest.fail("Unexpected pricing"))
    runner = CliRunner()
    return lambda *args: runner.invoke(main, list(args), catch_exceptions=False)


@pytest.fixture
def accounts(store):
    return [
        store.add_account(Account("Zinnia", AccountType.TFSA, "CAD", "Alpha Bank", track_cash=True)),
        store.add_account(Account("aster", AccountType.RRSP, "USD", "Beta Bank")),
        store.add_account(Account("Birch", AccountType.CASH, "CAD", "Alpha Bank")),
        store.add_account(Account("Hidden", AccountType.TFSA, "USD", archived=True)),
    ]


@pytest.fixture
def assets(store):
    items = [
        Asset("ART", AssetKind.MANUAL, "Zinnia painting", currency="CAD"),
        Asset("BOND", AssetKind.FIXED_INCOME, "Aster deposit", currency="USD", rate=4.25),
        Asset("SHARES", AssetKind.MARKET, "Birch shares", currency="CAD"),
    ]
    for item in items:
        store.upsert_asset(item)
    return items


@pytest.mark.parametrize("selector", ["1", "zinnia", "TFSA"])
def test_account_show_resolves_active_metadata_offline(cli, accounts, store, fake, selector):
    result = cli("accounts", "show", selector, "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == asdict(accounts[0])
    assert "track_cash" in cli("accounts", "show", selector).output
    assert fake.calls == [] and store.snapshots() == []


def test_account_show_refuses_archived_and_missing_without_creating(cli, accounts, store, fake):
    for selector in ["Hidden", str(accounts[-1].id), "missing"]:
        result = cli("accounts", "show", selector, "--json")
        assert result.exit_code == 1 and "No active account" in result.output
    assert len(store.accounts(include_archived=True)) == 4 and fake.calls == []


def test_account_show_empty_store_does_not_create_default(cli, store):
    assert cli("accounts", "show", "TFSA").exit_code == 1
    assert store.accounts() == []


@pytest.mark.parametrize(
    "args,names",
    [
        (["--currency", " cad "], ["Zinnia", "Birch"]),
        (["--cash"], ["Zinnia"]),
        (["--no-cash"], ["aster", "Birch"]),
        (["--currency", "cad", "--no-cash", "--institution", "Alpha Bank"], ["Birch"]),
        (["--sort", "name"], ["aster", "Birch", "Zinnia"]),
        (["--sort", "type"], ["Birch", "aster", "Zinnia"]),
        (["--sort", "institution"], ["Zinnia", "Birch", "aster"]),
        (["--sort", "currency", "--descending"], ["aster", "Birch", "Zinnia"]),
        (["--descending"], ["Birch", "aster", "Zinnia"]),
    ],
)
def test_account_filters_and_sort_compose(cli, accounts, fake, args, names):
    result = cli("accounts", "list", "--json", *args)
    assert result.exit_code == 0
    assert [a["name"] for a in json.loads(result.output)] == names
    assert fake.calls == []


def test_account_filter_empty_message_and_archived_opt_in(cli, accounts):
    assert "No accounts match" in cli("accounts", "list", "--offline", "--currency", "EUR").output
    result = cli("accounts", "list", "--json", "--archived", "--currency", "USD", "--no-cash")
    assert [a["name"] for a in json.loads(result.output)] == ["aster", "Hidden"]


def test_asset_show_all_metadata_offline_and_no_creation(cli, assets, store, fake):
    assert json.loads(cli("asset", "show", "bond", "--json").output) == asdict(assets[1])
    assert "4.25" in cli("asset", "show", "BOND").output
    assert cli("asset", "show", "missing", "--json").exit_code == 1
    assert len(store.assets()) == 3 and fake.calls == [] and store.snapshots() == []


def test_asset_show_privacy_masks_rate_but_json_is_raw(cli, assets):
    assert cli("config", "set", "privacy", "true").exit_code == 0
    assert "4.25" not in cli("asset", "show", "BOND").output
    assert json.loads(cli("asset", "show", "BOND", "--json").output)["rate"] == 4.25


@pytest.mark.parametrize(
    "args,symbols",
    [
        (["--sort", "name"], ["BOND", "SHARES", "ART"]),
        (["--sort", "kind"], ["BOND", "ART", "SHARES"]),
        (["--sort", "currency"], ["ART", "SHARES", "BOND"]),
        (["--sort", "symbol", "--descending"], ["SHARES", "BOND", "ART"]),
        (["--descending"], ["SHARES", "BOND", "ART"]),
        (["--sort", "name", "--limit", "1", "--offset", "1"], ["SHARES"]),
        (["--currency", "CAD", "--sort", "name", "--offset", "1"], ["ART"]),
        (["--offset", "20"], []),
    ],
)
def test_asset_order_then_paging(cli, assets, fake, args, symbols):
    result = cli("asset", "list", "--json", *args)
    assert result.exit_code == 0
    assert [a["symbol"] for a in json.loads(result.output)] == symbols
    assert fake.calls == []


@pytest.mark.parametrize("args", [("--limit", "0"), ("--offset", "-1"), ("--sort", "rate")])
def test_asset_invalid_paging_or_order_rejected(cli, assets, args):
    assert cli("asset", "list", *args).exit_code == 2
