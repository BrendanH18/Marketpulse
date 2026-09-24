import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.config import Config, config_path


@pytest.fixture
def cli(tracker, monkeypatch, fake):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "160")
    fake.set_history("AAPL", {"2024-01-02": 150.0, "2024-01-03": 155.0, "2024-01-04": 152.0})
    runner = CliRunner()

    def invoke(*args: str):
        return runner.invoke(main, list(args), catch_exceptions=False)

    return invoke


def test_trading_flow(cli, store):
    assert "Added My TFSA" in cli("accounts", "add", "My TFSA", "-t", "TFSA").output
    out = cli("buy", "AAPL", "10", "150", "-a", "My TFSA", "--fees", "5").output
    assert "Bought 10 AAPL @ 150.00 USD in My TFSA" in out and "avg 150.50" in out
    live = cli("buy", "XEQT.TO", "5", "-a", "tfsa").output
    assert "@ 40.00 CAD" in live
    oversell = cli("sell", "AAPL", "20", "160", "-a", "My TFSA")
    assert oversell.exit_code == 1 and "only 10 held" in oversell.output
    sold = cli("sell", "AAPL", "4", "160", "-a", "My TFSA").output
    assert "realized +38.00 USD" in sold  # 4 × (160 − 150.50 avg incl. fees)
    assert "BUY" in cli("activity").output
    assert "Deleted transaction" in cli("undo", "-y").output
    assert len(store.transactions()) == 2


def test_account_resolution_errors(cli, store):
    cli("accounts", "add", "A")
    cli("accounts", "add", "B")
    result = cli("buy", "AAPL", "1", "1")
    assert result.exit_code == 1 and "Several accounts" in result.output
    missing = cli("buy", "AAPL", "1", "1", "-a", "Nope")
    assert missing.exit_code == 1 and "No account 'Nope'" in missing.output


def test_first_trade_creates_default_account(cli, store):
    assert "Created account 'Main'" in cli("buy", "AAPL", "1", "100").output


def test_income_events_and_assets(cli, store):
    cli("accounts", "add", "Main")
    assert "Deposit" in cli("deposit", "1000").output
    assert "Dividend" in cli("dividend", "AAPL", "12.5").output
    assert "Added GIC1" in cli("asset", "fixed", "GIC1", "5000", "--rate", "4", "--maturity", "2030-01-01").output
    assert "Added HOUSE" in cli("asset", "manual", "HOUSE", "500000", "--class", "real_estate").output
    assert "valued at" in cli("asset", "value", "HOUSE", "550000").output
    assert "GIC1" in cli("asset", "list").output


def test_status_outputs(cli, store):
    cli("buy", "AAPL", "1", "100")
    payload = json.loads(cli("status", "--json").output)
    assert payload["net_worth"] == pytest.approx(270)
    waybar = json.loads(cli("status", "--waybar").output)
    assert waybar["class"] == "up" and "Net worth" in waybar["tooltip"]
    assert "▲" in cli("status", "--short").output
    assert "AAPL" in cli("holdings").output


def test_market_commands(cli):
    assert "Apple Inc." in cli("quote", "AAPL").output
    assert "XEQT.TO" in cli("quote", "AAPL", "XEQT.TO").output
    assert cli("chart", "AAPL", "-p", "1mo").exit_code == 0
    bad = cli("quote", "NOPE")
    assert bad.exit_code == 1


def test_config_theme_alerts_export(cli):
    assert cli("config", "set", "theme", "Kanagawa").exit_code == 0
    assert Config.load(config_path()).theme == "kanagawa"
    assert cli("config", "set", "refresh_seconds", "abc").exit_code == 1
    assert cli("config", "set", "privacy", "yes").exit_code == 0
    assert cli("theme", "set", "osaka", "jade").exit_code == 0
    assert cli("theme").exit_code == 0
    assert "Alert #1: AAPL ≥ 100.00" in cli("alerts", "add", "AAPL", ">", "100").output
    assert "Fired" in cli("alerts", "check").output
    cli("buy", "AAPL", "1", "100")
    assert cli("export").output.startswith("date,account,type")


def test_backup_commands(cli, store, tmp_path):
    assert "No backups yet" in cli("backup", "list").output
    assert "Backed up to" in cli("backup").output  # bare `backup` backs up now
    cli("backup", "now", str(tmp_path / "copy.db"))
    assert (tmp_path / "copy.db").exists()
    listing = cli("backup", "list").output
    assert "manual" in listing and "copy.db" not in listing  # explicit paths live outside the backups dir


def test_tax_report_explains_superficial_losses_and_transfer_issues(cli, store):
    cli("accounts", "add", "Taxable", "-t", "NONREG")
    cli("accounts", "add", "My TFSA", "-t", "TFSA")
    cli("buy", "XEQT.TO", "10", "30", "-a", "Taxable", "-d", "2024-01-02")
    cli("sell", "XEQT.TO", "10", "25", "-a", "Taxable", "-d", "2024-03-01")  # −$50 loss
    cli("buy", "XEQT.TO", "10", "25", "-a", "My TFSA", "-d", "2024-03-05")  # …bought back in the TFSA
    cli("buy", "XEQT.TO", "5", "20", "-a", "Taxable", "-d", "2024-06-03")
    moved = cli("transfer", "XEQT.TO", "5", "--from", "Taxable", "--to", "My TFSA", "-d", "2024-07-02")
    assert "no --price given" in moved.output  # back-dated and unpriced: warned, not guessed
    out = cli("tax", "-y", "2024").output
    assert "superficial" in out and "50.00 of a 50.00 loss denied" in out
    assert "deemed sale at market value" in out
    assert "spouse or a corporation" in out


def test_fhsa_room_shows_capped_carry_forward(cli, store):
    cli("accounts", "add", "My FHSA", "-t", "FHSA")
    cli("accounts", "room", "FHSA", "2023", "8000")
    out = cli("tax").output
    assert "Capped" in out and "16,000.00" in out  # never more than $16k in a year
