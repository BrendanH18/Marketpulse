"""The Tax workspace's bridge (`desktop tax`) and the accountant CSV (`tax --csv`), on a fictional ledger."""

import csv
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.desktop import tax_report
from marketpulse.models import Account, AccountType, Transaction, TxnType


def trade(store, acct, kind, day, symbol, qty, price, ccy="CAD"):
    store.add_transaction(
        Transaction(
            account_id=acct.saved_id, type=kind, date=day, symbol=symbol, quantity=qty, price=price, currency=ccy
        )
    )


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    return lambda *args: CliRunner().invoke(main, list(args), catch_exceptions=False)


@pytest.fixture
def ledger(store, fake):
    """2024: a superficial loss. 2025: the rebought shares sold at a gain, a USD sale with
    trade-date FX, a EUR sale with no FX rate, and a sale in an account archived since."""
    taxable = store.add_account(Account(name="Fictional Taxable", type=AccountType.NONREG))
    store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
    trade(store, taxable, TxnType.BUY, "2024-01-02", "XEQT.TO", 10, 30)
    trade(store, taxable, TxnType.SELL, "2024-03-01", "XEQT.TO", 10, 25)  # −$50…
    trade(store, taxable, TxnType.BUY, "2024-03-15", "XEQT.TO", 10, 26)  # …bought back within 30 days
    trade(store, taxable, TxnType.SELL, "2025-02-03", "XEQT.TO", 10, 35)  # ACB 260 + the denied 50
    trade(store, taxable, TxnType.BUY, "2025-01-02", "AAPL", 1, 100, "USD")  # US$100 × 1.30
    trade(store, taxable, TxnType.SELL, "2025-03-03", "AAPL", 1, 150, "USD")  # US$150 × 1.40
    trade(store, taxable, TxnType.BUY, "2025-01-10", "SAP.DE", 2, 100, "EUR")  # no EURCAD history
    trade(store, taxable, TxnType.SELL, "2025-04-01", "SAP.DE", 2, 120, "EUR")
    old = store.add_account(Account(name="Old Margin", type=AccountType.MARGIN))
    trade(store, old, TxnType.BUY, "2025-01-06", "ZAG.TO", 100, 15)
    trade(store, old, TxnType.SELL, "2025-05-01", "ZAG.TO", 100, 16)
    old.archived = True
    store.update_account(old)
    store.set_room("TFSA", 2025, 7000)
    fake.set_history("USDCAD=X", {"2024-12-20": 1.3, "2025-01-02": 1.3, "2025-03-01": 1.4}, currency="CAD")
    return taxable


def test_tax_report_matches_the_cli_report_year_by_year(tracker, ledger):
    payload = tax_report(tracker)
    json.dumps(payload, allow_nan=False)  # what the CLI emits
    assert (payload["version"], payload["demo"], payload["base_currency"]) == (1, False, "CAD")
    years, _ = tracker.tax_years()  # what `marketpulse tax` shows
    assert [y["year"] for y in payload["years"]] == [y.year for y in years] == [2025, 2024]
    for got, want in zip(payload["years"], years, strict=True):
        assert got["proceeds"] == pytest.approx(want.proceeds)
        assert got["acb"] == pytest.approx(want.cost)
        assert got["denied"] == pytest.approx(want.denied)
        assert got["net_gain"] == pytest.approx(want.net_gain)
        assert got["taxable"] == pytest.approx(want.taxable)
        assert got["dispositions"] == len(want.rows) and got["missing_fx"] == len(want.missing_fx)
        # Per-security totals add up to the year's.
        assert sum(s["net_gain"] for s in got["securities"]) == pytest.approx(want.net_gain)
        assert sum(s["proceeds"] for s in got["securities"]) == pytest.approx(want.proceeds)


def test_superficial_loss_is_denied_and_moves_into_the_rebought_shares(tracker, ledger):
    y2025, y2024 = tax_report(tracker)["years"]
    assert (y2024["net_gain"], y2024["denied"], y2024["taxable"], y2024["superficial"]) == (0, 50, 0, 1)
    (loss,) = y2024["rows"]
    assert loss["superficial"] and loss["denied_reason"] == "superficial" and loss["note"] == "superficial"
    assert (loss["gain"], loss["denied"], loss["allowed_gain"]) == (pytest.approx(-50), pytest.approx(50), 0)
    assert (loss["acquired_in_window"], loss["held_after_window"], loss["window_open"]) == (10, 10, False)
    xeqt = next(s for s in y2025["securities"] if s["symbol"] == "XEQT.TO")
    assert xeqt["acb"] == pytest.approx(310) and xeqt["net_gain"] == pytest.approx(40)  # not 90


def test_usd_sale_uses_each_trade_dates_rate_and_missing_fx_is_left_out(tracker, ledger):
    y2025 = tax_report(tracker)["years"][0]
    aapl = next(r for r in y2025["rows"] if r["symbol"] == "AAPL")
    assert (aapl["fx"], aapl["proceeds"], aapl["acb"]) == (1.4, pytest.approx(210), pytest.approx(130))
    assert aapl["allowed_gain"] == pytest.approx(80) and aapl["currency"] == "USD"
    sap = next(r for r in y2025["rows"] if r["symbol"] == "SAP.DE")
    assert not sap["complete"] and sap["note"] == "FX missing" and sap["fx"] is None
    assert [sap[k] for k in ("proceeds", "acb", "gain", "denied", "allowed_gain")] == [None] * 5  # unknown, not 0
    assert y2025["missing_fx"] == 1
    assert next(s for s in y2025["securities"] if s["symbol"] == "SAP.DE")["missing_fx"] == 1
    # XEQT 40 + AAPL 80 + ZAG 100; the EUR sale isn't guessed at.
    assert y2025["net_gain"] == pytest.approx(220) and y2025["taxable"] == pytest.approx(110)
    assert [s["symbol"] for s in y2025["securities"]] == ["AAPL", "SAP.DE", "XEQT.TO", "ZAG.TO"]


def test_archived_accounts_count_but_are_never_named(tracker, ledger):
    payload = tax_report(tracker)
    zag = next(r for r in payload["years"][0]["rows"] if r["symbol"] == "ZAG.TO")
    assert zag["allowed_gain"] == pytest.approx(100)  # CRA still counts the sale
    assert (zag["account"], zag["archived"], zag["account_type"]) == (None, True, "MARGIN")
    assert "Old Margin" not in json.dumps(payload)
    assert payload["years"][0]["rows"][0]["account"] == "Fictional Taxable"
    ((room,),) = [payload["room"]]
    assert room["account_type"] == "TFSA" and room["starting_room"] == 7000
    assert room["remaining"] == pytest.approx(room["starting_room"] + room["new_limits"])
    assert any("not tax advice" in note for note in payload["notes"])


def test_desktop_tax_cli_emits_the_report(cli, tracker, ledger, monkeypatch):
    out = cli("desktop", "tax")
    assert out.exit_code == 0
    assert json.loads(out.output) == json.loads(json.dumps(tax_report(tracker)))
    # The same figures as the terminal report.
    monkeypatch.setenv("COLUMNS", "160")
    report = cli("tax", "--year", "2025").output
    assert "+220.00" in report and "110.00  (50%)" in report and "FX missing" in report


def test_tax_csv_for_an_accountant(cli, ledger, tmp_path):
    path = tmp_path / "gains.csv"
    out = cli("tax", "--year", "2025", "--csv", str(path))
    assert out.exit_code == 0 and "Exported 4 disposition(s)" in out.output
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert [r["Symbol"] for r in rows] == ["XEQT.TO", "AAPL", "SAP.DE", "ZAG.TO"]
    aapl = rows[1]
    assert (aapl["Tax year"], aapl["Date"], aapl["Account"], aapl["Trading currency"]) == (
        "2025",
        "2025-03-03",
        "Fictional Taxable",
        "USD",
    )
    assert (aapl["FX rate to CAD"], aapl["Proceeds (CAD)"], aapl["ACB (CAD)"]) == ("1.400000", "210.00", "130.00")
    assert aapl["Reported gain or loss (CAD)"] == "80.00" and aapl["Type"] == "Sale"
    sap = rows[2]
    assert sap["Note"] == "FX missing" and sap["Proceeds (CAD)"] == sap["Reported gain or loss (CAD)"] == ""
    # The file is for the user's accountant, so it names every account, archived ones too.
    assert rows[3]["Account"] == "Old Margin" and rows[3]["Account type"] == "MARGIN"

    every = tmp_path / "all.csv"
    assert cli("tax", "--csv", str(every)).exit_code == 0
    rows = list(csv.DictReader(every.open(encoding="utf-8")))
    assert [r["Tax year"] for r in rows] == ["2024"] + ["2025"] * 4
    assert (rows[0]["Denied loss (CAD)"], rows[0]["Reported gain or loss (CAD)"]) == ("50.00", "0.00")
    assert rows[0]["Note"] == "superficial"

    none = cli("tax", "--year", "2023", "--csv", str(tmp_path / "empty.csv"))
    assert none.exit_code == 1 and "No capital gains or losses in 2023" in none.output
    assert not (tmp_path / "empty.csv").exists()


def test_demo_tax_never_opens_the_real_ledger(monkeypatch, tmp_path):
    def fail_open(*args, **kwargs):
        raise AssertionError("Real portfolio must not be opened")

    monkeypatch.setattr("marketpulse.services.Tracker.open", fail_open)
    monkeypatch.setattr(
        "marketpulse.market.MarketData._chart", lambda *a, **k: pytest.fail("The demo must not fetch history")
    )
    result = CliRunner().invoke(main, ["desktop", "tax", "--demo"], catch_exceptions=False)
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["demo"] is True and not (tmp_path / "data").exists()
    rows = [r for y in payload["years"] for r in y["rows"]]
    # A superficial loss, then a gain on the rebought shares, both converted from USD.
    assert [r["superficial"] for r in rows] == [True, False]
    assert all(r["complete"] and r["currency"] == "USD" and r["account"] == "Personal investing" for r in rows)
    assert sum(y["net_gain"] for y in payload["years"]) > 0


def test_ledger_revision_follows_everything_the_tax_report_reads(tracker, ledger):
    from marketpulse.desktop import ledger_revision

    store = tracker.store
    first = ledger_revision(tracker)
    assert ledger_revision(tracker) == first  # nothing changed, so the app keeps its report
    # An archived account's sale, edited in the terminal: the snapshot's activity never shows it.
    old = store.get_account("Old Margin")
    sale = next(t for t in store.transactions() if t.account_id == old.saved_id and t.type is TxnType.SELL)
    sale.price = 17
    store.update_transaction(sale)
    edited = ledger_revision(tracker)
    assert edited != first
    tracker.config.capital_gains_inclusion = 2 / 3
    assert ledger_revision(tracker) != edited


def test_ledger_revision_changes_with_the_day(tracker, ledger, monkeypatch):
    """Room rolls over on January 1 and superficial-loss windows close: a new day, a new report."""
    from datetime import date

    from marketpulse.desktop import ledger_revision

    class NewYear(date):
        @classmethod
        def today(cls):
            return cls(2027, 1, 1)

    today = ledger_revision(tracker)
    monkeypatch.setattr("marketpulse.desktop.date", NewYear)
    assert ledger_revision(tracker) != today


def test_tax_csv_warns_about_sales_it_cannot_include(cli, store, tmp_path):
    taxable = store.add_account(Account(name="Fictional Taxable"))
    tfsa = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
    trade(store, taxable, TxnType.BUY, "2024-01-02", "XEQT.TO", 10, 30)
    trade(store, taxable, TxnType.SELL, "2024-02-01", "XEQT.TO", 5, 31)
    # Moved into the TFSA with no price: a deemed sale whose proceeds aren't known.
    store.add_transaction(
        Transaction(
            account_id=taxable.saved_id,
            type=TxnType.TRANSFER,
            date="2024-07-02",
            symbol="XEQT.TO",
            quantity=5,
            target_account_id=tfsa.saved_id,
        )
    )
    out = cli("tax", "--year", "2024", "--csv", str(tmp_path / "gains.csv"))
    assert out.exit_code == 0 and "Exported 1 disposition(s)" in out.output
    assert "1 issue(s) may leave sales out of this file" in out.output and "2024-07-02" in out.output
    # The app's export reports what this export found, not what its loaded report showed.
    app = cli("desktop", "tax-csv", "--year", "2024", "--", str(tmp_path / "app.csv"))
    result = json.loads(app.output)
    assert result["exported"] == 1 and [i["date"] for i in result["issues"]] == ["2024-07-02"]
    assert (tmp_path / "app.csv").read_text(encoding="utf-8") == (tmp_path / "gains.csv").read_text(encoding="utf-8")
    missing = cli("desktop", "tax-csv", "--year", "2023", "--", str(tmp_path / "none.csv"))
    assert missing.exit_code == 1 and "No capital gains or losses in 2023" in missing.output


def test_tax_csv_quantities_are_never_rounded_or_in_exponent_form(tracker, store, tmp_path):
    from marketpulse.csvio import export_capital_gains

    taxable = store.add_account(Account(name="Fictional Taxable"))
    for symbol, qty in (("BIG.TO", 1234567), ("SMALL.TO", 0.000125), ("TINY.TO", 1.25e-09)):
        trade(store, taxable, TxnType.BUY, "2024-01-02", symbol, qty, 1)
        trade(store, taxable, TxnType.SELL, "2024-02-01", symbol, qty, 2)
    years, _ = tracker.tax_years()
    path = tmp_path / "gains.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        export_capital_gains(years, store.account_map(), "CAD", f)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert [r["Quantity"] for r in rows] == ["1234567", "0.000125", "0.00000000125"]
