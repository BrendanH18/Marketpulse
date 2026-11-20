"""Headless checks for the terminal app's items 81-100 in the second 100 CLI & TUI batch.

Every ledger here is fictional. Prices come from the fake market in conftest: AAPL 200 USD
(up from 190), XEQT.TO 40 CAD (down from 40.5) and USDCAD 1.35.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from pathlib import Path

from textual.widgets import DataTable, Static

from marketpulse import fmt
from marketpulse.models import Account, AccountType, Alert, Transaction, TxnType
from marketpulse.tui import extras
from marketpulse.tui.app import MarketPulseApp
from marketpulse.tui.commands import PortfolioCommands
from marketpulse.tui.screens import DetailsScreen, PromptScreen

SIZE = (180, 52)
SHOTS = os.environ.get("MARKETPULSE_TUI_SHOTS")  # a directory to save SVG screenshots into, when set


def run(coro):
    return asyncio.run(coro)


def seed(store):
    """Birch TFSA tracks cash: $5,000 in, 100 XEQT.TO bought. Cedar Margin holds AAPL and a little
    XEQT.TO and was paid one AAPL dividend. Aspen RRSP is empty."""
    birch = store.add_account(Account(name="Birch TFSA", type=AccountType.TFSA, track_cash=True))
    cedar = store.add_account(Account(name="Cedar Margin", type=AccountType.MARGIN))
    aspen = store.add_account(Account(name="Aspen RRSP", type=AccountType.RRSP))
    rows = [
        Transaction(birch.saved_id, TxnType.DEPOSIT, "2024-01-01", amount=5000, currency="CAD"),
        Transaction(birch.saved_id, TxnType.BUY, "2024-01-02", "XEQT.TO", 100, 30, currency="CAD", note="core"),
        Transaction(cedar.saved_id, TxnType.BUY, "2024-02-01", "AAPL", 10, 150, currency="USD"),
        Transaction(cedar.saved_id, TxnType.BUY, "2024-03-01", "XEQT.TO", 5, 42, currency="CAD"),
        Transaction(cedar.saved_id, TxnType.DIVIDEND, "2024-04-01", "AAPL", amount=2.4, currency="USD"),
    ]
    saved = [store.add_transaction(t) for t in rows]
    store.add_watch(["XEQT.TO", "AAPL"])
    return birch, cedar, aspen, saved


async def started(app, pilot):
    await app.workers.wait_for_complete()
    await pilot.pause()


def keys(table: DataTable) -> list[str]:
    return [str(k.value) for k in table.rows]


def subtitle(app, pane: str) -> str:
    return app.query_one(pane).border_subtitle


def messages(app) -> list[str]:
    """Every message notified so far, recorded as it is sent (Textual delivers and expires them later)."""
    return [message for message, _title in app.sent]


def select(table: DataTable, key: str) -> None:
    table.move_cursor(row=table.get_row_index(key), animate=False)


def shot(app, name: str) -> None:
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        app.save_screenshot(filename=name, path=SHOTS)


def new_app(tracker, copied: list[str] | None = None) -> MarketPulseApp:
    app = MarketPulseApp(tracker.config, tracker=tracker)
    if copied is not None:
        app.copy_to_clipboard = copied.append  # type: ignore[method-assign]
    app.sent = []  # type: ignore[attr-defined]
    original = app.notify

    def notify(message, *args, **kwargs):
        app.sent.append((str(message), kwargs.get("title", "")))  # type: ignore[attr-defined]
        return original(message, *args, **kwargs)

    app.notify = notify  # type: ignore[method-assign]
    return app


# 81 ─ row details (P) ─────────────────────────────────────────────────────────


def test_details_show_every_field_of_the_selected_row(tracker, store):
    _, _, _, saved = seed(store)

    async def scenario():
        app = new_app(tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("5")
            select(app.query_one("#activity-table", DataTable), str(saved[1].id))
            await pilot.press("P")
            assert isinstance(app.screen, DetailsScreen)
            body = str(app.screen.query_one("#details", Static).content)
            assert f"Transaction #{saved[1].id}" == app.screen.title_text
            assert "Birch TFSA" in body and "XEQT.TO" in body and "100" in body and "core" in body
            shot(app, "tui-more-details.svg")
            await pilot.press("P")
            assert not isinstance(app.screen, DetailsScreen)

            await pilot.press("2")
            select(app.query_one("#holdings-table", DataTable), "2:AAPL")
            app.config.privacy = True
            await pilot.press("P")
            body = str(app.screen.query_one("#details", Static).content)
            assert app.screen.title_text == "AAPL · Cedar Margin"
            assert f"Quantity      {fmt.MASK}" in body and "Average cost  150.00" in body
            await pilot.press("escape")
            await pilot.press("4")
            await pilot.press("P")
            assert "Select a row in holdings" in messages(app)[-1]

    run(scenario())


# 82 ─ add to or remove from the watchlist (W) ─────────────────────────────────


def test_w_toggles_the_selected_symbol_on_the_watchlist(tracker, store):
    seed(store)

    async def scenario():
        app = new_app(tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("2")
            select(app.query_one("#holdings-table", DataTable), "2:AAPL")
            await pilot.press("W")
            assert store.watchlist() == ["XEQT.TO"]
            assert "Removed AAPL" in messages(app)[-1]
            await pilot.press("W")
            await started(app, pilot)
            assert store.watchlist() == ["XEQT.TO", "AAPL"]
            assert keys(app.query_one("#watch-table", DataTable)) == ["XEQT.TO", "AAPL"]

    run(scenario())


# 83 + 100 ─ one account (;) and today's change in the holdings footer ───────────


def test_semicolon_scopes_to_the_selected_account_and_footer_shows_today(tracker, store):
    seed(store)

    async def scenario():
        app = new_app(tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("2")
            assert "today +$" in subtitle(app, "#pane-holdings")
            table = app.query_one("#holdings-table", DataTable)
            select(table, "1:XEQT.TO")
            await pilot.press("semicolon")
            assert app.account_filter == 1
            assert keys(table) == ["1:XEQT.TO", "cash:1:CAD"]
            # 100 XEQT.TO down 0.50 today
            assert "f ▸ Birch TFSA · 1 positions · $4,000 · today -$50" in subtitle(app, "#pane-holdings")
            await pilot.press("p")
            assert "today ••••" in subtitle(app, "#pane-holdings")
            await pilot.press("p")
            await pilot.press("semicolon")
            assert app.account_filter is None and len(keys(table)) == 4

            await pilot.press("5")
            activity = app.query_one("#activity-table", DataTable)
            select(activity, keys(activity)[0])  # the Cedar Margin dividend
            await pilot.press("semicolon")
            assert app.activity_account_filter == 2 and len(keys(activity)) == 3
            await pilot.press("semicolon")
            assert app.activity_account_filter is None and len(keys(activity)) == 5
            await pilot.press("3")
            await pilot.press("semicolon")
            assert "; shows one account" in messages(app)[-1]

    run(scenario())


# 84 ─ go to a row or a date (:) ───────────────────────────────────────────────


def test_colon_goes_to_a_row_number_or_an_activity_date(tracker, store):
    _, _, _, saved = seed(store)

    async def scenario():
        app = new_app(tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("5")
            table = app.query_one("#activity-table", DataTable)
            await pilot.press("colon")
            assert isinstance(app.screen, PromptScreen)
            await pilot.press("3", "enter")
            assert table.cursor_row == 2
            await pilot.press("colon")
            await pilot.press(*"2024-01", "enter")
            assert keys(table)[table.cursor_row] == str(saved[1].id)  # the newest January entry
            assert extras.go_to(app, "2023") is False
            assert "No entry dated 2023" in messages(app)[-1]
            assert extras.go_to(app, "99") is True and table.cursor_row == 4  # clamps to the last row

    run(scenario())


# 85 ─ activity date window (%) ────────────────────────────────────────────────


def test_percent_cycles_the_activity_date_window(tracker, store):
    birch, *_ = seed(store)
    recent = store.add_transaction(
        Transaction(birch.saved_id, TxnType.DEPOSIT, date.today().isoformat(), amount=100, currency="CAD")
    )

    async def scenario():
        app = new_app(tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("percent_sign")
            assert app.workspace == "activity" and app.activity_window == "30d"
            table = app.query_one("#activity-table", DataTable)
            assert keys(table) == [str(recent.id)]
            assert "% ▸ 30d" in subtitle(app, "#pane-activity")
            for _ in range(3):
                await pilot.press("percent_sign")
            assert app.activity_window == "1y"
            await pilot.press("escape")
            assert app.activity_window == "all" and len(keys(table)) == 6
            assert extras.window_start("ytd", date(2025, 6, 1)) == "2025-01-01"
            assert extras.window_start("30d", date(2025, 6, 30)) == "2025-06-01"  # today and the 29 days before
            assert extras.window_start("all") is None

    run(scenario())


# 86 + 93 + 97 ─ chart high/low (^ _), previous chart ('), chart CSV (palette) ───


def test_chart_high_low_previous_chart_and_csv(tracker, store, fake):
    seed(store)
    fake.set_history("AAPL", {"2024-01-02": 180, "2024-01-03": 210, "2024-01-04": 170, "2024-01-05": 200})
    fake.set_history("XEQT.TO", {"2024-01-02": 39, "2024-01-03": 40}, currency="CAD")
    copied: list[str] = []

    async def scenario():
        app = new_app(tracker, copied)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("circumflex_accent")
            assert "on the chart workspace" in messages(app)[-1]
            await pilot.press("apostrophe")
            assert "No earlier chart" in messages(app)[-1]
            app.open_chart("XEQT.TO")
            await started(app, pilot)
            app.open_chart("AAPL")
            await started(app, pilot)
            view = app.query_one("#chart-view")
            await pilot.press("circumflex_accent")
            assert view.marker == 1 and "AAPL 3mo high 210.00" == messages(app)[-1]
            await pilot.press("low_line")
            assert view.marker == 2
            shot(app, "tui-more-chart-low.svg")

            app.action_copy_chart_csv()
            lines = copied[-1].splitlines()
            assert lines[0] == "date,open,high,low,close,volume" and len(lines) == 5
            assert lines[2].endswith(",210.0,210.0,210.0,210.0,100")
            assert "Copied 4 bars of AAPL 3mo as CSV" in messages(app)[-1]

            await pilot.press("apostrophe")
            await started(app, pilot)
            assert app.chart_symbol == "XEQT.TO"
            # Turning privacy on redraws the held quantity and gain in the quote line that ctrl+t copies.
            await pilot.press("ctrl+t")
            assert "held 105 · gain +990.00" in copied[-1]
            await pilot.press("p")
            await pilot.press("ctrl+t")
            assert "held •••• · gain ••••" in copied[-1] and "990" not in copied[-1]
            await pilot.press("p")
            await pilot.press("apostrophe")
            await started(app, pilot)
            assert app.chart_symbol == "AAPL"

    run(scenario())


# 87 ─ previous / next group (( and )) ─────────────────────────────────────────


def test_parentheses_jump_between_groups(tracker, store):
    seed(store)

    async def scenario():
        app = new_app(tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("2")
            table = app.query_one("#holdings-table", DataTable)
            assert keys(table) == ["1:XEQT.TO", "2:AAPL", "2:XEQT.TO", "cash:1:CAD"]
            await pilot.press("right_parenthesis")
            assert table.cursor_row == 1 and messages(app)[-1] == "Cedar Margin"
            await pilot.press("right_parenthesis")
            assert table.cursor_row == 3
            await pilot.press("left_parenthesis")
            assert table.cursor_row == 1
            await pilot.press("left_parenthesis")
            assert table.cursor_row == 0
            await pilot.press("left_parenthesis")
            assert "No more groups" in messages(app)[-1]

            await pilot.press("5")  # by month: 04, 03, 02, then two January entries
            activity = app.query_one("#activity-table", DataTable)
            for row in (1, 2, 3):
                await pilot.press("right_parenthesis")
                assert activity.cursor_row == row
            assert messages(app)[-1] == "2024-01"
            await pilot.press("3")
            await pilot.press("right_parenthesis")
            assert "( and ) jump between groups" in messages(app)[-1]

    run(scenario())


# 88 ─ find a row (ctrl+f, ctrl+g) ─────────────────────────────────────────────


def test_find_and_find_next_move_through_matching_rows(tracker, store):
    seed(store)

    async def scenario():
        app = new_app(tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("2")
            table = app.query_one("#holdings-table", DataTable)
            await pilot.press("ctrl+f")
            assert isinstance(app.screen, PromptScreen)
            await pilot.press(*"xeqt", "enter")
            assert app.find_text == "xeqt" and table.cursor_row == 0
            await pilot.press("ctrl+g")
            assert table.cursor_row == 2 and "row 3/4" in messages(app)[-1]
            await pilot.press("ctrl+g")
            assert table.cursor_row == 0  # wraps
            app.find_text = "nothing like this"
            await pilot.press("ctrl+g")
            assert "No row contains" in messages(app)[-1] and table.cursor_row == 0

    run(scenario())


# 89 ─ copy pane as text (ctrl+t) ──────────────────────────────────────────────


def test_ctrl_t_copies_the_side_pane_or_report_as_text(tracker, store):
    seed(store)
    copied: list[str] = []

    async def scenario():
        app = new_app(tracker, copied)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("2")
            select(app.query_one("#holdings-table", DataTable), "2:AAPL")
            await pilot.pause()
            await pilot.press("ctrl+t")
            assert copied[-1].startswith("AAPL") and "Cedar Margin" in copied[-1]
            assert "Average cost" in copied[-1] and "\x1b" not in copied[-1]
            await pilot.press("p")
            await pilot.press("ctrl+t")
            assert fmt.MASK in copied[-1]
            await pilot.press("7")  # the tax report
            await started(app, pilot)
            before = len(copied)
            await pilot.press("ctrl+t")
            assert len(copied) == before + 1 and "Estimates only" in copied[-1]
            assert messages(app)[-1].startswith("Copied")
            await pilot.press("5")
            await pilot.press("ctrl+t")
            assert "ctrl+t copies a side pane" in messages(app)[-1]

    run(scenario())


# 90 ─ pause automatic refresh (ctrl+r) ────────────────────────────────────────


def test_ctrl_r_pauses_and_resumes_automatic_refresh(tracker, store):
    seed(store)

    async def scenario():
        app = new_app(tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            timer = app._refresh_timer
            assert timer is not None
            await pilot.press("ctrl+r")
            assert app.auto_refresh_paused and not timer._active.is_set()
            assert "auto-refresh paused" in str(app.query_one("#hints", Static).content)
            await pilot.press("ctrl+r")
            assert not app.auto_refresh_paused and timer._active.is_set()
            await started(app, pilot)
            assert "auto-refresh paused" not in str(app.query_one("#hints", Static).content)

    run(scenario())


# 91 ─ alerts for the selected symbol (&) ──────────────────────────────────────


def test_ampersand_lists_the_selected_symbols_alerts(tracker, store):
    seed(store)
    store.add_alert(Alert(symbol="AAPL", condition="above", threshold=250.0))
    store.add_alert(Alert(symbol="XEQT.TO", condition="below", threshold=30.0))
    store.add_alert(Alert(symbol="AAPL", condition="below", threshold=150.0, active=False))

    async def scenario():
        app = new_app(tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("3")
            select(app.query_one("#watch-table", DataTable), "AAPL")
            await pilot.press("ampersand")
            assert app.workspace == "alerts" and app.alerts_symbol == "AAPL"
            table = app.query_one("#alerts-table", DataTable)
            assert len(keys(table)) == 2
            assert subtitle(app, "#pane-alerts") == "2 armed of 3 · & ▸ AAPL"
            shot(app, "tui-more-alerts.svg")
            await pilot.press("ampersand")
            assert app.alerts_symbol is None and len(keys(table)) == 3
            app.alerts_symbol = "MSFT"
            app.render_alerts()
            assert "no match — escape clears" in subtitle(app, "#pane-alerts")
            assert app.context_symbol() == "MSFT"  # A on the empty list prefills MSFT
            await pilot.press("escape")
            assert app.alerts_symbol is None

    run(scenario())


# 92 ─ next ledger issue (ctrl+e) ──────────────────────────────────────────────


def test_ctrl_e_selects_transactions_with_ledger_issues(tracker, store):
    birch, *_ = seed(store)
    oversell = store.add_transaction(Transaction(birch.saved_id, TxnType.SELL, "2024-05-01", "XEQT.TO", 500, 41))

    async def scenario():
        app = new_app(tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("5")
            app.activity_filter_mode = "income"
            app.render_activity()
            await pilot.press("ctrl+e")
            table = app.query_one("#activity-table", DataTable)
            assert app.activity_filter_mode == "all"  # cleared so the entry shows
            assert keys(table)[table.cursor_row] == str(oversell.id)
            message, title = app.sent[-1]
            assert title == "Ledger issue 1 of 1" and "exceeds" in message
            await pilot.press("p")
            await pilot.press("ctrl+e")
            assert "500" not in messages(app)[-1] and fmt.MASK in messages(app)[-1]

    run(scenario())


def test_ctrl_e_without_issues_says_so(tracker, store):
    seed(store)

    async def scenario():
        app = new_app(tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("ctrl+e")
            assert "No ledger issues" in messages(app)[-1]

    run(scenario())


# 94 ─ copy table as JSON (") ──────────────────────────────────────────────────


def test_quotation_mark_copies_the_table_as_json(tracker, store):
    seed(store)
    copied: list[str] = []

    async def scenario():
        app = new_app(tracker, copied)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("7")
            await pilot.press("quotation_mark")
            rows = json.loads(copied[-1])
            assert [r["Account"] for r in rows] == ["Birch TFSA", "Cedar Margin", "Aspen RRSP"]
            assert list(rows[0]) == ["ID", "Account", "Type", "Value", "Today"]
            await pilot.press("p")
            await pilot.press("quotation_mark")
            assert json.loads(copied[-1])[0]["Value"] == fmt.MASK

    run(scenario())


# 95 ─ save the sorted watchlist (ctrl+s) ──────────────────────────────────────


def test_ctrl_s_saves_the_sorted_watchlist_order(tracker, store):
    seed(store)

    async def scenario():
        app = new_app(tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            await pilot.press("3")
            await pilot.press("ctrl+s")
            assert "Sort the watchlist with o first" in messages(app)[-1]
            await pilot.press("o")  # by symbol
            assert keys(app.query_one("#watch-table", DataTable)) == ["AAPL", "XEQT.TO"]
            await pilot.press("ctrl+s")
            await started(app, pilot)
            assert store.watchlist() == ["AAPL", "XEQT.TO"]
            assert "watchlist" not in app.table_sort
            assert "Saved the watchlist order (2 symbols)" in messages(app)[-1]

    run(scenario())


# 96 + 98 + 99 ─ command palette: watch holdings, year and mode choices ─────────


def test_palette_watch_holdings_and_direct_choices(tracker, store):
    seed(store)
    store.remove_watch(["AAPL", "XEQT.TO"])

    async def scenario():
        app = new_app(tracker)
        async with app.run_test(size=SIZE) as pilot:
            await started(app, pilot)
            entries = {name: callback for name, _help, callback in PortfolioCommands._more_workflow_actions(app)}
            entries["Watch every held symbol"]()
            await started(app, pilot)
            assert store.watchlist() == ["AAPL", "XEQT.TO"]
            entries["Watch every held symbol"]()
            assert "already on the watchlist" in messages(app)[-1]

            assert "Income year: 2024" in entries
            entries["Income year: 2024"]()
            assert app.workspace == "income" and app.income_year == 2024

            await pilot.press("7")
            await started(app, pilot)
            entries = {name: callback for name, _help, callback in PortfolioCommands._more_workflow_actions(app)}
            assert ("Tax year: 2024" in entries) == (2024 in extras.tax_years(app))

            entries["Holdings mode: losers"]()
            assert app.workspace == "holdings" and app.holdings_filter_mode == "losers"
            entries["Activity mode: income"]()
            assert app.workspace == "activity" and app.activity_filter_mode == "income"
            entries["Alerts mode: paused"]()
            assert app.alerts_filter_mode == "paused"
            entries["Movers: unrealized"]()
            assert app.workspace == "dashboard" and app.movers_mode == "unrealized"
            entries["Activity window: ytd"]()
            assert app.activity_window == "ytd"
            for name in ("Show row details", "Find in table…", "Copy pane as text", "Next ledger issue"):
                assert name in entries

    run(scenario())


def test_new_keys_are_unbound_elsewhere_and_listed_in_f1():
    from marketpulse.tui.constants import WORKSPACE_KEYS

    every = [k for b in MarketPulseApp.BINDINGS for k in b.key.split(",")]
    assert len(every) == len(set(every)), "no key may be bound twice"
    added = "P W semicolon colon percent_sign circumflex_accent low_line left_parenthesis right_parenthesis".split()
    added += "ctrl+f ctrl+g ctrl+t ctrl+r ampersand ctrl+e apostrophe quotation_mark ctrl+s".split()
    assert set(added) <= set(every)
    listed = {key for rows in WORKSPACE_KEYS.values() for key, _ in rows}
    assert {"P", "%", "ctrl+e", "^ / _", "ctrl+s", "&"} <= listed
