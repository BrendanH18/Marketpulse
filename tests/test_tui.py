"""Headless TUI smoke tests against the fake market."""

import asyncio

from marketpulse.models import Account, Asset, AssetKind, Transaction, TxnType
from marketpulse.tui.app import MarketPulseApp
from marketpulse.tui.screens import AccountForm, ConfirmScreen, PromptScreen, TransactionForm
from marketpulse.tui.widgets import WORKSPACES, big_text, big_width


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


def test_big_digits():
    assert big_width("$1,234") == len(big_text("$1,234", "x").plain.split("\n")[0])
    assert big_width("1,234 SEK") == len(big_text("1,234 SEK", "x").plain.split("\n")[0])
    assert big_text("12", "x").plain.count("\n") == 2


def test_income_forecast_survives_refresh_and_deletes_confirm(tracker, store):
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
            await pilot.press("r")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._income_forecast is not None, "refresh must reload the forecast, not drop it"

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
