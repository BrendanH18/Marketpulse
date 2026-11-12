"""Command palette discovery and search."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from textual.command import DiscoveryHit, Hit, Hits, Provider

from ..market import PERIODS
from ..themes import pretty_name, theme_names
from . import navigation
from .constants import ALLOC_MODES, NW_RANGES
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
            (f"Theme: {pretty_name(n)}", "Omarchy theme", partial(setattr, app, "theme", n)) for n in theme_names()
        ]
        entries += [(f"Chart {s}", "Open chart", partial(app.open_chart, s)) for s in app.known_symbols()]
        entries += self._view_actions(app)
        entries += self._selection_actions(app)
        entries += self._productivity_actions(app)
        return entries

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
