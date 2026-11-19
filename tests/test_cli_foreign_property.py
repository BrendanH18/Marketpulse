"""Foreign property (form T1135) in the CLI, the desktop bridge and the TUI (#179), on a fictional ledger."""

import asyncio
import io
import json

import pytest
from click.testing import CliRunner
from rich.console import Console
from rich.theme import Theme as RichTheme
from textual.widgets import Static

from marketpulse import render
from marketpulse.cli import main
from marketpulse.desktop import ledger_revision, tax_report
from marketpulse.models import Account, AccountType, Asset, AssetClass, AssetKind, Transaction, TxnType
from marketpulse.tax import ForeignPropertyYear
from marketpulse.themes import resolve_palette, rich_styles
from marketpulse.tui.app import MarketPulseApp


def trade(store, acct, kind, day, symbol, qty, price, ccy="CAD"):
    store.add_transaction(
        Transaction(
            account_id=acct.saved_id, type=kind, date=day, symbol=symbol, quantity=qty, price=price, currency=ccy
        )
    )


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "160")
    return lambda *args: CliRunner().invoke(main, list(args), catch_exceptions=False)


@pytest.fixture
def ledger(store, fake):
    """2024: US$100,000 of a US listing at 1.30 (CAD 130,000) in March, half sold in September,
    plus a Canadian-listed ETF and a TFSA holding that never count. 2025: a EUR listing with no rate."""
    taxable = store.add_account(Account(name="Fictional Taxable", type=AccountType.NONREG))
    tfsa = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
    trade(store, taxable, TxnType.BUY, "2024-03-04", "FICTUS", 1000, 100, "USD")
    trade(store, taxable, TxnType.SELL, "2024-09-03", "FICTUS", 500, 110, "USD")
    trade(store, taxable, TxnType.BUY, "2024-03-04", "XFIC.TO", 2000, 100)
    trade(store, tfsa, TxnType.BUY, "2024-03-04", "FICTTF", 5000, 100, "USD")
    trade(store, taxable, TxnType.BUY, "2025-02-03", "FICT.DE", 10, 100, "EUR")
    fake.set_history("USDCAD=X", {"2024-02-20": 1.3, "2024-09-01": 1.4}, currency="CAD")
    return taxable


def test_json_report_for_one_year(cli, ledger):
    r = cli("tax", "foreign-property", "--year", "2024", "--json")
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert payload["currency"] == "CAD" and payload["threshold"] == 100_000
    assert any("not tax advice" in n for n in payload["notes"])
    (y,) = payload["years"]
    assert (y["year"], y["status"], y["required"], y["incomplete"]) == (2024, "simplified", True, False)
    assert y["max_cost"] == pytest.approx(130_000) and y["max_cost_date"] == "2024-03-04"
    assert y["year_end_cost"] == pytest.approx(65_000)
    (h,) = y["holdings"]  # not the Canadian-listed ETF, not the TFSA
    assert h["symbol"] == "FICTUS" and h["dispositions"] == 1
    # 500 x US$110 x 1.40 = $77,000 against $65,000 of pooled ACB.
    assert h["gain"] == pytest.approx(12_000) and y["gain"] == pytest.approx(12_000)


def test_json_report_for_every_year(cli, ledger):
    years = json.loads(cli("tax", "foreign-property", "--json").output)["years"]
    assert [y["year"] for y in years][-2:] == [2025, 2024]
    newest = next(y for y in years if y["year"] == 2025)
    assert newest["incomplete"] and newest["max_cost_date"] == "2025-01-01"  # carried in from 2024
    assert [h["symbol"] for h in newest["holdings"]] == ["FICTUS", "FICT.DE"]


def test_human_report_with_and_without_a_year(cli, ledger):
    out = cli("tax", "foreign-property", "-y", "2024").output
    assert "Foreign property (T1135)" in out and "2024: highest cost $130,000.00 on 2024-03-04" in out
    assert "simplified method" in out and "FICTUS" in out and "XFIC.TO" not in out
    assert "not tax advice" in out
    every = cli("tax", "foreign-property").output
    assert "2024" in every and "2025" in every and "simplified" in every
    assert "FX rate was missing" in every and "may be too low" in every
    detail = cli("tax", "foreign-property", "-y", "2025").output
    assert "FICT.DE *" in detail and "missing an FX rate" in detail


def test_human_report_without_foreign_property(cli, store):
    acct = store.add_account(Account(name="Fictional Taxable"))
    trade(store, acct, TxnType.BUY, "2024-03-04", "XFIC.TO", 10, 100)
    assert "No foreign property in non-registered accounts." in cli("tax", "foreign-property").output
    out = cli("tax", "foreign-property", "-y", "2024").output
    assert "No foreign property in non-registered accounts in 2024." in out


def test_privacy_masks_the_amounts(cli, ledger, tracker):
    tracker.config.privacy = True
    out = cli("tax", "foreign-property", "-y", "2024").output
    assert "130,000" not in out and "65,000" not in out and "FICTUS" in out


def test_plain_tax_report_still_runs_beside_the_subcommand(cli, ledger):
    rows = json.loads(cli("tax", "--json").output)
    assert {r["symbol"] for r in rows} == {"FICTUS"}
    assert "foreign-property" in cli("tax", "--help").output


def test_asset_foreign_setting_both_ways(cli, ledger, store):
    r = cli("asset", "foreign", "fictus", "no", "--json")
    assert json.loads(r.output) == {"symbol": "FICTUS", "foreign_property": False, "counts": False, "saved": True}
    # A market symbol had no asset row: the setting made a minimal one.
    assert store.assets()["FICTUS"] == Asset("FICTUS", AssetKind.MARKET, foreign_property=False)
    r = cli("asset", "foreign", "XFIC.TO", "YES")
    assert "XFIC.TO counts as foreign property (by your setting)." in r.output
    (y,) = json.loads(cli("tax", "foreign-property", "-y", "2024", "--json").output)["years"]
    assert [h["symbol"] for h in y["holdings"]] == ["XFIC.TO"] and y["status"] == "simplified"
    # auto goes back to the listing, keeping the rest of the row.
    store.upsert_asset(Asset("XFIC.TO", asset_class=AssetClass.ETF, foreign_property=True))
    assert "does not count as foreign property (by listing)" in cli("asset", "foreign", "XFIC.TO", "auto").output
    assert store.assets()["XFIC.TO"] == Asset("XFIC.TO", asset_class=AssetClass.ETF)


def test_asset_foreign_dry_run_and_blank_symbol(cli, store):
    r = cli("asset", "foreign", "FICT.L", "no", "--dry-run")
    assert "Would set: FICT.L does not count as foreign property (by your setting) (not saved)." in r.output
    receipt = json.loads(cli("asset", "foreign", "FICT.L", "auto", "--dry-run", "--json").output)
    assert receipt == {"symbol": "FICT.L", "foreign_property": None, "counts": True, "saved": False}
    assert store.assets() == {}
    r = CliRunner().invoke(main, ["asset", "foreign", " ", "yes"])
    assert r.exit_code == 2 and "cannot be blank" in r.output


def test_report_is_in_cad_whatever_the_base_currency(tracker, store, fake):
    tracker.config.base_currency = "USD"
    acct = store.add_account(Account(name="Fictional USD", currency="USD"))
    trade(store, acct, TxnType.BUY, "2024-03-04", "FICTUS", 1000, 100, "USD")
    fake.set_history("USDCAD=X", {"2024-02-20": 1.3}, currency="CAD")
    (y,) = tracker.foreign_property(2024)
    assert y.currency == "CAD" and y.max_cost == pytest.approx(130_000) and y.status == "simplified"
    # The capital gains report itself stays in the base currency.
    _, report = tracker.tax_years()
    assert report.pools["FICTUS"].acb == pytest.approx(100_000)


def test_desktop_tax_carries_foreign_property(tracker, ledger, store):
    payload = tax_report(tracker)
    json.dumps(payload, allow_nan=False)
    years = payload["foreign_property"]
    assert payload["version"] == 1 and [y["year"] for y in years][-2:] == [2025, 2024]
    y2024 = next(y for y in years if y["year"] == 2024)
    assert y2024["status"] == "simplified" and y2024["holdings"][0]["symbol"] == "FICTUS"
    # The app reloads the report when a setting changes, and only then.
    before = ledger_revision(tracker)
    store.upsert_asset(Asset("XFIC.TO", asset_class=AssetClass.ETF))
    assert ledger_revision(tracker) == before
    store.upsert_asset(Asset("XFIC.TO", asset_class=AssetClass.ETF, foreign_property=True))
    assert ledger_revision(tracker) != before


def _text(renderable) -> str:
    console = Console(file=io.StringIO(), width=400, record=True, theme=RichTheme(rich_styles(resolve_palette("auto"))))
    console.print(renderable)
    return console.export_text()


def test_tax_view_line():
    y = ForeignPropertyYear(2024, "2024-12-31", max_cost=130_000, max_cost_date="2024-03-04")
    older = ForeignPropertyYear(2023, "2023-12-31", max_cost=50_000, max_cost_date="2023-05-01", incomplete=True)
    assert render.foreign_property_line([]) is None
    line = _text(render.foreign_property_line([y, older]))
    assert "Foreign property (T1135), 2024: highest cost $130,000.00 on 2024-03-04" in line
    assert "simplified method" in line and "Estimate, not tax advice" in line
    line = _text(render.foreign_property_line([y, older], 2023))
    assert "T1135 not required" in line and "may be too low" in line
    assert "none in non-registered accounts" in _text(render.foreign_property_line([y], 2022))
    assert "130,000" not in _text(render.foreign_property_line([y], privacy=True))


def test_tui_tax_workspace_shows_the_line(tracker, ledger):
    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=(180, 52)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.action_workspace("tax")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._tax is not None
            assert [y.year for y in app._tax[3]][-2:] == [2025, 2024]
            app.tax_year = 2024
            app.render_tax()
            return _text(app.query_one("#tax-view", Static).content)

    shown = asyncio.run(scenario())
    assert "Foreign property (T1135), 2024: highest cost $130,000.00" in shown
