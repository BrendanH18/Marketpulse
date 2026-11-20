"""Command palette discovery and search."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from textual.command import DiscoveryHit, Hit, Hits, Provider

from ..market import PERIODS
from ..themes import pretty_name, theme_names
from . import extras, navigation
from .constants import (
    ACTIVITY_FILTER_MODES,
    ACTIVITY_WINDOWS,
    ALERT_FILTER_MODES,
    ALLOC_MODES,
    HOLDING_FILTER_MODES,
    MOVERS_MODES,
    NW_RANGES,
    SORT_MODES,
)
from .widgets import WORKSPACES

if TYPE_CHECKING:
    from .app import MarketPulseApp


class PortfolioCommands(Provider):
    """Command palette entries: every action, theme and known symbol."""

    def _entries(self) -> list[tuple[str, str, object]]:
        app: MarketPulseApp = self.app  # type: ignore[assignment]
        entries = self._actions(app)
        entries += [
            (f"Go to {label}", f"Workspace {i}", partial(app.set_workspace, key))
            for i, (key, label) in enumerate(WORKSPACES, 1)
        ]
        entries += [
            ("Theme: Auto (Omarchy)", "Follow active Omarchy theme", app.action_restore_auto_theme),
        ]
        entries += [
            (f"Theme: {pretty_name(n)}", "Omarchy theme", partial(setattr, app, "theme", n)) for n in theme_names()
        ]
        entries += [(f"Chart {s}", "Open chart", partial(app.open_chart, s)) for s in app.known_symbols()]
        entries += self._view_actions(app)
        entries += self._selection_actions(app)
        entries += self._productivity_actions(app)
        entries += self._more_actions(app)
        entries += self._workflow_actions(app)
        entries += self._sort_actions(app)
        entries += self._more_workflow_actions(app)
        return entries

    @staticmethod
    def _more_workflow_actions(app: MarketPulseApp) -> list[tuple[str, str, object]]:
        """Actions added in the second 100 CLI & TUI batch, plus direct choices their keys cycle through."""
        entries: list[tuple[str, str, object]] = [
            ("Show row details", "P · every field of the selected row", app.action_details),
            ("Add or remove from watchlist", "W · selected symbol", app.action_toggle_watch),
            ("Watch every held symbol", "Add market-priced holdings to the watchlist", app.action_watch_holdings),
            ("Show only the selected account", "; · holdings or activity", app.action_scope_account),
            ("Go to row…", ": · row number, or a date in activity", app.action_go_to),
            ("Find in table…", "ctrl+f · ctrl+g finds next", app.action_find_row),
            ("Find next", "ctrl+g", app.action_find_next),
            ("Next group", ") · account, month, symbol or type", partial(app.action_jump_group, 1)),
            ("Previous group", "( · account, month, symbol or type", partial(app.action_jump_group, -1)),
            ("Cycle activity date window", "% · all / 30d / 90d / ytd / 1y", app.action_cycle_activity_window),
            ("Next ledger issue", "ctrl+e · select the transaction", app.action_next_issue),
            ("Alerts for selected symbol", "& · escape shows all", app.action_symbol_alerts),
            ("Chart: crosshair to period high", "^", partial(app.action_chart_extreme, True)),
            ("Chart: crosshair to period low", "_", partial(app.action_chart_extreme, False)),
            ("Previous chart", "' · the symbol charted before", app.action_previous_chart),
            ("Copy chart history as CSV", "date, open, high, low, close, volume", app.action_copy_chart_csv),
            ("Copy table as JSON", '" · objects keyed by column', app.action_copy_table_json),
            ("Copy pane as text", "ctrl+t · side pane or report", app.action_copy_pane),
            ("Pause or resume automatic refresh", "ctrl+r · r still refreshes", app.action_toggle_auto_refresh),
            ("Save watchlist sort as list order", "ctrl+s · watchlist", app.action_save_watch_order),
        ]
        entries += [
            (f"Activity window: {w}", "% · activity dates", partial(extras.set_activity_window, app, w))
            for w in ACTIVITY_WINDOWS
        ]
        modes = [
            ("holdings", "Holdings mode", HOLDING_FILTER_MODES),
            ("activity", "Activity mode", ACTIVITY_FILTER_MODES),
            ("alerts", "Alerts mode", ALERT_FILTER_MODES),
            ("dashboard", "Movers", MOVERS_MODES),
        ]
        entries += [
            (f"{label}: {mode}", "M / m cycle these", partial(extras.set_filter_mode, app, ws, mode))
            for ws, label, choices in modes
            for mode in choices
        ]
        entries += [
            (f"Tax year: {year}", "- / + · tax workspace", partial(navigation.set_tax_year, app, year))
            for year in extras.tax_years(app)
        ]
        entries += [
            (f"Income year: {year}", "- / + · income by symbol", partial(navigation.set_income_year, app, year))
            for year in extras.income_years(app)
        ]
        return entries

    @staticmethod
    def _more_actions(app: MarketPulseApp) -> list[tuple[str, str, object]]:
        """Actions added under #153, each with its key."""
        return [
            ("Copy table", "ctrl+y · every row shown, with headers", app.action_copy_table),
            ("Show or hide cash rows", "$ · holdings", app.action_toggle_cash),
            ("Duplicate selected transaction", "d · activity, dated today", app.action_duplicate),
            ("Show problems", "! · ledger issues, missing prices and quotes", app.action_problems),
        ]

    @staticmethod
    def _workflow_actions(app: MarketPulseApp) -> list[tuple[str, str, object]]:
        """Workflow actions added in the 100 CLI & TUI batch, each with its key."""
        entries: list[tuple[str, str, object]] = [
            ("Copy table as CSV", "# · RFC-4180 CSV with headers", app.action_copy_table_csv),
            ("Copy table as Markdown", "X · GitHub-Flavored Markdown table", app.action_copy_table_markdown),
            ("Copy portfolio summary", "Q · net worth, today, unrealized, income", app.action_copy_summary),
            ("Show or hide archived accounts", "I · accounts workspace", app.action_toggle_archived),
            ("Reset table sort", "0 · restore default table order", app.action_reset_sort),
            ("Focus filter or chart input", "F2 · holdings, activity or chart", app.action_focus_input),
            ("Jump to symbol in holdings", "S · locate selected symbol", app.action_jump_to_holding),
            ("Cycle workspace filter mode", "M · holdings / activity / alerts", app.action_cycle_filter_mode),
            ("Cycle activity account filter", "@ · activity workspace", app.action_cycle_activity_account),
            ("Cycle dashboard movers metric", "m · day % / day $ / unrealized", app.action_cycle_movers),
            ("Re-arm triggered alerts", "U · alerts workspace", app.action_rearm_triggered),
            ("Pause all alerts", "Pause every active alert", app.action_pause_all_alerts),
            ("Resume all alerts", "Resume every paused alert", app.action_resume_all_alerts),
            ("Create database backup", "Save a manual SQLite backup", app.action_create_backup),
            (
                "Activity: all accounts",
                "Clear activity account filter",
                partial(navigation.filter_activity_account, app, None),
            ),
            ("Tax year: all", "- / + · show every tax year", partial(navigation.set_tax_year, app, None)),
            (
                "Income year: all",
                "- / + · show all-time income by symbol",
                partial(navigation.set_income_year, app, None),
            ),
        ]
        entries += [
            (
                f"Activity: {a.name}",
                "Filter activity to this account",
                partial(navigation.filter_activity_account, app, a.id),
            )
            for a in app.tracker.store.accounts()
        ]
        return entries

    @staticmethod
    def _sort_actions(app: MarketPulseApp) -> list[tuple[str, str, object]]:
        """Sort any sortable table by one column directly; `o` / `O` can only cycle and reverse."""
        return [
            (
                f"Sort {'accounts' if ws == 'tax' else ws} by {name}",
                f"o / O · {'↓' if descending else '↑'}" + (" · the usual order" if index == 0 else ""),
                partial(navigation.set_sort, app, ws, name, descending),
            )
            for ws, modes in SORT_MODES.items()
            for index, (name, descending) in enumerate(modes)
        ]

    @staticmethod
    def _view_actions(app: MarketPulseApp) -> list[tuple[str, str, object]]:
        """View actions that used to have only a key, plus direct jumps the keys can only cycle through."""
        entries: list[tuple[str, str, object]] = [
            ("Cycle allocation grouping", f"g · {' / '.join(ALLOC_MODES)}", app.action_cycle_alloc),
            ("Cycle account filter", "f · holdings by account", app.action_filter_account),
            ("Next theme", "t · cycle Omarchy themes", app.action_next_theme),
            (
                "Holdings: all accounts",
                "Clear the account filter",
                partial(navigation.filter_holdings_account, app, None),
            ),
        ]
        entries += [
            (f"Net worth range: {r}", ", / . on the dashboard", partial(navigation.set_nw_range, app, r))
            for r in NW_RANGES
        ]
        entries += [
            (
                f"Holdings: {a.name}",
                "Filter holdings to this account",
                partial(navigation.filter_holdings_account, app, a.id),
            )
            for a in app.tracker.store.accounts()
        ]
        return entries

    @staticmethod
    def _selection_actions(app: MarketPulseApp) -> list[tuple[str, str, object]]:
        """Actions on the selected row or chart that used to have only a key."""
        entries: list[tuple[str, str, object]] = [
            ("Edit selected", "e · transaction or account", app.action_edit),
            ("Delete selected", "x · transaction, watch, alert or account", app.action_delete),
            ("Pause or resume selected alert", "space · alerts workspace", app.action_toggle_alert),
            ("Compare chart with…", "c · overlay symbols as % change", app.action_compare),
            ("Clear chart comparisons", "C", app.action_clear_compare),
            ("Move watch symbol up", "K · watchlist", partial(app.action_move_watch, -1)),
            ("Move watch symbol down", "J · watchlist", partial(app.action_move_watch, 1)),
            ("Quit", "q", app.exit),
        ]
        entries += [
            (f"Chart period: {per}", "[ / ] on the chart", partial(navigation.set_chart_period, app, per))
            for per in PERIODS
        ]
        return entries

    @staticmethod
    def _productivity_actions(app: MarketPulseApp) -> list[tuple[str, str, object]]:
        """Keyboard navigation and productivity actions added under #130, each with its key."""
        return [
            ("Previous workspace", "backspace", app.action_previous_workspace),
            ("Next workspace", "}", partial(app.action_cycle_workspace, 1)),
            ("Workspace to the left", "{", partial(app.action_cycle_workspace, -1)),
            ("First row", "<", partial(app.action_row_edge, False)),
            ("Last row", ">", partial(app.action_row_edge, True)),
            ("Filter holdings", "F · as you type", app.action_filter_holdings),
            ("Clear filter", "escape · holdings or activity", app.action_clear_filter),
            ("Sort by next column", "o · holdings or activity", app.action_sort),
            ("Reverse sort", "O · holdings or activity", app.action_sort_reverse),
            ("Copy selected symbol", "y · to the clipboard", app.action_copy_symbol),
            ("Copy selected row", "Y · tab-separated", app.action_copy_row),
            ("Chart selected symbol", "v", app.action_chart_selected),
            ("Show selected symbol's transactions", "T · activity filtered", app.action_symbol_activity),
            ("Record any transaction type…", "N · picker", app.action_pick_txn),
            ("Toggle zoom", "z · hide side panes", app.action_zoom),
            ("Workspace keys", "F1", app.action_workspace_keys),
        ]

    @staticmethod
    def _actions(app: MarketPulseApp) -> list[tuple[str, str, object]]:
        """The fixed actions, shown before the user types anything."""
        return [
            ("Buy", "Record a buy", partial(app.action_trade, "BUY")),
            ("Sell", "Record a sell", partial(app.action_trade, "SELL")),
            ("Record dividend", "Cash dividend or distribution", partial(app.action_trade, "DIVIDEND")),
            ("Record DRIP", "Reinvested dividend", partial(app.action_trade, "DRIP")),
            ("Record deposit", "Money into an account", partial(app.action_trade, "DEPOSIT")),
            ("Record withdrawal", "Money out of an account", partial(app.action_trade, "WITHDRAWAL")),
            ("Record interest", "Interest income", partial(app.action_trade, "INTEREST")),
            ("Record split", "Stock split", partial(app.action_trade, "SPLIT")),
            ("Transfer in-kind", "Move shares between accounts", partial(app.action_trade, "TRANSFER")),
            ("Record return of capital", "Reduces the ACB", partial(app.action_trade, "ROC")),
            ("Record fee", "Account or management fee", partial(app.action_trade, "FEE")),
            ("Record valuation", "Mark a manual asset at a price", partial(app.action_trade, "VALUATION")),
            ("New account", "TFSA, RRSP, FHSA, non-registered…", app.action_new_account),
            ("Add GIC or manual asset", "Fixed income, property, private holdings", app.action_add_asset),
            ("Update manual asset value", "Mark a manual asset", app.action_value_asset),
            ("Set contribution room", "TFSA / RRSP / FHSA", app.action_room),
            ("New price alert", "Notify on price or % move", app.action_alert),
            ("Add to watchlist", "Search and watch a symbol", app.action_watch_add),
            ("Search symbol", "Open a chart", app.action_search),
            ("Import CSV", "Broker or MarketPulse export", app.action_import_csv),
            ("Export CSV", "Full ledger", app.action_export_csv),
            ("Backfill net worth history", "Rebuild daily snapshots from your ledger", app.action_backfill),
            ("Toggle privacy mode", "Hide amounts", app.action_privacy),
            ("Refresh quotes", "Fetch fresh prices", app.action_refresh),
            ("Undo last transaction", "Delete the most recent entry", app.action_undo),
            ("Help", "Keyboard shortcuts", app.action_help),
        ]

    async def discover(self) -> Hits:
        for name, help_text, callback in self._actions(self.app):  # type: ignore[arg-type]
            yield DiscoveryHit(name, callback, help=help_text)  # type: ignore[arg-type]

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, help_text, callback in self._entries():
            score = matcher.match(name)
            if score > 0:
                yield Hit(score, matcher.highlight(name), callback, help=help_text)  # type: ignore[arg-type]
