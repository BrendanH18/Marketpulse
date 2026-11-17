"""Report spelling hints reject the original input without opening saved data."""

import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main


@pytest.fixture(autouse=True)
def no_tracker(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Report discovery must not open the tracker")

    monkeypatch.setattr("marketpulse.services.Tracker.open", forbidden)


@pytest.mark.parametrize("command", ["report", "summarize"])
@pytest.mark.parametrize("source,expected", [("positons", "positions"), ("derve-functions", "derive-functions")])
def test_source_typo_suggests_but_does_not_execute(command, source, expected, tmp_path):
    output = tmp_path / "report.json"
    result = CliRunner().invoke(main, [command, source, "--output", str(output)])
    assert result.exit_code == 2
    assert "Invalid value for 'SOURCE'" in result.output
    assert f"Did you mean '{expected}'?" in result.output
    assert not output.exists()
    assert not (tmp_path / "data" / "marketpulse.db").exists()


@pytest.mark.parametrize("command", ["report", "summarize"])
def test_unrelated_source_has_no_misleading_suggestion(command):
    result = CliRunner().invoke(main, [command, "zzzzzzzzzzzz"])
    assert result.exit_code == 2
    assert "Did you mean" not in result.output


@pytest.mark.parametrize("command", ["report", "summarize"])
def test_derive_typo_has_hint_before_loading_data(command, tmp_path):
    output = tmp_path / "report.json"
    result = CliRunner().invoke(main, [command, "positions", "--derive", "n=negat:quantity", "--output", str(output)])
    assert result.exit_code == 2
    assert "Unknown --derive function 'negat'" in result.output
    assert "Did you mean 'negate'?" in result.output
    assert "report derive-functions" in result.output
    assert not output.exists()


def test_unrelated_derive_function_keeps_discovery_guidance():
    result = CliRunner().invoke(main, ["report", "positions", "--derive", "n=zzzzzzzzzzzz:quantity"])
    assert result.exit_code == 2
    assert "report derive-functions" in result.output
    assert "Did you mean" not in result.output


@pytest.mark.parametrize("command", ["report", "summarize"])
def test_valid_source_remains_exact_and_offline(command):
    result = CliRunner().invoke(main, [command, "positions", "--describe"])
    assert result.exit_code == 0
    assert json.loads(result.output)["source"] == "positions"


def test_valid_derive_keeps_value_and_input_column():
    result = CliRunner().invoke(
        main,
        ["report", "derive-functions", "--derive", "shout=upper:function", "--where", "function=upper"],
    )
    assert result.exit_code == 0
    (row,) = json.loads(result.output)
    assert row["function"] == "upper"
    assert row["shout"] == "UPPER"
