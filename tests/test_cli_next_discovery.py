"""Offline discovery/diagnostics contracts, including lazy no-ledger discovery."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.cli.doctor import CHECKS, Check
from marketpulse.market import ProviderStatus


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))

    def invoke(*args):
        return CliRunner().invoke(main, args, catch_exceptions=False)

    return invoke


def test_catalog_is_lazy_and_complete(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Discovery must not open the tracker")

    monkeypatch.setattr("marketpulse.services.Tracker.open", forbidden)
    result = CliRunner().invoke(main, ["commands", "--json", "--details"], catch_exceptions=False)
    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert "provider status" in {r["command"] for r in rows}
    assert "commands" in {r["command"] for r in rows}
    buy = next(r for r in rows if r["command"] == "buy")
    assert any("--dry-run" in p["flags"] for p in buy["parameters"])
    assert "parameters" not in json.loads(CliRunner().invoke(main, ["commands", "--json"]).output)[0]


def test_catalog_filters_formats_and_pagination(cli):
    rows = json.loads(cli("commands", "--json").output)
    names = [r["command"] for r in rows]
    assert names == sorted(names)
    assert any(" " in n for n in names)
    assert int(cli("commands", "--count").output) == len(rows)
    assert all(r["group"] for r in json.loads(cli("commands", "--groups", "--json").output))
    assert all(not r["group"] for r in json.loads(cli("commands", "--leaves", "--json").output))
    assert all(r["depth"] == 1 for r in json.loads(cli("commands", "--depth", "1", "--json").output))
    group = json.loads(cli("commands", "--group", "provider", "--json").output)
    assert len(group) >= 4 and all(r["command"].startswith("provider") for r in group)
    found = json.loads(cli("commands", "--search", "OFFLINE", "--json").output)
    assert found and all("offline" in (r["command"] + " " + r["help"]).lower() for r in found)
    option = json.loads(cli("commands", "--option=--json", "--json", "--details").output)
    assert option and all(any("--json" in p["flags"] for p in r["parameters"]) for r in option)
    assert cli("commands", "--option", "nonexistent-flag", "--count").output.strip() == "0"
    page = json.loads(cli("commands", "--json", "--descending", "--offset", "2", "--limit", "3").output)
    assert [r["command"] for r in page] == sorted(names, reverse=True)[2:5]
    exported = list(csv.DictReader(io.StringIO(cli("commands", "--csv", "--details", "--limit", "1").output)))
    assert exported[0]["command"] == names[0] and isinstance(json.loads(exported[0]["parameters"]), list)
    assert "| Command | Help |" in cli("commands", "--markdown", "--limit", "1").output
    markdown = cli("commands", "--markdown", "--details", "--group", "provider").output
    assert "<br>" in markdown and all(line.startswith("|") for line in markdown.splitlines())
    assert "--json (boolean)" in cli("commands", "--group", "provider", "--details").output


@pytest.mark.parametrize(
    "args",
    [
        ("--json", "--csv"),
        ("--count", "--limit", "1"),
        ("--groups", "--leaves"),
        ("--group", "buy"),
        ("--depth", "0"),
        ("--offset", "-1"),
    ],
)
def test_catalog_invalid_combinations(cli, args):
    assert cli("commands", *args).exit_code == 2


def test_provider_status_selectors_and_csv(cli, tracker, fake, monkeypatch):
    rows = [
        ProviderStatus("yahoo", "Yahoo", "primary", ok=True),
        ProviderStatus("example", "Example", "fallback", ok=False, last_error="fictional,error"),
        ProviderStatus("unused", "Unused", "fallback"),
    ]
    monkeypatch.setattr(tracker.market, "provider_status", lambda: rows)
    before = len(fake.calls)
    assert json.loads(cli("provider", "status", "--json", "--name", "YAHOO").output) == [rows[0].__dict__]
    assert cli("provider", "status", "--role", "fallback", "--count").output.strip() == "2"
    for state, expected in [("ok", rows[0]), ("failing", rows[1]), ("untried", rows[2])]:
        assert json.loads(cli("provider", "status", "--state", state, "--json").output) == [expected.__dict__]
    output = cli("provider", "status", "--csv", "--state", "failing").output
    assert list(csv.DictReader(io.StringIO(output)))[0]["last_error"] == "fictional,error"
    assert cli("provider", "status", "--name", "missing", "--count").output.strip() == "0"
    assert cli("provider", "status", "--count", "--json").exit_code == 2
    assert len(fake.calls) == before


def test_doctor_filters_keep_unfiltered_strict_result(cli, monkeypatch):
    rows = [
        Check("version", "info", "Fictional version"),
        Check("ledger checks", "fail", "fictional issue"),
        Check("database", "ok", "fictional path"),
    ]
    monkeypatch.setattr("marketpulse.cli.doctor._collect", lambda *args, **kwargs: rows.copy())
    visible = cli("doctor", "--offline", "--status", "ok", "--json", "--strict")
    assert visible.exit_code == 1
    assert json.loads(visible.output) == {"ok": False, "checks": [rows[2].__dict__]}
    assert cli("doctor", "--search", "FICTIONAL", "--count").output.strip() == "3"
    assert cli("doctor", "--status", "ok", "--status", "fail", "--count").output.strip() == "2"
    output = cli("doctor", "--csv", "--search", "issue").output
    assert list(csv.DictReader(io.StringIO(output)))[0]["check"] == "ledger checks"
    summary = list(csv.DictReader(io.StringIO(cli("doctor", "--csv", "--summary").output)))
    assert {r["status"]: int(r["count"]) for r in summary} == {"ok": 1, "fail": 1, "info": 1, "skipped": 0}
    hidden = cli("doctor", "--failed-only", "--search", "version", "--strict")
    assert hidden.exit_code == 1 and "No matching failed checks." in hidden.output
    assert cli("doctor", "--csv", "--json").exit_code == 2
    assert cli("doctor", "--count", "--summary").exit_code == 2


def test_doctor_check_catalog_does_not_collect(cli, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("--list-checks must not execute checks")

    monkeypatch.setattr("marketpulse.cli.doctor._collect", forbidden)
    assert json.loads(cli("doctor", "--list-checks", "--json").output) == list(CHECKS)
    assert cli("doctor", "--list-checks", "--count").output.strip() == str(len(CHECKS))
    assert cli("doctor", "--list-checks").output.splitlines() == list(CHECKS)
    assert list(csv.DictReader(io.StringIO(cli("doctor", "--list-checks", "--csv").output))) == [
        {"check": name} for name in CHECKS
    ]
    assert cli("doctor", "--list-checks", "--strict").exit_code == 2
