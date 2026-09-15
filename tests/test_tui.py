"""Headless TUI smoke tests against the fake market."""

import asyncio

from marketpulse.models import Account, Transaction, TxnType
from marketpulse.tui.app import MarketPulseApp
from marketpulse.tui.screens import TransactionForm
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
    assert big_text("12", "x").plain.count("\n") == 2
