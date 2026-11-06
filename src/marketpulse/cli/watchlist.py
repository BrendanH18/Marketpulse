"""Watchlist and price alerts."""

from __future__ import annotations

import time

import click
from rich.console import Group
from rich.text import Text

from .. import render
from ..models import ALERT_CONDITIONS, Alert, parse_symbols
from .base import App, fail, pass_app
from .root import main


@main.group(invoke_without_command=True)
@click.pass_context
def watch(ctx: click.Context) -> None:
    """Watchlist."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(watch_list)


@watch.command("list")
@pass_app
def watch_list(app: App) -> None:
    with app.busy("Fetching watchlist…"):
        symbols, quotes, errors = app.tracker.watchlist_quotes()
    if not symbols:
        app.console.print(Text("Watchlist is empty — `marketpulse watch add NVDA XEQT.TO`.", style="muted"))
        return
    app.console.print(render.quotes_table(symbols, quotes, errors, width=app.console.width))


@watch.command("add")
@click.argument("symbols", nargs=-1, required=True)
@pass_app
def watch_add(app: App, symbols) -> None:
    added = app.store.add_watch(parse_symbols(" ".join(symbols)))
    app.ok(f"Watching {', '.join(added)}" if added else "Already on the watchlist.")


@watch.command("rm")
@click.argument("symbols", nargs=-1, required=True)
@pass_app
def watch_rm(app: App, symbols) -> None:
    removed = app.store.remove_watch(parse_symbols(" ".join(symbols)))
    app.ok(f"Removed {', '.join(removed)}" if removed else "Nothing removed.")


@watch.command("live")
@click.option("-r", "--refresh", type=int, default=15, show_default=True)
@pass_app
def watch_live(app: App, refresh: int) -> None:
    """Continuously refreshing watchlist (Ctrl+C to stop)."""
    from rich.live import Live

    tr = app.tracker
    try:
        with Live(console=app.console, auto_refresh=False) as live:
            while True:
                symbols, quotes, errors = tr.watchlist_quotes(use_cache=False)
                footer = Text(f"updated {time.strftime('%H:%M:%S')} · every {refresh}s · ctrl+c to stop", style="muted")
                live.update(
                    Group(
                        render.strip_text(tr.market_strip()),
                        Text(""),
                        render.quotes_table(symbols, quotes, errors, width=app.console.width),
                        footer,
                    ),
                    refresh=True,
                )
                time.sleep(max(refresh, 5))
    except KeyboardInterrupt:
        pass


_CONDITION_ALIASES = {">": "above", ">=": "above", "<": "below", "<=": "below", "up": "up_pct", "down": "down_pct"}


@main.group(invoke_without_command=True)
@click.pass_context
def alerts(ctx: click.Context) -> None:
    """Price alerts with desktop notifications."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(alerts_list)


@alerts.command("list")
@pass_app
def alerts_list(app: App) -> None:
    items = app.store.alerts()
    if not items:
        app.console.print(Text("No alerts — `marketpulse alerts add NVDA above 200`.", style="muted"))
        return
    t = render.table(("ID", "right"), "Alert", "State", "Note")
    for a in items:
        state = (
            Text("● triggered", style="warn")
            if a.triggered_at
            else Text("armed" if a.active else "paused", style="muted")
        )
        t.add_row(
            Text(str(a.id), style="muted"), Text(a.describe(), style="bright"), state, Text(a.note, style="muted")
        )
    app.console.print(t)


@alerts.command("add")
@click.argument("symbol")
@click.argument("condition")
@click.argument("threshold", type=float)
@click.option("-m", "--note", default="")
@pass_app
def alerts_add(app: App, symbol, condition, threshold, note) -> None:
    """CONDITION: above | below | up_pct | down_pct (or > < up down)."""
    cond = _CONDITION_ALIASES.get(condition.lower(), condition.lower())
    if cond not in ALERT_CONDITIONS:
        fail(f"Condition must be one of: {', '.join(ALERT_CONDITIONS)}")
    try:
        alert = app.store.add_alert(Alert(symbol=symbol, condition=cond, threshold=threshold, note=note))
    except ValueError as e:
        fail(str(e))
    app.ok(f"Alert #{alert.id}: {alert.describe()}")


@alerts.command("rm")
@click.argument("alert_id", type=int)
@pass_app
def alerts_rm(app: App, alert_id: int) -> None:
    app.store.delete_alert(alert_id)
    app.ok(f"Removed alert #{alert_id}.")


@alerts.command("check")
@click.option("-q", "--quiet", is_flag=True)
@pass_app
def alerts_check(app: App, quiet: bool) -> None:
    """Evaluate alerts now and send notifications (cron/launchd friendly)."""
    fired = app.tracker.check_alerts(notify=True)
    if not quiet:
        for a in fired:
            app.ok(f"Fired: {a.describe()}")
        if not fired:
            app.console.print(Text("No alerts fired.", style="muted"))
