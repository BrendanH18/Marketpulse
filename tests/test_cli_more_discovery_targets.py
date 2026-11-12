"""Saved target inspection and command selection on fictional, offline data (#134)."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))

    def invoke(*args):
        return CliRunner().invoke(main, args, catch_exceptions=False)

    return invoke


@pytest.fixture
def saved(store):
    values = {"equity": 45.0, "etf": 45.0, "cash": 10.0, "other": 0.0}
    store.set_targets(values)
    return values


def rows(cli, *args):
    result = cli("targets", "--json", *args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_target_exports_and_projection(cli, saved):
    assert "Saved allocation targets" in " ".join(cli("targets").output.split())
    assert rows(cli) == [
        {"bucket": "cash", "label": "Cash", "target": 10.0},
        {"bucket": "equity", "label": "Equity", "target": 45.0},
        {"bucket": "etf", "label": "ETF", "target": 45.0},
        {"bucket": "other", "label": "Other", "target": 0.0},
    ]
    exported = list(csv.DictReader(io.StringIO(cli("targets", "--csv", "--fields", "target,bucket").output)))
    assert list(exported[0]) == ["target", "bucket"]
    assert exported[0] == {"target": "10.0", "bucket": "cash"}
    assert rows(cli, "--fields", "target,bucket")[0] == {"target": 10.0, "bucket": "cash"}
    assert cli("targets", "--buckets-only", "--descending", "--offset", "1", "--limit", "2").output == "etf\nequity\n"
    assert cli("targets", "--count").output.strip() == "4"


@pytest.mark.parametrize(
    "args,expected",
    [
        (("--class", "CASH", "--class", "other"), ["cash", "other"]),
        (("--exclude-class", "cash", "--exclude-class", "other"), ["equity", "etf"]),
        (("--search", " ETF "), ["etf"]),
        (("--search", "quity"), ["equity"]),
        (("--min-target", "45"), ["equity", "etf"]),
        (("--max-target", "10"), ["cash", "other"]),
        (("--positive",), ["cash", "equity", "etf"]),
        (("--zero",), ["other"]),
        (("--sort", "label"), ["cash", "etf", "equity", "other"]),
        (("--sort", "target", "--descending"), ["etf", "equity", "cash", "other"]),
        (("--limit", "1"), ["cash"]),
        (("--offset", "2"), ["etf", "other"]),
        (("--min-target", "10", "--max-target", "10", "--positive"), ["cash"]),
        (("--search", "unknown"), []),
    ],
)
def test_target_selection(cli, saved, args, expected):
    assert [r["bucket"] for r in rows(cli, *args)] == expected


def test_target_pages_and_no_side_effects(cli, saved, tracker, store, fake, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Target inspection must not value holdings or record snapshots")

    monkeypatch.setattr(tracker, "valuation", forbidden)
    fake.offline = True
    before = store.transactions(), store.snapshots(), store.targets()
    payload = rows(cli, "--min-target", "10", "--page-info", "--offset", "1", "--limit", "1")
    assert payload == {
        "rows": [{"bucket": "equity", "label": "Equity", "target": 45.0}],
        "total": 3,
        "offset": 1,
        "limit": 1,
    }
    assert rows(cli, "--page-info", "--offset", "9")["rows"] == []
    assert not fake.calls
    assert (store.transactions(), store.snapshots(), store.targets()) == before


@pytest.mark.parametrize(
    "args",
    [
        ("--positive", "--zero"),
        ("--min-target", "50", "--max-target", "10"),
        ("--min-target", "nan"),
        ("--max-target", "inf"),
        ("--max-target", "101"),
        ("--json", "--csv"),
        ("--count", "--json"),
        ("--buckets-only", "--csv"),
        ("--page-info",),
        ("--count", "--limit", "1"),
        ("--count", "--offset", "1"),
        ("--fields", "bucket"),
        ("--json", "--fields", "bucket,bucket"),
        ("--json", "--fields", "unknown"),
        ("--json", "--fields", ""),
        ("--class", "fictional"),
        ("--search", " "),
        ("--limit", "0"),
        ("--offset", "-1"),
    ],
)
def test_target_validation(cli, saved, store, args):
    assert cli("targets", *args).exit_code == 2
    assert store.targets() == saved


def test_empty_targets(cli):
    assert rows(cli) == []
    assert cli("targets", "--csv").output == "bucket,label,target\n"
    assert cli("targets", "--count").output.strip() == "0"
    assert cli("targets", "--buckets-only").output == ""
    assert "No targets saved" in cli("targets").output


def catalog(*args):
    result = CliRunner().invoke(main, ["commands", *args], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result.output


def test_command_exact_prefix_exclusions_and_depth(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Catalog must not open the tracker")

    monkeypatch.setattr("marketpulse.services.Tracker.open", forbidden)
    assert catalog("--exact", "  PROVIDER   STATUS ", "--paths") == "provider status\n"
    assert catalog("--exact", "missing", "--count").strip() == "0"
    assert catalog("--prefix", "PROVIDER S", "--paths") == "provider status\n"
    assert catalog("--group", "provider", "--exclude-group", "provider", "--paths") == ""
    all_paths = catalog("--paths").splitlines()
    selected = catalog("--exclude-group", "provider", "--exclude-group", "asset", "--paths").splitlines()
    assert selected == [p for p in all_paths if p.split()[0] not in {"provider", "asset"}]
    assert catalog("--group", "provider", "--min-depth", "2", "--depth", "2", "--paths").splitlines() == [
        "provider clear",
        "provider key",
        "provider status",
        "provider test",
    ]


@pytest.mark.parametrize(
    "option,condition",
    [
        ("--has-arguments", lambda ps: any(p["kind"] == "argument" for p in ps)),
        ("--no-arguments", lambda ps: not any(p["kind"] == "argument" for p in ps)),
        ("--has-required", lambda ps: any(p["required"] for p in ps)),
        ("--no-required", lambda ps: not any(p["required"] for p in ps)),
    ],
)
def test_command_parameter_presence(option, condition):
    all_rows = json.loads(catalog("--json", "--details"))
    selected = json.loads(catalog("--json", "--details", option))
    assert selected == [r for r in all_rows if condition(r["parameters"])]
    assert selected


def test_parameter_search_and_command_page_info():
    assert "provider key" in catalog("--parameter-search", "NAME", "--paths").splitlines()
    assert "provider status" in catalog("--parameter-search", "--csv", "--paths").splitlines()
    assert catalog("--parameter-search", "doesnotexist", "--count").strip() == "0"
    payload = json.loads(
        catalog("--group", "provider", "--leaves", "--json", "--page-info", "--limit", "2", "--offset", "1")
    )
    assert payload["total"] == 4 and payload["limit"] == 2 and payload["offset"] == 1
    assert [r["command"] for r in payload["rows"]] == ["provider key", "provider status"]
    assert "parameters" not in payload["rows"][0]
    assert "parameters" in json.loads(catalog("--json", "--page-info", "--details", "--limit", "1"))["rows"][0]


@pytest.mark.parametrize(
    "args",
    [
        ("--page-info",),
        ("--paths", "--details"),
        ("--paths", "--json"),
        ("--min-depth", "3", "--depth", "2"),
        ("--min-depth", "0"),
        ("--exclude-group", "unknown"),
        ("--exclude-group", "buy"),
        ("--exact", " "),
        ("--prefix", " "),
        ("--parameter-search", " "),
    ],
)
def test_command_validation(args):
    assert CliRunner().invoke(main, ["commands", *args], catch_exceptions=False).exit_code == 2
