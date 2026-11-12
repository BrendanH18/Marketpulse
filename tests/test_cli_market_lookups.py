"""Chart and quote lookups (#130, items 41–50) against the fake Yahoo transport; no network."""

import csv
import io
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.market import CHART_URL, SPARK_URL

GOLDEN = Path(__file__).parent / "fixtures" / "market_lookups"
DAYS = [f"2025-03-{d:02d}" for d in (3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 17, 18, 19, 20, 21)]
AAPL = [100, 102, 101, 104, 103, 99, 97, 98, 101, 105, 107, 106, 108, 110, 109]
XEQT = [30, 30.2, 30.1, 30.5, 30.4, 30.0, 29.8, 29.9, 30.3, 30.6, 30.8, 30.7, 31.0, 31.2, 31.1]
VFV = [120, 119, 121, 118, 117, 116, 118, 115, 114, 116, 113, 112, 114, 111, 110]


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


def requests_for(cli, tracker, fake, *args) -> list[tuple[str, dict]]:
    """The provider requests one fresh invocation makes."""
    tracker.market.clear_cache()
    fake.calls.clear()
    cli(*args)
    return list(fake.calls)


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("chart_plain.txt", ["chart", "AAPL", "-p", "1mo"]),
        ("chart_vs.txt", ["chart", "AAPL", "-p", "1mo", "--vs", "XEQT.TO", "-H", "8"]),
        ("compare_plain.txt", ["compare", "AAPL", "XEQT.TO", "VFV.TO", "-p", "1mo"]),
        ("search_plain.txt", ["search", "maple"]),
    ],
)
def test_plain_commands_print_exactly_what_they_did(cli, market_data, name, args):
    """Byte-for-byte output captured before #130's options were added."""
    assert ok(cli(*args)) == (GOLDEN / name).read_text()


def test_chart_options_reuse_the_plain_requests(cli, tracker, market_data):
    plain = requests_for(cli, tracker, market_data, "chart", "AAPL", "-p", "1mo", "--vs", "XEQT.TO")
    assert [url for url, _ in plain] == [CHART_URL.format(symbol="AAPL"), CHART_URL.format(symbol="XEQT.TO"), SPARK_URL]
    for extra in (["--json"], ["--csv"], ["--stats"], ["--from", "2025-03-10", "--last", "3"], ["--width", "40"]):
        assert requests_for(cli, tracker, market_data, "chart", "AAPL", "-p", "1mo", "--vs", "XEQT.TO", *extra) == plain


# 41 ── chart --json


def test_41_chart_json_prints_the_fetched_bars(cli, market_data):
    payload = json.loads(ok(cli("chart", "aapl", "-p", "1mo", "--json")))
    assert payload["symbol"] == "AAPL" and payload["period"] == "1mo" and payload["interval"] == "1h"
    assert payload["currency"] == "USD" and payload["vs"] == {}
    assert [b["date"] for b in payload["bars"]] == DAYS
    assert [b["close"] for b in payload["bars"]] == AAPL
    first = payload["bars"][0]
    assert set(first) == {"symbol", "date", "time", "open", "high", "low", "close", "volume"}
    assert first["volume"] == 100 and first["time"].startswith("2025-03-03T")


def test_41_chart_json_includes_vs_series_and_fails_like_plain(cli, market_data):
    payload = json.loads(ok(cli("chart", "AAPL", "-p", "1mo", "--vs", "xeqt.to", "--json")))
    assert [b["close"] for b in payload["vs"]["XEQT.TO"]] == XEQT
    assert payload["vs"]["XEQT.TO"][0]["symbol"] == "XEQT.TO"
    missing = cli("chart", "NOPE", "--json")
    assert missing.exit_code == 1 and "NOPE" in missing.output


# 42 ── chart --csv


def test_42_chart_csv_prints_one_row_per_bar(cli, market_data):
    out = ok(cli("chart", "AAPL", "-p", "1mo", "--vs", "VFV.TO", "--csv"))
    rows = list(csv.DictReader(io.StringIO(out)))
    assert out.splitlines()[0] == "symbol,date,time,open,high,low,close,volume"
    assert [r["symbol"] for r in rows] == ["AAPL"] * 15 + ["VFV.TO"] * 15
    assert rows[0]["date"] == "2025-03-03" and float(rows[0]["close"]) == 100
    assert float(rows[-1]["close"]) == 110 and "\r" not in out


def test_42_chart_json_and_csv_are_exclusive(cli, market_data):
    result = cli("chart", "AAPL", "--json", "--csv")
    assert result.exit_code == 2 and "--json or --csv" in result.output


# 43 ── chart --stats


def test_43_chart_stats_table(cli, market_data):
    out = ok(cli("chart", "AAPL", "-p", "1mo", "--stats"))
    assert "1mo statistics · 2025-03-03 to 2025-03-21 · 15 bars" in out
    row = next(line for line in out.splitlines() if line.strip().startswith("AAPL")).split()
    assert row == ["AAPL", "100.00", "109.00", "+9.00", "▲", "+9.00%", "110.00", "97.00", "-6.73%", "95.03%"]
    assert "Apple Inc." not in out and "┤" not in out  # no card, no chart


def test_43_chart_stats_json_and_csv(cli, market_data):
    rows = json.loads(ok(cli("chart", "AAPL", "-p", "1mo", "--vs", "VFV.TO", "--stats", "--json")))
    aapl, vfv = rows
    assert aapl["symbol"] == "AAPL" and aapl["bars"] == 15
    assert aapl["first"] == 100 and aapl["last"] == 109 and aapl["change"] == 9
    assert aapl["change_pct"] == pytest.approx(9.0)
    assert (aapl["high"], aapl["high_date"], aapl["low"], aapl["low_date"]) == (110, "2025-03-20", 97, "2025-03-11")
    assert aapl["max_drawdown_pct"] == pytest.approx((97 / 104 - 1) * 100)
    assert aapl["volatility_pct"] == pytest.approx(95.03, abs=0.01)  # the same figure `compare` shows
    assert vfv["symbol"] == "VFV.TO" and vfv["change_pct"] == pytest.approx(-8.3333, abs=1e-3)
    out = ok(cli("chart", "AAPL", "-p", "1mo", "--stats", "--csv"))
    assert out.splitlines()[0].startswith("symbol,period,interval,from,to,bars,first,last,change,change_pct")
    assert out.splitlines()[1].startswith("AAPL,1mo,1h,2025-03-03,2025-03-21,15,100.0,109.0,9.0,")


def test_43_chart_stats_without_history(cli, market_data):
    market_data.set_history("EMPTY", {})
    rows = json.loads(ok(cli("chart", "EMPTY", "--stats", "--json")))
    assert rows[0]["bars"] == 0 and rows[0]["first"] is None and rows[0]["high"] is None
    assert "EMPTY" in ok(cli("chart", "EMPTY", "--stats"))


# 44 ── chart --from / --to


def test_44_chart_from_to_trims_the_fetched_series(cli, market_data):
    payload = json.loads(
        ok(cli("chart", "AAPL", "-p", "1mo", "--vs", "XEQT.TO", "--from", "2025-03-10", "--to", "2025-03-14", "--json"))
    )
    assert [b["date"] for b in payload["bars"]] == [
        "2025-03-10",
        "2025-03-11",
        "2025-03-12",
        "2025-03-13",
        "2025-03-14",
    ]
    assert [b["date"] for b in payload["vs"]["XEQT.TO"]][0] == "2025-03-10"
    out = ok(cli("chart", "AAPL", "-p", "1mo", "--from", "2025-03-17"))
    assert "2025-03-17" in out and "2025-03-03" not in out.split("\n\n\n")[-1]
    stats = json.loads(ok(cli("chart", "AAPL", "-p", "1mo", "--to", "2025-03-07", "--stats", "--json")))[0]
    assert stats["to"] == "2025-03-07" and stats["last"] == 103


def test_44_chart_from_to_validation(cli, market_data):
    backwards = cli("chart", "AAPL", "--from", "2025-03-14", "--to", "2025-03-10")
    assert backwards.exit_code == 2 and "--from must be on or before --to" in backwards.output
    assert cli("chart", "AAPL", "--from", "someday").exit_code == 2
    empty = cli("chart", "AAPL", "-p", "1mo", "--from", "2026-01-01")
    assert empty.exit_code == 1 and "No AAPL 1mo bars in the selected range." in empty.output


# 45 ── chart --last


def test_45_chart_last_keeps_the_latest_bars(cli, market_data):
    payload = json.loads(ok(cli("chart", "AAPL", "-p", "1mo", "--last", "3", "--json")))
    assert [b["close"] for b in payload["bars"]] == [108, 110, 109]
    rows = json.loads(
        ok(
            cli(
                "chart",
                "AAPL",
                "-p",
                "1mo",
                "--from",
                "2025-03-10",
                "--to",
                "2025-03-14",
                "--last",
                "2",
                "--stats",
                "--json",
            )
        )
    )
    assert (rows[0]["from"], rows[0]["to"]) == ("2025-03-13", "2025-03-14")
    assert cli("chart", "AAPL", "--last", "1").exit_code == 2


# 46 ── chart --normalize


def test_46_chart_normalize_draws_percent_change(cli, market_data):
    out = ok(cli("chart", "AAPL", "-p", "1mo", "--normalize", "--no-card"))
    assert "━━ AAPL +9.00%" in out and "%" in out.splitlines()[2]
    assert "+0.0%" in out or "-0" in out  # a percent axis, not a price axis
    assert "110.78" not in out
    # Overlays are already drawn as % change, so --vs output is unchanged.
    assert (
        ok(cli("chart", "AAPL", "-p", "1mo", "--vs", "XEQT.TO", "-H", "8", "--normalize"))
        == (GOLDEN / "chart_vs.txt").read_text()
    )


def test_46_drawing_options_reject_machine_output(cli, market_data):
    for extra in (["--normalize"], ["--width", "40"], ["--no-card"]):
        for fmt in ("--json", "--csv", "--stats"):
            result = cli("chart", "AAPL", fmt, *extra)
            assert result.exit_code == 2 and "only change the drawn chart" in result.output


# 47 ── chart --width


def test_47_chart_width(cli, market_data):
    out = ok(cli("chart", "AAPL", "-p", "1mo", "--width", "40", "--no-card"))
    chart_lines = [line for line in out.splitlines() if "┤" in line or "│" in line]
    assert chart_lines and max(len(line.rstrip()) for line in chart_lines) <= 40
    assert cli("chart", "AAPL", "--width", "10").exit_code == 2


# 48 ── chart --no-card


def test_48_chart_no_card(cli, market_data):
    out = ok(cli("chart", "AAPL", "-p", "1mo", "--no-card"))
    assert "Apple Inc." not in out and "52w range" not in out
    plain = (GOLDEN / "chart_plain.txt").read_text()
    assert plain.endswith(out)  # the same chart, without the card above it


# 49 ── quote --field


def test_49_quote_field_prints_bare_values(cli, market_data):
    assert ok(cli("quote", "AAPL", "--field", "price")) == "200.0\n"
    assert ok(cli("quote", "AAPL", "XEQT.TO", "--field", "currency")) == "AAPL\tUSD\nXEQT.TO\tCAD\n"
    assert ok(cli("quote", "AAPL", "--field", "name")) == "Apple Inc.\n"
    assert float(ok(cli("quote", "AAPL", "--field", "change_pct"))) == pytest.approx(10 / 190 * 100)


def test_49_quote_field_missing_symbols(cli, market_data):
    result = cli("quote", "AAPL", "NOPE", "--field", "price")
    assert result.exit_code == 0 and "AAPL\t200.0" in result.output and "NOPE:" in result.output
    assert cli("quote", "NOPE", "--field", "price").exit_code == 1
    for extra in (["--cached"], ["--json"]):
        bad = cli("quote", "AAPL", "--field", "price", *extra)
        assert bad.exit_code == 2 and "--field" in bad.output
    assert cli("quote", "AAPL", "--field", "bid").exit_code == 2


# 50 ── quote --strict


def test_50_quote_strict_exits_1_when_any_symbol_is_missing(cli, market_data):
    loose = cli("quote", "AAPL", "NOPE")
    strict = cli("quote", "AAPL", "NOPE", "--strict")
    assert loose.exit_code == 0 and strict.exit_code == 1
    assert strict.output == loose.output  # the same table, just a failing status
    assert cli("quote", "AAPL", "XEQT.TO", "--strict").exit_code == 0
    assert cli("quote", "AAPL", "NOPE", "--json", "--strict").exit_code == 1
    assert cli("quote", "AAPL", "NOPE", "--field", "price", "--strict").exit_code == 1
    bad = cli("quote", "AAPL", "--cached", "--strict")
    assert bad.exit_code == 2 and "--strict applies to live quotes" in bad.output
