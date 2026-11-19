"""Keyboard navigation and productivity helpers; Textual entry points stay on the app.

Workspace history and cycling, table cursor jumps, the holdings filter, column
sorting, clipboard copies, zoom, the transaction-type picker and the footer's
row position and refresh age. Everything here only reorders, selects or copies
what the views already show; no figure is computed differently.
"""

from __future__ import annotations

import csv
import io
import re
import time
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Input

from .. import fmt
from ..market import PERIODS
from ..models import Transaction
from ..themes import pretty_name, resolve_palette
from ..valuation import PositionView
from .constants import (
    ACTIVITY_FILTER_MODES,
    ALERT_FILTER_MODES,
    GLOBAL_KEYS,
    HINTS,
    HOLDING_FILTER_MODES,
    MOVERS_MODES,
    NW_RANGES,
    SORT_MODES,
    TABLES,
    TXN_CHOICES,
    WORKSPACE_KEYS,
)
from .screens import ProblemsScreen, TxnTypeScreen, WorkspaceKeysScreen
from .widgets import WORKSPACES, ChartView

if TYPE_CHECKING:
    from .app import MarketPulseApp

T = TypeVar("T")
_ORDER = [key for key, _label in WORKSPACES]
_LABELS = dict(WORKSPACES)


# ── workspaces ────────────────────────────────────────────────────────────────


def previous_workspace(app: MarketPulseApp) -> None:
    """Return to the workspace shown before the current one (press again to come back)."""
    target = app.last_workspace
    if target and target != app.workspace:
        app.set_workspace(target)


def cycle_workspace(app: MarketPulseApp, delta: int) -> None:
    current = app.workspace
    index = _ORDER.index(current) if current in _ORDER else 0
    app.set_workspace(_ORDER[(index + delta) % len(_ORDER)])


# ── tables ────────────────────────────────────────────────────────────────────


def current_table(app: MarketPulseApp) -> DataTable | None:
    selector = TABLES.get(app.workspace)
    return app.query_one(selector, DataTable) if selector else None


def _scroll_pane(app: MarketPulseApp) -> VerticalScroll | None:
    if app.workspace == "income":
        return app.query_one("#income", VerticalScroll)
    focused = app.focused
    if isinstance(focused, VerticalScroll):
        return focused
    return None


def move_cursor(app: MarketPulseApp, delta: int) -> None:
    table = current_table(app)
    if table is not None and table.row_count > 0:
        row = max(0, min(table.row_count - 1, table.cursor_row + delta))
        table.move_cursor(row=row, animate=False)
        table.focus()
        return
    pane = _scroll_pane(app)
    if pane is not None:
        if delta > 0:
            pane.scroll_down(animate=False)
        else:
            pane.scroll_up(animate=False)


def jump_half_page(app: MarketPulseApp, down: bool) -> None:
    table = current_table(app)
    if table is not None and table.row_count > 0:
        step = max(table.size.height // 2, 1)
        move_cursor(app, step if down else -step)
        return
    pane = _scroll_pane(app)
    if pane is not None:
        step = max(pane.size.height // 2, 1)
        pane.scroll_relative(y=step if down else -step, animate=False)


def jump_row(app: MarketPulseApp, last: bool) -> None:
    table = current_table(app)
    if table is not None and table.row_count > 0:
        table.move_cursor(row=table.row_count - 1 if last else 0, animate=False)
        table.focus()
        return
    pane = _scroll_pane(app)
    if pane is not None:
        if last:
            pane.scroll_end(animate=False)
        else:
            pane.scroll_home(animate=False)


def row_position(app: MarketPulseApp) -> tuple[int, int] | None:
    table = current_table(app)
    if table is None or table.row_count == 0:
        return None
    return min(table.cursor_row, table.row_count - 1) + 1, table.row_count


# ── holdings filter ───────────────────────────────────────────────────────────


def holdings_needle(app: MarketPulseApp) -> str:
    return app.query_one("#holdings-filter", Input).value.strip().lower()


def holdings_match(needle: str, *texts: str) -> bool:
    return not needle or any(needle in t.lower() for t in texts)


def show_holdings_filter(app: MarketPulseApp) -> None:
    if app.workspace != "holdings":
        app.set_workspace("holdings")
    box = app.query_one("#holdings-filter", Input)
    box.add_class("-shown")
    box.focus()


def holdings_filter_done(app: MarketPulseApp) -> None:
    """Enter: keep a non-empty filter visible and move to the table; an empty one closes."""
    box = app.query_one("#holdings-filter", Input)
    if not box.value.strip():
        box.remove_class("-shown")
    app.query_one("#holdings-table", DataTable).focus()


def clear_filter(app: MarketPulseApp) -> None:
    """Escape: empty the holdings, activity or alerts filters and put the cursor back in the table."""
    ws = app.workspace
    if ws == "holdings":
        box = app.query_one("#holdings-filter", Input)
        had_mode = app.holdings_filter_mode != "all"
        if not (box.value or box.has_class("-shown") or had_mode):
            return
        box.value = ""
        box.remove_class("-shown")
        app.holdings_filter_mode = "all"
        app.render_holdings()
        app.query_one("#holdings-table", DataTable).focus()
    elif ws == "activity":
        box = app.query_one("#activity-filter", Input)
        had_extra = app.activity_filter_mode != "all" or app.activity_account_filter is not None
        if not (box.value or box.has_focus or had_extra):
            return
        box.value = ""
        app.activity_filter_mode = "all"
        app.activity_account_filter = None
        app.render_activity()
        app.query_one("#activity-table", DataTable).focus()
    elif ws == "alerts":
        if app.alerts_filter_mode == "all":
            return
        app.alerts_filter_mode = "all"
        app.render_alerts()
        app.query_one("#alerts-table", DataTable).focus()


# ── sorting ───────────────────────────────────────────────────────────────────


def sort_state(app: MarketPulseApp, ws: str) -> tuple[str, bool]:
    """The workspace's (column, descending) sort, defaulting to its original order."""
    return app.table_sort.get(ws) or SORT_MODES[ws][0]


def sort_label(app: MarketPulseApp, ws: str) -> str:
    """'sort value ↓' when the order differs from the default, else ''."""
    state = sort_state(app, ws)
    if state == SORT_MODES[ws][0]:
        return ""
    return f"sort {state[0]} {'↓' if state[1] else '↑'}"


_NOT_SORTABLE = "Sorting works in holdings, watchlist, activity, accounts and alerts"


def cycle_sort(app: MarketPulseApp) -> None:
    ws = app.workspace
    if ws not in SORT_MODES:
        app.notify(_NOT_SORTABLE, timeout=3)
        return
    modes = SORT_MODES[ws]
    names = [name for name, _desc in modes]
    current = sort_state(app, ws)[0]
    app.table_sort[ws] = modes[(names.index(current) + 1) % len(modes)]
    _rerender_sorted(app, ws)


def reverse_sort(app: MarketPulseApp) -> None:
    ws = app.workspace
    if ws not in SORT_MODES:
        app.notify(_NOT_SORTABLE, timeout=3)
        return
    name, descending = sort_state(app, ws)
    app.table_sort[ws] = (name, not descending)
    _rerender_sorted(app, ws)


def reset_sort(app: MarketPulseApp) -> None:
    ws = app.workspace
    if ws not in SORT_MODES:
        app.notify(_NOT_SORTABLE, timeout=3)
        return
    app.table_sort.pop(ws, None)
    _rerender_sorted(app, ws)


def set_sort(app: MarketPulseApp, ws: str, name: str, descending: bool) -> None:
    """Command-palette target: sort a workspace's table by one column directly, then show it."""
    if (name, descending) not in SORT_MODES.get(ws, []):
        return
    app.table_sort[ws] = (name, descending)
    app.set_workspace(ws)
    _rerender_sorted(app, ws)


def _rerender_sorted(app: MarketPulseApp, ws: str) -> None:
    {
        "holdings": app.render_holdings,
        "watchlist": app.render_watchlist,
        "activity": app.render_activity,
        "tax": app.render_accounts,
        "alerts": app.render_alerts,
    }[ws]()
    name, descending = sort_state(app, ws)
    app.notify(f"Sorted by {name} {'↓' if descending else '↑'}", timeout=2)


def _ordered(items: Iterable[T], key: Callable[[T], Any], descending: bool) -> list[T]:
    """Sort by key, keeping rows without a value (unpriced, no FX) last in either direction."""
    items = list(items)
    known = [x for x in items if key(x) is not None]
    missing = [x for x in items if key(x) is None]
    return sorted(known, key=key, reverse=descending) + missing


def sort_positions(app: MarketPulseApp, positions: list[PositionView]) -> list[PositionView]:
    name, descending = sort_state(app, "holdings")
    if (name, descending) == SORT_MODES["holdings"][0]:
        return sorted(positions, key=lambda x: (x.account.name, -(x.value_base or 0)))
    keys: dict[str, Callable[[PositionView], Any]] = {
        "account": lambda x: (x.account.name, -(x.value_base or 0)),
        "symbol": lambda x: (x.symbol, x.account.name),
        "value": lambda x: x.value_base,
        "day %": lambda x: x.day_change_pct,
        "gain": lambda x: x.gain_base,
        "gain %": lambda x: x.gain_pct,
    }
    return _ordered(positions, keys[name], descending)


def sort_transactions(app: MarketPulseApp, txns: list[Transaction], accounts: dict) -> list[Transaction]:
    name, descending = sort_state(app, "activity")
    newest = sorted(txns, key=lambda t: (t.date, t.id or 0), reverse=True)
    if (name, descending) == SORT_MODES["activity"][0]:
        return newest
    if name == "date":
        return newest[::-1]

    def account_name(t: Transaction) -> str:
        acct = accounts.get(t.account_id)
        return acct.name.lower() if acct else ""

    keys: dict[str, Callable[[Transaction], Any]] = {
        "symbol": lambda t: t.symbol,
        "type": lambda t: t.type.value,
        "account": account_name,
        "amount": lambda t: abs(t.gross_value or 0),
    }
    # Stable sort over newest-first keeps the latest entry first within ties.
    return sorted(newest, key=keys[name], reverse=descending)


def sort_items(app: MarketPulseApp, ws: str, items: Iterable[T], keys: Mapping[str, Callable[[T], Any]]) -> list[T]:
    """Order the watchlist, accounts or alerts rows; the default keeps the order they arrive in."""
    name, descending = sort_state(app, ws)
    if (name, descending) == SORT_MODES[ws][0]:
        return list(items)
    return _ordered(items, keys[name], descending)


# ── clipboard, chart, transactions ────────────────────────────────────────────


def copy_symbol(app: MarketPulseApp) -> None:
    symbol = app.context_symbol()
    if not symbol:
        app.notify("Select a row with a symbol first", timeout=3)
        return
    app.copy_to_clipboard(symbol)
    app.notify(f"Copied {symbol}", timeout=2)


def copy_row(app: MarketPulseApp) -> None:
    """Copy the selected row as tab-separated text, or on chart copy the active bar/summary."""
    if app.workspace == "chart":
        chart = app.query_one("#chart-view", ChartView)
        if not app.chart_symbol:
            app.notify("Open a chart first", timeout=3)
            return
        if chart.marker is not None and 0 <= chart.marker < len(chart.bars):
            bar = chart.bars[chart.marker]
            text = (
                f"{app.chart_symbol}\t{bar.date}\tO {fmt.price(bar.open)}\tH {fmt.price(bar.high)}\t"
                f"L {fmt.price(bar.low)}\tC {fmt.price(bar.close)}"
            )
            app.copy_to_clipboard(text)
            app.notify(f"Copied {app.chart_symbol} bar {bar.date}", timeout=2)
            return
        if chart.bars:
            first, last = chart.bars[0], chart.bars[-1]
            pct = (last.close - first.close) / first.close * 100 if first.close else 0.0
            text = f"{app.chart_symbol}\t{app.chart_period}\t{fmt.price(last.close)}\t{fmt.pct(pct)}"
            app.copy_to_clipboard(text)
            app.notify(f"Copied {app.chart_symbol} chart summary", timeout=2)
            return
        app.copy_to_clipboard(app.chart_symbol)
        app.notify(f"Copied {app.chart_symbol}", timeout=2)
        return
    table = current_table(app)
    if table is None or table.row_count == 0:
        app.notify("No table row selected", timeout=3)
        return
    cells = table.get_row_at(min(table.cursor_row, table.row_count - 1))
    text = "\t".join(c.plain if isinstance(c, Text) else str(c) for c in cells)
    app.copy_to_clipboard(text)
    app.notify(f"Copied row {table.cursor_row + 1}", timeout=2)


def _table_matrix(app: MarketPulseApp) -> tuple[list[str], list[list[str]]] | None:
    table = current_table(app)
    if table is None or table.row_count == 0:
        app.notify("No table rows to copy here", timeout=3)
        return None

    def plain(cell: object) -> str:
        return cell.plain if isinstance(cell, Text) else str(cell)

    headers = [plain(c.label) for c in table.ordered_columns]
    rows = [[plain(c) for c in table.get_row_at(i)] for i in range(table.row_count)]
    return headers, rows


def copy_table(app: MarketPulseApp) -> None:
    """Copy the whole table as shown: headers first, then every row the filters and sort leave, masks included."""
    data = _table_matrix(app)
    if data is None:
        return
    headers, rows = data
    lines = ["\t".join(headers), *("\t".join(r) for r in rows)]
    app.copy_to_clipboard("\n".join(lines))
    app.notify(f"Copied {len(rows)} row{'' if len(rows) == 1 else 's'} with headers", timeout=2)


def copy_table_csv(app: MarketPulseApp) -> None:
    """Copy the visible table with headers as RFC-4180 CSV, masks included."""
    data = _table_matrix(app)
    if data is None:
        return
    headers, rows = data
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    app.copy_to_clipboard(stream.getvalue())
    app.notify(f"Copied {len(rows)} row{'' if len(rows) == 1 else 's'} as CSV", timeout=2)


def copy_table_markdown(app: MarketPulseApp) -> None:
    """Copy the visible table with headers as GitHub-Flavored Markdown, masks included."""
    data = _table_matrix(app)
    if data is None:
        return
    headers, rows = data

    def esc(val: str) -> str:
        return " ".join(val.splitlines()).replace("\\", "\\\\").replace("|", "\\|")

    lines = [
        "| " + " | ".join(esc(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(esc(c) for c in r) + " |" for r in rows),
    ]
    app.copy_to_clipboard("\n".join(lines))
    app.notify(f"Copied {len(rows)} row{'' if len(rows) == 1 else 's'} as Markdown", timeout=2)


def copy_portfolio_summary(app: MarketPulseApp) -> None:
    """Copy a concise plain-text portfolio summary to the clipboard (respecting privacy mode)."""
    v = app.view
    if v is None:
        app.notify("Portfolio not loaded yet", timeout=3)
        return
    priv = app.privacy
    lines = [
        f"Net worth ({v.base}): {fmt.money(v.net_worth, v.base, privacy=priv)}",
        f"Today: {fmt.money(v.day_change, v.base, sign=True, privacy=priv)} ({fmt.pct(v.day_change_pct)})",
        f"Unrealized: {fmt.money(v.unrealized, v.base, sign=True, privacy=priv)} ({fmt.pct(v.unrealized_pct)})",
        f"Income YTD: {fmt.money(v.income_ytd, v.base, privacy=priv)}",
        f"Positions: {len(v.positions)}",
    ]
    app.copy_to_clipboard("\n".join(lines))
    app.notify("Copied portfolio summary", timeout=2)


def toggle_cash(app: MarketPulseApp) -> None:
    app.hide_cash = not app.hide_cash
    if app.workspace != "holdings":
        app.set_workspace("holdings")
    app.render_holdings()
    app.notify("Cash rows hidden" if app.hide_cash else "Cash rows shown", timeout=2)


def toggle_archived_accounts(app: MarketPulseApp) -> None:
    app.hide_archived = not app.hide_archived
    if app.workspace != "tax":
        app.set_workspace("tax")
    app.render_accounts()
    app.notify("Archived accounts hidden" if app.hide_archived else "Archived accounts shown", timeout=2)


def jump_to_holding(app: MarketPulseApp) -> None:
    """Switch to holdings and move cursor to the context symbol's row."""
    symbol = app.context_symbol()
    if not symbol:
        app.notify("Select a row with a symbol first", timeout=3)
        return
    v = app.view
    if v is None or not any(p.symbol == symbol for p in v.positions):
        app.notify(f"{symbol} is not in current holdings", timeout=3)
        return
    app.account_filter = None
    app.holdings_filter_mode = "all"
    box = app.query_one("#holdings-filter", Input)
    box.value = ""
    box.remove_class("-shown")
    app.set_workspace("holdings")
    app.render_holdings()
    table = app.query_one("#holdings-table", DataTable)
    for row_key in table.rows:
        key_val = str(row_key.value)
        if not key_val.startswith("cash:") and ":" in key_val and key_val.split(":", 1)[1] == symbol:
            table.move_cursor(row=table.get_row_index(row_key), animate=False)
            table.focus()
            app._show_position(key_val)
            return


def cycle_filter_mode(app: MarketPulseApp) -> None:
    """Cycle workspace-specific quick filter mode (holdings / activity / alerts)."""
    ws = app.workspace
    if ws == "holdings":
        modes = HOLDING_FILTER_MODES
        app.holdings_filter_mode = modes[(modes.index(app.holdings_filter_mode) + 1) % len(modes)]
        app.render_holdings()
        app.notify(f"Holdings filter: {app.holdings_filter_mode}", timeout=2)
    elif ws == "activity":
        modes = ACTIVITY_FILTER_MODES
        app.activity_filter_mode = modes[(modes.index(app.activity_filter_mode) + 1) % len(modes)]
        app.render_activity()
        app.notify(f"Activity filter: {app.activity_filter_mode}", timeout=2)
    elif ws == "alerts":
        modes = ALERT_FILTER_MODES
        app.alerts_filter_mode = modes[(modes.index(app.alerts_filter_mode) + 1) % len(modes)]
        app.render_alerts()
        app.notify(f"Alerts filter: {app.alerts_filter_mode}", timeout=2)
    else:
        app.notify("Filter modes work in holdings, activity and alerts", timeout=3)


def cycle_activity_account(app: MarketPulseApp) -> None:
    """Cycle account filter while staying on the activity workspace."""
    accounts = app.tracker.store.accounts()
    ids: list[int | None] = [None, *(a.id for a in accounts)]
    cur = ids.index(app.activity_account_filter) if app.activity_account_filter in ids else 0
    app.activity_account_filter = ids[(cur + 1) % len(ids)]
    if app.workspace != "activity":
        app.set_workspace("activity")
    app.render_activity()
    name = "all accounts"
    if app.activity_account_filter is not None:
        acct = app.tracker.store.get_account(app.activity_account_filter)
        if acct:
            name = acct.name
    app.notify(f"Activity: {name}", timeout=2)


def filter_activity_account(app: MarketPulseApp, account_id: int | None) -> None:
    app.activity_account_filter = account_id
    app.set_workspace("activity")
    app.render_activity()


def cycle_movers_mode(app: MarketPulseApp) -> None:
    modes = MOVERS_MODES
    app.movers_mode = modes[(modes.index(app.movers_mode) + 1) % len(modes)]
    if app.workspace != "dashboard":
        app.set_workspace("dashboard")
    app.render_dashboard()
    app.notify(f"Movers: {app.movers_mode}", timeout=2)


def step_year(app: MarketPulseApp, delta: int) -> None:
    """Step the selected year on the tax or income workspace (or return to all years)."""
    if app.workspace == "tax":
        if app._tax is None:
            app.notify("Tax report still loading", timeout=2)
            return
        years = sorted({y.year for y in app._tax[0]})
        if not years:
            app.notify("No tax years to select", timeout=2)
            return
        choices: list[int | None] = [None, *years]
        cur = choices.index(app.tax_year) if app.tax_year in choices else 0
        app.tax_year = choices[(cur + delta) % len(choices)]
        app.render_tax()
        app.notify(f"Tax year: {app.tax_year or 'all'}", timeout=2)
    elif app.workspace == "income":
        state = app.tracker.store.ledger()
        years = sorted({int(e.date[:4]) for e in state.income})
        if not years:
            app.notify("No income years to select", timeout=2)
            return
        choices = [None, *years]
        cur = choices.index(app.income_year) if app.income_year in choices else 0
        app.income_year = choices[(cur + delta) % len(choices)]
        app.render_income()
        app.notify(f"Income year: {app.income_year or 'all'}", timeout=2)
    else:
        app.notify("Year stepping works in tax and income", timeout=3)


def set_tax_year(app: MarketPulseApp, year: int | None) -> None:
    app.tax_year = year
    app.set_workspace("tax")
    app.render_tax()


def set_income_year(app: MarketPulseApp, year: int | None) -> None:
    app.income_year = year
    app.set_workspace("income")
    app.render_income()


def rearm_triggered_alerts(app: MarketPulseApp) -> None:
    with app.tracker.store.transaction():
        triggered = [a for a in app.tracker.store.alerts() if a.triggered_at]
        for a in triggered:
            a.active = True
            a.triggered_at = ""
            app.tracker.store.update_alert(a)
    if not triggered:
        app.notify("No triggered alerts to re-arm", timeout=2)
        return
    app.render_alerts()
    app.notify(f"Re-armed {len(triggered)} alert{'' if len(triggered) == 1 else 's'}", timeout=2)


def bulk_alerts_active(app: MarketPulseApp, active: bool) -> None:
    with app.tracker.store.transaction():
        changed = [a for a in app.tracker.store.alerts() if a.active != active]
        for a in changed:
            a.active = active
            app.tracker.store.update_alert(a)
    if not changed:
        app.notify("All alerts already " + ("active" if active else "paused"), timeout=2)
        return
    app.render_alerts()
    verb = "Resumed" if active else "Paused"
    app.notify(f"{verb} {len(changed)} alert{'' if len(changed) == 1 else 's'}", timeout=2)


def create_backup(app: MarketPulseApp) -> None:
    path = app.tracker.store.backup(reason="manual")
    app.notify(f"Backup saved: {path.name}", timeout=3)


def focus_workspace_input(app: MarketPulseApp) -> None:
    """F2: focus the current workspace's filter or chart input."""
    ws = app.workspace
    if ws == "holdings":
        show_holdings_filter(app)
    elif ws == "activity":
        app.query_one("#activity-filter", Input).focus()
    elif ws == "chart":
        app.query_one("#chart-input", Input).focus()
    else:
        app.notify("No text input in this workspace", timeout=2)


def restore_auto_theme(app: MarketPulseApp) -> None:
    app.config.theme = "auto"
    app.config.save()
    app._auto_theme = True
    target = resolve_palette("auto").name
    app.theme = target
    app.notify(f"Theme: Auto ({pretty_name(target)})", timeout=2)


# A quantity or amount in an English message, but not part of a symbol (0700.HK) or a date.
_NUMBER = re.compile(r"(?<![\w.])(?<!\d-)\d[\d,]*(?:\.\d+)?(?!\w|\.\w|-\d)")


def problems(app: MarketPulseApp) -> list[tuple[str, list[str]]]:
    """What needs attention, from the ledger replay and the last refresh; nothing is fetched.

    Privacy mode masks the quantities and amounts in the messages, as the tables do.
    """

    def shown(text: str) -> str:
        return _NUMBER.sub(fmt.MASK, text) if app.privacy else text

    issues = [
        "  ".join(part for part in (i.date, f"#{i.txn_id}" if i.txn_id is not None else "", shown(i.message)) if part)
        for i in app.tracker.store.ledger().issues
    ]
    v = app.view
    left_out = [shown(text) for text in v.excluded] if v else []
    if v is not None:
        left_out += [f"Archived {name} still holds value" for name in v.archived_with_value]
    errors = {**(v.errors if v else {}), **app.watch_errors}
    quotes = [f"{symbol}: {message}" for symbol, message in sorted(errors.items())]
    return [("Ledger issues", issues), ("Left out of net worth", left_out), ("Quotes unavailable", quotes)]


def show_problems(app: MarketPulseApp) -> None:
    app.push_screen(ProblemsScreen(problems(app)))


def chart_selected(app: MarketPulseApp) -> None:
    symbol = app.context_symbol()
    if symbol:
        app.open_chart(symbol)
    else:
        app.notify("Select a row with a symbol first", timeout=3)


def symbol_activity(app: MarketPulseApp) -> None:
    symbol = app.context_symbol()
    if not symbol:
        app.notify("Select a row with a symbol first", timeout=3)
        return
    app.query_one("#activity-filter", Input).value = f"={symbol}"  # exact: A doesn't match AAPL
    app.set_workspace("activity")
    app.render_activity()


# ── pickers, overlays, zoom ───────────────────────────────────────────────────


def pick_transaction(app: MarketPulseApp) -> None:
    def picked(kind: str | None) -> None:
        if kind:
            app.action_trade(kind)

    app.push_screen(TxnTypeScreen(TXN_CHOICES), picked)


def workspace_keys(app: MarketPulseApp) -> None:
    ws = app.workspace
    hints = []
    for chunk in HINTS.get(ws, "").split(" · "):
        key, _, desc = chunk.partition(" ")
        if key:
            hints.append((key, desc))
    label = _LABELS.get(ws, ws)
    sections = [
        (f"{label} workspace", hints),
        ("Also here", WORKSPACE_KEYS.get(ws, [])),
        ("Everywhere", GLOBAL_KEYS),
    ]
    app.push_screen(WorkspaceKeysScreen(f"Keys · {label}", sections))


def toggle_zoom(app: MarketPulseApp) -> None:
    zoomed = not app.has_class("-zoom")
    app.set_class(zoomed, "-zoom")
    app.notify("Zoom on — side panes hidden" if zoomed else "Zoom off", timeout=2)


# ── command-palette targets ───────────────────────────────────────────────────


def set_nw_range(app: MarketPulseApp, value: str) -> None:
    if value in NW_RANGES:
        app.nw_range = value
        app.set_workspace("dashboard")
        app.render_dashboard()


def set_chart_period(app: MarketPulseApp, period: str) -> None:
    if period not in PERIODS:
        return
    app.chart_period = period
    if app.chart_symbol:
        app.open_chart(app.chart_symbol)
    else:
        app.render_chart_info()
        app.notify(f"Chart period {period} — pick a symbol with /", timeout=3)


def filter_holdings_account(app: MarketPulseApp, account_id: int | None) -> None:
    app.account_filter = account_id
    app._detail_key = None
    app.render_holdings()
    app.set_workspace("holdings")


# ── footer ────────────────────────────────────────────────────────────────────


def refresh_age(app: MarketPulseApp, now: float | None = None) -> str:
    if app.refreshed_at is None:
        return ""
    seconds = max(0, int((time.monotonic() if now is None else now) - app.refreshed_at))
    if seconds < 60:
        return f"updated {seconds}s ago"
    if seconds < 3600:
        return f"updated {seconds // 60}m ago"
    return f"updated {seconds // 3600}h ago"


def footer_status(app: MarketPulseApp) -> Text:
    """Row position of the workspace's table and the age of the last refresh, for the hints line."""
    p = app.palette
    t = Text()
    position = row_position(app)
    if position:
        t.append(f"row {position[0]}/{position[1]}   ", style=p.muted)
    age = refresh_age(app)
    if age:
        t.append(f"{age}   ", style=p.muted)
    return t
