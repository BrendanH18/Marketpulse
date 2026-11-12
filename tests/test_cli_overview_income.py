"""Overview improvements 71–80 for `income` (#130) on a fictional ledger (fake quotes and FX only)."""

import csv
import io
import json
from datetime import date

import pytest
from click.testing import CliRunner
from rich.console import Console
from rich.theme import Theme as RichTheme

from marketpulse import render
from marketpulse.analytics import income_by_month, income_by_symbol
from marketpulse.cli import main
from marketpulse.models import Account, Transaction, TxnType
from marketpulse.themes import resolve_palette, rich_styles

YEAR = date.today().year
JAN = f"{YEAR}-01-01"  # always in the current year and inside the last-12-months window
OLD = f"{YEAR - 2}-06-01"  # always outside both


def month_key(day: str) -> str:
    return day[:7]


@pytest.fixture
def cli(store, tracker, fake, monkeypatch):
    """Fictional Growth (CAD, tracks cash): XEQT.TO dividends 50 (Jan) and 30 (two years ago), interest 10 (Jan),
    a DRIP of 1 XEQT.TO at 40 (Jan). Fictional Income: an AAPL dividend of 10 USD (Jan, = 13.50 CAD).
    Fictional Old (archived): a 1000 CAD XEQT.TO dividend (Jan)."""
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "180")
    growth = store.add_account(Account(name="Fictional Growth", track_cash=True))
    income = store.add_account(Account(name="Fictional Income"))
    old = store.add_account(Account(name="Fictional Old", archived=True))
    for account, kind, day, symbol, quantity, price, amount, currency in [
        (growth, TxnType.DEPOSIT, "2020-01-02", "", 0, 0, 10000, "CAD"),
        (growth, TxnType.BUY, "2020-01-03", "XEQT.TO", 100, 30, 0, "CAD"),
        (growth, TxnType.DIVIDEND, OLD, "XEQT.TO", 0, 0, 30, "CAD"),
        (growth, TxnType.DIVIDEND, JAN, "XEQT.TO", 0, 0, 50, "CAD"),
        (growth, TxnType.INTEREST, JAN, "", 0, 0, 10, "CAD"),
        (growth, TxnType.DRIP, JAN, "XEQT.TO", 1, 40, 0, "CAD"),
        (income, TxnType.BUY, "2020-01-05", "AAPL", 10, 150, 0, "USD"),
        (income, TxnType.DIVIDEND, JAN, "AAPL", 0, 0, 10, "USD"),
        (old, TxnType.DIVIDEND, JAN, "XEQT.TO", 0, 0, 1000, "CAD"),
    ]:
        store.add_transaction(
            Transaction(account.saved_id, kind, day, symbol, quantity, price, amount, currency=currency)
        )

    def invoke(*args):
        return CliRunner().invoke(main, list(args), catch_exceptions=False)

    return invoke


def with_dividend_history(fake):
    """Trailing distributions for the forward estimate: XEQT.TO 0.50/share, AAPL 1.00/share."""
    today = date.today()
    recent = date(today.year, today.month, 1).isoformat() if today.day > 1 else today.isoformat()
    fake.set_history("XEQT.TO", {recent: 40.0}, "CAD")
    fake.set_history("AAPL", {recent: 200.0}, "USD")
    fake.dividends["XEQT.TO"] = [(recent, 0.5)]
    fake.dividends["AAPL"] = [(recent, 1.0)]


def expected_plain(tracker, store, forecast: bool) -> str:
    view = tracker.valuation(record=False)
    state = store.ledger()
    months = income_by_month(state, view.fx.convert)
    sources = income_by_symbol(state, view.fx.convert, date.today().year)
    rows = tracker.income_forecast(view) if forecast else None
    c = Console(file=io.StringIO(), width=180, theme=RichTheme(rich_styles(resolve_palette("auto"))), highlight=False)
    from rich.text import Text

    c.print(Text("▍Income", style="title"))
    c.print(render.income_group(months, sources, rows, view, privacy=False))
    return c.file.getvalue()


@pytest.mark.parametrize("forecast", [True, False])
def test_plain_income_is_unchanged(cli, tracker, store, fake, forecast):
    with_dividend_history(fake)
    result = cli("income") if forecast else cli("income", "--no-forecast")
    assert result.exit_code == 0
    assert result.output == expected_plain(tracker, store, forecast)
    assert ("NEXT 12M EST." in result.output) is forecast
    assert "$1,113.50" in result.output  # the plain report still counts the archived account, as it always has


def report(cli, *args) -> dict:
    result = cli("income", *args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def dividends_fetched(fake) -> bool:
    return any("events" in params for _, params in fake.calls)


# ── 71 income --json ──────────────────────────────────────────────────────────


def test_income_json_is_raw_unmasked_and_leaves_archived_accounts_out(cli, tracker, fake):
    with_dividend_history(fake)
    tracker.config.privacy = True
    data = report(cli)
    assert list(data) == [
        "base_currency", "window_months", "year", "months", "window_total", "sources_year", "sources",
        "sources_total", "forecast", "forecast_total", "unconverted",
    ]  # fmt: skip
    assert data["base_currency"] == "CAD" and data["window_months"] == 12 and data["year"] is None
    assert len(data["months"]) == 12 and data["months"][-1]["month"] == date.today().isoformat()[:7]
    assert {m["month"]: m["amount"] for m in data["months"]}[month_key(JAN)] == pytest.approx(113.5)
    assert data["window_total"] == pytest.approx(113.5)  # 50 + 10 + 40 + 13.50; archived 1000 left out
    assert data["sources_year"] == YEAR and data["sources_total"] == pytest.approx(113.5)
    assert [(s["source"], s["amount"]) for s in data["sources"]] == [
        ("XEQT.TO", pytest.approx(90)),
        ("AAPL", pytest.approx(13.5)),
        ("Interest", pytest.approx(10)),
    ]
    forecast = {r["symbol"]: r for r in data["forecast"]}
    assert forecast["XEQT.TO"]["quantity"] == 101 and forecast["XEQT.TO"]["annual"] == pytest.approx(50.5)
    assert forecast["AAPL"]["annual"] == pytest.approx(10) and forecast["AAPL"]["annual_base"] == pytest.approx(13.5)
    assert list(forecast["AAPL"]) == [
        "symbol", "name", "quantity", "per_share_ttm", "currency", "annual", "base_currency", "annual_base",
        "yield_pct", "yield_on_cost_pct",
    ]  # fmt: skip
    assert data["forecast_total"] == pytest.approx(64) and data["unconverted"] == []


def test_income_json_no_forecast_fetches_nothing_extra(cli, fake):
    data = report(cli, "--no-forecast")
    assert data["forecast"] is None and data["forecast_total"] is None
    assert not dividends_fetched(fake)


def test_unconverted_payouts_are_listed_not_counted_as_zero(cli, store):
    growth = store.get_account("Fictional Growth")
    store.add_transaction(Transaction(growth.saved_id, TxnType.DIVIDEND, JAN, "EURO", 0, 0, 7, currency="EUR"))
    data = report(cli, "--no-forecast")
    euro = {"date": JAN, "account": "Fictional Growth", "symbol": "EURO", "kind": "dividend"}
    assert data["unconverted"] == [{**euro, "amount": 7, "currency": "EUR"}]
    assert data["window_total"] == pytest.approx(113.5)
    store.add_transaction(Transaction(growth.saved_id, TxnType.DIVIDEND, OLD, "EURO", 0, 0, 3, currency="EUR"))
    assert len(report(cli, "--no-forecast")["unconverted"]) == 1  # the old one is outside what is shown
    assert len(report(cli, "--months", "36", "--by", "month")["unconverted"]) == 2
    human = cli("income", "--no-forecast", "--months", "12")
    assert "1 payout in EUR has no FX rate to CAD and is left out." in human.output
    csv_out = cli("income", "--no-forecast", "--months", "12", "--csv")
    assert "! 1 payout in EUR has no FX rate to CAD and is left out." in csv_out.stderr
    assert csv_out.stdout.startswith("month,amount,base_currency\n") and "EUR" not in csv_out.stdout
    by_month = cli("income", "--by", "month", "--months", "12", "--csv")
    assert "! 1 payout in EUR" in by_month.stderr and "!" not in by_month.stdout


# ── 72 income --csv ───────────────────────────────────────────────────────────


def test_income_csv_prints_monthly_totals_offline(cli, tracker, fake):
    with_dividend_history(fake)
    tracker.config.privacy = True
    result = cli("income", "--csv")
    assert result.exit_code == 0 and "\r" not in result.output
    lines = result.output.splitlines()
    assert lines[0] == "month,amount,base_currency" and len(lines) == 13
    rows = {r["month"]: r for r in csv.DictReader(io.StringIO(result.output))}
    assert rows[month_key(JAN)]["amount"] == "113.5" and rows[month_key(JAN)]["base_currency"] == "CAD"
    assert not dividends_fetched(fake)  # CSV never fetches the forecast
    assert cli("income", "--csv", "--json").exit_code == 2


# ── 73 income --months ────────────────────────────────────────────────────────


def test_income_months_widens_the_history_window(cli):
    data = report(cli, "--months", "36", "--no-forecast")
    assert data["window_months"] == 36 and len(data["months"]) == 36
    assert data["window_total"] == pytest.approx(143.5)  # the dividend from two years ago is now inside
    assert data["sources_total"] == pytest.approx(113.5)  # sources stay this year's
    human = cli("income", "--months", "36", "--no-forecast")
    assert human.exit_code == 0 and "LAST 36 MONTHS" in human.output and "$143.50" in human.output
    assert cli("income", "--months", "0").exit_code == 2


def test_income_months_chart_fits_the_terminal(cli):
    human = cli("income", "--months", "120", "--no-forecast")
    assert human.exit_code == 0 and "LAST 120 MONTHS" in human.output
    assert max(len(line) for line in human.output.splitlines()) <= 180


# ── 74 income --year ──────────────────────────────────────────────────────────


def test_income_year_charts_one_calendar_year_and_its_sources(cli):
    data = report(cli, "--year", str(YEAR - 2), "--no-forecast")
    assert [m["month"] for m in data["months"]] == [f"{YEAR - 2}-{m:02d}" for m in range(1, 13)]
    assert data["window_total"] == pytest.approx(30) and data["window_months"] is None
    assert data["year"] == data["sources_year"] == YEAR - 2
    assert data["sources"] == [{"source": "XEQT.TO", "amount": 30}]
    human = cli("income", "--year", str(YEAR - 2), "--no-forecast").output
    assert f"{YEAR - 2}  $30.00" in human and "YTD" not in human and f"{YEAR - 2}" in human.split("By source")[1]
    clash = cli("income", "--year", "2024", "--months", "6")
    assert clash.exit_code == 2 and "Choose either --months or --year" in clash.output


# ── 75 income -a ACCOUNT ──────────────────────────────────────────────────────


def test_income_for_one_account(cli, fake):
    with_dividend_history(fake)
    data = report(cli, "-a", "Fictional Income")
    assert data["window_total"] == pytest.approx(13.5)
    assert [s["source"] for s in data["sources"]] == ["AAPL"]
    assert [r["symbol"] for r in data["forecast"]] == ["AAPL"]  # the forecast follows the account's holdings
    hidden = cli("income", "-a", "Fictional Old")
    assert hidden.exit_code == 1 and "No active account 'Fictional Old'" in hidden.output


# ── 76 income --symbol ────────────────────────────────────────────────────────


def test_income_for_one_symbol(cli, fake):
    with_dividend_history(fake)
    data = report(cli, "--symbol", " xeqt.to ")
    assert data["window_total"] == pytest.approx(90)  # dividend 50 + DRIP 40; archived 1000 left out
    assert [r["symbol"] for r in data["forecast"]] == ["XEQT.TO"] and data["forecast_total"] == pytest.approx(50.5)
    assert report(cli, "--symbol", "NONE", "--no-forecast")["window_total"] == 0
    blank = cli("income", "--symbol", " ")
    assert blank.exit_code == 2 and "--symbol cannot be blank" in blank.output


# ── 77 income --kind ──────────────────────────────────────────────────────────


def test_income_by_kind_filter(cli, fake):
    with_dividend_history(fake)
    interest = report(cli, "--kind", "interest")
    assert interest["window_total"] == pytest.approx(10) and interest["forecast"] is None  # no dividends asked for
    paid = report(cli, "--kind", "DIVIDEND", "--kind", "drip", "--no-forecast")
    assert paid["window_total"] == pytest.approx(103.5)
    assert cli("income", "--kind", "bonus").exit_code == 2


# ── 78 income --by ────────────────────────────────────────────────────────────


def groups(cli, *args) -> list[tuple]:
    data = report(cli, *args)
    return [(g["label"], g["count"], pytest.approx(g["amount"])) for g in data["groups"]]


def test_income_by_groups_in_base_currency(cli, fake):
    assert groups(cli, "--by", "account") == [("Fictional Growth", 3, 100), ("Fictional Income", 1, 13.5)]
    assert groups(cli, "--by", "kind") == [("Dividend", 2, 63.5), ("DRIP", 1, 40), ("Interest", 1, 10)]
    assert groups(cli, "--by", "symbol") == [("XEQT.TO", 2, 90), ("AAPL", 1, 13.5), ("Interest", 1, 10)]
    assert groups(cli, "--by", "month", "--months", "36") == [(OLD[:7], 1, 30), (JAN[:7], 4, 113.5)]
    data = report(cli, "--by", "account")
    assert data["total"] == pytest.approx(113.5) and data["payouts"] == 4 and data["by"] == "account"
    assert data["groups"][0]["group"] == "1"
    assert not dividends_fetched(fake)  # grouped views are offline


def test_income_by_csv_and_human_table(cli, tracker):
    result = cli("income", "--by", "kind", "--csv")
    assert result.output.splitlines()[0] == "group,label,count,amount,base_currency"
    assert result.output.splitlines()[1] == "dividend,Dividend,2,63.5,CAD"
    human = cli("income", "--by", "account").output
    assert "By account" in human and "Fictional Growth" in human and "$100.00" in human and "Fictional Old" not in human
    assert "$113.50 CAD from 4 payouts in the last 12 months" in human
    tracker.config.privacy = True
    assert "$100.00" not in cli("income", "--by", "account").output
    assert "No income matches" in cli("income", "--by", "kind", "--symbol", "NONE").output


# ── 79 income --top ───────────────────────────────────────────────────────────


def test_income_top_keeps_the_largest_rows_but_full_totals(cli, fake):
    with_dividend_history(fake)
    data = report(cli, "--top", "1")
    assert [s["source"] for s in data["sources"]] == ["XEQT.TO"] and data["sources_total"] == pytest.approx(113.5)
    assert [r["symbol"] for r in data["forecast"]] == ["XEQT.TO"] and data["forecast_total"] == pytest.approx(64)
    assert groups(cli, "--by", "kind", "--top", "2") == [("Dividend", 2, 63.5), ("DRIP", 1, 40)]
    months = report(cli, "--by", "month", "--months", "36", "--top", "1")
    assert [g["group"] for g in months["groups"]] == [JAN[:7]] and months["total"] == pytest.approx(143.5)
    human = cli("income", "--top", "1", "--no-forecast").output
    assert "XEQT.TO" in human.split("By source")[1] and "Interest" not in human.split("By source")[1]


# ── 80 income --forecast-only ─────────────────────────────────────────────────


def test_income_forecast_only(cli, tracker, fake):
    with_dividend_history(fake)
    data = report(cli, "--forecast-only")
    assert list(data) == ["base_currency", "forecast", "total"] and data["total"] == pytest.approx(64)
    assert [r["symbol"] for r in data["forecast"]] == ["XEQT.TO", "AAPL"]
    rows = list(csv.DictReader(io.StringIO(cli("income", "--forecast-only", "--csv").output)))
    assert [r["symbol"] for r in rows] == ["XEQT.TO", "AAPL"] and rows[1]["annual_base"] == "13.5"
    human = cli("income", "--forecast-only", "--symbol", "AAPL").output
    assert "NEXT 12M EST.  $13.50" in human and "Forward income" in human and "By source" not in human
    tracker.config.privacy = True
    assert "$13.50" not in cli("income", "--forecast-only").output
    for extra in (["--no-forecast"], ["--by", "kind"], ["--year", "2024"], ["--kind", "drip"]):
        assert cli("income", "--forecast-only", *extra).exit_code == 2


def test_income_forecast_only_without_distributions(cli):
    assert "No trailing distributions" in cli("income", "--forecast-only").output
    assert report(cli, "--forecast-only") == {"base_currency": "CAD", "forecast": [], "total": 0}


def test_selected_income_report_honours_privacy(cli, tracker, fake):
    with_dividend_history(fake)
    tracker.config.privacy = True
    human = cli("income", "--months", "12").output
    assert "LAST 12 MONTHS" in human and "$113.50" not in human and "••••" in human and "Forward income" in human
