"""Tests for items 41-60 of the third 100-improvement batch: `cli/quotes.py` and `cli/history.py`.

All symbols, prices, accounts and transactions here are fictional.
"""

from __future__ import annotations

import csv
import io
import json
import time
from datetime import date, timedelta

import pytest
from click.testing import CliRunner

from marketpulse.cli import App, main
from marketpulse.models import Account, AccountType, Quote, Transaction, TxnType

DAYS = [
    "2025-03-03",
    "2025-03-04",
    "2025-03-05",
    "2025-03-06",
    "2025-03-07",
    "2025-03-10",
    "2025-03-11",
    "2025-03-12",
    "2025-04-01",
    "2025-04-02",
]
BASE = [100.0, 102.0, 101.0, 104.0, 103.0, 106.0, 105.0, 108.0, 110.0, 109.0]


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    runner = CliRunner()

    def invoke(*args: str, input_text: str | None = None):
        return runner.invoke(main, list(args), input=input_text, catch_exceptions=False)

    return invoke


@pytest.fixture
def histories(fake):
    """Three fictional series: TWIN doubles BASE (perfect correlation), MIRR moves against it."""
    fake.set_history("BASE.TO", dict(zip(DAYS, BASE, strict=True)), currency="CAD")
    fake.set_history("TWIN.TO", {d: c * 2 for d, c in zip(DAYS, BASE, strict=True)}, currency="CAD")
    fake.set_history("MIRR.TO", {d: 300 - c for d, c in zip(DAYS, BASE, strict=True)}, currency="CAD")
    fake.set_quote("BASE.TO", 109.0, 110.0, "CAD", "Fictional Base Fund", "ETF")
    return fake


def ok(result) -> str:
    assert result.exit_code == 0, result.output
    return result.output


def usage(result, text: str) -> None:
    assert result.exit_code == 2, result.output
    assert text in result.output


# ── quote (41-48) ────────────────────────────────────────────────────────────


def test_41_quote_jsonl_live_and_cached(cli):
    lines = ok(cli("quote", "AAPL", "XEQT.TO", "--jsonl")).splitlines()
    rows = [json.loads(line) for line in lines]
    assert [r["symbol"] for r in rows] == ["AAPL", "XEQT.TO"]
    assert rows[0]["price"] == 200.0 and rows[0]["error"] is None
    cached = [json.loads(line) for line in ok(cli("quote", "--cached", "--all", "--jsonl")).splitlines()]
    assert {r["symbol"] for r in cached} == {"AAPL", "XEQT.TO"}
    assert all(r["stale"] for r in cached)
    usage(cli("quote", "AAPL", "--jsonl", "--json"), "Choose one output format")


def test_42_quote_min_move(cli):
    # AAPL moved +5.26%, XEQT.TO -1.23%.
    rows = json.loads(ok(cli("quote", "AAPL", "XEQT.TO", "--min-move", "2", "--json")))
    assert [r["symbol"] for r in rows] == ["AAPL"]
    out = ok(cli("quote", "AAPL", "XEQT.TO", "--min-move", "1"))
    assert "AAPL" in out and "XEQT.TO" in out
    assert "No quotes match" in ok(cli("quote", "AAPL", "XEQT.TO", "--min-move", "10"))
    usage(cli("quote", "--cached", "--all", "--min-move", "1"), "--min-move applies to live quotes")


def test_43_quote_direction(cli):
    assert ok(cli("quote", "AAPL", "XEQT.TO", "--direction", "down", "--field", "price")) == "XEQT.TO\t40.0\n"
    rows = json.loads(ok(cli("quote", "AAPL", "XEQT.TO", "--direction", "up", "--json")))
    assert [r["symbol"] for r in rows] == ["AAPL"]


def test_44_quote_summary_breadth(cli):
    out = ok(cli("quote", "AAPL", "XEQT.TO", "--summary"))
    assert "Breadth: 1 up · 1 down · 0 unchanged · average" in out
    usage(cli("quote", "AAPL", "--summary", "--json"), "--summary adds a line")


def test_45_quote_check_above(cli):
    ok(cli("quote", "AAPL", "XEQT.TO", "--check-above", "30", "--json"))
    result = cli("quote", "AAPL", "XEQT.TO", "--check-above", "100")
    assert result.exit_code == 1
    assert "XEQT.TO 40.00 is below 100.00" in result.output
    missing = cli("quote", "AAPL", "NOPE", "--check-above", "1", "--json")
    assert missing.exit_code == 1


def test_46_quote_check_below(cli):
    ok(cli("quote", "AAPL", "--check-below", "250"))
    result = cli("quote", "AAPL", "--check-below", "150")
    assert result.exit_code == 1
    assert "AAPL 200.00 is above 150.00" in result.output
    usage(cli("quote", "AAPL", "--check-above", "300", "--check-below", "100"), "--check-above must be at or below")


def test_47_quote_fail_on_stale(cli, store, fake):
    store.cache_quotes([Quote(symbol="OLDF.TO", price=12.0, prev_close=11.0, currency="CAD", fetched_at=time.time())])
    fake.offline = True
    plain = cli("quote", "OLDF.TO", "--json")
    assert plain.exit_code == 0 and json.loads(plain.stdout)[0]["stale"] is True
    result = cli("quote", "OLDF.TO", "--json", "--fail-on-stale")
    assert result.exit_code == 1
    assert "stale" in result.output
    # A stale quote never passes a price check, even when the price would.
    assert cli("quote", "OLDF.TO", "--check-above", "1").exit_code == 1


def test_48_quote_cached_count(cli):
    ok(cli("quote", "AAPL", "XEQT.TO", "--json"))
    assert ok(cli("quote", "--cached", "--all", "--count")) == "2\n"
    assert ok(cli("quote", "--cached", "--all", "--currency", "CAD", "--count")) == "1\n"
    assert ok(cli("quote", "--cached", "NOPE", "--count")) == "0\n"
    usage(cli("quote", "AAPL", "--count"), "--count requires --cached")
    usage(cli("quote", "--cached", "--all", "--count", "--json"), "--count prints a number")


# ── chart (49-50) ────────────────────────────────────────────────────────────


def test_49_chart_jsonl(cli, histories):
    rows = [json.loads(line) for line in ok(cli("chart", "BASE.TO", "-p", "1y", "--jsonl")).splitlines()]
    assert len(rows) == len(DAYS) and rows[0]["date"] == DAYS[0] and rows[-1]["close"] == BASE[-1]
    both = ok(cli("chart", "BASE.TO", "-p", "1y", "--vs", "TWIN.TO", "--jsonl", "--last", "2")).splitlines()
    assert [json.loads(line)["symbol"] for line in both] == ["BASE.TO", "BASE.TO", "TWIN.TO", "TWIN.TO"]
    stats = [json.loads(line) for line in ok(cli("chart", "BASE.TO", "-p", "1y", "--stats", "--jsonl")).splitlines()]
    assert stats[0]["symbol"] == "BASE.TO" and stats[0]["bars"] == len(DAYS)
    usage(cli("chart", "BASE.TO", "--jsonl", "--csv"), "Choose one output format")


def test_50_chart_resample(cli, histories):
    out = ok(cli("chart", "BASE.TO", "-p", "1y", "--csv", "--resample", "month"))
    rows = list(csv.DictReader(io.StringIO(out)))
    assert [(r["date"], float(r["close"])) for r in rows] == [("2025-03-12", 108.0), ("2025-04-02", 109.0)]
    weeks = json.loads(ok(cli("chart", "BASE.TO", "-p", "1y", "--json", "--resample", "week")))["bars"]
    assert [b["date"] for b in weeks] == ["2025-03-07", "2025-03-12", "2025-04-02"]
    usage(cli("chart", "BASE.TO", "--resample", "week"), "--resample applies to")
    usage(cli("chart", "BASE.TO", "--stats", "--json", "--resample", "week"), "--resample applies to")


# ── compare (51-54) ──────────────────────────────────────────────────────────


def test_51_compare_since(cli, histories):
    rows = json.loads(ok(cli("compare", "BASE.TO", "TWIN.TO", "--since", "2025-04-01", "--json")))
    assert {r["from"] for r in rows} == {"2025-04-01"}
    base = next(r for r in rows if r["symbol"] == "BASE.TO")
    assert base["bars"] == 2 and base["start"] == 110.0 and base["return_pct"] == pytest.approx(109 / 110 * 100 - 100)
    result = cli("compare", "BASE.TO", "--since", "2030-01-01", "--json")
    assert result.exit_code == 1 and "No data on or after 2030-01-01" in result.output


def test_52_compare_min_return(cli, histories):
    rows = json.loads(ok(cli("compare", "BASE.TO", "MIRR.TO", "--min-return", "0", "--json")))
    assert [r["symbol"] for r in rows] == ["BASE.TO"]
    result = cli("compare", "BASE.TO", "MIRR.TO", "--min-return", "50", "--json")
    assert result.exit_code == 1 and "No symbol returned at least 50%" in result.output


def test_53_compare_strict(cli, histories):
    assert cli("compare", "BASE.TO", "NOPE", "--json").exit_code == 0
    result = cli("compare", "BASE.TO", "NOPE", "--json", "--strict")
    assert result.exit_code == 1
    assert "NOPE: no 1y history to compare" in result.output
    assert json.loads(result.stdout.splitlines()[0])[0]["symbol"] == "BASE.TO"
    ok(cli("compare", "BASE.TO", "TWIN.TO", "--strict", "--no-chart"))


def test_54_compare_correlation(cli, histories):
    rows = json.loads(ok(cli("compare", "BASE.TO", "TWIN.TO", "MIRR.TO", "--correlation", "--json")))
    by = {r["symbol"]: r for r in rows}
    assert by["BASE.TO"]["BASE.TO"] == 1.0
    assert by["BASE.TO"]["TWIN.TO"] == pytest.approx(1.0)
    assert by["TWIN.TO"]["BASE.TO"] == pytest.approx(1.0)
    assert by["BASE.TO"]["MIRR.TO"] < -0.9
    table = ok(cli("compare", "BASE.TO", "TWIN.TO", "--correlation"))
    assert "return correlation" in table and "+1.00" in table
    out = ok(cli("compare", "BASE.TO", "TWIN.TO", "--correlation", "--csv"))
    assert out.splitlines()[0] == "symbol,BASE.TO,TWIN.TO"
    usage(cli("compare", "BASE.TO", "TWIN.TO", "--correlation", "--top", "1"), "--top can't be combined")
    assert cli("compare", "BASE.TO", "NOPE", "--correlation").exit_code == 1


# ── search (55) ──────────────────────────────────────────────────────────────


def test_55_search_canadian(cli, fake):
    fake.search_results = [
        {"symbol": "MAPL", "shortname": "Maple Holdings Inc.", "exchDisp": "NASDAQ", "typeDisp": "Equity"},
        {"symbol": "MAPL.TO", "longname": "Maple Leaf Growth ETF", "exchDisp": "Toronto", "typeDisp": "ETF"},
        {"symbol": "MAPL.V", "longname": "Maple Ventures Corp.", "exchDisp": "TSXV", "typeDisp": "Equity"},
        {"symbol": "MAPL.NE", "longname": "Maple NEO Units", "exchDisp": "NEO", "typeDisp": "ETF"},
        {"symbol": "MAPL.L", "longname": "Maple London plc", "exchDisp": "London", "typeDisp": "Equity"},
    ]
    rows = json.loads(ok(cli("search", "maple", "--canadian", "--json")))
    assert [r["symbol"] for r in rows] == ["MAPL.TO", "MAPL.V", "MAPL.NE"]
    assert ok(cli("search", "maple", "--canadian", "--first")) == "MAPL.TO\n"
    fake.search_results = fake.search_results[:1]
    result = cli("search", "maple", "--canadian")
    assert result.exit_code == 1 and "No Canadian listings match" in result.output


# ── activity and txn check (56-60) ───────────────────────────────────


@pytest.fixture
def ledger(store):
    tfsa = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA, currency="CAD", track_cash=True))
    usd = store.add_account(Account(name="Fictional USD", type=AccountType.NONREG, currency="USD"))
    today = date.today()
    recent = (today - timedelta(days=3)).isoformat()
    old = (today - timedelta(days=100)).isoformat()
    txns = [
        Transaction(account_id=tfsa.id, type=TxnType.DEPOSIT, date=old, amount=5000, currency="CAD"),
        Transaction(
            account_id=tfsa.id,
            type=TxnType.BUY,
            date=old,
            symbol="XEQT.TO",
            quantity=10,
            price=30,
            fees=4.95,
            currency="CAD",
            note="fictional buy",
        ),
        Transaction(
            account_id=usd.id,
            type=TxnType.BUY,
            date=recent,
            symbol="AAPL",
            quantity=2,
            price=150,
            fees=1,
            currency="USD",
        ),
        Transaction(
            account_id=tfsa.id, type=TxnType.DIVIDEND, date=recent, symbol="XEQT.TO", amount=12.5, currency="CAD"
        ),
    ]
    for t in txns:
        store.add_transaction(t)
    return txns


def test_56_activity_jsonl(cli, ledger):
    rows = [json.loads(line) for line in ok(cli("activity", "--jsonl")).splitlines()]
    assert len(rows) == 4
    assert rows[0]["date"] >= rows[-1]["date"]  # newest first, like the table
    assert {"account", "target_account", "revision"} <= set(rows[0])
    usage(cli("activity", "--jsonl", "--json"), "Choose one output format")


def test_57_activity_ids(cli, ledger):
    ids = [int(line) for line in ok(cli("activity", "--ids", "--oldest-first")).splitlines()]
    assert ids == sorted(t.id for t in ledger)
    assert ok(cli("activity", "--ids", "--symbol", "AAPL")) == f"{ledger[2].id}\n"
    assert ok(cli("activity", "--ids", "--type", "deposit", "--limit", "1")) == f"{ledger[0].id}\n"
    usage(cli("activity", "--ids", "--count"), "Choose one output format")


def test_58_activity_totals(cli, ledger):
    rows = json.loads(ok(cli("activity", "--totals", "--json")))
    assert rows == [
        {"currency": "CAD", "entries": 3, "amount": 5012.5, "fees": 4.95},
        {"currency": "USD", "entries": 1, "amount": 0.0, "fees": 1.0},
    ]
    out = ok(cli("activity", "--totals", "--csv", "--currency", "USD"))
    assert out.splitlines() == ["currency,entries,amount,fees", "USD,1,0.0,1.0"]
    table = ok(cli("activity", "--totals", "--limit", "1"))  # totals cover every match, not one page
    assert "Matching activity totals" in table and "CAD" in table and "USD" in table
    usage(cli("activity", "--totals", "--summary", "type"), "Choose one output format")


def test_59_activity_last_days(cli, ledger):
    ids = {int(line) for line in ok(cli("activity", "--ids", "--last-days", "30")).splitlines()}
    assert ids == {ledger[2].id, ledger[3].id}
    assert ok(cli("activity", "--count", "--last-days", "365")) == "4\n"
    # Combined with --since, the later of the two dates wins.
    since = (date.today() - timedelta(days=1)).isoformat()
    assert ok(cli("activity", "--count", "--last-days", "30", "--since", since)) == "0\n"


def test_60_txn_check_summary(cli, store, ledger):
    buy = ledger[1]
    # A sale of more units than were held is a fictional ledger issue.
    clean = cli("txn", "check", "--summary", "--json")
    assert clean.exit_code == 0 and json.loads(clean.output) == {"ok": True, "codes": []}
    store.add_transaction(
        Transaction(
            account_id=buy.account_id,
            type=TxnType.SELL,
            date=date.today().isoformat(),
            symbol="ZZZ.TO",
            quantity=5,
            price=10,
            currency="CAD",
        )
    )
    result = cli("txn", "check", "--summary", "--json")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False and payload["codes"][0]["count"] == 1
    table = cli("txn", "check", "--summary")
    assert table.exit_code == 1 and "by code" in table.output and payload["codes"][0]["code"] in table.output
