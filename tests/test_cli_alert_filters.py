"""Offline saved-alert filters on fictional metadata."""

import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Alert


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    return lambda *args: CliRunner().invoke(main, ["alerts", "list", *args], catch_exceptions=False)


@pytest.fixture
def alerts(store):
    return [
        store.add_alert(Alert("ZETA", "above", 100, note="Fictional", triggered_at="2024-01-02T23:00:00+00:00")),
        store.add_alert(Alert("ALPHA", "below", 50, note=" \n", active=False)),
        store.add_alert(Alert("BETA", "up_pct", 10, note="", triggered_at="2024-02-01T01:00:00+00:00")),
        store.add_alert(Alert("GAMMA", "above", 100, note="Fictional second")),
    ]


@pytest.mark.parametrize(
    ("options", "indices"),
    [
        (("--min-threshold", "100"), [3, 0]),
        (("--max-threshold", "50"), [1, 2]),
        (("--min-threshold", "100", "--max-threshold", "100"), [3, 0]),
        (("--with-note",), [3, 0]),
        (("--without-note",), [1, 2]),
        (("--triggered-since", "2024-02-01"), [2]),
        (("--triggered-until", "2024-01-02"), [0]),
        (("--triggered-since", "2024-01-02", "--triggered-until", "2024-01-02"), [0]),
        (("--exclude-symbol", " zeta ", "--exclude-symbol", "ALPHA"), [2, 3]),
        (("--sort", "threshold"), [2, 1, 0, 3]),
        (("--sort", "threshold", "--descending"), [3, 0, 1, 2]),
        (("--sort", "triggered-at"), [0, 2, 1, 3]),
        (("--sort", "triggered-at", "--descending"), [2, 0, 3, 1]),
    ],
)
def test_filters_and_order(cli, store, fake, alerts, options, indices):
    before = store.alerts()
    rows = json.loads(cli(*options, "--json").output)
    assert [r["id"] for r in rows] == [alerts[i].id for i in indices]
    assert store.alerts() == before
    assert fake.calls == []


def test_page_metadata_counts_and_composition(cli, alerts, fake):
    options = ("--with-note", "--min-threshold", "100", "--sort", "threshold", "--descending")
    result = json.loads(cli(*options, "--json", "--page-info", "--limit", "1").output)
    assert result["total"] == 2 and result["returned"] == 1 and result["next_offset"] == 1
    assert result["items"][0]["id"] == alerts[3].id
    last = json.loads(cli(*options, "--json", "--page-info", "--offset", "1").output)
    assert last["items"][0]["id"] == alerts[0].id and last["next_offset"] is None
    empty = json.loads(cli(*options, "--json", "--page-info", "--offset", "99").output)
    assert empty == {"items": [], "total": 2, "returned": 0, "next_offset": None, "offset": 99, "limit": None}
    assert cli(*options, "--count", "--offset", "99").output.strip() == "2"
    assert fake.calls == []


@pytest.mark.parametrize(
    "options",
    [
        ("--min-threshold", "nan"),
        ("--max-threshold", "inf"),
        ("--min-threshold", "2", "--max-threshold", "1"),
        ("--with-note", "--without-note"),
        ("--page-info",),
        ("--page-info", "--csv"),
        ("--triggered-since", "2024-02-30"),
        ("--triggered-since", "2024-02-01", "--triggered-until", "2024-01-01"),
        ("--exclude-symbol", " "),
    ],
)
def test_invalid_filters(cli, fake, options):
    assert cli(*options).exit_code == 2
    assert fake.calls == []


def test_legacy_unknown_threshold_sorts_last_and_is_excluded_from_bounds(cli, store, fake):
    store._exec("INSERT INTO alerts(symbol, condition, threshold) VALUES ('FICTION', 'above', ?)", (float("inf"),))
    store.add_alert(Alert("ALPHA", "above", 10))
    for extra in [(), ("--descending",)]:
        rows = json.loads(cli("--json", "--sort", "threshold", *extra).output)
        assert [r["symbol"] for r in rows] == ["ALPHA", "FICTION"]
    assert len(json.loads(cli("--json", "--min-threshold", "0").output)) == 1
    assert fake.calls == []


def test_empty_human_output_and_privacy(cli, alerts, tracker):
    assert "No alerts match" in cli("--min-threshold", "999").output
    tracker.config.privacy = True
    tracker.config.save()
    result = cli("--min-threshold", "100")
    assert result.exit_code == 0
    assert "100" not in result.output
