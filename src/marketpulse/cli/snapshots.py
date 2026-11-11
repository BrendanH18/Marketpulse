"""`marketpulse snapshots`: browse recorded daily net-worth snapshots offline."""

from __future__ import annotations

import csv
import io
import json

import click
from rich.text import Text

from .. import fmt, render
from ..db import Snapshot
from .base import App, date_callback, fail, pass_app
from .root import main

SNAPSHOT_FIELDS = ["date", "net_worth", "book", "contributions", "change", "currency"]


def _changes(snaps: list[Snapshot]) -> dict[str, float | None]:
    """Each snapshot's difference from the previous recorded one (by date), or None when
    there is no previous snapshot or the two were recorded in different currencies."""
    out: dict[str, float | None] = {}
    prev: Snapshot | None = None
    for s in snaps:
        # Rounded only to drop binary float noise (e.g. 0.09999999999999432), not to cents.
        out[s.date] = round(s.net_worth - prev.net_worth, 6) if prev and prev.currency == s.currency else None
        prev = s
    return out


def _record(s: Snapshot, change: float | None) -> dict:
    return {
        "date": s.date,
        "net_worth": s.net_worth,
        "book": s.book,
        "contributions": s.contributions,
        "change": change,
        "currency": s.currency,
    }


@main.command()
@click.option("--since", callback=date_callback, help="Include snapshots on or after this date.")
@click.option("--until", callback=date_callback, help="Include snapshots on or before this date.")
@click.option("--currency", help="Include only snapshots recorded in this currency.")
@click.option("-n", "--limit", type=click.IntRange(min=1), help="Show only the most recent N matches (oldest first).")
@click.option("--latest", is_flag=True, help="Show only the most recent matching snapshot.")
@click.option("--count", "count_only", is_flag=True, help="Print the number of matching snapshots.")
@click.option("--json", "as_json", is_flag=True, help="Print raw, unmasked snapshots as JSON.")
@click.option("--csv", "as_csv", is_flag=True, help="Print raw, unmasked snapshot CSV to stdout.")
@pass_app
def snapshots(
    app: App,
    since: str | None,
    until: str | None,
    currency: str | None,
    limit: int | None,
    latest: bool,
    count_only: bool,
    as_json: bool,
    as_csv: bool,
) -> None:
    """Recorded daily net-worth snapshots, oldest first. Offline: no prices are fetched."""
    if since and until and since > until:
        raise click.UsageError("--since must be on or before --until.")
    if as_json and as_csv:
        raise click.UsageError("Choose one output format: --json or --csv.")
    if count_only and (as_json or as_csv or latest or limit is not None):
        raise click.UsageError("--count cannot be combined with --json, --csv, --latest or --limit.")
    if latest and limit is not None:
        raise click.UsageError("--latest cannot be combined with --limit.")
    ccy = currency.strip().upper() if currency is not None else None
    if ccy == "":
        raise click.UsageError("--currency cannot be blank.")

    every = app.store.snapshots()
    changes = _changes(every)
    rows = [
        s
        for s in every
        if (not since or s.date >= since) and (not until or s.date <= until) and (ccy is None or s.currency == ccy)
    ]
    if count_only:
        click.echo(len(rows))
        return
    if latest:
        if not rows:
            fail("No matching snapshots." if every else "No snapshots recorded yet.")
        rows = rows[-1:]
    elif limit is not None:
        rows = rows[-limit:]

    if as_json:
        records = [_record(s, changes[s.date]) for s in rows]
        click.echo(json.dumps(records[0] if latest else records, ensure_ascii=False))
        return
    if as_csv:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=SNAPSHOT_FIELDS)
        writer.writeheader()
        for s in rows:
            record = _record(s, changes[s.date])
            writer.writerow({k: "" if v is None else v for k, v in record.items()})
        click.echo(stream.getvalue(), nl=False)
        return
    if not rows:
        message = (
            "No matching snapshots."
            if every
            else "No snapshots recorded yet. `marketpulse status` records today's;"
            " `marketpulse backfill` rebuilds history."
        )
        app.console.print(Text(message, style="muted"))
        return
    table = render.table(
        "Date",
        ("Net worth", "right"),
        ("Book", "right"),
        ("Change", "right"),
        "Ccy",
        title="Net-worth snapshots",
    )
    for s in rows:
        change = changes[s.date]
        change_cell = (
            Text("")
            if change is None
            else Text(fmt.money(change, privacy=True), style="muted")
            if app.privacy
            else render.trend(fmt.money(change, sign=True), change)
        )
        table.add_row(
            Text(s.date),
            Text(fmt.money(s.net_worth, privacy=app.privacy), style="bright"),
            Text(fmt.money(s.book, privacy=app.privacy), style="muted"),
            change_cell,
            Text(s.currency, style="muted"),
        )
    app.console.print(table)
