"""Keyboard navigation and productivity helpers; Textual entry points stay on the app.

Workspace history and cycling, table cursor jumps, the holdings filter, column
sorting, clipboard copies, zoom, the transaction-type picker and the footer's
row position and refresh age. Everything here only reorders, selects or copies
what the views already show; no figure is computed differently.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, TypeVar

from rich.text import Text
from textual.widgets import DataTable, Input

from ..market import PERIODS
from ..models import Transaction
from ..valuation import PositionView
from .constants import GLOBAL_KEYS, HINTS, NW_RANGES, SORT_MODES, TABLES, TXN_CHOICES, WORKSPACE_KEYS
from .screens import TxnTypeScreen, WorkspaceKeysScreen
from .widgets import WORKSPACES

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


def move_cursor(app: MarketPulseApp, delta: int) -> None:
    table = current_table(app)
    if table is None or table.row_count == 0:
        return
    row = max(0, min(table.row_count - 1, table.cursor_row + delta))
    table.move_cursor(row=row, animate=False)
    table.focus()


def jump_row(app: MarketPulseApp, last: bool) -> None:
    table = current_table(app)
    if table is None or table.row_count == 0:
        return
    table.move_cursor(row=table.row_count - 1 if last else 0, animate=False)
    table.focus()


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
    """Escape: empty the holdings or activity filter and put the cursor back in the table."""
    ws = app.workspace
    if ws == "holdings":
        box = app.query_one("#holdings-filter", Input)
        if not (box.value or box.has_class("-shown")):
            return
        box.value = ""
        box.remove_class("-shown")
        app.render_holdings()
        app.query_one("#holdings-table", DataTable).focus()
    elif ws == "activity":
        box = app.query_one("#activity-filter", Input)
        if not (box.value or box.has_focus):
            return
        box.value = ""
        app.render_activity()
        app.query_one("#activity-table", DataTable).focus()


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


def cycle_sort(app: MarketPulseApp) -> None:
    ws = app.workspace
    if ws not in SORT_MODES:
        app.notify("Sorting works in holdings and activity", timeout=3)
        return
    modes = SORT_MODES[ws]
    names = [name for name, _desc in modes]
    current = sort_state(app, ws)[0]
    app.table_sort[ws] = modes[(names.index(current) + 1) % len(modes)]
    _rerender_sorted(app, ws)


def reverse_sort(app: MarketPulseApp) -> None:
    ws = app.workspace
    if ws not in SORT_MODES:
        app.notify("Sorting works in holdings and activity", timeout=3)
        return
    name, descending = sort_state(app, ws)
    app.table_sort[ws] = (name, not descending)
    _rerender_sorted(app, ws)


def _rerender_sorted(app: MarketPulseApp, ws: str) -> None:
    if ws == "holdings":
        app.render_holdings()
    else:
        app.render_activity()
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


# ── clipboard, chart, transactions ────────────────────────────────────────────


def copy_symbol(app: MarketPulseApp) -> None:
    symbol = app.context_symbol()
    if not symbol:
        app.notify("Select a row with a symbol first", timeout=3)
        return
    app.copy_to_clipboard(symbol)
    app.notify(f"Copied {symbol}", timeout=2)


def copy_row(app: MarketPulseApp) -> None:
    """Copy the selected row as tab-separated text, exactly as shown (privacy masks included)."""
    table = current_table(app)
    if table is None or table.row_count == 0:
        app.notify("No table row selected", timeout=3)
        return
    cells = table.get_row_at(min(table.cursor_row, table.row_count - 1))
    text = "\t".join(c.plain if isinstance(c, Text) else str(c) for c in cells)
    app.copy_to_clipboard(text)
    app.notify(f"Copied row {table.cursor_row + 1}", timeout=2)


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
