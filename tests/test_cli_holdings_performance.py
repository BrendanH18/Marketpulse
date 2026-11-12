"""Fictional-ledger checks for priced holdings selection and performance output (fake quotes only)."""

import csv
import io
import json

import pytest
from click.testing import CliRunner
from rich.console import Console
from rich.text import Text
from rich.theme import Theme as RichTheme

from marketpulse import render
from marketpulse.cli import main
from marketpulse.models import Account, Transaction, TxnType
from marketpulse.themes import resolve_palette, rich_styles


@pytest.fixture
def priced(store, tracker, fake, monkeypatch):
    """Growth (tracks cash): XEQT.TO +1000 CAD, LOSS.TO −250 CAD, 6000 CAD cash. Income: AAPL +500 USD."""
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "180")
    fake.set_quote("LOSS.TO", 15.0, 14.0, "CAD", "Fictional Loss Fund", "ETF")
    growth = store.add_account(Account(name="Fictional Growth", track_cash=True))
    income = store.add_account(Account(name="Fictional Income"))
    for account, kind, day, symbol, quantity, price, amount, currency in [
        (growth, TxnType.DEPOSIT, "2024-01-02", "", 0, 0, 10000, "CAD"),
        (growth, TxnType.BUY, "2024-01-03", "XEQT.TO", 100, 30, 0, "CAD"),
        (growth, TxnType.BUY, "2024-01-04", "LOSS.TO", 50, 20, 0, "CAD"),
        (income, TxnType.BUY, "2024-01-05", "AAPL", 10, 150, 0, "USD"),
    ]:
        store.add_transaction(
            Transaction(account.saved_id, kind, day, symbol, quantity, price, amount, currency=currency)
        )

    def invoke(*args):
        return CliRunner().invoke(main, list(args), catch_exceptions=False)

    return invoke


def rows(priced, *args):
    result = priced("holdings", *args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def symbols(priced, *args):
    return [r["symbol"] for r in rows(priced, *args)]


def unpriced_extra(store):
    """An unlisted fictional symbol and an archived account; both stay out of the totals."""
    income = store.get_account("Fictional Income")
    store.add_transaction(Transaction(income.saved_id, TxnType.BUY, "2024-02-01", "GONE", 5, 10, 0, currency="USD"))
    hidden = store.add_account(Account(name="Fictional Hidden", archived=True))
    store.add_transaction(Transaction(hidden.saved_id, TxnType.BUY, "2024-02-01", "SECRET", 1, 5, 0, currency="CAD"))


def expected_default(tracker):
    view = tracker.valuation(record=False)
    console = Console(
        file=io.StringIO(), width=180, theme=RichTheme(rich_styles(resolve_palette("auto"))), highlight=False
    )
    console.print(render.holdings_table(view, privacy=tracker.config.privacy, width=180))
    console.print(render.summary(view, privacy=tracker.config.privacy))
    for reason in sorted(set(view.errors.values())):
        console.print(Text("! ") + Text(reason))
    return console.file.getvalue()


def test_default_holdings_and_perf_are_unchanged_and_record_a_snapshot(priced, tracker, store):
    result = priced("holdings")
    assert result.exit_code == 0
    assert result.output == expected_default(tracker)
    assert "CASH" in result.output and "NET WORTH" in result.output and "Showing" not in result.output
    assert len(store.snapshots()) == 1
    perf = priced("perf")
    assert perf.exit_code == 0
    assert "Performance" in perf.output and "Tracking since" in perf.output and "2024-01-02" in perf.output


def test_holdings_json_is_raw_priced_positions_and_unmasked(priced, tracker, store):
    tracker.config.privacy = True
    data = {r["symbol"]: r for r in rows(priced)}
    assert set(data) == {"XEQT.TO", "LOSS.TO", "AAPL"}
    xeqt = data["XEQT.TO"]
    assert xeqt["account"] == "Fictional Growth" and xeqt["currency"] == "CAD" and xeqt["base_currency"] == "CAD"
    assert xeqt["quantity"] == 100 and xeqt["price"] == 40 and xeqt["book"] == 3000
    assert xeqt["market_value"] == 4000 and xeqt["unrealized"] == 1000
    assert xeqt["unrealized_pct"] == pytest.approx(100 / 3)
    assert xeqt["day_change"] == pytest.approx(-50) and xeqt["priced"] is True and xeqt["stale"] is False
    assert xeqt["weight"] == pytest.approx(4000 / 13450 * 100)
    aapl = data["AAPL"]
    assert aapl["market_value"] == 2000 and aapl["value_base"] == pytest.approx(2700)
    assert aapl["unrealized_base"] == pytest.approx(675) and aapl["day_change_base"] == pytest.approx(135)
    assert aapl["fx_rate"] == 1.35 and aapl["first_date"] == "2024-01-05"
    assert list(xeqt) == [
        "account_id", "account", "symbol", "name", "asset_class", "kind", "currency", "quantity", "average_cost",
        "price", "book", "market_value", "unrealized", "unrealized_pct", "day_change", "day_change_pct",
        "base_currency", "fx_rate", "value_base", "book_base", "unrealized_base", "day_change_base", "weight",
        "priced", "stale", "first_date",
    ]  # fmt: skip
    assert symbols(priced, "-a", "Fictional Income") == ["AAPL"]
    assert len(store.snapshots()) == 1  # same valuation, same snapshot as the plain table


def test_holdings_csv_matches_json_with_unix_line_endings(priced):
    result = priced("holdings", "--csv", "--sort", "symbol")
    assert result.exit_code == 0 and "\r" not in result.output
    parsed = list(csv.DictReader(io.StringIO(result.output)))
    assert [r["symbol"] for r in parsed] == ["AAPL", "LOSS.TO", "XEQT.TO"]
    assert parsed[2]["market_value"] == "4000.0" and parsed[2]["priced"] == "True"
    assert result.output.splitlines()[0].startswith("account_id,account,symbol,name,")


def test_sort_orders_by_metric_with_unpriced_last_either_way(priced, store):
    assert symbols(priced, "--sort", "value", "--descending") == ["XEQT.TO", "AAPL", "LOSS.TO"]
    assert symbols(priced, "--sort", "value") == ["LOSS.TO", "AAPL", "XEQT.TO"]
    assert symbols(priced, "--sort", "gain", "--descending") == ["XEQT.TO", "AAPL", "LOSS.TO"]
    assert symbols(priced, "--sort", "gain-pct") == ["LOSS.TO", "XEQT.TO", "AAPL"]  # equal % ties by account
    assert symbols(priced, "--sort", "day-pct", "--descending") == ["LOSS.TO", "AAPL", "XEQT.TO"]
    assert symbols(priced, "--sort", "day") == ["XEQT.TO", "LOSS.TO", "AAPL"]
    assert symbols(priced, "--sort", "account") == ["LOSS.TO", "XEQT.TO", "AAPL"]
    unpriced_extra(store)
    assert symbols(priced, "--sort", "weight")[-1] == "GONE"
    assert symbols(priced, "--sort", "weight", "--descending")[-1] == "GONE"
    assert "SECRET" not in symbols(priced)


def test_symbol_and_currency_filters(priced):
    assert symbols(priced, "--symbol", " .to ", "--sort", "symbol") == ["LOSS.TO", "XEQT.TO"]
    assert symbols(priced, "--currency", "usd") == ["AAPL"]
    assert symbols(priced, "--symbol", "xeqt", "--currency", "USD") == []


def test_gainers_losers_and_min_weight(priced, store):
    assert symbols(priced, "--gainers", "--sort", "symbol") == ["AAPL", "XEQT.TO"]
    assert symbols(priced, "--losers") == ["LOSS.TO"]
    assert symbols(priced, "--min-weight", "20", "--sort", "symbol") == ["AAPL", "XEQT.TO"]
    assert symbols(priced, "--min-weight", "0", "--sort", "symbol") == ["AAPL", "LOSS.TO", "XEQT.TO"]
    unpriced_extra(store)
    assert "GONE" not in symbols(priced, "--min-weight", "0") + symbols(priced, "--gainers")
    assert "GONE" in symbols(priced)


def test_limit_offset_and_count(priced):
    base = ("--sort", "value", "--descending")
    assert symbols(priced, *base, "--limit", "1") == ["XEQT.TO"]
    assert symbols(priced, *base, "--offset", "1", "--limit", "1") == ["AAPL"]
    assert symbols(priced, *base, "--offset", "5") == []
    assert priced("holdings", "--count").output == "3\n"
    assert priced("holdings", "--count", "--currency", "cad").output == "2\n"
    assert priced("holdings", "--count", "--losers").output == "1\n"


def test_stale_lists_positions_priced_from_cached_quotes(priced, tracker, fake):
    assert priced("holdings", "--stale", "--count").output == "0\n"
    fake.offline = True
    tracker.market._quote_cache.clear()
    assert symbols(priced, "--stale", "--currency", "CAD", "--sort", "symbol") == ["LOSS.TO", "XEQT.TO"]
    assert all(r["stale"] for r in rows(priced))
    human = priced("holdings", "--stale")
    assert human.exit_code == 0 and "◌" in human.output and "Prices are offline" in human.output


def test_excluded_lists_what_totals_leave_out_with_reasons(priced, store):
    assert rows(priced, "--excluded") == []
    assert "Nothing is left out of the totals." in priced("holdings", "--excluded").output
    unpriced_extra(store)
    data = rows(priced, "--excluded")
    assert [(r["code"], r["item"], r["account"]) for r in data] == [
        ("unpriced", "GONE", "Fictional Income"),
        ("archived_holding", "SECRET in archived Fictional Hidden", "Fictional Hidden"),
        ("archived_account", "Fictional Hidden", "Fictional Hidden"),
    ]
    assert data[0]["reason"] == "no price or FX rate" and data[0]["detail"] == "symbol not found"
    human = priced("holdings", "--excluded")
    assert "Left out of totals" in human.output and "GONE" in human.output and "symbol not found" in human.output
    assert rows(priced, "--excluded", "-a", "Fictional Growth") == []
    filtered = priced("holdings", "--sort", "value")
    assert "holdings --excluded" in filtered.output


def test_selection_human_output_omits_cash_and_totals_and_respects_privacy(priced, tracker):
    result = priced("holdings", "--currency", "cad")
    assert result.exit_code == 0
    assert "XEQT.TO" in result.output and "LOSS.TO" in result.output and "AAPL" not in result.output
    assert "CASH" not in result.output and "NET WORTH" not in result.output
    assert "Showing 2 of 3 positions" in result.output
    assert "No holdings match these filters." in priced("holdings", "--symbol", "nope").output
    assert "No holdings on this page." in priced("holdings", "--offset", "9").output
    tracker.config.privacy = True
    masked = priced("holdings", "--sort", "value", "--descending")
    assert "4,000" not in masked.output and "••••" in masked.output


@pytest.mark.parametrize(
    "args",
    [
        ("--json", "--csv"),
        ("--count", "--json"),
        ("--count", "--limit", "1"),
        ("--gainers", "--losers"),
        ("--descending",),
        ("--excluded", "--csv"),
        ("--excluded", "--sort", "value"),
        ("--excluded", "--symbol", "X"),
        ("--min-weight", "nan"),
        ("--min-weight", "-1"),
        ("--limit", "0"),
        ("--sort", "nope"),
    ],
)
def test_conflicting_or_invalid_holdings_options_are_usage_errors(priced, args):
    assert priced("holdings", *args).exit_code == 2


def test_perf_json_and_metric(priced, tracker):
    result = priced("perf", "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert list(payload) == [
        "base_currency", "since", "days", "net_contributions", "total_gain", "xirr_pct", "twr_pct",
        "twr_annual_pct", "max_drawdown_pct", "volatility_pct", "index", "stale", "excluded",
    ]  # fmt: skip
    assert payload["base_currency"] == "CAD" and payload["since"] == "2024-01-02"
    assert payload["net_contributions"] == pytest.approx(12025)  # 10000 CAD cash + AAPL 1500 USD at 1.35
    assert payload["total_gain"] == pytest.approx(13450 - 12025)
    assert payload["twr_pct"] is None and payload["index"] == [] and payload["excluded"] == []
    tracker.config.privacy = True  # machine output stays raw
    assert float(priced("perf", "--metric", "total-gain").output) == pytest.approx(payload["total_gain"])
    assert priced("perf", "--metric", "since").output == "2024-01-02\n"
    assert float(priced("perf", "--metric", "xirr").output) == pytest.approx(payload["xirr_pct"])
    missing = priced("perf", "--metric", "twr")
    assert missing.exit_code == 1 and missing.output.startswith("Error: twr isn't available yet")
    assert priced("perf", "--json", "--metric", "days").exit_code == 2
    assert priced("perf", "--metric", "nope").exit_code == 2
