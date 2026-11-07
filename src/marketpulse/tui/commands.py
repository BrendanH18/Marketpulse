"""Command palette discovery and search."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from textual.command import DiscoveryHit, Hit, Hits, Provider

from ..themes import pretty_name, theme_names
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
        return entries

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
