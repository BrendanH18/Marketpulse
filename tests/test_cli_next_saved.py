"""Fresh saved-item workflows use fictional local metadata, never requests."""

import csv
import io
import json
from dataclasses import fields

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.config import Config, config_path
from marketpulse.models import Account, Alert, Quote, Transaction, TxnType
from marketpulse.themes import OMARCHY_PALETTES, palette_from_colors


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))

    def forbidden(*args, **kwargs):
        raise AssertionError("These saved-item commands must stay offline")

    monkeypatch.setattr(tracker, "watchlist_quotes", forbidden)
    return lambda *args: CliRunner().invoke(main, list(args), catch_exceptions=False)


@pytest.fixture
def saved(store):
    active = store.add_account(Account("Fictional Active"))
    archived = store.add_account(Account("Fictional Archived", archived=True))
    store.add_transactions(
        [
            Transaction(
                type=TxnType.BUY, date="2024-01-01", account_id=active.id, symbol="ALPHA.TO", quantity=1, price=10
            ),
            Transaction(
                type=TxnType.BUY, date="2024-01-01", account_id=archived.id, symbol="BETA", quantity=1, price=10
            ),
        ]
    )
    store.add_watch(["BETA", "ALPHA.TO", "GAMMA.TO"])
    store.cache_quotes([Quote("BETA", 10, 9)])
    return [
        store.add_alert(Alert("ALPHA.TO", "above", 100)),
        store.add_alert(Alert("ALPHA.TO", "below", 50, active=False, triggered_at="2024-02-03T12:00:00Z")),
        store.add_alert(Alert("OTHER", "up_pct", 3, triggered_at="2024-01-04T12:00:00Z")),
    ]


@pytest.mark.parametrize(
    "options,expected",
    [
        (("--held",), ["ALPHA.TO"]),
        (("--not-held",), ["BETA", "GAMMA.TO"]),
        (("--cached",), ["BETA"]),
        (("--not-cached",), ["ALPHA.TO", "GAMMA.TO"]),
        (("--suffix", " .to "), ["ALPHA.TO", "GAMMA.TO"]),
        (("--exclude-search", " aLpHa "), ["BETA", "GAMMA.TO"]),
    ],
)
def test_watch_membership_and_text(cli, saved, fake, store, options, expected):
    before = store.watchlist()
    result = cli("watch", "list", *options, "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == expected
    assert cli("watch", "list", *options).exit_code == 0
    assert store.watchlist() == before
    assert fake.calls == []


def test_watch_lines_compose_after_filter_order_and_paging(cli, saved, fake):
    result = cli("watch", "list", "--lines", "--suffix", ".TO", "--descending", "--limit", "1")
    assert result.output == "GAMMA.TO\n"
    assert cli("watch", "list", "--lines", "--held", "--cached").output == ""
    assert fake.calls == []


@pytest.mark.parametrize(
    "option,indices",
    [
        ("--watched", [0, 1]),
        ("--not-watched", [2]),
        ("--ever-triggered", [1, 2]),
        ("--never-triggered", [0]),
    ],
)
def test_alert_membership(cli, saved, fake, option, indices):
    result = cli("alerts", "list", option, "--json")
    assert result.exit_code == 0, result.output
    assert [a["id"] for a in json.loads(result.output)] == [saved[i].id for i in indices]
    assert fake.calls == []


def test_alert_id_ranges_and_condition_exclusion(cli, saved, fake):
    ids = [str(a.id) for a in saved]
    assert [a["id"] for a in json.loads(cli("alerts", "list", "--id", ids[2], "--id", ids[0], "--json").output)] == [
        saved[0].id,
        saved[2].id,
    ]
    args = ("alerts", "list", "--min-id", ids[0], "--max-id", ids[1], "--exclude-condition", "BELOW")
    assert [a["id"] for a in json.loads(cli(*args, "--json").output)] == [saved[0].id]
    assert cli(*args, "--count").output == "1\n"
    assert len(list(csv.DictReader(io.StringIO(cli(*args, "--csv").output)))) == 1
    assert fake.calls == []


def test_trigger_month_summary_counts_paused_history_and_uses_all_matches(cli, saved, fake):
    args = ("alerts", "list", "--summary", "trigger-month", "--limit", "1", "--offset", "99")
    expected = [{"group": "2024-01", "count": 1}, {"group": "2024-02", "count": 1}, {"group": "never", "count": 1}]
    assert json.loads(cli(*args, "--json").output) == expected
    assert list(csv.DictReader(io.StringIO(cli(*args, "--csv").output)))[1] == {"group": "2024-02", "count": "1"}
    assert "Matching alerts" in cli(*args).output
    assert fake.calls == []


@pytest.mark.parametrize(
    "args",
    [
        ("watch", "list", "--suffix", " "),
        ("watch", "list", "--exclude-search", " "),
        ("watch", "list", "--lines", "--json"),
        ("watch", "list", "--lines", "--csv"),
        ("watch", "list", "--lines", "--count"),
        ("watch", "list", "--lines", "--page-info"),
        ("alerts", "list", "--id", "0"),
        ("alerts", "list", "--min-id", "3", "--max-id", "1"),
        ("alerts", "list", "--exclude-condition", "unknown"),
    ],
)
def test_invalid_saved_options(cli, fake, args):
    assert cli(*args).exit_code == 2
    assert fake.calls == []


@pytest.fixture
def config_cli(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Appearance/configuration commands must not open a tracker")

    monkeypatch.setattr("marketpulse.services.Tracker.open", forbidden)
    return lambda *args: CliRunner().invoke(main, list(args), catch_exceptions=False)


def test_theme_catalog_search_modes_exports_and_paging(config_cli):
    all_names = sorted(OMARCHY_PALETTES)
    assert config_cli("theme", "list", "--names").output.splitlines() == all_names
    assert "Embedded themes" in config_cli("theme", "list").output
    assert config_cli("theme", "list", "--count", "--limit", "1", "--offset", "999").output == f"{len(all_names)}\n"
    assert (
        config_cli("theme", "list", "--descending", "--offset", "1", "--limit", "2", "--names").output.splitlines()
        == list(reversed(all_names))[1:3]
    )
    assert config_cli("theme", "list", "--search", "TOKYO", "--names").output.strip() == "tokyo-night"
    for mode in ("dark", "light"):
        rows = list(csv.DictReader(io.StringIO(config_cli("theme", "list", "--mode", mode.upper(), "--csv").output)))
        expected = [n for n in all_names if palette_from_colors(n, OMARCHY_PALETTES[n]).dark == (mode == "dark")]
        assert [r["name"] for r in rows] == expected
        assert all(r["mode"] == mode and r["label"] for r in rows)
    assert not config_path().exists()


@pytest.mark.parametrize(
    "options",
    [
        ("--search", " "),
        ("--mode", "invalid"),
        ("--count", "--csv"),
        ("--names", "--csv"),
        ("--offset", "-1"),
        ("--limit", "0"),
    ],
)
def test_invalid_theme_options(config_cli, options):
    assert config_cli("theme", "list", *options).exit_code == 2


def test_setting_receipts_and_reset_preview_preserve_other_values_and_secret(config_cli):
    Config(privacy=True, quote_api_key="fictional-secret", refresh_seconds=60).save()
    before = config_path().read_bytes()
    assert json.loads(config_cli("config", "reset", "privacy", "--dry-run", "--json").output) == {
        "key": "privacy",
        "value": False,
        "saved": False,
    }
    assert "not saved" in config_cli("config", "reset", "privacy", "--dry-run").output
    assert json.loads(config_cli("config", "set", "base_currency", "usd", "--dry-run", "--json").output) == {
        "key": "base_currency",
        "value": "USD",
        "saved": False,
    }
    assert config_path().read_bytes() == before
    assert json.loads(config_cli("config", "reset", "privacy", "--json").output) == {
        "key": "privacy",
        "value": False,
        "saved": True,
    }
    assert json.loads(config_cli("config", "set", "base_currency", "usd", "--json").output) == {
        "key": "base_currency",
        "value": "USD",
        "saved": True,
    }
    actual = Config.load()
    assert not actual.privacy and actual.base_currency == "USD"
    assert actual.refresh_seconds == 60 and actual.quote_api_key == "fictional-secret"
    for command in ("set", "reset"):
        args = ("config", command, "quote_api_key", *(["sentinel"] if command == "set" else []), "--json")
        result = config_cli(*args)
        assert result.exit_code == 1 and "sentinel" not in result.output and "fictional-secret" not in result.output


def test_config_keys_type_and_count_filters(config_cli):
    defaults = Config()
    for value_type in ("bool", "int", "float", "str", "list"):
        expected = [f.name for f in fields(Config) if type(getattr(defaults, f.name)).__name__ == value_type]
        assert json.loads(config_cli("config", "keys", "--type", value_type, "--json").output) == expected
        assert config_cli("config", "keys", "--type", value_type, "--count").output == f"{len(expected)}\n"
    Config(privacy=True).save()
    assert config_cli("config", "keys", "--type", "bool", "--changed", "--search", "PRIV", "--count").output == "1\n"
    assert config_cli("config", "keys", "--count", "--json").exit_code == 2
