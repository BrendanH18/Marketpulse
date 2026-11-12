"""Offline quote-cache browsing and selectable diagnostics (#126) on fictional data."""

import csv
import io
import json
import time

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.cli.doctor import CHECKS
from marketpulse.models import Quote


@pytest.fixture
def cli(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "160")

    def invoke(*args):
        return CliRunner().invoke(main, list(args), catch_exceptions=False)

    return invoke


@pytest.fixture
def offline(cli, fake):
    """Invoke a command and assert it made no network request at all."""
    fake.offline = True

    def invoke(*args):
        result = cli(*args)
        assert fake.calls == [], f"{args} made a network request"
        return result

    return invoke


@pytest.fixture
def cache(store, offline):
    now = time.time()
    store.cache_quotes(
        [
            Quote("MAPL.TO", 12.5, 12.0, name="Fictional Maple Fund", currency="CAD", fetched_at=now - 2 * 3600),
            Quote("ZZZ", 50.0, 52.0, name="Imaginary Corp", currency="USD", fetched_at=now - 3 * 86400),
            Quote("MOON", 10.0, 10.0, name="Lunar Holdings", currency="USD", fetched_at=now - 600),
            Quote("NOAGE", 5.0, 4.0, name="Undated Maple Trust", currency="cad", fetched_at=0.0),
        ]
    )
    return offline


def rows(invoke, *args) -> list[dict]:
    result = invoke("quote", "--cached", *args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def symbols(invoke, *args) -> list[str]:
    return [r["symbol"] for r in rows(invoke, *args)]


# ── 1. --all ──────────────────────────────────────────────────────────────────


def test_all_lists_every_cached_quote_offline_and_stale(cache, store):
    payload = rows(cache, "--all")
    assert [r["symbol"] for r in payload] == ["MAPL.TO", "MOON", "NOAGE", "ZZZ"]
    assert all(r["stale"] is True and r["error"] is None for r in payload)
    human = cache("quote", "--cached", "--all")
    assert human.exit_code == 0
    assert "Cached quotes (offline)" in human.output and "Lunar Holdings" in human.output
    assert "Imaginary Corp" in human.output and "3 d ago" in human.output
    assert set(store.all_cached_quotes()) == {"MAPL.TO", "MOON", "NOAGE", "ZZZ"}


def test_all_on_an_empty_cache_fails(offline):
    result = offline("quote", "--cached", "--all")
    assert result.exit_code == 1 and "offline quote cache is empty" in result.output
    empty = offline("quote", "--cached", "--all", "--json")
    assert empty.exit_code == 1 and json.loads(empty.output) == []


def test_symbols_stay_required_without_all(cli, fake):
    assert cli("quote").exit_code == 2
    assert cli("quote", "--cached").exit_code == 2
    assert cli("quote", "--cached", "--all", "ZZZ").exit_code == 2
    assert fake.calls == []


# ── 2. --currency ─────────────────────────────────────────────────────────────


def test_currency_filter_ignores_case_and_repeats(cache):
    assert symbols(cache, "--all", "--currency", "cad") == ["MAPL.TO", "NOAGE"]
    assert symbols(cache, "--all", "--currency", " usd ", "--currency", "CAD") == ["MAPL.TO", "MOON", "NOAGE", "ZZZ"]
    assert symbols(cache, "MOON", "MAPL.TO", "--currency", "USD") == ["MOON"]


# ── 3. --search ───────────────────────────────────────────────────────────────


def test_search_matches_symbol_or_name(cache):
    assert symbols(cache, "--all", "--search", "MAPLE") == ["MAPL.TO", "NOAGE"]
    assert symbols(cache, "--all", "--search", "zz") == ["ZZZ"]
    none = cache("quote", "--cached", "--all", "--search", "nothing")
    assert none.exit_code == 1 and "No cached quotes match the filters" in none.output


# ── 4. --older-than / --newer-than ────────────────────────────────────────────


def test_cache_age_filters(cache):
    assert symbols(cache, "--all", "--older-than", "1d") == ["ZZZ"]
    assert symbols(cache, "--all", "--newer-than", "1h") == ["MOON"]
    assert symbols(cache, "--all", "--older-than", "30m", "--newer-than", "1w") == ["MAPL.TO", "ZZZ"]
    assert symbols(cache, "--all", "--older-than", "900S", "--newer-than", "2.5h") == ["MAPL.TO"]


# ── 5. --sort / --descending ──────────────────────────────────────────────────


def test_sort_by_symbol_age_and_change(cache):
    assert symbols(cache, "--all", "--sort", "symbol", "--descending") == ["ZZZ", "NOAGE", "MOON", "MAPL.TO"]
    assert symbols(cache, "--all", "--sort", "age") == ["MOON", "MAPL.TO", "ZZZ", "NOAGE"]
    assert symbols(cache, "--all", "--sort", "change") == ["ZZZ", "MOON", "MAPL.TO", "NOAGE"]
    assert symbols(cache, "--all", "--sort", "change", "--descending") == ["NOAGE", "MAPL.TO", "MOON", "ZZZ"]


def test_named_symbols_keep_order_and_missing_rows(cache):
    payload = rows(cache, "ZZZ", "MISSING", "MOON")
    assert [(r["symbol"], r["error"]) for r in payload] == [
        ("ZZZ", None),
        ("MISSING", "not in the offline cache"),
        ("MOON", None),
    ]
    sorted_rows = rows(cache, "ZZZ", "MISSING", "MOON", "--sort", "age")
    assert [r["symbol"] for r in sorted_rows] == ["MOON", "ZZZ", "MISSING"]
    human = cache("quote", "--cached", "ZZZ", "MISSING", "--sort", "age")
    assert human.exit_code == 0 and "MISSING: not in the offline cache" in human.output


# ── 6. --csv ──────────────────────────────────────────────────────────────────


def test_csv_export(cache):
    result = cache("quote", "--cached", "--all", "--currency", "USD", "--sort", "change", "--csv")
    assert result.exit_code == 0
    reader = csv.DictReader(io.StringIO(result.output))
    assert reader.fieldnames is not None and reader.fieldnames[:3] == ["symbol", "name", "price"]
    data = list(reader)
    assert [r["symbol"] for r in data] == ["ZZZ", "MOON"]
    assert data[0]["price"] == "50.0" and data[0]["stale"] == "True" and data[0]["currency"] == "USD"
    missing = cache("quote", "--cached", "NOPE", "--csv")
    assert missing.exit_code == 1
    assert list(csv.DictReader(io.StringIO(missing.output)))[0]["error"] == "not in the offline cache"


# ── usage rules for the cache options ─────────────────────────────────────────


@pytest.mark.parametrize(
    "args",
    [
        ["--all"],
        ["ZZZ", "--currency", "USD"],
        ["ZZZ", "--search", "x"],
        ["ZZZ", "--older-than", "1h"],
        ["ZZZ", "--newer-than", "1h"],
        ["ZZZ", "--sort", "age"],
        ["ZZZ", "--csv"],
        ["--cached", "--all", "--descending"],
        ["--cached", "--all", "--json", "--csv"],
        ["--cached", "--all", "--search", "  "],
        ["--cached", "--all", "--currency", " "],
        ["--cached", "--all", "--older-than", "2"],
        ["--cached", "--all", "--older-than", "0h"],
        ["--cached", "--all", "--newer-than", "1y"],
        ["--cached", "--all", "--older-than", "2h", "--newer-than", "1h"],
        ["--cached", "--all", "--sort", "price"],
    ],
)
def test_cache_option_usage_errors(cache, args):
    result = cache("quote", *args)
    assert result.exit_code == 2, result.output


def test_cache_options_require_cached_message(cli):
    result = cli("quote", "ZZZ", "--csv", "--sort", "age")
    assert "--sort, --csv require --cached" in result.output


# ── 7–10. doctor selection ────────────────────────────────────────────────────


def check_names(payload: dict) -> list[str]:
    return [c["check"] for c in payload["checks"]]


def doctor_json(invoke, *args) -> dict:
    result = invoke("doctor", *args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_doctor_only_runs_named_checks(offline):
    payload = doctor_json(offline, "--offline", "--only", "Ledger-Checks", "--only", "market_data", "--only", "version")
    assert check_names(payload) == ["version", "ledger checks", "market data"]
    assert payload["checks"][-1]["status"] == "skipped"


def test_doctor_only_market_data_still_respects_offline(offline):
    payload = doctor_json(offline, "--offline", "--only", "market data")
    assert payload["checks"] == [
        {"check": "market data", "status": "skipped", "detail": "Yahoo not contacted (--offline)"}
    ]


def test_doctor_exclude_skips_network_checks_entirely(cli, fake):
    fake.offline = True
    payload = doctor_json(cli, "--exclude", "market-data", "--exclude", "fallback-quotes")
    assert fake.calls == []  # excluded checks never run, even online
    assert "market data" not in check_names(payload) and "version" in check_names(payload)
    assert payload["ok"] is True


def test_doctor_failed_only(cli, fake):
    fake.offline = True
    result = cli("doctor", "--failed-only")
    assert result.exit_code == 0
    assert result.output.splitlines() == [line for line in result.output.splitlines() if line.startswith("✗")]
    assert "market data" in result.output
    payload = doctor_json(cli, "--failed-only")
    assert payload["ok"] is False and check_names(payload) == ["market data"]
    assert cli("doctor", "--failed-only", "--strict").exit_code == 1
    clean = cli("doctor", "--offline", "--failed-only")
    assert clean.exit_code == 0 and "No failed checks." in clean.output
    assert doctor_json(cli, "--offline", "--failed-only") == {"ok": True, "checks": []}


def test_doctor_summary_counts_by_status(cli, fake, offline):
    payload = doctor_json(offline, "--offline", "--summary")
    summary = payload["summary"]
    assert list(summary) == ["ok", "fail", "info", "skipped"]
    assert summary["skipped"] == 1 and summary["fail"] == 0 and payload["ok"] is True
    assert sum(summary.values()) == len(doctor_json(offline, "--offline")["checks"])
    human = offline("doctor", "--offline", "--summary", "--only", "market-data", "--only", "ledger-checks")
    assert human.output.strip() == "1 ok · 0 fail · 0 info · 1 skipped"


def test_doctor_summary_strict_with_a_failure(cli, fake):
    fake.offline = True
    result = cli("doctor", "--summary", "--strict", "--only", "market-data")
    assert result.exit_code == 1 and result.output.strip() == "0 ok · 1 fail · 0 info · 0 skipped"


@pytest.mark.parametrize(
    "args",
    [
        ["--only", "bogus"],
        ["--exclude", "network"],
        ["--only", "version", "--exclude", "theme"],
        ["--failed-only", "--summary"],
    ],
)
def test_doctor_usage_errors(offline, args):
    result = offline("doctor", "--offline", *args)
    assert result.exit_code == 2


def test_doctor_unknown_check_lists_valid_names(offline):
    result = offline("doctor", "--only", "bogus")
    assert "unknown check 'bogus'" in result.output
    assert all(name in result.output for name in CHECKS)


def test_doctor_default_output_unchanged(offline):
    payload = doctor_json(offline, "--offline")
    names = check_names(payload)
    assert names[:7] == ["version", "config", "database", "backups", "ledger", "ledger checks", "market data"]
    assert set(names) <= set(CHECKS)
