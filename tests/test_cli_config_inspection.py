"""Configuration and theme inspection (#126): fictional settings and a sentinel API key, never written."""

import csv
import io
import json
from dataclasses import fields

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.config import Config, config_path
from marketpulse.themes import OMARCHY_PALETTES

SECRET = "fictional-secret-sentinel"


@pytest.fixture
def cli(monkeypatch):
    def no_tracker(*args, **kwargs):
        raise AssertionError("Inspection commands must not open the ledger or market client")

    monkeypatch.setattr("marketpulse.services.Tracker.open", no_tracker)
    runner = CliRunner()
    return lambda *args: runner.invoke(main, list(args), catch_exceptions=False)


@pytest.fixture
def saved():
    """A fictional configuration with a sentinel key; yields its bytes to compare after inspection."""
    Config(
        quote_api_key=SECRET,
        privacy=True,
        refresh_seconds=60,
        default_account="Fictional, TFSA",
        market_strip=["XEQT.TO", "VFV.TO"],
    ).save()
    before = config_path().read_bytes()
    yield before
    assert config_path().read_bytes() == before


def _csv(output: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(output)))


def test_get_accepts_several_keys_in_request_order(cli, saved):
    result = cli("config", "get", "refresh_seconds", "privacy", "quote_api_key", "--json")
    assert result.exit_code == 0
    assert list(json.loads(result.output).items()) == [
        ("refresh_seconds", 60),
        ("privacy", True),
        ("quote_api_key", "(set)"),
    ]
    assert json.loads(cli("config", "get", "privacy", "privacy", "--json").output) == {"privacy": True}
    text = cli("config", "get", "privacy", "refresh_seconds").output
    assert "privacy" in text and "refresh_seconds" in text
    assert json.loads(cli("config", "get", "privacy", "--json").output) == {"privacy": True}
    assert SECRET not in result.output


def test_get_value_prints_raw_values_one_per_line(cli, saved):
    assert cli("config", "get", "--value", "refresh_seconds").output == "60\n"
    result = cli("config", "get", "--value", "privacy", "market_strip", "default_account", "quote_api_key", "theme")
    assert result.output.splitlines() == ["true", "XEQT.TO,VFV.TO", "Fictional, TFSA", "(set)", "auto"]
    assert SECRET not in result.output
    assert cli("config", "get", "--value", "--json", "privacy").exit_code == 2
    assert cli("config", "get", "--value", "--csv", "privacy").exit_code == 2


def test_csv_output_for_config_get_defaults_and_diff(cli, saved):
    rows = _csv(cli("config", "--csv").output)
    assert rows[0] == ["key", "value"]
    assert [row[0] for row in rows[1:]] == [f.name for f in fields(Config)]
    assert ["quote_api_key", "(set)"] in rows
    assert ["default_account", "Fictional, TFSA"] in rows
    assert _csv(cli("config", "get", "privacy", "--csv").output) == [["key", "value"], ["privacy", "true"]]
    assert _csv(cli("config", "defaults", "quote_api_key", "--csv").output) == [
        ["key", "value"],
        ["quote_api_key", ""],
    ]
    diff = _csv(cli("config", "diff", "--csv").output)
    assert diff[0] == ["key", "value"]
    assert {row[0] for row in diff[1:]} == {
        "quote_api_key",
        "privacy",
        "refresh_seconds",
        "default_account",
        "market_strip",
    }
    for args in (("config", "--csv"), ("config", "diff", "--csv"), ("config", "get", "quote_api_key", "--csv")):
        assert SECRET not in cli(*args).output
    assert cli("config", "--json", "--csv").exit_code == 2
    assert cli("config", "--csv", "keys").exit_code == 2
    assert cli("config", "get", "privacy", "--json", "--csv").exit_code == 2
    assert cli("config", "defaults", "--json", "--csv").exit_code == 2
    assert cli("config", "diff", "--json", "--csv").exit_code == 2


def test_csv_diff_without_changes_keeps_header(cli):
    assert _csv(cli("config", "diff", "--csv").output) == [["key", "value"]]
    assert not config_path().exists()


def test_defaults_restricted_to_keys(cli, saved):
    result = cli("config", "defaults", "refresh_seconds", "privacy", "--json")
    assert json.loads(result.output) == {"refresh_seconds": 30, "privacy": False}
    assert "base_currency" not in cli("config", "defaults", "privacy").output
    assert json.loads(cli("config", "defaults", "--json").output) == Config().redacted()


def test_diff_restricted_to_keys(cli, saved):
    assert json.loads(cli("config", "diff", "privacy", "base_currency", "--json").output) == {"privacy": True}
    assert json.loads(cli("config", "diff", "base_currency", "--json").output) == {}
    assert "Selected settings match defaults" in cli("config", "diff", "base_currency").output
    assert json.loads(cli("config", "diff", "quote_api_key", "--json").output) == {"quote_api_key": "(set)"}


def test_diff_exit_code(cli, saved):
    assert cli("config", "diff", "--exit-code").exit_code == 1
    assert cli("config", "diff", "--exit-code", "privacy", "--json").exit_code == 1
    assert cli("config", "diff", "--exit-code", "base_currency").exit_code == 0
    assert cli("config", "diff").exit_code == 0


def test_diff_exit_code_zero_when_defaults(cli):
    assert cli("config", "diff", "--exit-code").exit_code == 0
    assert not config_path().exists()


def test_keys_json_search_and_changed(cli, saved):
    assert json.loads(cli("config", "keys", "--json").output) == [f.name for f in fields(Config)]
    assert cli("config", "keys", "--search", "MENUBAR").output.splitlines() == ["menubar_display", "menubar_symbol"]
    assert json.loads(cli("config", "keys", "--search", "quote", "--json").output) == [
        "quote_provider",
        "quote_api_key",
    ]
    assert cli("config", "keys", "--search", "no-such-fictional").output == ""
    assert json.loads(cli("config", "keys", "--search", "no-such-fictional", "--json").output) == []
    assert cli("config", "keys", "--search", " ").exit_code == 2
    changed = cli("config", "keys", "--changed").output.splitlines()
    assert changed == ["refresh_seconds", "privacy", "default_account", "market_strip", "quote_api_key"]
    assert json.loads(cli("config", "keys", "--changed", "--search", "refresh", "--json").output) == ["refresh_seconds"]
    assert SECRET not in cli("config", "keys", "--changed").output


def test_keys_changed_is_empty_for_defaults(cli):
    assert json.loads(cli("config", "keys", "--changed", "--json").output) == []
    assert not config_path().exists()


def test_validate_quiet_reports_only_through_exit_status(cli):
    result = cli("config", "validate", "--quiet")
    assert (result.exit_code, result.output) == (0, "")
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text(f'quote_api_key = "{SECRET}"\nrefresh_seconds = 1\n', encoding="utf-8")
    before = config_path().read_bytes()
    result = cli("config", "validate", "-q")
    assert (result.exit_code, result.output) == (1, "")
    assert cli("config", "validate", "--quiet", "--json").exit_code == 2
    assert config_path().read_bytes() == before


def test_theme_json_lists_embedded_palettes(cli):
    Config(theme="kanagawa").save()
    before = config_path().read_bytes()
    payload = json.loads(cli("theme", "--json").output)
    assert payload["theme"] == "kanagawa"
    assert payload["current"] == "kanagawa"
    assert [t["name"] for t in payload["themes"]] == sorted(OMARCHY_PALETTES)
    assert all(t["mode"] in ("dark", "light") for t in payload["themes"])
    assert {"name": "kanagawa", "label": "Kanagawa"}.items() <= next(
        t for t in payload["themes"] if t["name"] == "kanagawa"
    ).items()
    assert cli("theme", "--json", "set", "kanagawa").exit_code == 2
    assert config_path().read_bytes() == before


def test_theme_json_auto_without_omarchy(cli):
    payload = json.loads(cli("theme", "--json").output)
    assert payload["theme"] == "auto"
    assert payload["current"] in OMARCHY_PALETTES
    assert not config_path().exists()


@pytest.mark.parametrize(
    "args",
    [
        ("config", "get", "privacy", "fictional_unknown"),
        ("config", "get", "--value", "fictional_unknown"),
        ("config", "defaults", "fictional_unknown"),
        ("config", "diff", "fictional_unknown", "--exit-code"),
    ],
)
def test_unknown_keys_fail_with_existing_error(cli, saved, args):
    result = cli(*args)
    assert result.exit_code == 1
    assert "Unknown setting 'fictional_unknown'" in result.output
