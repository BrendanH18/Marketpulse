"""Headless checks for the TUI keyboard navigation and productivity additions (#130, items 81–100)."""

import asyncio
import time

from textual.widgets import DataTable, Input, Static

from marketpulse import fmt
from marketpulse.models import Account, AccountType, Transaction, TxnType
from marketpulse.tui import navigation
from marketpulse.tui.app import MarketPulseApp
from marketpulse.tui.commands import PortfolioCommands
from marketpulse.tui.screens import HelpScreen, TransactionForm, TxnTypeScreen, WorkspaceKeysScreen

SIZE = (180, 52)


def run(coro):
    return asyncio.run(coro)


def seed(store):
    """A fictional two-account ledger: Birch TFSA holds XEQT.TO and AAPL, Cedar Margin a little XEQT.TO."""
    birch = store.add_account(Account(name="Birch TFSA", type=AccountType.TFSA))
    cedar = store.add_account(Account(name="Cedar Margin"))
    rows = [
        (birch, TxnType.BUY, "2024-01-02", "XEQT.TO", 100, 30, "CAD"),
        (birch, TxnType.BUY, "2024-02-01", "AAPL", 10, 150, "USD"),
        (cedar, TxnType.BUY, "2024-03-01", "XEQT.TO", 5, 42, "CAD"),
    ]
    for acct, kind, day, sym, qty, price, ccy in rows:
        store.add_transaction(
            Transaction(
                account_id=acct.saved_id, type=kind, date=day, symbol=sym, quantity=qty, price=price, currency=ccy
            )
        )
    store.add_transaction(
        Transaction(account_id=birch.saved_id, type=TxnType.DIVIDEND, date="2024-04-01", symbol="AAPL", amount=2.4)
    )
    store.add_watch(["AAPL", "XEQT.TO"])
    return birch, cedar


async def started(app, pilot):
    await app.workers.wait_for_complete()
    await pilot.pause()


def keys(table: DataTable) -> list[str]:
    return [k.value for k in table.rows]


def hints(app) -> str:
    return str(app.query_one("#hints", Static).content)


def test_previous_workspace_and_cycling(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("backspace")  # 81: nothing earlier yet → stays put
            assert app.workspace == "dashboard"
            await pilot.press("2", "5", "backspace")
            assert app.workspace == "holdings"
            await pilot.press("backspace")  # toggles back
            assert app.workspace == "activity"
            await pilot.press("4", "backspace")  # works with the chart focused too
            assert app.workspace == "activity"
            await pilot.press("right_curly_bracket")  # 82
            assert app.workspace == "income"
            await pilot.press("left_curly_bracket", "left_curly_bracket")
            assert app.workspace == "chart"
            await pilot.press("1", "left_curly_bracket")  # wraps from the first to the last
            assert app.workspace == "alerts"
            await pilot.press("right_curly_bracket")
            assert app.workspace == "dashboard"

    run(scenario())


def test_row_keys_and_footer_position(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("2")
            table = app.query_one("#holdings-table", DataTable)
            assert table.row_count == 3 and table.cursor_row == 0
            assert "row 1/3" in hints(app)  # 88
            await pilot.press("j")  # 83
            assert table.cursor_row == 1
            await pilot.press("j", "j", "j")  # stops at the last row
            assert table.cursor_row == 2
            await pilot.press("k")
            assert table.cursor_row == 1
            await pilot.press("greater_than_sign")  # 84
            assert table.cursor_row == 2
            await pilot.pause()
            assert "row 3/3" in hints(app)
            await pilot.press("less_than_sign")
            assert table.cursor_row == 0
            await pilot.press("5", "greater_than_sign")
            activity = app.query_one("#activity-table", DataTable)
            assert activity.cursor_row == activity.row_count - 1 == 3
            await pilot.pause()
            assert "row 4/4" in hints(app)
            await pilot.press("1", "j", "less_than_sign")  # no table on the dashboard: harmless
            assert "row " not in hints(app)

    run(scenario())


def test_footer_shows_refresh_age(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        assert navigation.refresh_age(app) == ""
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            assert app.refreshed_at is not None
            assert "updated 0s ago" in hints(app) or "updated 1s ago" in hints(app)  # 89
            app.refreshed_at = time.monotonic() - 125
            app._tick()
            assert "updated 2m ago" in hints(app)
            assert navigation.refresh_age(app, now=app.refreshed_at + 7300) == "updated 2h ago"

    run(scenario())


def test_holdings_filter_and_escape_clears(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            box = app.query_one("#holdings-filter", Input)
            table = app.query_one("#holdings-table", DataTable)
            assert not box.display
            await pilot.press("F")  # 86: from any workspace
            assert app.workspace == "holdings" and box.has_focus and box.display
            await pilot.press("c", "e", "d", "a", "r")
            await pilot.pause()
            assert keys(table) == [f"{store.get_account('Cedar Margin').id}:XEQT.TO"]
            assert "1 of 3 positions" in app.query_one("#pane-holdings").border_subtitle
            assert "F ▸ “cedar”" in app.query_one("#pane-holdings").border_subtitle
            await pilot.press("enter")
            assert table.has_focus and box.display
            await pilot.press("F", "ctrl+a", "ctrl+k", "z", "z", "z")
            await pilot.pause()
            assert table.row_count == 0
            assert "no match" in app.query_one("#pane-holdings").border_subtitle
            await pilot.press("escape")  # 87
            await pilot.pause()
            assert box.value == "" and not box.display and table.has_focus and table.row_count == 3
            assert "F ▸" not in app.query_one("#pane-holdings").border_subtitle
            await pilot.press("F", "enter")  # an empty filter closes on enter
            assert not box.display and table.has_focus

            await pilot.press("5", "slash", "a", "a", "p", "l")
            activity = app.query_one("#activity-table", DataTable)
            await pilot.pause()
            assert activity.row_count == 2
            await pilot.press("escape")
            await pilot.pause()
            assert app.query_one("#activity-filter", Input).value == ""
            assert activity.has_focus and activity.row_count == 4
            await pilot.press("escape")  # nothing to clear: no change
            assert activity.has_focus and app.workspace == "activity"

    run(scenario())


def test_sort_cycling_and_reverse(tracker, store):
    birch, cedar = seed(store)
    b, c = birch.id, cedar.id

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("2")
            table = app.query_one("#holdings-table", DataTable)
            subtitle = app.query_one("#pane-holdings")
            default = [f"{b}:XEQT.TO", f"{b}:AAPL", f"{c}:XEQT.TO"]
            assert keys(table) == default and "sort" not in subtitle.border_subtitle
            await pilot.press("o")  # 91: symbol
            assert keys(table) == [f"{b}:AAPL", f"{b}:XEQT.TO", f"{c}:XEQT.TO"]
            assert "sort symbol ↑" in subtitle.border_subtitle
            await pilot.press("o")  # value, largest first
            assert keys(table) == [f"{b}:XEQT.TO", f"{b}:AAPL", f"{c}:XEQT.TO"]
            await pilot.press("O")  # 92: smallest first
            assert keys(table) == [f"{c}:XEQT.TO", f"{b}:AAPL", f"{b}:XEQT.TO"]
            assert "sort value ↑" in subtitle.border_subtitle
            await pilot.press("o")  # day %: AAPL rose, XEQT.TO fell
            assert keys(table)[0] == f"{b}:AAPL"
            await pilot.press("o", "o")  # gain, gain %
            assert keys(table)[0] == f"{b}:AAPL"
            await pilot.press("o")  # back to the default order
            assert keys(table) == default and "sort" not in subtitle.border_subtitle

            await pilot.press("5")
            activity = app.query_one("#activity-table", DataTable)
            newest = keys(activity)
            await pilot.press("O")  # oldest first
            assert keys(activity) == newest[::-1]
            assert "sort date ↑" in app.query_one("#pane-activity").border_subtitle
            await pilot.press("O", "o", "o")  # symbol, then type
            types = [str(activity.get_row(k)[3]) for k in keys(activity)]
            assert types == sorted(types)
            await pilot.press("o", "o")  # amount, largest first
            first = next(t for t in store.transactions() if str(t.id) == keys(activity)[0])
            assert first.symbol == "XEQT.TO" and first.quantity == 100
            await pilot.press("3", "o")  # elsewhere it only explains
            assert app.table_sort.get("watchlist") is None

    run(scenario())


def test_copy_symbol_and_row(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("2", "y")  # 93
            assert app.clipboard == "XEQT.TO"
            await pilot.press("Y")  # 94
            cells = app.clipboard.split("\t")
            assert cells[:2] == ["Birch TFSA", "XEQT.TO"] and len(cells) == 9
            await pilot.press("p", "Y")  # privacy masks travel with the copy
            assert fmt.MASK in app.clipboard
            await pilot.press("3", "j", "y")
            assert app.clipboard == "XEQT.TO"
            app.copy_to_clipboard("unchanged")
            await pilot.press("1", "y", "Y")  # nothing selected on the dashboard
            assert app.clipboard == "unchanged"

    run(scenario())


def test_chart_selected_and_symbol_transactions(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("5")  # newest first: the AAPL dividend
            await pilot.press("v")  # 97: enter would edit here; v charts
            assert app.workspace == "chart" and app.chart_symbol == "AAPL"
            await pilot.press("y")
            assert app.clipboard == "AAPL"
            await pilot.press("T")  # 85: the chart's symbol, in activity
            await pilot.pause()
            assert app.workspace == "activity"
            assert app.query_one("#activity-filter", Input).value == "AAPL"
            assert app.query_one("#activity-table", DataTable).row_count == 2
            await pilot.press("2", "T")
            await pilot.pause()
            assert app.query_one("#activity-filter", Input).value == "XEQT.TO"
            assert app.query_one("#activity-table", DataTable).row_count == 2
            await pilot.press("7", "v", "T")  # accounts have no symbol
            assert app.workspace == "tax"

    run(scenario())


def test_transaction_type_picker(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("N")  # 96
            assert isinstance(app.screen, TxnTypeScreen)
            await pilot.press("escape")
            assert not isinstance(app.screen, TxnTypeScreen)
            await pilot.press("N", "down", "down", "down", "down", "enter")
            await pilot.pause()
            form = app.screen
            assert isinstance(form, TransactionForm) and form.kind is TxnType.DEPOSIT
            await pilot.press("escape")

    run(scenario())


def test_zoom_hides_side_panes(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            side = app.query_one("#dash-side")
            assert side.display
            await pilot.press("z")  # 95
            await pilot.pause()
            assert app.has_class("-zoom") and not side.display
            await pilot.press("2")
            await pilot.pause()
            detail = app.query_one("#holding-detail").parent.parent
            assert not detail.display
            await pilot.press("z")
            await pilot.pause()
            assert detail.display and side.display

    run(scenario())


def test_workspace_keys_overlay_and_help(tracker, store):
    seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("2", "f1")  # 90
            screen = app.screen
            assert isinstance(screen, WorkspaceKeysScreen) and "holdings" in screen.title_text
            body = str(screen.query_one("#ws-keys", Static).content)
            assert "  f                 account\n" in body and "holdings workspace" in body
            assert "filter holdings as you type" in body and "previous workspace" in body
            await pilot.press("f1")
            assert not isinstance(app.screen, WorkspaceKeysScreen)
            await pilot.press("4", "f1")  # also with the chart focused
            assert isinstance(app.screen, WorkspaceKeysScreen)
            assert "crosshair" in str(app.screen.query_one("#ws-keys", Static).content)
            await pilot.press("escape", "6", "f1")
            assert "dividend" in str(app.screen.query_one("#ws-keys", Static).content)
            await pilot.press("q")
            await pilot.press("question_mark")
            assert isinstance(app.screen, HelpScreen)
            assert "Navigation and productivity" in str(app.screen.query_one("VerticalScroll Static", Static).content)

    run(scenario())


def test_palette_entries_for_key_only_actions(tracker, store):
    birch, cedar = seed(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            view = {name: cb for name, _help, cb in PortfolioCommands._view_actions(app)}
            selection = {name: cb for name, _help, cb in PortfolioCommands._selection_actions(app)}
            new = {name: cb for name, _help, cb in PortfolioCommands._productivity_actions(app)}
            # 98: view actions and direct jumps
            view["Net worth range: all"]()
            assert app.nw_range == "all" and app.workspace == "dashboard"
            view["Cycle allocation grouping"]()
            assert app.alloc_mode == "account"
            view["Holdings: Cedar Margin"]()
            assert app.workspace == "holdings" and app.account_filter == cedar.id
            assert app.query_one("#holdings-table", DataTable).row_count == 1
            view["Holdings: all accounts"]()
            assert app.account_filter is None
            assert "Holdings: Birch TFSA" in view and "Next theme" in view
            # 99: selection actions and chart periods
            selection["Chart period: 1y"]()
            assert app.chart_period == "1y" and app.workspace == "holdings"
            app.open_chart("AAPL")
            selection["Chart period: 5d"]()
            assert app.chart_period == "5d" and app.workspace == "chart"
            assert {"Edit selected", "Delete selected", "Compare chart with…", "Quit"} <= set(selection)
            # every new key has a palette entry too
            new["Previous workspace"]()
            assert app.workspace == "holdings"
            new["Toggle zoom"]()
            assert app.has_class("-zoom")
            # The palette's search covers them all.
            names = [name for name, _help, _cb in PortfolioCommands(app.screen)._entries()]
            assert {"Net worth range: 1m", "Chart period: 1d", "Workspace keys", "Sort by next column"} <= set(names)
            # And the real palette runs them.
            await pilot.press("ctrl+p")
            await pilot.pause()
            await pilot.press(*"toggle zoom")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await pilot.pause()
            assert not app.has_class("-zoom")

    run(scenario())


def test_accounts_pane_counts(tracker, store):
    birch, _cedar = seed(store)
    store.add_account(Account(name="Larch RRSP", type=AccountType.RRSP, archived=True))

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("7")
            assert app.query_one("#pane-accts").border_subtitle == "2 accounts · 1 archived"  # 100

    run(scenario())


def test_empty_accounts_pane_and_existing_bindings_unchanged(tracker):
    before = {
        "q": "quit",
        "r": "refresh",
        "p": "privacy",
        "t": "next_theme",
        "question_mark": "help",
        "slash": "search",
        "n": "new",
        "a": "add",
        "e": "edit",
        "x,delete": "delete",
        "u": "undo",
        "w": "watch_add",
        "A": "alert",
        "f": "filter_account",
        "g": "cycle_alloc",
        "c": "compare",
        "C": "clear_compare",
        "i": "import_csv",
        "E": "export_csv",
        "R": "room",
        "G": "add_asset",
        "V": "value_asset",
        "space": "toggle_alert",
    }
    bound = {b.key: b.action for b in MarketPulseApp.BINDINGS}
    assert all(bound[k] == v for k, v in before.items())
    every = [k for b in MarketPulseApp.BINDINGS for k in b.key.split(",")]
    assert len(every) == len(set(every)), "no key may be bound twice"

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("7")
            assert app.query_one("#pane-accts").border_subtitle == "No accounts — n to add one"

    run(scenario())
