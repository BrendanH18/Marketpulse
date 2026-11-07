"""Actions helpers for the terminal app; Textual entry points stay on the app."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from textual.widgets import DataTable, Input

from ..alerts import notify as desktop_notify
from ..themes import pretty_name, theme_names
from .constants import ALLOC_MODES, NW_RANGES
from .screens import AlertForm, HelpScreen, PromptScreen, SearchScreen

if TYPE_CHECKING:
    from .app import MarketPulseApp


def action_alert(app: MarketPulseApp) -> None:
    def done(alert) -> None:
        if alert is not None:
            app.tracker.store.add_alert(alert)
            app.render_alerts()
            app.notify(f"Alert set: {alert.describe()}")

    app.push_screen(AlertForm(app.context_symbol()), done)


def action_toggle_alert(app: MarketPulseApp) -> None:
    if app.workspace != "alerts":
        return
    key = app._selected_key(app.query_one("#alerts-table", DataTable))
    alert = next((a for a in app.tracker.store.alerts() if str(a.id) == key), None)
    if alert:
        alert.active = not alert.active
        alert.triggered_at = ""
        app.tracker.store.update_alert(alert)
        app.render_alerts()


def action_watch_add(app: MarketPulseApp, prompt: bool = False) -> None:
    sym = "" if prompt else app.context_symbol()

    def add(symbol: str | None) -> None:
        if not symbol:
            return
        added = app.tracker.store.add_watch([symbol])
        app.notify(f"Watching {symbol}" if added else f"{symbol} is already on the watchlist")
        if added:
            app.watch_symbols = app.tracker.store.watchlist()
            app.render_watchlist()
            app.load_data()

    if sym:
        add(sym)
    else:
        app.push_screen(SearchScreen(app.tracker, app.known_symbols(), "Add to watchlist"), add)


def action_move_watch(app: MarketPulseApp, delta: int) -> None:
    if app.workspace != "watchlist":
        return
    sym = app.context_symbol()
    if sym:
        app.tracker.store.move_watch(sym, delta)
        app.watch_symbols = app.tracker.store.watchlist()
        app.render_watchlist()


def action_search(app: MarketPulseApp) -> None:
    if app.workspace == "activity":
        app.query_one("#activity-filter", Input).focus()
        return

    def picked(symbol: str | None) -> None:
        if symbol:  # None/empty when the search was cancelled
            app.open_chart(symbol)

    app.push_screen(SearchScreen(app.tracker, app.known_symbols(), "Open chart"), picked)


def action_filter_account(app: MarketPulseApp) -> None:
    ids = [None, *(a.id for a in app.tracker.store.accounts())]
    app.account_filter = ids[(ids.index(app.account_filter) + 1) % len(ids)] if app.account_filter in ids else None
    app._detail_key = None
    app.render_holdings()
    if app.workspace != "holdings":
        app.set_workspace("holdings")


def action_cycle_alloc(app: MarketPulseApp) -> None:
    app.alloc_mode = ALLOC_MODES[(ALLOC_MODES.index(app.alloc_mode) + 1) % len(ALLOC_MODES)]
    app.render_dashboard()


def action_nw_range(app: MarketPulseApp, delta: int) -> None:
    if app.workspace != "dashboard":
        return
    app.nw_range = NW_RANGES[max(0, min(len(NW_RANGES) - 1, NW_RANGES.index(app.nw_range) + delta))]
    app.render_dashboard()


def action_import_csv(app: MarketPulseApp) -> None:
    def done(path: str | None) -> None:
        if path:
            app.import_csv(path)

    app.push_screen(
        PromptScreen(
            "Import transactions from CSV",
            "~/Downloads/activities.csv",
            hint="Detects Questrade and Wealthsimple exports and common columns; duplicates are skipped.",
        ),
        done,
    )


def import_csv(app: MarketPulseApp, path: str) -> None:
    from ..csvio import import_transactions

    store = app.tracker.store
    try:
        result = import_transactions(store, Path(path).expanduser(), default_account=next(iter(store.accounts()), None))
    except (OSError, ValueError) as e:
        app.call_from_thread(app.notify, str(e), title="Import failed", severity="error")
        return
    message = f"Imported {result.added} · {result.duplicates} duplicates · {len(result.skipped)} skipped"
    if result.profile != "generic":
        message = f"{result.profile_label}: {message}"
    if result.backup is not None:
        # Same safety net as the CLI: name the file that undoes this import.
        message += f"\nbackup: {result.backup.name}"
    app.call_from_thread(app.after_change, message)


def action_export_csv(app: MarketPulseApp) -> None:
    default = str(Path.home() / f"marketpulse-{date.today():%Y%m%d}.csv")

    def done(path: str | None) -> None:
        if not path:
            return
        from ..csvio import export_transactions

        target = Path(path).expanduser()
        try:
            with target.open("w", newline="", encoding="utf-8") as f:
                n = export_transactions(app.tracker.store, f)
        except OSError as e:
            app.notify(str(e), severity="error")
            return
        app.notify(f"Exported {n} transactions → {target}")

    app.push_screen(PromptScreen("Export ledger to CSV", default, default), done)


def action_backfill(app: MarketPulseApp) -> None:
    app.call_from_thread(app.notify, "Rebuilding history from your ledger…", title="Backfill")
    try:
        n = app.tracker.backfill()
    except Exception as e:
        app.call_from_thread(app.notify, str(e), title="Backfill failed", severity="error")
        return
    app.call_from_thread(app.after_change, f"Rebuilt {n:,} daily snapshots")


def action_privacy(app: MarketPulseApp) -> None:
    app.config.privacy = not app.config.privacy
    app.config.save()
    app.refresh_all_views()
    app.notify("Privacy mode on — amounts hidden" if app.privacy else "Privacy mode off")


def action_next_theme(app: MarketPulseApp) -> None:
    names = theme_names()
    current = app.theme if app.theme in names else names[0]
    app.theme = names[(names.index(current) + 1) % len(names)]
    app.notify(pretty_name(app.theme), title="Theme", timeout=2)


def action_help(app: MarketPulseApp) -> None:
    app.push_screen(HelpScreen())


def notify_desktop(app: MarketPulseApp, title: str, message: str) -> None:
    desktop_notify(title, message)
