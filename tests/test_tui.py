"""Headless TUI smoke tests against the fake market."""

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import replace
from threading import Event
from unittest.mock import patch

import pytest
from textual.widgets import DataTable, Input, Static, Switch

from marketpulse import fmt
from marketpulse.db import Store
from marketpulse.market import MarketError
from marketpulse.models import Account, AccountType, Asset, AssetKind, Transaction, TxnType
from marketpulse.tax import TaxReport
from marketpulse.tui import chart, extras
from marketpulse.tui.app import MarketPulseApp
from marketpulse.tui.screens import AccountForm, ConfirmScreen, PromptScreen, TransactionForm, input_number
from marketpulse.tui.widgets import WORKSPACES, ChartView, TopBar, big_text, big_width


def run(coro):
    return asyncio.run(coro)


def test_every_workspace_renders_and_a_buy_can_be_recorded(tracker, store):
    acct = store.add_account(Account(name="Main"))
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.BUY,
            date="2024-01-02",
            symbol="XEQT.TO",
            quantity=10,
            price=30,
            currency="CAD",
        )
    )
    store.add_watch(["AAPL"])

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=(170, 50)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view is not None and app.view.net_worth == 400
            for i, (key, _label) in enumerate(WORKSPACES, 1):
                await pilot.press(str(i))
                await pilot.pause()
                assert app.workspace == key
            # The tax workspace loads its report in a worker: make sure it
            # finished and rendered with the pooled-ACB report shape.
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._tax is not None and isinstance(app._tax[1], TaxReport)
            await pilot.press("2")
            await pilot.press("b")
            await pilot.pause()
            form = app.screen
            assert isinstance(form, TransactionForm)
            form.query_one("#f-symbol").value = "AAPL"
            form.query_one("#f-quantity").value = "3"
            form.query_one("#f-price").value = "150"
            form.action_save()
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

    run(scenario())
    bought = [t for t in store.transactions() if t.symbol == "AAPL"]
    assert len(bought) == 1 and bought[0].quantity == 3 and bought[0].currency == "USD"


def test_tax_workspace_shows_unavailable_room_when_fx_is_missing(tracker, store):
    rrsp = store.add_account(Account(name="Fictional RRSP", type=AccountType.RRSP))
    store.set_room("RRSP", 2025, 7000)
    store.add_transaction(Transaction(rrsp.saved_id, TxnType.DEPOSIT, "2025-01-03", amount=100, currency="USD"))

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.press("7")
            await app.workers.wait_for_complete()
            await pilot.pause()
            with app.console.capture() as capture:
                app.console.print(app.query_one("#tax-view", Static).content, width=80)
            output = capture.get()
            assert "Unavailable" in output and "USD on 2025-01-03" in output, output

    run(scenario())


def test_privacy_and_theme_cycling_persist(tracker):
    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.press("p")
            await pilot.press("t")
            await pilot.pause()
            return app.theme

    theme = run(scenario())
    assert tracker.config.privacy is True
    assert theme != "tokyo-night" and tracker.config.theme == theme


def test_csv_export_keeps_unicode_account_names(tracker, store, tmp_path):
    name = "Fictional é 東京"
    acct = store.add_account(Account(name=name))
    store.add_transaction(Transaction(account_id=acct.saved_id, type=TxnType.DEPOSIT, amount=100))
    target = tmp_path / "ledger.csv"

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=(140, 40)) as pilot:
            await app.workers.wait_for_complete()
            app.action_export_csv()
            await pilot.pause()
            assert isinstance(app.screen, PromptScreen)
            app.screen.query_one("#p-input").value = str(target)
            app.screen.action_save()
            await pilot.pause()

    run(scenario())
    assert name.encode("utf-8") in target.read_bytes()


def test_big_digits():
    assert big_width("$1,234") == len(big_text("$1,234", "x").plain.split("\n")[0])
    assert big_width("1,234 SEK") == len(big_text("1,234 SEK", "x").plain.split("\n")[0])
    assert big_text("12", "x").plain.count("\n") == 2


def test_clock_tick_during_shutdown(tracker, monkeypatch):
    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        close_all = app._close_all

        async def close_all_with_pending_tick():
            await close_all()
            assert not app.is_running
            # Force the CI race: widgets are gone, but the app's timers have
            # not yet been stopped by _close_messages().
            app._tick()

        monkeypatch.setattr(app, "_close_all", close_all_with_pending_tick)
        async with app.run_test(size=(140, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            with patch.object(app.query_one(TopBar), "refresh") as refresh:
                app._tick()
                refresh.assert_called_once_with()

    run(scenario())


def test_income_forecast_survives_refresh_and_deletes_confirm(tracker, store, monkeypatch):
    monkeypatch.setattr(tracker, "trailing_dividends", lambda symbols: {"AAPL": 2.70})
    acct = store.add_account(Account(name="Main"))
    store.add_transaction(
        Transaction(account_id=acct.id, type=TxnType.BUY, date="2024-01-02", symbol="AAPL", quantity=1, price=100)
    )
    store.add_watch(["AAPL", "XEQT.TO"])

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=(170, 50)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("6")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._income_forecast is not None
            assert app._income_forecast[0].quantity == 1
            old_amount = fmt.money(app._income_forecast[0].annual_base, app.view.base)
            assert old_amount in extras.pane_text(app, "#income-view")

            store.add_transaction(Transaction(acct.saved_id, TxnType.BUY, "2024-01-03", "AAPL", 1, 100, currency="USD"))
            started, release = Event(), Event()
            valuation = tracker.valuation

            def delayed_valuation(**kwargs):
                started.set()
                assert release.wait(10)
                return valuation(**kwargs)

            with patch.object(tracker, "valuation", side_effect=OSError("Fictional valuation failure")):
                await pilot.press("r")
                await app.workers.wait_for_complete()
                await pilot.press("1", "6")
                await app.workers.wait_for_complete()
                assert "NEXT 12M EST." not in extras.pane_text(app, "#income-view")
                assert "Press r to retry" in extras.pane_text(app, "#income-hint")

            with patch.object(tracker, "valuation", delayed_valuation):
                try:
                    await pilot.press("r")
                    assert await asyncio.to_thread(started.wait, 5)
                    assert old_amount not in extras.pane_text(app, "#income-view")
                    await pilot.press("1", "6")
                    report = extras.pane_text(app, "#income-view")
                    assert "LAST 12 MONTHS" in report and "NEXT 12M EST." not in report
                    assert old_amount not in report
                finally:
                    release.set()
                await app.workers.wait_for_complete()
                await pilot.pause()
            assert app._income_forecast[0].quantity == 2
            report = extras.pane_text(app, "#income-view")
            assert "NEXT 12M EST." in report and fmt.money(app._income_forecast[0].annual_base, app.view.base) in report

            await pilot.press("3")
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("n")
            await pilot.pause()
            assert store.watchlist() == ["AAPL", "XEQT.TO"]
            await pilot.press("x")
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            assert store.watchlist() == ["XEQT.TO"]

    run(scenario())


def test_account_archive_toggle_and_manual_value_validation(tracker, store):
    acct = store.add_account(Account(name="Main"))
    store.upsert_asset(Asset("COTTAGE", kind=AssetKind.MANUAL, name="Cottage"))
    store.add_transaction(
        Transaction(account_id=acct.id, type=TxnType.BUY, date="2024-01-02", symbol="COTTAGE", quantity=1, price=500000)
    )

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=(170, 50)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("7")
            await pilot.pause()
            app.action_edit()
            await pilot.pause()
            form = app.screen
            assert isinstance(form, AccountForm)
            form.query_one("#a-archived").value = True
            form.action_save()
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert store.get_account(acct.id).archived is True

            app.action_value_asset()
            await pilot.pause()
            assert isinstance(app.screen, PromptScreen)
            app.screen.dismiss("COTTAGE -5")
            await pilot.pause()
            assert not [t for t in store.transactions() if t.type is TxnType.VALUATION]
            app.action_value_asset()
            await pilot.pause()
            app.screen.dismiss("COTTAGE 600000")
            await pilot.pause()
            await app.workers.wait_for_complete()
            marks = [t for t in store.transactions() if t.type is TxnType.VALUATION]
            assert len(marks) == 1 and marks[0].price == 600000

    run(scenario())


@pytest.mark.parametrize("editing", [False, True], ids=["create", "edit"])
def test_account_form_keeps_values_after_failed_save_and_retries(tracker, store, editing):
    original = store.add_account(Account(name="Original account"))

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("7")
            await app.workers.wait_for_complete()
            await pilot.press("e" if editing else "n")
            form = app.screen
            assert isinstance(form, AccountForm)
            name = form.query_one("#a-name", Input)
            institution = form.query_one("#a-institution", Input)
            cash = form.query_one("#a-cash", Switch)
            name.value = "Fictional account"
            institution.value = "Fictional institution"
            cash.value = True

            with patch.object(store, "_exec", side_effect=sqlite3.OperationalError("database is locked")):
                await pilot.press("ctrl+s")

            assert app.screen is form
            error = form.query_one("#form-error", Static)
            assert "database is locked" in str(error.content) and "try saving again" in str(error.content)
            assert form.query_one(".modal").scrollable_content_region.contains_region(error.region)
            assert (name.value, institution.value, cash.value) == ("Fictional account", "Fictional institution", True)
            assert store.accounts() == [original]

            await pilot.press("ctrl+s")
            await app.workers.wait_for_complete()
            assert app.screen is not form
            saved = store.get_account("Fictional account")
            assert saved is not None and saved.institution == "Fictional institution" and saved.track_cash
            assert len(store.accounts()) == (1 if editing else 2)
            assert (saved.id == original.id) == editing

    run(scenario())


def test_account_form_preserves_concurrent_edit(tracker, store):
    original = store.add_account(Account(name="Original account"))
    concurrent = replace(original, name="Changed elsewhere")

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("7", "e")
            await app.workers.wait_for_complete()
            form = app.screen
            assert isinstance(form, AccountForm)
            name = form.query_one("#a-name", Input)
            name.value = "Pending edit"
            with closing(Store(store.path)) as other:
                other.update_account(concurrent)

            await pilot.press("ctrl+s")
            assert app.screen is form and name.value == "Pending edit"
            assert "reopen the form" in str(form.query_one("#form-error", Static).content)
            assert store.accounts() == [concurrent]

    run(scenario())


def test_short_transaction_form_scrolls_to_validation_error(tracker):
    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("2", "b")
            form = app.screen
            assert isinstance(form, TransactionForm)
            modal = form.query_one(".modal")
            assert modal.max_scroll_y > 0
            await pilot.press("ctrl+s")
            await pilot.pause()
            error = form.query_one("#form-error")
            assert str(error.content)
            assert modal.scrollable_content_region.contains_region(error.region)
            await pilot.press("escape")
            assert app.screen is not form

    run(scenario())


def test_terminal_numeric_input_preserves_decimal_magnitude():
    assert input_number("1,234.50") == 1234.5
    assert input_number("1.5") == 1.5
    for invalid in ("1,5", "1,23,456", ",", "1.2,345", "1_5", "1_000.5", "nan", "inf", "1e999"):
        with pytest.raises(ValueError):
            input_number(invalid)


def test_private_manual_price_and_full_activity_search_on_compact_terminal(tracker, store):
    account = store.add_account(Account(name="Fictional Property"))
    store.upsert_asset(Asset(symbol="ART-QA", name="Painting", kind=AssetKind.MANUAL))
    store.add_transaction(
        Transaction(
            account.saved_id,
            TxnType.BUY,
            "2024-01-02",
            "ART-QA",
            1,
            65432.10,
            currency="CAD",
            note="Fictional acquisition details beyond column width",
        )
    )
    store.add_transaction(Transaction(account.saved_id, TxnType.BUY, "2024-01-02", "AAPL", 1, 12345.67, currency="USD"))
    tracker.config.privacy = True

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            dashboard = app.query_one("#dashboard")
            assert app.focused is dashboard and dashboard.scroll_y == 0
            assert dashboard.scrollable_content_region.contains_region(app.query_one("#tiles").region)
            await pilot.press("pagedown")
            await pilot.wait_for_scheduled_animations()
            assert dashboard.scroll_y > 0
            await pilot.press("home")
            await pilot.wait_for_scheduled_animations()
            assert dashboard.scroll_y == 0
            assert app.query_one("#dash-side").display
            await pilot.press("2")
            holdings = app.query_one("#holdings-table", DataTable)
            for index in range(holdings.row_count):
                holdings.move_cursor(row=index)
                title, rows = extras.row_details(app)
                details = dict(rows)
                assert details["Average cost"] == fmt.MASK
                position = next(p for p in app.view.positions if title.startswith(p.symbol + " ·"))
                assert details["Price"] == (fmt.price(position.price) if position.symbol == "AAPL" else fmt.MASK)
                cells = " ".join(str(cell) for cell in holdings.get_row_at(index))
                assert "65,432" not in cells and "12,345" not in cells
            await pilot.press("5")
            app.query_one("#activity-filter", Input).value = "beyond column width"
            await pilot.pause()
            activity = app.query_one("#activity-table", DataTable)
            assert activity.row_count == 1
            assert "65,432" not in " ".join(str(cell) for cell in activity.get_row_at(0))
            await pilot.press("7")
            assert app.query_one("#tax-view").size.width > 60

    run(scenario())


def test_failed_workspace_loads_offer_a_retry(tracker):
    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            for key, section, method, selector in [
                ("6", "income", "income_forecast", "#income-hint"),
                ("7", "tax", "tax_years", "#tax-view"),
            ]:
                with patch.object(tracker, method, side_effect=OSError("Fictional read failure")):
                    await pilot.press(key)
                    await app.workers.wait_for_complete()
                    await pilot.pause()
                    assert "Press r to retry" in str(app.query_one(selector).content)
                    if section == "income":
                        with app.console.capture() as report:
                            app.console.print(app.query_one("#income-view").content)
                        assert "LAST 12 MONTHS" in report.get()
                await pilot.press("r")
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert section not in app.load_errors
                assert "Press r to retry" not in str(app.query_one(selector).content)

    run(scenario())


def test_terminal_save_confirmation_lookup_failure_is_safe_to_retry(tracker, store):
    account = store.add_account(Account(name="Fictional"))
    deposit = Transaction(account.saved_id, TxnType.DEPOSIT, amount=125, currency="CAD")

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            with patch.object(store, "get_account", side_effect=sqlite3.OperationalError("Fictional read error")):
                with patch.object(app, "notify") as notify:
                    await app.save_txn(deposit).wait()
                    notify.assert_called_once_with("Fictional read error", title="Not saved", severity="error")
            assert store.transactions() == []
            await app.save_txn(deposit).wait()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(store.transactions()) == 1

    run(scenario())


@pytest.mark.parametrize("section, key, method", [("tax", "7", "tax_years"), ("income", "6", "income_forecast")])
def test_workspace_retry_ignores_late_failure(tracker, section, key, method):
    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        started, release, finished = Event(), Event(), Event()
        original = getattr(tracker, method)

        def delayed(*args):
            if not started.is_set():
                started.set()
                assert release.wait(10)
                raise OSError("Fictional stale error")
            return original(*args)

        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            run_worker = app.run_worker

            def track_thread(work, **options):
                if options.get("group") == section and not started.is_set():

                    def first_attempt():
                        try:
                            work()
                        finally:
                            finished.set()

                    return run_worker(first_attempt, **options)
                return run_worker(work, **options)

            with patch.object(tracker, method, delayed), patch.object(app, "run_worker", track_thread):
                try:
                    await pilot.press(key)
                    assert await asyncio.to_thread(started.wait, 5)
                    await pilot.press("r")
                    await app.workers.wait_for_complete()
                    assert (app._tax if section == "tax" else app._income_forecast) is not None
                finally:
                    release.set()
                assert await asyncio.to_thread(finished.wait, 5)
                assert section not in app.load_errors

    run(scenario())


def test_income_history_waits_for_a_new_valuation_after_a_write(tracker, store):
    account = store.add_account(Account(name="Fictional income"))
    store.add_transaction(Transaction(account.saved_id, TxnType.INTEREST, amount=11, currency="CAD"))

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("6")
            await app.workers.wait_for_complete()
            assert "$11.00" in extras.pane_text(app, "#income-view")
            with patch.object(tracker, "valuation", side_effect=OSError("Fictional reload failure")):
                await app.save_txn(Transaction(account.saved_id, TxnType.INTEREST, amount=17, currency="CAD")).wait()
                await app.workers.wait_for_complete()
                await pilot.press("1", "6")
                assert "$11.00" not in extras.pane_text(app, "#income-view")
                assert "Press r to retry" in extras.pane_text(app, "#income-hint")
            await pilot.press("r")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "$28.00" in extras.pane_text(app, "#income-view")

    run(scenario())


def test_detail_history_can_retry_after_bad_provider_response(tracker, fake):
    fake.set_history("AAPL", {"2024-01-02": 100.0})

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test():
            await app.workers.wait_for_complete()
            bars = tracker.market.history("AAPL", "3mo")
            with patch.object(tracker.market, "history", side_effect=[ValueError("Bad response"), bars]) as history:
                app.load_detail_bars("AAPL")
                await app.workers.wait_for_complete()
                assert "AAPL" not in app._detail_bars
                app.load_detail_bars("AAPL")
                app.load_detail_bars("AAPL")
                await app.workers.wait_for_complete()
                assert history.call_count == 2 and app._detail_bars["AAPL"] == bars

    run(scenario())


def test_income_shows_first_portfolio_failure_and_recovers(tracker):
    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        started, release = Event(), Event()
        valuation = tracker.valuation

        def fail_once(**kwargs):
            if started.is_set():
                return valuation(**kwargs)
            started.set()
            assert release.wait(10)
            raise OSError("Fictional first load failure")

        with patch.object(tracker, "valuation", fail_once):
            async with app.run_test() as pilot:
                try:
                    assert await asyncio.to_thread(started.wait, 5)
                    await pilot.press("6")
                    assert app.workspace == "income" and app.view is None
                finally:
                    release.set()
                await app.workers.wait_for_complete()
                assert "Press r to retry" in extras.pane_text(app, "#income-hint")
                await pilot.press("1", "6")
                assert "Press r to retry" in extras.pane_text(app, "#income-hint")
                await pilot.press("r")
                await app.workers.wait_for_complete()
                assert "Press r to retry" not in extras.pane_text(app, "#income-hint")
                assert "LAST 12 MONTHS" in extras.pane_text(app, "#income-view")

    run(scenario())


def test_cancelled_chart_cannot_replace_a_retry_with_the_same_settings(tracker, fake):
    fake.set_history("AAPL", {"2024-01-02": 100.0})

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        started, release, finished = Event(), Event(), Event()
        history = tracker.market.history
        load = chart._load_chart

        def delayed(*args):
            if not started.is_set():
                started.set()
                assert release.wait(10)
                raise MarketError("Fictional late chart failure")
            return history(*args)

        def track(app, view):
            first = not started.is_set()
            try:
                load(app, view)
            finally:
                if first:
                    finished.set()

        async with app.run_test():
            await app.workers.wait_for_complete()
            with patch.object(tracker.market, "history", delayed), patch.object(chart, "_load_chart", track):
                try:
                    app.open_chart("AAPL")
                    assert await asyncio.to_thread(started.wait, 5)
                    view = app.query_one(ChartView)
                    await app._load_chart(view).wait()
                    assert view.bars and view.symbol == "AAPL"
                finally:
                    release.set()
                assert await asyncio.to_thread(finished.wait, 5)
                assert view.bars and view.message != "Fictional late chart failure"

    run(scenario())
