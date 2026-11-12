"""Watchlist and price alerts."""

from __future__ import annotations

import csv
import io
import json
import math
import time
from collections import Counter
from dataclasses import asdict, fields

import click
from rich.console import Group
from rich.text import Text

from .. import fmt, render
from ..models import ALERT_CONDITIONS, Alert, parse_symbols
from .base import App, date_callback, fail, pass_app
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
@click.option("--search", help="Offline symbol substring filter (case-insensitive).")
@click.option("--offset", type=click.IntRange(min=0), help="Skip matching symbols (implies offline).")
@click.option("--limit", type=click.IntRange(min=1), help="Maximum matching symbols (implies offline).")
@click.option("--count", "count_only", is_flag=True, help="Count matches before pagination, offline.")
@click.option("--alphabetical", is_flag=True, help="Sort offline output without changing saved order.")
@click.option("--csv", "as_csv", is_flag=True, help="Export saved positions and symbols offline as CSV.")
@click.option("--descending", is_flag=True, help="Reverse offline output before pagination.")
@click.option("--exclude-symbol", "excluded_symbols", multiple=True, help="Exclude exact symbols; repeat for several.")
@click.option("--symbol", "included_symbols", multiple=True, help="Include exact symbols; repeat for several, offline.")
@click.option("--min-position", type=click.IntRange(min=1), help="Minimum saved position, inclusive, offline.")
@click.option("--max-position", type=click.IntRange(min=1), help="Maximum saved position, inclusive, offline.")
@click.option(
    "--with-alert/--without-alert", default=None, help="Match symbols with or without any saved alert, offline."
)
@click.option("--page-info", is_flag=True, help="With --json, include pagination metadata.")
@click.option("--held/--not-held", default=None, help="Match symbols held in active accounts, offline.")
@click.option("--cached/--not-cached", default=None, help="Match symbols with a saved quote, offline.")
@click.option("--suffix", help="Match a symbol suffix, ignoring case; e.g. .TO, offline.")
@click.option("--exclude-search", help="Exclude symbols containing this text, ignoring case, offline.")
@click.option("--lines", is_flag=True, help="Print one saved symbol per line, offline.")
@pass_app
def watch_list(
    app: App,
    offline: bool,
    as_json: bool,
    search: str | None,
    offset: int | None,
    limit: int | None,
    count_only: bool,
    alphabetical: bool,
    as_csv: bool,
    descending: bool,
    excluded_symbols: tuple[str, ...],
    page_info: bool,
    included_symbols: tuple[str, ...],
    min_position: int | None,
    max_position: int | None,
    with_alert: bool | None,
    held: bool | None,
    cached: bool | None,
    suffix: str | None,
    exclude_search: str | None,
    lines: bool,
) -> None:
    """List watched symbols; filters, paging and reports imply offline output."""
    if sum((as_json, as_csv, count_only, lines)) > 1:
        raise click.UsageError("Choose one of --json, --csv, --count or --lines.")
    if page_info and not as_json:
        raise click.UsageError("--page-info requires --json.")
    included = _symbol_selection(included_symbols, "--symbol")
    if min_position is not None and max_position is not None and min_position > max_position:
        raise click.UsageError("--min-position must be at most --max-position.")
    for option, value in (("--suffix", suffix), ("--exclude-search", exclude_search)):
        if value is not None and not value.strip():
            raise click.UsageError(f"{option} cannot be blank.")
    if (
        held is not None
        or cached is not None
        or suffix is not None
        or exclude_search is not None
        or lines
        or included
        or min_position is not None
        or max_position is not None
        or with_alert is not None
        or as_csv
        or descending
        or excluded_symbols
        or page_info
        or offline
        or as_json
        or search is not None
        or offset is not None
        or limit is not None
        or count_only
        or alphabetical
    ):
        saved = app.store.watchlist()
        excluded = {symbol.strip().upper() for symbol in excluded_symbols}
        alerted = {a.symbol for a in app.store.alerts()} if with_alert is not None else set()
        active = {a.id for a in app.store.accounts()} if held is not None else set()
        held_symbols = (
            {h.symbol for h in app.store.ledger().open_holdings() if h.account_id in active}
            if held is not None
            else set()
        )
        cached_symbols = set(app.store.cached_quotes(saved)) if cached is not None else set()
        symbols = [
            symbol
            for position, symbol in enumerate(saved, 1)
            if (search or "").casefold() in symbol.casefold()
            and symbol not in excluded
            and (not included or symbol in included)
            and (min_position is None or position >= min_position)
            and (max_position is None or position <= max_position)
            and (with_alert is None or (symbol in alerted) == with_alert)
            and (held is None or (symbol in held_symbols) == held)
            and (cached is None or (symbol in cached_symbols) == cached)
            and (suffix is None or symbol.casefold().endswith(suffix.strip().casefold()))
            and (exclude_search is None or exclude_search.strip().casefold() not in symbol.casefold())
        ]
        total = len(symbols)
        if count_only:
            click.echo(len(symbols))
            return
        if alphabetical:
            symbols.sort()
        if descending:
            symbols.reverse()
        start = offset or 0
        symbols = symbols[start:] if limit is None else symbols[start : start + limit]
        if lines:
            if symbols:
                click.echo("\n".join(symbols))
        elif as_csv:
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=["position", "symbol"])
            writer.writeheader()
            writer.writerows({"position": saved.index(symbol) + 1, "symbol": symbol} for symbol in symbols)
            click.echo(stream.getvalue(), nl=False)
        elif as_json:
            payload = (
                {
                    "total": total,
                    "offset": start,
                    "limit": limit,
                    "returned": len(symbols),
                    "next_offset": start + len(symbols) if start + len(symbols) < total else None,
                    "items": symbols,
                }
                if page_info
                else symbols
            )
            click.echo(json.dumps(payload, ensure_ascii=False))
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


def _symbol_selection(values: tuple[str, ...], option: str) -> set[str]:
    symbols = {value.strip().upper() for value in values}
    if "" in symbols:
        raise click.UsageError(f"{option} cannot be blank.")
    return symbols


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
@click.option("--csv", "as_csv", is_flag=True, help="Export raw, unmasked alert metadata as CSV, offline.")
@click.option("--search", help="Find symbol or note text, ignoring case.")
@click.option(
    "--sort", "sort_by", type=click.Choice(["id", "symbol", "state", "condition", "threshold", "triggered-at"])
)
@click.option("--min-threshold", type=float, help="Inclusive finite threshold minimum, in the condition's units.")
@click.option("--max-threshold", type=float, help="Inclusive finite threshold maximum, in the condition's units.")
@click.option("--with-note", is_flag=True, help="Only alerts with a nonblank note.")
@click.option("--without-note", is_flag=True, help="Only alerts with an empty or whitespace-only note.")
@click.option("--triggered-since", callback=date_callback, help="Trigger date on or after YYYY-MM-DD.")
@click.option("--triggered-until", callback=date_callback, help="Trigger date on or before YYYY-MM-DD.")
@click.option("--exclude-symbol", "excluded_symbols", multiple=True, help="Exclude exact symbols; repeat for several.")
@click.option("--page-info", is_flag=True, help="With --json, include pagination metadata.")
@click.option("--descending", is_flag=True, help="Reverse output before pagination.")
@click.option("--limit", type=click.IntRange(min=1), help="Show at most this many matching alerts.")
@click.option("--offset", type=click.IntRange(min=0), default=0, help="Skip matching alerts.")
@click.option("--symbols", "included_symbols", multiple=True, help="Include exact symbols; repeat for several.")
@click.option(
    "--exclude-state",
    "excluded_states",
    multiple=True,
    type=click.Choice(["armed", "paused", "triggered"], case_sensitive=False),
    help="Exclude alert states; repeat for several.",
)
@click.option("--note", help="Find text only in notes, ignoring case.")
@click.option(
    "--summary",
    type=click.Choice(["symbol", "state", "condition", "trigger-month"]),
    help="Count matches by field before paging.",
)
@click.option(
    "--id",
    "included_ids",
    multiple=True,
    type=click.IntRange(min=1),
    help="Include exact alert IDs; repeat for several.",
)
@click.option("--min-id", type=click.IntRange(min=1), help="Inclusive saved alert ID minimum.")
@click.option("--max-id", type=click.IntRange(min=1), help="Inclusive saved alert ID maximum.")
@click.option(
    "--exclude-condition",
    "excluded_conditions",
    multiple=True,
    type=click.Choice(ALERT_CONDITIONS, case_sensitive=False),
)
@click.option("--watched/--not-watched", default=None, help="Match alerts whose symbol is on the saved watchlist.")
@click.option(
    "--ever-triggered/--never-triggered", default=None, help="Match retained trigger history, including paused alerts."
)
@pass_app
def alerts_list(
    app: App,
    symbol: str | None,
    state: str | None,
    as_json: bool,
    condition: str | None,
    count_only: bool,
    as_csv: bool,
    search: str | None,
    sort_by: str | None,
    descending: bool,
    limit: int | None,
    offset: int,
    min_threshold: float | None,
    max_threshold: float | None,
    with_note: bool,
    without_note: bool,
    triggered_since: str | None,
    triggered_until: str | None,
    excluded_symbols: tuple[str, ...],
    page_info: bool,
    included_symbols: tuple[str, ...],
    excluded_states: tuple[str, ...],
    note: str | None,
    summary: str | None,
    included_ids: tuple[int, ...],
    min_id: int | None,
    max_id: int | None,
    excluded_conditions: tuple[str, ...],
    watched: bool | None,
    ever_triggered: bool | None,
) -> None:
    """List saved alerts, optionally filtered by symbol and current state."""
    if sum((as_json, as_csv, count_only)) > 1:
        raise click.UsageError("Choose one of --json, --csv or --count.")
    if page_info and not as_json:
        raise click.UsageError("--page-info requires --json.")
    if summary and (count_only or page_info):
        raise click.UsageError("--summary cannot be combined with --count or --page-info.")
    if min_id is not None and max_id is not None and min_id > max_id:
        raise click.UsageError("--min-id must be at most --max-id.")
    watched_symbols = set(app.store.watchlist()) if watched is not None else set()
    included = _symbol_selection(included_symbols, "--symbols")
    if with_note and without_note:
        raise click.UsageError("Choose one of --with-note or --without-note.")
    for name, value in (("--min-threshold", min_threshold), ("--max-threshold", max_threshold)):
        if value is not None and not math.isfinite(value):
            raise click.BadParameter("Must be a finite number.", param_hint=name)
    if min_threshold is not None and max_threshold is not None and min_threshold > max_threshold:
        raise click.UsageError("--min-threshold must be at most --max-threshold.")
    if triggered_since and triggered_until and triggered_since > triggered_until:
        raise click.UsageError("--triggered-since must be on or before --triggered-until.")
    excluded = {s.strip().upper() for s in excluded_symbols}
    if "" in excluded:
        raise click.UsageError("--exclude-symbol cannot be blank.")
    items = [
        a
        for a in app.store.alerts()
        if a.symbol not in excluded
        and (not included or a.symbol in included)
        and _alert_state(a) not in excluded_states
        and (not included_ids or a.id in included_ids)
        and (min_id is None or (a.id is not None and a.id >= min_id))
        and (max_id is None or (a.id is not None and a.id <= max_id))
        and a.condition not in excluded_conditions
        and (watched is None or (a.symbol in watched_symbols) == watched)
        and (ever_triggered is None or bool(a.triggered_at) == ever_triggered)
        and (note is None or note.casefold() in a.note.casefold())
        and (min_threshold is None or (math.isfinite(a.threshold) and a.threshold >= min_threshold))
        and (max_threshold is None or (math.isfinite(a.threshold) and a.threshold <= max_threshold))
        and (not with_note or bool(a.note.strip()))
        and (not without_note or not a.note.strip())
        and (not triggered_since or bool(a.triggered_at) and a.triggered_at[:10] >= triggered_since)
        and (not triggered_until or bool(a.triggered_at) and a.triggered_at[:10] <= triggered_until)
    ]
    if symbol is not None:
        items = [a for a in items if a.symbol == symbol.strip().upper()]
    if state is not None:
        items = [a for a in items if _alert_state(a) == state]
    if condition is not None:
        items = [a for a in items if a.condition == condition]
    if search is not None:
        items = [a for a in items if search.casefold() in a.symbol.casefold() or search.casefold() in a.note.casefold()]
    if count_only:
        click.echo(len(items))
        return
    if summary:
        counts = Counter(
            _alert_state(a)
            if summary == "state"
            else (a.triggered_at[:7] if a.triggered_at else "never")
            if summary == "trigger-month"
            else getattr(a, summary)
            for a in items
        )
        rows = [{"group": group, "count": count} for group, count in sorted(counts.items())]
        if as_json:
            click.echo(json.dumps(rows, ensure_ascii=False))
        elif as_csv:
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=["group", "count"])
            writer.writeheader()
            writer.writerows(rows)
            click.echo(stream.getvalue(), nl=False)
        else:
            table = render.table(summary.title(), ("Alerts", "right"), title="Matching alerts")
            for row in rows:
                table.add_row(Text(str(row["group"])), Text(str(row["count"])))
            app.console.print(table)
        return
    total = len(items)
    if sort_by in ("threshold", "triggered-at"):
        field = sort_by.replace("-", "_")
        known = (
            [a for a in items if math.isfinite(a.threshold)]
            if field == "threshold"
            else [a for a in items if a.triggered_at]
        )
        unknown = [a for a in items if a not in known]
        known.sort(key=lambda a: (getattr(a, field), a.id or 0), reverse=descending)
        unknown.sort(key=lambda a: a.id or 0, reverse=descending)
        items = known + unknown
    else:
        if sort_by is not None:
            items.sort(key=lambda a: ((_alert_state(a) if sort_by == "state" else getattr(a, sort_by)), a.id or 0))
        if descending:
            items.reverse()
    items = items[offset:] if limit is None else items[offset : offset + limit]
    if as_csv:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=[f.name for f in fields(Alert)] + ["state"])
        writer.writeheader()
        writer.writerows(_alert_json(a) for a in items)
        click.echo(stream.getvalue(), nl=False)
        return
    if as_json:
        records = [_alert_json(a) for a in items]
        payload = (
            {
                "items": records,
                "total": total,
                "offset": offset,
                "limit": limit,
                "returned": len(records),
                "next_offset": offset + len(records) if offset + len(records) < total else None,
            }
            if page_info
            else records
        )
        click.echo(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        return
    if not items:
        message = (
            "No alerts match these filters."
            if included_ids
            or min_id is not None
            or max_id is not None
            or excluded_conditions
            or watched is not None
            or ever_triggered is not None
            or included_symbols
            or excluded_states
            or note is not None
            or symbol is not None
            or state
            or condition
            or search is not None
            or offset
            or limit is not None
            or min_threshold is not None
            or max_threshold is not None
            or with_note
            or without_note
            or triggered_since
            or triggered_until
            or excluded_symbols
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
        description = (
            {
                "above": f"{a.symbol} ≥ {fmt.MASK}",
                "below": f"{a.symbol} ≤ {fmt.MASK}",
                "up_pct": f"{a.symbol} up {fmt.MASK}% today",
                "down_pct": f"{a.symbol} down {fmt.MASK}% today",
            }[a.condition]
            if app.privacy
            else a.describe()
        )
        t.add_row(
            Text(str(a.id), style="muted"),
            Text(description, style="bright"),
            shown_state,
            Text(a.note, style="muted"),
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
