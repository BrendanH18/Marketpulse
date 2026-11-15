"""Headless checks for the 15 terminal app improvements in #153 (docs/tui-thousand-improvements.md).

Every ledger here is fictional. Prices come from the fake market in conftest: AAPL 200 USD
(up from 190), XEQT.TO 40 CAD (down from 40.5) and USDCAD 1.35; ZZZQ has no quote at all.
"""

import asyncio
from datetime import date

from textual.widgets import DataTable, Input, Label, Static

from marketpulse import fmt
from marketpulse.models import Account, AccountType, Alert, Transaction, TxnType
from marketpulse.tui import chart, navigation
from marketpulse.tui.app import MarketPulseApp
from marketpulse.tui.commands import PortfolioCommands
from marketpulse.tui.screens import HelpScreen, ProblemsScreen, PromptScreen, TransactionForm, WorkspaceKeysScreen

SIZE = (180, 52)


def run(coro):
    return asyncio.run(coro)


def seed(store, watch=("XEQT.TO", "AAPL")):
    """Birch TFSA tracks cash: $5,000 in, 100 XEQT.TO bought, $2,000 left. Cedar Margin holds AAPL and
    a little XEQT.TO and was paid one AAPL dividend. Aspen RRSP is empty."""
    birch = store.add_account(Account(name="Birch TFSA", type=AccountType.TFSA, track_cash=True))
    cedar = store.add_account(Account(name="Cedar Margin", type=AccountType.MARGIN))
    aspen = store.add_account(Account(name="Aspen RRSP", type=AccountType.RRSP))
    rows = [
        Transaction(birch.saved_id, TxnType.DEPOSIT, "2024-01-01", amount=5000, currency="CAD"),
        Transaction(birch.saved_id, TxnType.BUY, "2024-01-02", "XEQT.TO", 100, 30, currency="CAD"),
        Transaction(cedar.saved_id, TxnType.BUY, "2024-02-01", "AAPL", 10, 150, currency="USD"),
        Transaction(cedar.saved_id, TxnType.BUY, "2024-03-01", "XEQT.TO", 5, 42, currency="CAD"),
        Transaction(cedar.saved_id, TxnType.DIVIDEND, "2024-04-01", "AAPL", amount=2.4, currency="USD"),
    ]
    saved = [store.add_transaction(t) for t in rows]
    store.add_watch(list(watch))
    return birch, cedar, aspen, saved


async def started(app, pilot):
    await app.workers.wait_for_complete()
    await pilot.pause()


def keys(table: DataTable) -> list[str]:
    return [k.value for k in table.rows]


def subtitle(app, pane: str) -> str:
    return app.query_one(pane).border_subtitle


def messages(app) -> list[str]:
    return [str(n.message) for n in app._notifications]


def select(table: DataTable, key: str) -> None:
    table.move_cursor(row=table.get_row_index(key), animate=False)


# 1 ─ watchlist sorting ───────────────────────────────────────────────────────


def test_watchlist_sorts_by_symbol_and_day_change(tracker, store):
    seed(store, watch=("XEQT.TO", "AAPL", "ZZZQ"))

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("3")
            table = app.query_one("#watch-table", DataTable)
            assert keys(table) == ["XEQT.TO", "AAPL", "ZZZQ"]  # the saved list order
            await pilot.press("o")
            assert keys(table) == ["AAPL", "XEQT.TO", "ZZZQ"]
            assert "sort symbol ↑" in subtitle(app, "#pane-watch")
            await pilot.press("o")  # day %, biggest gain first; no quote stays last
            assert keys(table) == ["AAPL", "XEQT.TO", "ZZZQ"]
            await pilot.press("O")
            assert keys(table) == ["XEQT.TO", "AAPL", "ZZZQ"]
            assert "sort day % ↑" in subtitle(app, "#pane-watch")
            await pilot.press("J")  # reordering a sorted view would be invisible: refused
            assert store.watchlist() == ["XEQT.TO", "AAPL", "ZZZQ"]
            assert any("J / K reorder" in m for m in messages(app))
            await pilot.press("o")  # back to the list order, where J moves the row
            assert keys(table) == ["XEQT.TO", "AAPL", "ZZZQ"] and "sort" not in subtitle(app, "#pane-watch")
            await pilot.press("J")
            assert store.watchlist() == ["AAPL", "XEQT.TO", "ZZZQ"]

    run(scenario())


# 2 ─ accounts sorting ────────────────────────────────────────────────────────


def test_accounts_sort_by_name_type_and_value(tracker, store):
    birch, cedar, aspen, _ = seed(store)
    b, c, a = str(birch.id), str(cedar.id), str(aspen.id)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("7")
            table = app.query_one("#accounts-table", DataTable)
            assert keys(table) == [b, c, a]  # by id, as before
            await pilot.press("o")
            assert keys(table) == [a, b, c]  # Aspen, Birch, Cedar
            await pilot.press("o")  # type label: Margin, RRSP, TFSA
            assert keys(table) == [c, a, b]
            await pilot.press("o")  # value, largest first: Birch $6,000, Cedar $2,900, Aspen has none
            assert keys(table) == [b, c, a]
            await pilot.press("O")
            assert keys(table) == [c, b, a]  # an account without a value stays last
            assert subtitle(app, "#pane-accts") == "3 accounts · sort value ↑"
            assert app._selected_key(table) == b  # the cursor follows its row through every sort
            await pilot.press("less_than_sign", "enter")  # enter still opens that account's holdings
            assert app.workspace == "holdings" and app.account_filter == cedar.id

    run(scenario())


# 3 ─ alerts sorting ──────────────────────────────────────────────────────────


def seed_alerts(store):
    ids = [
        store.add_alert(Alert("AAPL", "above", 500)).id,  # armed
        store.add_alert(Alert("XEQT.TO", "below", 10, active=False)).id,  # paused
        store.add_alert(Alert("AAPL", "above", 100)).id,  # AAPL is at 200: triggers on the first refresh
    ]
    return [str(i) for i in ids]


def test_alerts_sort_by_id_and_state(tracker, store):
    seed(store)
    armed, paused, fired = seed_alerts(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("8")
            table = app.query_one("#alerts-table", DataTable)
            assert keys(table) == [armed, fired, paused]  # by symbol, then id, as before
            await pilot.press("o")
            assert keys(table) == [armed, paused, fired]
            await pilot.press("o")  # state: triggered, armed, paused
            assert keys(table) == [fired, armed, paused]
            await pilot.press("O")
            assert keys(table) == [paused, armed, fired]
            assert "sort state ↓" in subtitle(app, "#pane-alerts")

    run(scenario())


# 4 ─ duplicate a transaction ─────────────────────────────────────────────────


def test_duplicate_transaction_prefills_a_new_entry_dated_today(tracker, store):
    _birch, cedar, _aspen, saved = seed(store)
    aapl_buy = saved[2]

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("d")  # nothing to duplicate on the dashboard
            assert not isinstance(app.screen, TransactionForm)
            assert any("to duplicate it" in m for m in messages(app))
            await pilot.press("5")
            select(app.query_one("#activity-table", DataTable), str(aapl_buy.id))
            await pilot.press("d")
            await pilot.pause()
            form = app.screen
            assert isinstance(form, TransactionForm)
            assert str(form.query_one(".modal-title", Label).content) == "New transaction"
            assert form.kind is TxnType.BUY and form.account_id == cedar.id
            assert form.query_one("#f-symbol", Input).value == "AAPL"
            assert form.query_one("#f-quantity", Input).value == "10"
            assert form.query_one("#f-price", Input).value == "150"
            assert form.query_one("#f-date", Input).value == date.today().isoformat()
            form.action_save()
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not isinstance(app.screen, TransactionForm)

            cedar.archived = True  # its entries stay listed, but can't gain a copy
            store.update_account(cedar)
            app.render_activity()
            select(app.query_one("#activity-table", DataTable), str(aapl_buy.id))
            await pilot.press("d")
            assert not isinstance(app.screen, TransactionForm)
            assert any("Cedar Margin is archived" in m for m in messages(app))

    run(scenario())
    buys = [t for t in store.transactions() if t.symbol == "AAPL" and t.type is TxnType.BUY]
    assert len(buys) == 2
    original = next(t for t in buys if t.id == aapl_buy.id)
    copy = next(t for t in buys if t.id != aapl_buy.id)
    assert original.date == "2024-02-01"
    assert (copy.account_id, copy.quantity, copy.price, copy.currency) == (cedar.id, 10, 150, "USD")
    assert copy.date == date.today().isoformat()


def test_duplicate_and_edit_keep_every_digit_of_the_saved_numbers(tracker, store):
    birch = store.add_account(Account(name="Birch TFSA", type=AccountType.TFSA, track_cash=True))
    deposit = store.add_transaction(Transaction(birch.saved_id, TxnType.DEPOSIT, "2024-01-01", amount=12345.67))
    buy = store.add_transaction(
        Transaction(birch.saved_id, TxnType.BUY, "2024-01-02", "XEQT.TO", 123.456789, 30.123456, fees=9.99)
    )

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("5")
            for txn in (buy, deposit):
                select(app.query_one("#activity-table", DataTable), str(txn.id))
                await pilot.press("d")
                await pilot.pause()
                form = app.screen
                assert isinstance(form, TransactionForm)
                form.action_save()
                await pilot.pause()
                await app.workers.wait_for_complete()
                await pilot.pause()
            select(app.query_one("#activity-table", DataTable), str(buy.id))
            await pilot.press("e")
            await pilot.pause()
            form = app.screen
            assert isinstance(form, TransactionForm)
            assert form.query_one("#f-quantity", Input).value == "123.456789"
            assert form.query_one("#f-price", Input).value == "30.123456"
            assert form.query_one("#f-fees", Input).value == "9.99"

    run(scenario())
    buys = [t for t in store.transactions() if t.type is TxnType.BUY]
    deposits = [t for t in store.transactions() if t.type is TxnType.DEPOSIT]
    assert sorted((t.quantity, t.price, t.fees) for t in buys) == [(123.456789, 30.123456, 9.99)] * 2
    assert [t.amount for t in deposits] == [12345.67, 12345.67]


# 5 ─ problems overlay ────────────────────────────────────────────────────────


def test_problems_overlay_lists_ledger_issues_and_unpriced_positions(tracker, store):
    birch, cedar, _aspen, _saved = seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("exclamation_mark")
            assert isinstance(app.screen, ProblemsScreen)
            body = str(app.screen.query_one("#problems", Static).content)
            assert body.startswith("No problems")
            await pilot.press("exclamation_mark")  # ! closes it again
            assert not isinstance(app.screen, ProblemsScreen)

            # A sell of more than Cedar holds, and a holding the market has no price for.
            oversell = store.add_transaction(
                Transaction(cedar.saved_id, TxnType.SELL, "2024-05-01", "XEQT.TO", 50, 41, currency="CAD")
            )
            store.add_transaction(Transaction(birch.saved_id, TxnType.BUY, "2024-05-02", "ZZZQ", 1, 10, currency="CAD"))
            app.after_change()
            await started(app, pilot)
            await pilot.press("5")
            assert "⚠ 1 ledger issue(s) (! lists them)" in subtitle(app, "#pane-activity")
            await pilot.press("exclamation_mark")
            body = str(app.screen.query_one("#problems", Static).content)
            assert f"Ledger issues (1)\n  2024-05-01  #{oversell.id}  Sell of 50.0000 XEQT.TO exceeds" in body
            left_out = body.split("Left out of net worth (1)\n")[1].split("\n")[0]
            assert "ZZZQ" in left_out
            assert "Quotes unavailable (1)\n  ZZZQ: " in body
            await pilot.press("escape")
            assert not isinstance(app.screen, ProblemsScreen)

    run(scenario())


# 6 ─ trades from activity use the selected entry's account ───────────────────


def test_trade_keys_in_activity_prefill_the_selected_entrys_account(tracker, store):
    birch, cedar, _aspen, saved = seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("5")
            table = app.query_one("#activity-table", DataTable)
            select(table, str(saved[3].id))  # Cedar's XEQT.TO buy
            await pilot.press("b")
            await pilot.pause()
            form = app.screen
            assert isinstance(form, TransactionForm)
            assert form.account_id == cedar.id and form.symbol == "XEQT.TO"
            await pilot.press("escape")
            select(table, str(saved[0].id))  # Birch's deposit
            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, TransactionForm) and app.screen.account_id == birch.id

    run(scenario())


# 7 ─ no-match states say how to clear the filter ─────────────────────────────


def test_no_match_states_say_escape_clears(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("F", "q", "q", "q")
            await pilot.pause()
            assert "f ▸ all accounts · no match — escape clears" in subtitle(app, "#pane-holdings")
            await pilot.press("escape")
            await pilot.pause()
            assert "no match" not in subtitle(app, "#pane-holdings")
            await pilot.press("5", "slash", "q", "q", "q")
            await pilot.pause()
            assert subtitle(app, "#pane-activity") == "0 of 5 transactions · no match — escape clears"
            await pilot.press("escape")
            await pilot.pause()
            assert "no match" not in subtitle(app, "#pane-activity")

    run(scenario())


# 8 ─ a lone "=" in the activity filter no longer hides every symbol ──────────


def test_lone_equals_in_activity_filter_shows_everything(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("5", "slash", "equals_sign")
            await pilot.pause()
            table = app.query_one("#activity-table", DataTable)
            assert app.query_one("#activity-filter", Input).value == "="
            assert table.row_count == 5  # before the fix: only the deposit, the one entry without a symbol
            await pilot.press("A", "A", "P", "L")
            await pilot.pause()
            assert table.row_count == 2  # =AAPL: its buy and dividend

    run(scenario())


# 9 ─ watchlist footer counts ─────────────────────────────────────────────────


def test_watchlist_footer_counts_risers_fallers_and_missing(tracker, store):
    seed(store, watch=("XEQT.TO", "AAPL", "ZZZQ"))

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            assert subtitle(app, "#pane-watch") == "3 symbols · 1 up · 1 down · 1 unavailable"
            app.watch_symbols = ["AAPL"]
            app.render_watchlist()
            assert subtitle(app, "#pane-watch") == "1 symbol · 1 up · 0 down"

    run(scenario())


# 10 ─ alerts footer counts triggered alerts ──────────────────────────────────


def test_alerts_footer_counts_triggered(tracker, store):
    seed(store)
    seed_alerts(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("8")
            assert subtitle(app, "#pane-alerts") == "2 armed of 3 · 1 triggered"

    run(scenario())


# 11 ─ activity footer shows the dates the listed entries span ────────────────


def test_activity_footer_shows_date_span(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("5")
            assert subtitle(app, "#pane-activity") == "5 of 5 transactions · 2024-01-01 → 2024-04-01"
            box = app.query_one("#activity-filter", Input)
            box.value = "=AAPL"
            await pilot.pause()
            assert subtitle(app, "#pane-activity") == "2 of 5 transactions · 2024-02-01 → 2024-04-01"
            box.value = "deposit"
            await pilot.pause()
            assert subtitle(app, "#pane-activity") == "1 of 5 transactions · 2024-01-01"

    run(scenario())


# 12 ─ copy the whole table ───────────────────────────────────────────────────


def test_ctrl_y_copies_the_table_with_headers(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            app.copy_to_clipboard("unchanged")
            await pilot.press("ctrl+y")  # the dashboard has no table
            assert app.clipboard == "unchanged"
            await pilot.press("2", "ctrl+y")
            lines = app.clipboard.split("\n")
            assert lines[0].split("\t")[:3] == ["Account", "Symbol", "Qty"]
            assert [line.split("\t")[1] for line in lines[1:]] == ["XEQT.TO", "AAPL", "XEQT.TO", "CASH"]
            assert lines[1].startswith("Birch TFSA\tXEQT.TO\t100")
            await pilot.press("5")
            app.query_one("#activity-filter", Input).value = "=AAPL"
            await pilot.pause()
            await pilot.press("p", "ctrl+y")  # filtered rows only, privacy masks included
            lines = app.clipboard.split("\n")
            assert len(lines) == 3 and lines[0].startswith("ID\tDate\tAccount\tType\tSymbol")
            assert all("\tAAPL\t" in line for line in lines[1:]) and fmt.MASK in lines[1]

    run(scenario())


# 13 ─ hide cash rows ─────────────────────────────────────────────────────────


def test_dollar_sign_hides_and_shows_cash_rows(tracker, store):
    birch, *_ = seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            table = app.query_one("#holdings-table", DataTable)
            await pilot.press("dollar_sign")  # from anywhere: goes to holdings
            assert app.workspace == "holdings"
            assert table.row_count == 3 and not [k for k in keys(table) if k.startswith("cash:")]
            assert subtitle(app, "#pane-holdings").endswith("cash hidden ($)")
            await pilot.press("1", "dollar_sign")
            assert app.workspace == "holdings" and f"cash:{birch.id}:CAD" in keys(table)
            assert "cash hidden" not in subtitle(app, "#pane-holdings")

    run(scenario())


# 14 ─ direct sort choices and the new actions in the command palette ─────────


def test_palette_sorts_directly_and_lists_new_actions(tracker, store):
    birch, cedar, aspen, _ = seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            sorts = {name: cb for name, _help, cb in PortfolioCommands._sort_actions(app)}
            assert len(sorts) == 6 + 5 + 3 + 4 + 3  # holdings, activity, watchlist, accounts, alerts
            assert {"Sort holdings by gain %", "Sort watchlist by day %", "Sort alerts by state"} <= set(sorts)
            sorts["Sort accounts by name"]()
            assert app.workspace == "tax" and app.table_sort["tax"] == ("name", False)
            assert keys(app.query_one("#accounts-table", DataTable)) == [str(aspen.id), str(birch.id), str(cedar.id)]
            more = {name: cb for name, _help, cb in PortfolioCommands._more_actions(app)}
            assert set(more) == {
                "Copy table",
                "Show or hide cash rows",
                "Duplicate selected transaction",
                "Show problems",
            }
            more["Show problems"]()
            await pilot.pause()
            assert isinstance(app.screen, ProblemsScreen)
            await pilot.press("escape")
            names = [name for name, _help, _cb in PortfolioCommands(app.screen)._entries()]
            assert "Sort holdings by value" in names and "Copy table" in names
            await pilot.press("ctrl+p")
            await pilot.pause()
            await pilot.press(*"sort holdings by value")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await pilot.pause()
            assert app.workspace == "holdings" and app.table_sort["holdings"] == ("value", True)
            assert "sort value ↓" in subtitle(app, "#pane-holdings")

    run(scenario())


# 15 ─ chart keys explain themselves when there's no chart ────────────────────


def test_chart_keys_explain_when_there_is_no_chart(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("2", "right_square_bracket")
            assert app.workspace == "holdings" and "[ and ] change the period on the chart workspace (4)" in messages(
                app
            )
            await pilot.press("4", "right_square_bracket")
            assert chart.NO_CHART in messages(app) and app.chart_period == "3mo"
            app.clear_notifications()
            await pilot.press("c")
            assert not isinstance(app.screen, PromptScreen) and messages(app) == [chart.NO_CHART]
            await pilot.press("C")
            assert "No comparisons to clear: c adds one on the chart" in messages(app)
            app.open_chart("AAPL")
            await pilot.press("c")  # with a chart open, c still asks what to compare
            assert isinstance(app.screen, PromptScreen)

    run(scenario())


# F1 and ? list the new keys ──────────────────────────────────────────────────


def test_f1_and_help_list_the_new_keys(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("5", "f1")
            assert isinstance(app.screen, WorkspaceKeysScreen)
            body = str(app.screen.query_one("#ws-keys", Static).content)
            assert "duplicate the entry, dated today" in body and "copy the whole table" in body
            assert "problems: ledger issues" in body
            await pilot.press("escape", "8", "f1")
            assert "sort column / reverse" in str(app.screen.query_one("#ws-keys", Static).content)
            await pilot.press("escape", "question_mark")
            assert isinstance(app.screen, HelpScreen)
            text = str(app.screen.query_one("VerticalScroll Static", Static).content)
            assert "show / hide cash rows in holdings" in text and "sort the current table / reverse" in text
            assert navigation.problems(app)[0] == ("Ledger issues", [])

    run(scenario())
