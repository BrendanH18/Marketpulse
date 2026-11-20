"""Overview improvements 21–40 for `holdings`, `status`, `summary`, `perf` and `income` (fictional, fake quotes)."""

import csv
import io
import json
import shlex
from datetime import date

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.db import Snapshot
from marketpulse.models import Account, Asset, AssetClass, AssetKind, Transaction, TxnType

YEAR = date.today().year
JAN = f"{YEAR}-01-01"


@pytest.fixture
def cli(store, tracker, fake, monkeypatch):
    """Fictional Growth (tracks cash): XEQT.TO 100 @ 30, LOSS.TO 50 @ 20, FICT-ART (manual) 1 @ 500, 5500 CAD cash.
    Fictional Income: AAPL 10 @ 150 USD. Fictional Old (archived) holds nothing.

    Fake quotes: XEQT.TO 40 (prev 40.5), LOSS.TO 15 (prev 14), AAPL 200 USD (prev 190), USD/CAD 1.35."""
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "180")
    fake.set_quote("LOSS.TO", 15.0, 14.0, "CAD", "Fictional Loss Fund", "ETF")
    store.upsert_asset(Asset("FICT-ART", AssetKind.MANUAL, "Fictional Art", AssetClass.ALTERNATIVE, "CAD"))
    growth = store.add_account(Account(name="Fictional Growth", track_cash=True))
    income = store.add_account(Account(name="Fictional Income"))
    store.add_account(Account(name="Fictional Old", archived=True))
    for account, kind, day, symbol, quantity, price, amount, currency in [
        (growth, TxnType.DEPOSIT, "2024-01-02", "", 0, 0, 10000, "CAD"),
        (growth, TxnType.BUY, "2024-01-03", "XEQT.TO", 100, 30, 0, "CAD"),
        (growth, TxnType.BUY, "2024-01-04", "LOSS.TO", 50, 20, 0, "CAD"),
        (growth, TxnType.BUY, "2025-03-01", "FICT-ART", 1, 500, 0, "CAD"),
        (growth, TxnType.VALUATION, "2025-06-01", "FICT-ART", 0, 600, 0, "CAD"),
        (income, TxnType.BUY, "2024-01-05", "AAPL", 10, 150, 0, "USD"),
    ]:
        store.add_transaction(
            Transaction(account.saved_id, kind, day, symbol, quantity, price, amount, currency=currency)
        )

    def invoke(*args):
        return CliRunner().invoke(main, list(args), catch_exceptions=False)

    return invoke


def holding_rows(cli, *args) -> list[dict]:
    result = cli("holdings", *args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def symbols(cli, *args) -> list[str]:
    return sorted(r["symbol"] for r in holding_rows(cli, *args))


# ── 21–30 holdings ───────────────────────────────────────────────────────────


def test_21_holdings_asset_class_filter(cli):
    by_class = {r["symbol"]: r["asset_class"] for r in holding_rows(cli)}
    etfs = sorted(s for s, c in by_class.items() if c == "etf")
    assert etfs and symbols(cli, "--asset-class", "ETF") == etfs
    assert symbols(cli, "--asset-class", "alternative") == ["FICT-ART"]
    both = symbols(cli, "--asset-class", "alternative", "--asset-class", "etf")
    assert both == sorted(["FICT-ART", *etfs])
    assert cli("holdings", "--asset-class", "nonsense").exit_code == 2


def test_22_holdings_kind_filter(cli):
    assert symbols(cli, "--kind", "manual") == ["FICT-ART"]
    assert symbols(cli, "--kind", "MARKET") == ["AAPL", "LOSS.TO", "XEQT.TO"]
    assert symbols(cli, "--kind", "fixed_income") == []


def test_23_holdings_min_value_in_base_currency(cli):
    # XEQT.TO 4000, AAPL 2000 USD = 2700 CAD, LOSS.TO 750, FICT-ART 600.
    assert symbols(cli, "--min-value", "2700") == ["AAPL", "XEQT.TO"]
    assert symbols(cli, "--min-value", "700") == ["AAPL", "LOSS.TO", "XEQT.TO"]
    assert cli("holdings", "--min-value", "-1").exit_code == 2
    assert cli("holdings", "--min-value", "inf").exit_code == 2


def test_24_holdings_day_move_either_way(cli):
    # LOSS.TO +7.14%, AAPL +5.26%, XEQT.TO −1.23%; the manual asset doesn't move (0%).
    assert symbols(cli, "--day-move", "5") == ["AAPL", "LOSS.TO"]
    assert symbols(cli, "--day-move", "1") == ["AAPL", "LOSS.TO", "XEQT.TO"]
    assert symbols(cli, "--day-move", "0") == ["AAPL", "FICT-ART", "LOSS.TO", "XEQT.TO"]


def test_25_holdings_opened_since(cli):
    assert symbols(cli, "--opened-since", "2025-01-01") == ["FICT-ART"]
    assert symbols(cli, "--opened-since", "2024-01-04") == ["AAPL", "FICT-ART", "LOSS.TO"]
    bad = cli("holdings", "--opened-since", "01/02/2025")
    assert bad.exit_code == 2 and "YYYY-MM-DD" in bad.output


def test_26_holdings_fields_choose_json_and_csv_columns(cli):
    rows = holding_rows(cli, "--sort", "symbol", "--fields", "symbol, value_base,symbol")
    assert rows[0] == {"symbol": "AAPL", "value_base": pytest.approx(2700)}
    result = cli("holdings", "--csv", "--sort", "symbol", "--fields", "symbol,weight")
    assert result.exit_code == 0
    parsed = list(csv.DictReader(io.StringIO(result.output)))
    assert result.output.splitlines()[0] == "symbol,weight" and parsed[0]["symbol"] == "AAPL"
    unknown = cli("holdings", "--json", "--fields", "symbol,bogus")
    assert unknown.exit_code == 2 and "bogus" in unknown.output
    assert cli("holdings", "--fields", "symbol").exit_code == 2  # needs --json or --csv


def test_27_holdings_markdown_table_honours_privacy(cli, tracker):
    result = cli("holdings", "--markdown", "--sort", "symbol")
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[0].startswith("| Account | Symbol | Quantity | Price | Value (CAD)")
    assert lines[1].startswith("| --- | --- | ---: |")
    assert lines[2].startswith("| Fictional Income | AAPL | 10 |") and "$2,700.00" in lines[2]
    assert len(lines) == 6
    tracker.config.privacy = True
    masked = cli("holdings", "--markdown").output
    assert "$2,700.00" not in masked and "AAPL" in masked
    assert cli("holdings", "--markdown", "--json").exit_code == 2


def test_28_holdings_symbols_only(cli, store):
    other = store.get_account("Fictional Income")
    store.add_transaction(Transaction(other.saved_id, TxnType.BUY, "2024-02-01", "XEQT.TO", 1, 30, 0, currency="CAD"))
    result = cli("holdings", "--symbols-only", "--sort", "symbol")
    assert result.exit_code == 0
    assert result.output.splitlines() == ["AAPL", "FICT-ART", "LOSS.TO", "XEQT.TO"]  # each symbol once
    assert sorted(cli("holdings", "--symbols-only", "--day-move", "5").output.split()) == ["AAPL", "LOSS.TO"]


def test_29_holdings_subtotal_of_shown_positions(cli):
    result = cli("holdings", "--subtotal", "--currency", "CAD")
    assert result.exit_code == 0
    # XEQT.TO 4000 + LOSS.TO 750 + FICT-ART 600 = 5350 against a book of 3000 + 1000 + 500 = 4500.
    assert "Subtotal of 3 priced positions" in result.output
    assert "$5,350.00" in result.output and "$4,500.00" in result.output and "+$850.00" in result.output
    assert "Showing 3 of 4 positions" in result.output
    assert cli("holdings", "--subtotal", "--json").exit_code == 2


def test_30_holdings_concentration_limit_exit_code(cli):
    # XEQT.TO 4000 / 13550 ≈ 29.5%, AAPL 2700 / 13550 ≈ 19.9%.
    plain = cli("holdings", "--concentration-limit", "25")
    assert plain.exit_code == 1 and "XEQT.TO in Fictional Growth is 29.52% of net worth, over 25%." in plain.output
    assert "NET WORTH" in plain.output  # the plain table is still printed
    assert cli("holdings", "--concentration-limit", "35").exit_code == 0
    scripted = cli("holdings", "--count", "--concentration-limit", "15")
    assert scripted.exit_code == 1 and scripted.stdout.strip() == "4"
    assert "AAPL" in scripted.stderr and "XEQT.TO" in scripted.stderr
    assert cli("holdings", "--symbol", "LOSS", "--concentration-limit", "15").exit_code == 0
    assert cli("holdings", "--concentration-limit", "0").exit_code == 2


# ── 31–33 status ─────────────────────────────────────────────────────────────


def test_31_status_env_assignments(cli):
    result = cli("status", "--env")
    assert result.exit_code == 0
    env = dict(line.split("=", 1) for line in result.output.splitlines())
    assert env["MARKETPULSE_NET_WORTH"] == "13550.0"
    assert env["MARKETPULSE_BASE"] == "CAD" and env["MARKETPULSE_STALE"] == "false"
    assert len(env) == 12 and all(k.startswith("MARKETPULSE_") for k in env)
    assert all(shlex.split(v) for k, v in env.items() if k != "MARKETPULSE_MARKET_STATE")
    one = dict(line.split("=", 1) for line in cli("status", "--env", "-a", "Fictional Income").output.splitlines())
    assert one["MARKETPULSE_NET_WORTH"] == "2700.0"
    clash = cli("status", "--env", "--short")
    assert clash.exit_code == 2 and "Choose one of" in clash.output


def test_32_status_change_since_snapshot(cli, store):
    store.upsert_snapshot(Snapshot("2025-01-31", 12000.0, 9000.0, 9000.0, "CAD", {}))
    store.upsert_snapshot(Snapshot("2025-06-30", 13000.0, 9000.0, 9000.0, "CAD", {}))
    result = cli("status", "--change-since", "2025-03-01")
    assert result.exit_code == 0
    assert "Since 2025-01-31" in result.output and "+$1,550.00" in result.output and "+12.92%" in result.output
    assert "from $12,000.00 CAD" in result.output
    none = cli("status", "--change-since", "2020-01-01")
    assert none.exit_code == 0 and "No net worth snapshot on or before 2020-01-01" in none.output
    assert cli("status", "--change-since", "2025-03-01", "--short").exit_code == 2
    assert cli("status", "--change-since", "2025-03-01", "-a", "Fictional Income").exit_code == 2


def test_33_status_fail_on_move(cli, tracker):
    view = tracker.valuation(record=False)
    move = abs(view.day_change_pct)
    assert move > 0
    assert cli("status", "--short", "--fail-on-move", f"{move + 1:.2f}").exit_code == 0
    tripped = cli("status", "--short", "--fail-on-move", f"{move - 0.01:.4f}")
    assert tripped.exit_code == 1 and "·" in tripped.output  # output unchanged, exit status set
    as_json = cli("status", "--json", "--fail-on-move", "0")
    assert as_json.exit_code == 1 and isinstance(json.loads(as_json.output), dict)


def test_33_status_fail_on_move_ignores_stale_prices(cli, fake, tracker):
    assert cli("status", "--short", "--fail-on-move", "0").exit_code == 1  # caches quotes; a live move trips it
    fake.offline = True
    tracker.market._quote_cache.clear()
    stale = cli("status", "--short", "--fail-on-move", "0")
    assert stale.exit_code == 0 and "·" in stale.output  # a cached quote's move is not today's move


# ── 34–35 summary ────────────────────────────────────────────────────────────


def test_34_summary_exclude_section(cli):
    data = json.loads(cli("summary", "--json", "--exclude-section", "markets", "--exclude-section", "chart").output)
    assert "markets" not in data and "history" not in data
    assert "net_worth" in data and "allocation" in data and "movers" in data
    clash = cli("summary", "--section", "totals", "--exclude-section", "chart")
    assert clash.exit_code == 2 and "Choose either" in clash.output
    every = ["--exclude-section", "markets", "--exclude-section", "totals", "--exclude-section", "chart"]
    every += ["--exclude-section", "allocation", "--exclude-section", "movers"]
    assert cli("summary", *every).exit_code == 2


def test_35_summary_min_move(cli):
    def movers(*args):
        data = json.loads(cli("summary", "--json", "--section", "movers", *args).output)
        return [m["symbol"] for m in data["movers"]]

    assert movers() == ["LOSS.TO", "AAPL", "XEQT.TO"]
    assert movers("--min-move", "5") == ["LOSS.TO", "AAPL"]
    assert movers("--min-move", "5", "--top", "1") == ["LOSS.TO"]
    assert movers("--min-move", "50") == []
    plain = cli("summary", "--section", "movers", "--min-move", "6")
    assert plain.exit_code == 0 and "LOSS.TO" in plain.output and "AAPL" not in plain.output


# ── 36–37 perf ───────────────────────────────────────────────────────────────


def test_36_perf_csv_metrics(cli):
    result = cli("perf", "--csv")
    assert result.exit_code == 0 and "\r" not in result.output
    rows = list(csv.DictReader(io.StringIO(result.output)))
    assert [r["metric"] for r in rows] == [
        "since", "days", "net_contributions", "total_gain", "xirr_pct", "twr_pct", "twr_annual_pct",
        "max_drawdown_pct", "volatility_pct",
    ]  # fmt: skip
    assert rows[0]["value"] == "2024-01-02" and all(r["base_currency"] == "CAD" for r in rows)
    payload = json.loads(cli("perf", "--json").output)
    assert rows[2]["value"] == str(payload["net_contributions"])
    clash = cli("perf", "--csv", "--json")
    assert clash.exit_code == 2


def test_37_perf_index_csv(cli, store):
    for day, value in [("2025-01-01", 10000.0), ("2025-02-01", 10500.0)]:
        store.upsert_snapshot(Snapshot(day, value, 9000.0, 9000.0, "CAD", {}))
    result = cli("perf", "--index-csv")
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[0] == "date,level"
    payload = json.loads(cli("perf", "--json").output)
    assert len(lines) - 1 == len(payload["index"])
    assert cli("perf", "--index-csv", "--metric", "twr").exit_code == 2


# ── 38–40 income ─────────────────────────────────────────────────────────────


def with_dividends(store, fake):
    """XEQT.TO pays 0.50/share and AAPL 1.00/share (trailing); a fictional XEQT.TO dividend of 50 CAD in January."""
    today = date.today()
    recent = date(today.year, today.month, 1).isoformat() if today.day > 1 else today.isoformat()
    fake.set_history("XEQT.TO", {recent: 40.0}, "CAD")
    fake.set_history("AAPL", {recent: 200.0}, "USD")
    fake.dividends["XEQT.TO"] = [(recent, 0.5)]
    fake.dividends["AAPL"] = [(recent, 1.0)]
    growth = store.get_account("Fictional Growth")
    store.add_transaction(Transaction(growth.saved_id, TxnType.DIVIDEND, JAN, "XEQT.TO", 0, 0, 50, currency="CAD"))


def income_json(cli, *args) -> dict:
    result = cli("income", *args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_38_income_forecast_sort(cli, store, fake):
    with_dividends(store, fake)
    # XEQT.TO: 50 CAD a year, yield 1.25%; AAPL: 13.50 CAD a year, yield 0.5%.
    assert [r["symbol"] for r in income_json(cli, "--forecast-sort", "symbol")["forecast"]] == ["AAPL", "XEQT.TO"]
    assert [r["symbol"] for r in income_json(cli, "--forecast-sort", "annual")["forecast"]] == ["XEQT.TO", "AAPL"]
    by_yield = income_json(cli, "--forecast-only", "--forecast-sort", "yield", "--top", "1")
    assert [r["symbol"] for r in by_yield["forecast"]] == ["XEQT.TO"]
    assert by_yield["total"] == pytest.approx(63.5)  # the total still covers every row
    cost = income_json(cli, "--forecast-only", "--forecast-sort", "yield-on-cost")["forecast"]
    assert [r["symbol"] for r in cost] == ["XEQT.TO", "AAPL"]
    clash = cli("income", "--forecast-sort", "annual", "--no-forecast")
    assert clash.exit_code == 2 and "forward estimate" in clash.output
    assert cli("income", "--forecast-sort", "annual", "--by", "month").exit_code == 2


def test_39_income_min_yield(cli, store, fake):
    with_dividends(store, fake)
    data = income_json(cli, "--min-yield", "1")
    assert [r["symbol"] for r in data["forecast"]] == ["XEQT.TO"]
    assert data["forecast_total"] == pytest.approx(50)
    assert income_json(cli, "--forecast-only", "--min-yield", "5")["forecast"] == []
    table = cli("income", "--forecast-only", "--min-yield", "1")
    assert table.exit_code == 0 and "XEQT.TO" in table.output and "AAPL" not in table.output
    assert cli("income", "--min-yield", "-1").exit_code == 2


def test_40_income_stats(cli, store, fake):
    with_dividends(store, fake)
    data = income_json(cli, "--stats", "--no-forecast")
    stats = data["stats"]
    assert stats["months"] == 12 and stats["paying_months"] == 1
    assert stats["monthly_average"] == pytest.approx(50 / 12)
    assert stats["best_month"] == JAN[:7] and stats["best_month_amount"] == pytest.approx(50)
    assert "stats" not in income_json(cli, "--no-forecast")
    table = cli("income", "--stats", "--no-forecast")
    assert table.exit_code == 0
    assert "Monthly average $4.17" in table.output and f"best month {JAN[:7]}" in table.output
    assert "1 of 12 months paid" in table.output
    assert cli("income", "--stats", "--csv").exit_code == 2
    assert cli("income", "--stats", "--by", "symbol").exit_code == 2


def test_new_options_leave_the_plain_commands_unchanged(cli):
    plain = cli("holdings")
    assert plain.exit_code == 0 and "Subtotal" not in plain.output and "NET WORTH" in plain.output
    assert cli("status").exit_code == 0
