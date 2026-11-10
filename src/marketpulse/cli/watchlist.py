"""Watchlist and price alerts."""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict

import click
from rich.console import Group
from rich.text import Text

from .. import fmt, render
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
@click.option("--offline", is_flag=True, help="List saved symbols without fetching prices.")
@click.option("--json", "as_json", is_flag=True, help="Saved symbols as JSON (offline; no prices).")
@click.option("--search", default="", help="Offline symbol substring filter (case-insensitive).")
@click.option("--offset", type=click.IntRange(min=0), help="Skip matching symbols (implies offline).")
@click.option("--limit", type=click.IntRange(min=1), help="Maximum matching symbols (implies offline).")
@click.option("--count", "count_only", is_flag=True, help="Count matches before pagination, offline.")
@click.option("--alphabetical", is_flag=True, help="Sort offline output without changing saved order.")
@pass_app
def watch_list(
    app: App,
    offline: bool,
    as_json: bool,
    search: str,
    offset: int | None,
    limit: int | None,
    count_only: bool,
    alphabetical: bool,
) -> None:
    """List watched symbols; filters, paging and reports imply offline output."""
    if offline or as_json or search or offset is not None or limit is not None or count_only or alphabetical:
        saved = app.store.watchlist()
        symbols = [symbol for symbol in saved if search.casefold() in symbol.casefold()]
        if count_only:
            click.echo(len(symbols))
            return
        if alphabetical:
            symbols.sort()
        start = offset or 0
        symbols = symbols[start:] if limit is None else symbols[start : start + limit]
        if as_json:
            click.echo(json.dumps(symbols, ensure_ascii=False))
        elif symbols:
            t = render.table(("Position", "right"), "Symbol")
            for symbol in symbols:
                position = saved.index(symbol) + 1
                t.add_row(Text(str(position), style="muted"), Text(symbol, style="bright"))
            app.console.print(t)
        else:
            message = (
                "No watchlist symbols on this page."
                if saved
                else "Watchlist is empty — `marketpulse watch add NVDA XEQT.TO`."
            )
            app.console.print(Text(message, style="muted"))
        return
    with app.busy("Fetching watchlist…"):
        symbols, quotes, errors = app.tracker.watchlist_quotes()
    if not symbols:
        app.console.print(Text("Watchlist is empty — `marketpulse watch add NVDA XEQT.TO`.", style="muted"))
        return
    app.console.print(render.quotes_table(symbols, quotes, errors, width=app.console.width))


@watch.command("move")
@click.argument("symbol")
@click.option("--to", "position", type=click.IntRange(min=1), required=True, help="New position (1 is first).")
@pass_app
def watch_move(app: App, symbol: str, position: int) -> None:
    """Move an existing symbol to a position in the saved watchlist."""
    symbol = symbol.strip().upper()
    with app.store.transaction():
        items = app.store.watchlist()
        if symbol not in items:
            fail(f"{symbol} is not on the watchlist.")
        if position > len(items):
            raise click.BadParameter(f"must be between 1 and {len(items)}", param_hint="--to")
        app.store.move_watch(symbol, position - 1 - items.index(symbol))
    app.ok(f"Moved {symbol} to position {position}.")


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
@click.option("-s", "--symbol", help="Only alerts for this symbol.")
@click.option("--state", type=click.Choice(["armed", "paused", "triggered"], case_sensitive=False))
@click.option("--json", "as_json", is_flag=True, help="Alert metadata as JSON (unmasked; offline).")
@click.option("--condition", type=click.Choice(ALERT_CONDITIONS, case_sensitive=False))
@click.option("--count", "count_only", is_flag=True, help="Print the number of matching alerts.")
@pass_app
def alerts_list(
    app: App,
    symbol: str | None,
    state: str | None,
    as_json: bool,
    condition: str | None,
    count_only: bool,
) -> None:
    """List saved alerts, optionally filtered by symbol and current state."""
    items = app.store.alerts()
    if symbol is not None:
        items = [a for a in items if a.symbol == symbol.strip().upper()]
    if state is not None:
        items = [a for a in items if _alert_state(a) == state]
    if condition is not None:
        items = [a for a in items if a.condition == condition]
    if count_only:
        click.echo(len(items))
        return
    if as_json:
        click.echo(json.dumps([_alert_json(a) for a in items], ensure_ascii=False, allow_nan=False))
        return
    if not items:
        message = (
            "No alerts match these filters."
            if symbol is not None or state or condition
            else ("No alerts — `marketpulse alerts add NVDA above 200`.")
        )
        app.console.print(Text(message, style="muted"))
        return
    t = render.table(("ID", "right"), "Alert", "State", "Note")
    for a in items:
        shown_state = (
            Text("● triggered", style="warn")
            if _alert_state(a) == "triggered"
            else Text(_alert_state(a), style="muted")
        )
        t.add_row(
            Text(str(a.id), style="muted"), Text(a.describe(), style="bright"), shown_state, Text(a.note, style="muted")
        )
    app.console.print(t)


def _alert_json(alert: Alert) -> dict:
    row = asdict(alert)
    # Invalid legacy alerts remain inspectable, but JSON has no Infinity/NaN.
    row["threshold"] = alert.threshold if math.isfinite(alert.threshold) else None
    row["state"] = _alert_state(alert)
    return row


@alerts.command("show")
@click.argument("alert_id", type=click.IntRange(min=1))
@click.option("--json", "as_json", is_flag=True, help="Print unmasked alert metadata, offline.")
@pass_app
def alerts_show(app: App, alert_id: int, as_json: bool) -> None:
    """Inspect an alert's full note, threshold, state and trigger history."""
    alert = next((a for a in app.store.alerts() if a.id == alert_id), None)
    if alert is None:
        fail(f"No alert #{alert_id}.")
    row = _alert_json(alert)
    if as_json:
        click.echo(json.dumps(row, ensure_ascii=False, allow_nan=False))
        return
    table = render.table("Field", "Value", title=f"Alert #{alert_id}")
    for field, value in row.items():
        shown = fmt.MASK if app.privacy and field == "threshold" else str(value)
        table.add_row(Text(field), Text(shown))
    app.console.print(table)


@alerts.command("edit")
@click.argument("alert_id", type=click.IntRange(min=1))
@click.option("--threshold", type=float, help="New finite, positive threshold.")
@click.option("--condition", type=click.Choice(ALERT_CONDITIONS, case_sensitive=False))
@click.option("--note", help="Replace the note; pass an empty string to clear it.")
@pass_app
def alerts_edit(app: App, alert_id: int, threshold: float | None, condition: str | None, note: str | None) -> None:
    """Edit saved criteria or notes offline, preserving state and trigger history.

    Use `alerts rearm` explicitly to clear the trigger history after an edit.
    """
    if threshold is None and condition is None and note is None:
        raise click.UsageError("Supply --threshold, --condition, or --note.")
    with app.store.transaction():
        alert = next((a for a in app.store.alerts() if a.id == alert_id), None)
        if alert is None:
            fail(f"No alert #{alert_id}.")
        if threshold is not None:
            alert.threshold = threshold
        if condition is not None:
            alert.condition = condition
        if note is not None:
            alert.note = note
        try:
            alert.validate()
        except ValueError as e:
            fail(str(e))
        app.store.update_alert(alert)
    app.ok(f"Updated alert #{alert_id}.")


def _alert_state(alert: Alert) -> str:
    if not alert.active:
        return "paused"
    return "triggered" if alert.triggered_at else "armed"


def _set_alert_state(app: App, alert_id: int, *, active: bool, rearm: bool = False) -> None:
    with app.store.transaction():
        alert = next((a for a in app.store.alerts() if a.id == alert_id), None)
        if alert is None:
            fail(f"No alert #{alert_id}.")
        if active:
            try:
                alert.validate()
            except ValueError as e:
                fail(str(e))
        alert.active = active
        if rearm:
            alert.triggered_at = ""
        app.store.update_alert(alert)
    verb = "Rearmed" if rearm else ("Resumed" if active else "Paused")
    app.ok(f"{verb} alert #{alert_id}.")


@alerts.command("pause")
@click.argument("alert_id", type=click.IntRange(min=1))
@pass_app
def alerts_pause(app: App, alert_id: int) -> None:
    """Pause an alert without clearing its trigger history."""
    _set_alert_state(app, alert_id, active=False)


@alerts.command("resume")
@click.argument("alert_id", type=click.IntRange(min=1))
@pass_app
def alerts_resume(app: App, alert_id: int) -> None:
    """Resume an alert, preserving its trigger history to avoid duplicate notifications."""
    _set_alert_state(app, alert_id, active=True)


@alerts.command("rearm")
@click.argument("alert_id", type=click.IntRange(min=1))
@pass_app
def alerts_rearm(app: App, alert_id: int) -> None:
    """Activate and clear the trigger history; the next matching fresh price can fire again."""
    _set_alert_state(app, alert_id, active=True, rearm=True)


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
