"""Offline snapshot history, cached quotes and scriptable diagnostics on fictional data."""

import csv
import io
import json
import time

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.db import Snapshot
from marketpulse.models import Quote

SNAPS = [
    ("2024-01-02", 1000.0, 900.0, "CAD"),
    ("2024-01-03", 1012.5, 900.0, "CAD"),
    ("2024-01-04", 1001.25, 905.0, "CAD"),
    ("2024-01-05", 800.0, 700.0, "USD"),  # base currency changed: no change against CAD
    ("2024-01-08", 810.0, 700.0, "USD"),
]


@pytest.fixture
def cli(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "160")
    runner = CliRunner()

    def invoke(*args):
        return runner.invoke(main, list(args), catch_exceptions=False)

    return invoke


@pytest.fixture
def offline(cli, fake):
    """Invoke a command and assert it made no network request at all."""
    fake.offline = True

    def invoke(*args):
        calls = len(fake.calls)
        result = cli(*args)
        assert len(fake.calls) == calls, f"{args} made a network request"
        return result

    return invoke


@pytest.fixture
def snaps(store, offline):
    store.upsert_snapshots(
        [Snapshot(d, nw, book, 0.0, ccy, {"accounts": {"Secret": nw}}) for d, nw, book, ccy in SNAPS]
    )
    return offline


def as_json(invoke, *args):
    result = invoke(*args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


# ── 21–25: snapshots ──────────────────────────────────────────────────────────


def test_snapshots_table_lists_oldest_first_with_changes(snaps):
    out = snaps("snapshots").output
    assert "Net-worth snapshots" in out
    lines = [line for line in out.splitlines() if line.strip().startswith("2024-")]
    assert [line.split()[0] for line in lines] == [d for d, *_ in SNAPS]
    assert "1,012.50" in lines[1] and "+12.50" in lines[1]
    assert "-11.25" in lines[2]
    # The first row and the row after a currency change have no change value.
    assert len(lines[0].split()) == 4
    assert "800.00" in lines[3] and len(lines[3].split()) == 4
    assert "+10.00" in lines[4] and "USD" in lines[4]


def test_snapshots_json_records_and_change(snaps):
    rows = as_json(snaps, "snapshots")
    assert [r["date"] for r in rows] == [d for d, *_ in SNAPS]
    assert set(rows[0]) == {"date", "net_worth", "book", "contributions", "change", "currency"}
    assert [r["change"] for r in rows] == [None, 12.5, -11.25, None, 10.0]
    assert rows[1]["net_worth"] == 1012.5 and rows[1]["book"] == 900.0 and rows[1]["currency"] == "CAD"


def test_snapshots_since_until_filters_keep_change_against_previous_recorded(snaps):
    rows = as_json(snaps, "snapshots", "--since", "2024-01-03", "--until", "2024-01-05")
    assert [r["date"] for r in rows] == ["2024-01-03", "2024-01-04", "2024-01-05"]
    assert rows[0]["change"] == 12.5  # versus 2024-01-02, which is filtered out
    assert snaps("snapshots", "--since", "2025-01-01").output.strip() == "No matching snapshots."


def test_snapshots_limit_and_currency(snaps):
    assert [r["date"] for r in as_json(snaps, "snapshots", "--limit", "2")] == ["2024-01-05", "2024-01-08"]
    cad = as_json(snaps, "snapshots", "--currency", " cad ", "-n", "2")
    assert [r["date"] for r in cad] == ["2024-01-03", "2024-01-04"]
    assert as_json(snaps, "snapshots", "--currency", "EUR") == []
    assert [r["date"] for r in as_json(snaps, "snapshots", "--currency", "usd")] == ["2024-01-05", "2024-01-08"]


def test_snapshots_csv(snaps):
    result = snaps("snapshots", "--csv", "--currency", "CAD")
    assert result.exit_code == 0
    assert result.output.splitlines()[0] == "date,net_worth,book,contributions,change,currency"
    rows = list(csv.DictReader(io.StringIO(result.output)))
    assert [r["date"] for r in rows] == ["2024-01-02", "2024-01-03", "2024-01-04"]
    assert rows[0]["change"] == "" and float(rows[1]["change"]) == 12.5 and rows[2]["net_worth"] == "1001.25"


def test_snapshots_count_and_latest(snaps):
    assert snaps("snapshots", "--count").output == "5\n"
    assert snaps("snapshots", "--count", "--currency", "CAD", "--until", "2024-01-03").output == "2\n"
    latest = as_json(snaps, "snapshots", "--latest")
    assert latest["date"] == "2024-01-08" and latest["change"] == 10.0
    assert as_json(snaps, "snapshots", "--latest", "--currency", "CAD")["date"] == "2024-01-04"
    out = snaps("snapshots", "--latest").output
    assert "2024-01-08" in out and "2024-01-02" not in out
    rows = list(csv.DictReader(io.StringIO(snaps("snapshots", "--latest", "--csv").output)))
    assert [r["date"] for r in rows] == ["2024-01-08"]
    missing = snaps("snapshots", "--latest", "--currency", "EUR", "--json")
    assert missing.exit_code == 1 and "No matching snapshots" in missing.output


def test_snapshots_empty_store(offline):
    assert "No snapshots recorded yet" in offline("snapshots").output
    assert offline("snapshots", "--json").output == "[]\n"
    assert offline("snapshots", "--count").output == "0\n"
    assert offline("snapshots", "--csv").output.strip() == "date,net_worth,book,contributions,change,currency"
    assert offline("snapshots", "--latest").exit_code == 1


def test_snapshots_privacy_masks_human_output_only(snaps, tracker):
    tracker.config.privacy = True
    out = snaps("snapshots").output
    assert "2024-01-03" in out and "CAD" in out
    assert "1,012" not in out and "12.50" not in out and "900" not in out
    assert as_json(snaps, "snapshots")[1]["net_worth"] == 1012.5
    assert "1012.5" in snaps("snapshots", "--csv").output


@pytest.mark.parametrize(
    "args",
    [
        ["--json", "--csv"],
        ["--count", "--json"],
        ["--count", "--csv"],
        ["--count", "--latest"],
        ["--count", "--limit", "2"],
        ["--latest", "--limit", "2"],
        ["--limit", "0"],
        ["--since", "2024-02-01", "--until", "2024-01-01"],
        ["--since", "not-a-date"],
        ["--until", "2024-13-40"],
        ["--currency", "  "],
    ],
)
def test_snapshots_usage_errors(snaps, args):
    assert snaps("snapshots", *args).exit_code == 2


# ── 26–27: quotes ─────────────────────────────────────────────────────────────


@pytest.fixture
def cached(store, offline):
    fetched = time.time() - 7200
    store.cache_quotes(
        [
            Quote("FICT.TO", 12.5, 12.0, name="Fictional Maple Fund", currency="CAD", fetched_at=fetched),
            Quote("ZZZ", 50.0, 52.0, name="Imaginary Corp", currency="USD", fetched_at=fetched, source="fallback"),
        ]
    )
    return offline


def test_quote_cached_reads_only_the_store(cached):
    result = cached("quote", "--cached", "fict.to", "ZZZ", "MISSING")
    assert result.exit_code == 0
    out = result.output
    assert "Cached quotes (offline)" in out and "Fictional Maple Fund" in out and "Imaginary Corp" in out
    assert "2 h ago" in out and "MISSING: not in the offline cache" in out


def test_quote_cached_fails_when_nothing_is_cached(cached):
    result = cached("quote", "--cached", "NOPE", "NADA")
    assert result.exit_code == 1 and "No cached quotes for NOPE, NADA" in result.output


def test_quote_cached_json(cached):
    result = cached("quote", "--cached", "--json", "FICT.TO", "MISSING")
    assert result.exit_code == 0
    first, missing = json.loads(result.output)
    assert first["symbol"] == "FICT.TO" and first["price"] == 12.5 and first["prev_close"] == 12.0
    assert first["change"] == pytest.approx(0.5) and first["change_pct"] == pytest.approx(0.5 / 12 * 100)
    assert first["stale"] is True and first["currency"] == "CAD" and first["source"] == "yahoo"
    assert first["error"] is None and first["fetched_at"].startswith(time.strftime("%Y-"))
    assert missing == {
        "symbol": "MISSING",
        "name": None,
        "price": None,
        "prev_close": None,
        "change": None,
        "change_pct": None,
        "currency": None,
        "stale": None,
        "fetched_at": None,
        "source": None,
        "error": "not in the offline cache",
    }
    none = cached("quote", "--cached", "--json", "NOPE")
    assert none.exit_code == 1 and json.loads(none.output)[0]["error"] == "not in the offline cache"


def test_quote_json_live_uses_one_existing_request(cli, fake):
    calls = len(fake.calls)
    result = cli("quote", "--json", "AAPL", "NOPE")
    assert result.exit_code == 0
    assert len(fake.calls) == calls + 1  # the same single batch request as `quote AAPL NOPE`
    aapl, nope = json.loads(result.output)
    assert aapl["name"] == "Apple Inc." and aapl["price"] == 200.0 and aapl["prev_close"] == 190.0
    assert aapl["change"] == 10.0 and aapl["stale"] is False and aapl["source"] == "yahoo" and aapl["fetched_at"]
    assert nope["price"] is None and nope["error"]
    assert cli("quote", "--json", "NOPE").exit_code == 1


def test_quote_human_output_is_unchanged(cli):
    assert "Apple Inc." in cli("quote", "AAPL").output
    assert cli("quote", "NOPE").exit_code == 1
    assert cli("quote", ",").exit_code == 2


# ── 28–30: doctor ─────────────────────────────────────────────────────────────


def test_doctor_default_rows_and_exit_status(cli, fake):
    fake.set_quote("SPY", 500.0)
    result = cli("doctor")
    assert result.exit_code == 0
    labels = [line[2:20].strip() for line in result.output.splitlines()]
    assert labels[:8] == [
        "version",
        "config",
        "database",
        "backups",
        "ledger",
        "ledger checks",
        "market data",
        "theme",
    ]
    assert "✓ market data" in result.output and "Yahoo reachable" in result.output


def test_doctor_offline_makes_no_requests(offline, tracker, monkeypatch):
    monkeypatch.setattr(tracker.config, "quote_provider", "alphavantage")
    result = offline("doctor", "--offline")
    assert result.exit_code == 0
    assert "- market data" in result.output and "Yahoo not contacted (--offline)" in result.output
    # A missing key is a local configuration problem, so it is still reported offline.
    assert "fallback quotes" in result.output and "no key set" in result.output


def test_doctor_offline_skips_a_configured_fallback(offline, tracker):
    class Fallback:
        name = "fictional"
        label = "Fictional Quotes"

    tracker.market.fallback = Fallback()
    payload = as_json(offline, "doctor", "--offline")
    fallback = next(c for c in payload["checks"] if c["check"] == "fallback quotes")
    assert fallback == {
        "check": "fallback quotes",
        "status": "skipped",
        "detail": "Fictional Quotes not checked (--offline)",
    }


def test_doctor_json(cli, fake):
    fake.set_quote("SPY", 500.0)
    payload = as_json(cli, "doctor")
    assert payload["ok"] is True
    assert all(set(c) == {"check", "status", "detail"} for c in payload["checks"])
    assert {c["status"] for c in payload["checks"]} <= {"ok", "fail", "info", "skipped"}
    by_name = {c["check"]: c for c in payload["checks"]}
    assert by_name["market data"]["status"] == "ok" and by_name["version"]["status"] == "info"
    assert by_name["ledger checks"] == {"check": "ledger checks", "status": "ok", "detail": "consistent"}


def test_doctor_strict_exit_codes(cli, fake):
    fake.set_quote("SPY", 500.0)
    assert cli("doctor", "--strict").exit_code == 0
    # Offline Yahoo fails the market data check: reported but exit 0 unless --strict.
    fake.offline = True
    failing = cli("doctor")
    assert failing.exit_code == 0 and "✗ market data" in failing.output
    assert cli("doctor", "--strict").exit_code == 1
    strict_json = cli("doctor", "--strict", "--json")
    assert strict_json.exit_code == 1 and json.loads(strict_json.output)["ok"] is False
    # Skipped checks are not failures.
    calls = len(fake.calls)
    skipped = cli("doctor", "--offline", "--strict", "--json")
    assert len(fake.calls) == calls
    assert skipped.exit_code == 0 and json.loads(skipped.output)["ok"] is True
