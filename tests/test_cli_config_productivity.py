"""Offline configuration tooling: fictional paths, settings, and sentinel API keys."""

import json
from dataclasses import fields

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.config import Config, config_path


@pytest.fixture
def cli(monkeypatch):
    def no_tracker(*args, **kwargs):
        raise AssertionError("Configuration commands must not open the ledger or market client")

    monkeypatch.setattr("marketpulse.services.Tracker.open", no_tracker)
    runner = CliRunner()
    return lambda *args: runner.invoke(main, list(args), catch_exceptions=False)


def test_redacted_json_get_and_diff_do_not_write_or_open_ledger(cli):
    Config(quote_api_key="fictional-secret-sentinel", privacy=True, default_account="Fictional TFSA").save()
    path = config_path()
    before = path.read_bytes()
    result = cli("config", "--json")
    assert result.exit_code == 0
    settings = json.loads(result.output)
    assert settings["quote_api_key"] == "(set)"
    assert settings["privacy"] is True
    assert "fictional-secret-sentinel" not in result.output
    result = cli("config", "get", "quote_api_key", "--json")
    assert json.loads(result.output) == {"quote_api_key": "(set)"}
    assert "(set)" in cli("config", "get", "quote_api_key").output
    assert json.loads(cli("config", "diff", "--json").output) == {
        "quote_api_key": "(set)",
        "privacy": True,
        "default_account": "Fictional TFSA",
    }
    assert "Fictional TFSA" in cli("config", "diff").output
    assert path.read_bytes() == before


def test_defaults_keys_and_empty_diff_work_without_config_file(cli):
    assert not config_path().exists()
    assert json.loads(cli("config", "defaults", "--json").output) == Config().redacted()
    assert cli("config", "keys").output.splitlines() == [f.name for f in fields(Config)]
    assert "base_currency" in cli("config", "defaults").output
    assert json.loads(cli("config", "diff", "--json").output) == {}
    assert "match defaults" in cli("config", "diff").output
    assert not config_path().exists()


def test_reset_one_key_preserves_other_values_and_secret(cli):
    Config(privacy=True, quote_api_key="fictional-secret-sentinel", refresh_seconds=60).save()
    result = cli("config", "reset", "privacy")
    assert result.exit_code == 0
    actual = Config.load()
    assert not actual.privacy
    assert actual.refresh_seconds == 60
    assert actual.quote_api_key == "fictional-secret-sentinel"
    before = config_path().read_bytes()
    assert cli("config", "reset", "quote_api_key").exit_code == 1
    assert config_path().read_bytes() == before


def test_dry_run_normalizes_and_validates_without_creating_or_changing_file(cli):
    result = cli("config", "set", "--dry-run", "base_currency", "usd")
    assert result.exit_code == 0
    assert "USD" in result.output and "not saved" in result.output
    assert not config_path().exists()
    Config(refresh_seconds=60).save()
    before = config_path().read_bytes()
    assert cli("config", "set", "--dry-run", "refresh_seconds", "90").exit_code == 0
    assert cli("config", "set", "--dry-run", "refresh_seconds", "1").exit_code == 1
    assert config_path().read_bytes() == before


@pytest.mark.parametrize("value", ["12$", "éUR", "C A", "CADDD"])
def test_currency_rejects_non_ascii_or_nonletter_codes_without_writing(cli, value):
    result = cli("config", "set", "base_currency", value)
    assert result.exit_code == 1 and "3-letter" in result.output
    assert not config_path().exists()


def test_terminal_validation_and_valid_save(cli):
    assert cli("config", "set", "terminal", "invented-shell").exit_code == 1
    assert not config_path().exists()
    assert cli("config", "set", "terminal", "wezterm").exit_code == 0
    assert Config.load().terminal == "wezterm"
    assert cli("config", "set", "base_currency", "usd").exit_code == 0
    assert Config.load().base_currency == "USD"


@pytest.mark.parametrize("command", [("get", "unknown"), ("reset", "unknown"), ("set", "unknown", "x")])
def test_unknown_keys_fail_without_writing(cli, command):
    assert cli("config", *command).exit_code == 1
    assert not config_path().exists()


def test_validate_missing_and_valid_files_without_writing(cli):
    assert json.loads(cli("config", "validate", "--json").output) == {"ok": True, "issues": []}
    assert not config_path().exists()
    Config(terminal="kitty", quote_api_key="fictional-secret-sentinel").save()
    before = config_path().read_bytes()
    assert cli("config", "validate").exit_code == 0
    assert config_path().read_bytes() == before


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ('privacy = "yes"', "privacy"),
        ("market_strip = [1]", "market_strip"),
        ("refresh_seconds = 5.5", "refresh_seconds"),
        ("refresh_seconds = inf", "refresh_seconds"),
        ("refresh_seconds = nan", "refresh_seconds"),
        ("capital_gains_inclusion = nan", "capital_gains_inclusion"),
        ("capital_gains_inclusion = 2", "capital_gains_inclusion"),
        ("refresh_seconds = 1", "refresh_seconds"),
        ('base_currency = "12$"', "base_currency"),
        ('terminal = "invalid"', "terminal"),
        ('chart_period = "invalid"', "chart_period"),
        ('menubar_display = "invalid"', "menubar_display"),
        ('quote_provider = "invalid"', "quote_provider"),
        ('theme = "invalid"', "theme"),
        ('fictional_unknown_key = "fictional-secret-sentinel"', ""),
        ("quote_api_key = 12345", "quote_api_key"),
    ],
)
def test_validate_checks_raw_values_ignored_or_coerced_by_loader(cli, raw, key):
    path = config_path()
    path.write_text(raw, encoding="utf-8")
    result = cli("config", "validate", "--json")
    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert len(report["issues"]) == 1
    assert report["issues"][0]["key"] == key
    assert report["issues"][0]["message"]
    assert "fictional-secret-sentinel" not in result.output
    assert path.read_text(encoding="utf-8") == raw


@pytest.mark.parametrize("raw", [b'quote_api_key = "fictional-secret-sentinel"\n!bad', b"\xff"])
def test_validate_malformed_file_does_not_echo_source_or_crash(cli, raw):
    config_path().write_bytes(raw)
    result = cli("config", "validate", "--json")
    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["issues"] == [{"key": "", "message": "Cannot read configuration as UTF-8 TOML."}]
    assert "fictional-secret-sentinel" not in result.output
    assert config_path().read_bytes() == raw


def test_nonfinite_legacy_numbers_remain_inspectable_with_strict_json(cli):
    config_path().write_text("capital_gains_inclusion = inf\nrefresh_seconds = nan", encoding="utf-8")
    assert Config.load().refresh_seconds == 30
    report = json.loads(cli("config", "--json").output)
    assert report["capital_gains_inclusion"] is None
    assert report["refresh_seconds"] == 30
    assert cli("config", "set", "capital_gains_inclusion", "inf").exit_code == 1
