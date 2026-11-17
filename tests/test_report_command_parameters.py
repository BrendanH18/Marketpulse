"""Command parameters are available as ordinary offline report and summary rows."""

import json
from collections import Counter
from itertools import groupby

import click
import pytest
from click.testing import CliRunner

from marketpulse.cli import App, main
from marketpulse.market import MarketData


@pytest.fixture
def cli(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("Command discovery must not open the tracker or market client")

    monkeypatch.setattr(App, "tracker", property(forbidden))
    monkeypatch.setattr(MarketData, "__init__", forbidden)
    original_files = list(tmp_path.iterdir())
    runner = CliRunner()

    def invoke(*arguments):
        result = runner.invoke(main, arguments)
        assert result.exit_code == 0, result.output
        assert list(tmp_path.iterdir()) == original_files
        return json.loads(result.output)

    return invoke


def test_report_matches_the_existing_command_catalog(cli):
    rows = cli("report", "command-parameters")
    assert all(
        tuple(row) == ("command", "position", "name", "kind", "flags", "required", "type", "help") for row in rows
    )

    commands = cli("commands", "--details", "--json")
    groups = [(command, list(parameters)) for command, parameters in groupby(rows, key=lambda row: row["command"])]
    assert [command for command, _ in groups] == [row["command"] for row in commands if row["parameters"]]
    expected = {row["command"]: row["parameters"] for row in commands}
    for command, parameters in groups:
        assert [row["position"] for row in parameters] == list(range(1, len(parameters) + 1))
        assert [
            {key: value for key, value in row.items() if key not in {"command", "position"}} for row in parameters
        ] == (expected[command])


def test_only_visible_parameters_receive_positions(cli, monkeypatch):
    monkeypatch.setitem(
        main.commands,
        "example-visible",
        click.Command(
            "example-visible",
            params=[
                click.Argument(["source"], required=True),
                click.Option(["--internal"], hidden=True),
                click.Option(["--visible"], help="A public option."),
            ],
        ),
    )
    monkeypatch.setitem(
        main.commands,
        "example-hidden",
        click.Command("example-hidden", params=[click.Option(["--public"])], hidden=True),
    )

    assert cli("report", "command-parameters", "--prefix", "command=example-") == [
        {
            "command": "example-visible",
            "position": 1,
            "name": "source",
            "kind": "argument",
            "flags": ["source"],
            "required": True,
            "type": "text",
            "help": "",
        },
        {
            "command": "example-visible",
            "position": 2,
            "name": "visible",
            "kind": "option",
            "flags": ["--visible"],
            "required": False,
            "type": "text",
            "help": "A public option.",
        },
    ]


def test_report_finds_secondary_flags_and_summarize_counts_parameter_kinds(cli):
    assert cli("report", "command-parameters", "--has-item", 'flags="--no-required"', "--fields", "command,flags") == [
        {"command": "commands", "flags": ["--has-required", "--no-required"]}
    ]

    commands = cli("commands", "--exact", "accounts add", "--details", "--json")
    counts = Counter(parameter["kind"] for parameter in commands[0]["parameters"])
    assert cli(
        "summarize",
        "command-parameters",
        "--where",
        "command=accounts add",
        "--group-by",
        "kind",
        "--metric",
        "parameters=count",
        "--sort",
        "kind",
    ) == [{"kind": kind, "parameters": count} for kind, count in sorted(counts.items())]
