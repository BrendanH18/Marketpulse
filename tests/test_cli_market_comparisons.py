"""Comparisons and symbol search (#130, items 51–60) against the fake Yahoo transport; no network."""

import csv
import io
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.market import CHART_URL, SEARCH_URL

GOLDEN = Path(__file__).parent / "fixtures" / "market_lookups"
DAYS = [f"2025-03-{d:02d}" for d in (3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 17, 18, 19, 20, 21)]
AAPL = [100, 102, 101, 104, 103, 99, 97, 98, 101, 105, 107, 106, 108, 110, 109]
XEQT = [30, 30.2, 30.1, 30.5, 30.4, 30.0, 29.8, 29.9, 30.3, 30.6, 30.8, 30.7, 31.0, 31.2, 31.1]
VFV = [120, 119, 121, 118, 117, 116, 118, 115, 114, 116, 113, 112, 114, 111, 110]
SYMS = ["AAPL", "XEQT.TO", "VFV.TO"]


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "120")
    return lambda *args: CliRunner().invoke(main, list(args), catch_exceptions=False)


@pytest.fixture
def market_data(fake):
    """Fifteen fictional March 2025 sessions for three symbols, and a fictional search."""
    fake.set_history("AAPL", dict(zip(DAYS, AAPL, strict=True)))
    fake.set_history("XEQT.TO", dict(zip(DAYS, XEQT, strict=True)), currency="CAD")
    fake.set_history("VFV.TO", dict(zip(DAYS, VFV, strict=True)), currency="CAD")
    fake.search_results = [
        {"symbol": "MAPL.TO", "longname": "Maple Leaf Growth ETF", "exchDisp": "Toronto", "typeDisp": "ETF"},
        {"symbol": "MAPL", "shortname": "Maple Holdings Inc.", "exchDisp": "NASDAQ", "typeDisp": "Equity"},
        {"symbol": "MAPL.V", "longname": "Maple Ventures Corp.", "exchDisp": "TSXV", "typeDisp": "Equity"},
        {"symbol": "MAPLX", "longname": "Maple Balanced Fund", "exchange": "NAS", "quoteType": "MUTUALFUND"},
        {"symbol": "MAPL-U.TO", "longname": "Maple Leaf Growth ETF USD", "exchDisp": "Toronto", "typeDisp": "ETF"},
    ]
    return fake


def ok(result):
    assert result.exit_code == 0, result.output
    return result.output


def rows(cli, *args) -> list[dict]:
    return json.loads(ok(cli("compare", *SYMS, "-p", "1mo", "--json", *args)))


def requests_for(cli, tracker, fake, *args) -> list[tuple[str, dict]]:
    tracker.market.clear_cache()
    fake.calls.clear()
    cli(*args)
    return list(fake.calls)


def test_compare_and_search_options_reuse_the_plain_requests(cli, tracker, market_data):
    plain = requests_for(cli, tracker, market_data, "compare", *SYMS, "-p", "1mo")
    assert [url for url, _ in plain] == [CHART_URL.format(symbol=s) for s in SYMS]
    for extra in (["--json"], ["--csv", "--sort", "drawdown"], ["--base", "VFV.TO", "--top", "1"], ["--no-chart"]):
        assert requests_for(cli, tracker, market_data, "compare", *SYMS, "-p", "1mo", *extra) == plain
    plain = requests_for(cli, tracker, market_data, "search", "maple")
    assert plain == [(SEARCH_URL, plain[0][1])] and plain[0][1]["quotesCount"] == 12
    for extra in (["--json"], ["--csv"], ["--type", "etf"], ["--exchange", "tor"], ["--limit", "2"], ["--first"]):
        assert requests_for(cli, tracker, market_data, "search", "maple", *extra) == plain


# 51 ── compare --json


def test_51_compare_json(cli, market_data):
    out = rows(cli)
    assert [r["symbol"] for r in out] == ["AAPL", "XEQT.TO", "VFV.TO"]  # best return first, as the table
    aapl = out[0]
    assert set(aapl) == {
        "symbol",
        "period",
        "interval",
        "from",
        "to",
        "bars",
        "start",
        "end",
        "return_pct",
        "max_drawdown_pct",
        "volatility_pct",
        "vs_base_pp",
    }
    assert (aapl["period"], aapl["interval"], aapl["from"], aapl["to"], aapl["bars"]) == (
        "1mo",
        "1h",
        "2025-03-03",
        "2025-03-21",
        15,
    )
    assert (aapl["start"], aapl["end"]) == (100, 109)
    assert aapl["return_pct"] == pytest.approx(9.0)
    assert aapl["max_drawdown_pct"] == pytest.approx(-6.7308, abs=1e-4)
    assert aapl["volatility_pct"] == pytest.approx(95.03, abs=0.01)
    assert aapl["vs_base_pp"] is None


def test_51_compare_json_reports_failures_on_stderr(cli, market_data):
    result = CliRunner().invoke(main, ["compare", "AAPL", "NOPE", "-p", "1mo", "--json"])
    assert result.exit_code == 0
    assert [r["symbol"] for r in json.loads(result.stdout)] == ["AAPL"]
    assert "NOPE" in result.stderr and "NOPE" not in result.stdout
    assert cli("compare", "NOPE", "--json").exit_code == 1


# 52 ── compare --csv


def test_52_compare_csv(cli, market_data):
    out = ok(cli("compare", *SYMS, "-p", "1mo", "--csv"))
    lines = out.splitlines()
    assert lines[0] == (
        "symbol,period,interval,from,to,bars,start,end,return_pct,max_drawdown_pct,volatility_pct,vs_base_pp"
    )
    parsed = list(csv.DictReader(io.StringIO(out)))
    assert [r["symbol"] for r in parsed] == ["AAPL", "XEQT.TO", "VFV.TO"]
    assert parsed[2]["start"] == "120.0" and parsed[2]["vs_base_pp"] == ""
    bad = cli("compare", "AAPL", "--json", "--csv")
    assert bad.exit_code == 2 and "--json or --csv" in bad.output


# 53 ── compare --sort / --reverse


def test_53_compare_sort_and_reverse(cli, market_data):
    assert [r["symbol"] for r in rows(cli, "--sort", "return")] == ["AAPL", "XEQT.TO", "VFV.TO"]
    assert [r["symbol"] for r in rows(cli, "--sort", "drawdown")] == ["XEQT.TO", "AAPL", "VFV.TO"]
    assert [r["symbol"] for r in rows(cli, "--sort", "volatility")] == ["XEQT.TO", "VFV.TO", "AAPL"]
    assert [r["symbol"] for r in rows(cli, "--sort", "symbol")] == ["AAPL", "VFV.TO", "XEQT.TO"]
    assert [r["symbol"] for r in rows(cli, "--reverse")] == ["VFV.TO", "XEQT.TO", "AAPL"]
    assert [r["symbol"] for r in rows(cli, "--sort", "volatility", "--reverse")] == ["AAPL", "VFV.TO", "XEQT.TO"]
    table = ok(cli("compare", *SYMS, "-p", "1mo", "--sort", "symbol", "--no-chart"))
    order = [
        line.split()[0]
        for line in table.splitlines()
        if line.strip().split()[:1] in (["AAPL"], ["VFV.TO"], ["XEQT.TO"])
    ]
    assert order == ["AAPL", "VFV.TO", "XEQT.TO"]
    assert cli("compare", "AAPL", "--sort", "sharpe").exit_code == 2


def test_53_volatility_unknown_stays_last(cli, market_data):
    market_data.set_history("SHORT.TO", {"2025-03-20": 10, "2025-03-21": 11}, currency="CAD")
    for extra in ([], ["--reverse"]):
        out = json.loads(ok(cli("compare", "SHORT.TO", "AAPL", "-p", "1mo", "--json", "--sort", "volatility", *extra)))
        assert [r["symbol"] for r in out] == ["AAPL", "SHORT.TO"] and out[1]["volatility_pct"] is None


# 54 ── compare --base


def test_54_compare_base(cli, market_data):
    out = {r["symbol"]: r for r in rows(cli, "--base", "xeqt.to")}
    assert out["XEQT.TO"]["vs_base_pp"] == 0
    assert out["AAPL"]["vs_base_pp"] == pytest.approx(9.0 - (31.1 / 30 - 1) * 100)
    assert out["VFV.TO"]["vs_base_pp"] == pytest.approx((110 / 120 - 1) * 100 - (31.1 / 30 - 1) * 100)
    table = ok(cli("compare", *SYMS, "-p", "1mo", "--base", "XEQT.TO", "--no-chart"))
    assert "vs XEQT.TO" in table and "base" in table and "+5.33 pp" in table and "-12.00 pp" in table


def test_54_compare_base_must_be_compared(cli, market_data):
    bad = cli("compare", "AAPL", "VFV.TO", "--base", "XEQT.TO")
    assert bad.exit_code == 2 and "--base XEQT.TO must be one of the compared symbols" in bad.output
    assert cli("compare", "AAPL", "VFV.TO", "--base", "AAPL VFV.TO").exit_code == 2
    gone = cli("compare", "AAPL", "NOPE", "-p", "1mo", "--base", "NOPE")
    assert gone.exit_code == 1 and "NOPE: no 1mo history to compare against." in gone.output


# 55 ── compare --top


def test_55_compare_top(cli, market_data):
    assert [r["symbol"] for r in rows(cli, "--top", "2")] == ["AAPL", "XEQT.TO"]
    assert [r["symbol"] for r in rows(cli, "--top", "1", "--sort", "drawdown")] == ["XEQT.TO"]
    out = ok(cli("compare", *SYMS, "-p", "1mo", "--top", "2"))
    assert "━━ AAPL" in out and "━━ XEQT.TO" in out and "VFV.TO" not in out
    assert cli("compare", "AAPL", "--top", "0").exit_code == 2


# 56 ── compare --no-chart


def test_56_compare_no_chart(cli, market_data):
    out = ok(cli("compare", *SYMS, "-p", "1mo", "--no-chart"))
    assert "┤" not in out and "━━" not in out
    assert (GOLDEN / "compare_plain.txt").read_text(encoding="utf-8").endswith(out)  # the plain table, unchanged
    bad = cli("compare", "AAPL", "--json", "--no-chart")
    assert bad.exit_code == 2 and "drop --no-chart" in bad.output


# 57 ── search --json / --csv


def test_57_search_json_and_csv(cli, market_data):
    found = json.loads(ok(cli("search", "maple", "--json")))
    assert found[0] == {"symbol": "MAPL.TO", "name": "Maple Leaf Growth ETF", "exchange": "Toronto", "type": "ETF"}
    assert [r["symbol"] for r in found] == ["MAPL.TO", "MAPL", "MAPL.V", "MAPLX", "MAPL-U.TO"]
    out = ok(cli("search", "maple", "--csv"))
    assert out.splitlines()[0] == "symbol,name,exchange,type"
    assert out.splitlines()[4] == "MAPLX,Maple Balanced Fund,NAS,MUTUALFUND"
    market_data.search_results = []
    empty = cli("search", "nothing", "--json")
    assert empty.exit_code == 1 and empty.output == "[]\n"
    assert cli("search", "nothing", "--csv").output == "symbol,name,exchange,type\n"
    assert cli("search", "maple", "--json", "--csv").exit_code == 2


# 58 ── search --type / --exchange


def test_58_search_type_and_exchange_filters(cli, market_data):
    def symbols(*args):
        return [r["symbol"] for r in json.loads(ok(cli("search", "maple", "--json", *args)))]

    assert symbols("--type", "etf") == ["MAPL.TO", "MAPL-U.TO"]
    assert symbols("--type", "Mutual Fund") == ["MAPLX"]
    assert symbols("--type", "equity", "--type", "mutual-fund") == ["MAPL", "MAPL.V", "MAPLX"]
    assert symbols("--exchange", "tor") == ["MAPL.TO", "MAPL-U.TO"]
    assert symbols("--exchange", "nas") == ["MAPL", "MAPLX"]
    assert symbols("--type", "equity", "--exchange", "tsxv") == ["MAPL.V"]
    none = cli("search", "maple", "--type", "bond")
    assert none.exit_code == 1 and "No matches for --type/--exchange." in none.output
    assert "MAPL.V" not in ok(cli("search", "maple", "--exchange", "toronto"))
    assert cli("search", "maple", "--type", " ").exit_code == 2
    assert cli("search", "maple", "--exchange", "").exit_code == 2


# 59 ── search --limit


def test_59_search_limit(cli, market_data):
    out = ok(cli("search", "maple", "--limit", "2"))
    assert "MAPL.TO" in out and "MAPL " in out and "MAPL.V" not in out
    assert [r["symbol"] for r in json.loads(ok(cli("search", "maple", "--type", "etf", "--limit", "1", "--json")))] == [
        "MAPL.TO"
    ]
    assert cli("search", "maple", "--limit", "0").exit_code == 2
    assert cli("search", "maple", "--limit", "13").exit_code == 2


# 60 ── search --first


def test_60_search_first(cli, market_data):
    assert ok(cli("search", "maple", "--first")) == "MAPL.TO\n"
    assert ok(cli("search", "maple", "--first", "--type", "mutualfund")) == "MAPLX\n"
    market_data.search_results = []
    none = cli("search", "nothing", "--first")
    assert none.exit_code == 1 and "No matches." in none.output
    bad = cli("search", "maple", "--first", "--json")
    assert bad.exit_code == 2 and "--first" in bad.output
