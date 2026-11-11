"""`marketpulse snapshots`: browse recorded daily net-worth snapshots offline."""

from __future__ import annotations

import csv
import io
import json
import math
import re
from datetime import date

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


def _month_callback(ctx, param, value: str | None) -> str | None:
    if value is None:
        return None
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        raise click.BadParameter("Use YYYY-MM.")
    try:
        date.fromisoformat(value + "-01")
    except ValueError as exc:
        raise click.BadParameter("Use a valid calendar month (YYYY-MM).") from exc
    return value


def _finite_callback(ctx, param, value: float | None) -> float | None:
    if value is not None and not math.isfinite(value):
        raise click.BadParameter("Must be a finite number.")
    return value


def _exclude_dates_callback(ctx, param, values: tuple[str, ...]) -> tuple[str, ...]:
    dates = []
    for value in values:
        normalized = date_callback(ctx, param, value)
        assert normalized is not None  # Click supplies strings for a repeatable option.
        dates.append(normalized)
    return tuple(dates)


@main.command()
@click.option("--since", callback=date_callback, help="Include snapshots on or after this date.")
@click.option("--until", callback=date_callback, help="Include snapshots on or before this date.")
@click.option("--currency", help="Include only snapshots recorded in this currency.")
@click.option(
    "-n",
    "--limit",
    type=click.IntRange(min=1),
    help="Most recent N matches, oldest first; first N when ordering or pagination is requested.",
)
@click.option("--year", type=click.IntRange(min=1, max=9999), help="Only this calendar year.")
@click.option("--month", callback=_month_callback, help="Only this calendar month (YYYY-MM).")
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(["date", "net-worth", "book", "contributions", "change"]),
    help="Order by this field; use forward pagination with --limit.",
)
@click.option("--descending", is_flag=True, help="Reverse the selected order (default: date).")
@click.option("--offset", type=click.IntRange(min=0), help="Skip N ordered matches; enables forward pagination.")
@click.option("--page-info", is_flag=True, help="Include total and paging metadata; requires --json.")
@click.option("--min-net-worth", type=float, callback=_finite_callback, help="Inclusive native net-worth minimum.")
@click.option("--max-net-worth", type=float, callback=_finite_callback, help="Inclusive native net-worth maximum.")
@click.option("--changed-only", is_flag=True, help="Only snapshots with a known, nonzero recorded change.")
@click.option("--unchanged-only", is_flag=True, help="Only snapshots with a known zero recorded change.")
@click.option("--min-book", type=float, callback=_finite_callback, help="Inclusive recorded book-value minimum.")
@click.option("--max-book", type=float, callback=_finite_callback, help="Inclusive recorded book-value maximum.")
@click.option(
    "--min-contributions", type=float, callback=_finite_callback, help="Inclusive recorded contributions minimum."
)
@click.option(
    "--max-contributions", type=float, callback=_finite_callback, help="Inclusive recorded contributions maximum."
)
@click.option("--min-change", type=float, callback=_finite_callback, help="Inclusive known recorded-change minimum.")
@click.option("--max-change", type=float, callback=_finite_callback, help="Inclusive known recorded-change maximum.")
@click.option("--increases-only", is_flag=True, help="Only snapshots with a known positive recorded change.")
@click.option("--decreases-only", is_flag=True, help="Only snapshots with a known negative recorded change.")
@click.option("--unknown-change-only", is_flag=True, help="Only snapshots without a comparable previous snapshot.")
@click.option(
    "--exclude-date",
    "excluded_dates",
    multiple=True,
    callback=_exclude_dates_callback,
    help="Exclude a recorded date (YYYY-MM-DD); repeat for several.",
)
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
    year: int | None,
    month: str | None,
    sort_by: str | None,
    descending: bool,
    offset: int | None,
    page_info: bool,
    min_net_worth: float | None,
    max_net_worth: float | None,
    changed_only: bool,
    unchanged_only: bool,
    min_book: float | None,
    max_book: float | None,
    min_contributions: float | None,
    max_contributions: float | None,
    min_change: float | None,
    max_change: float | None,
    increases_only: bool,
    decreases_only: bool,
    unknown_change_only: bool,
    excluded_dates: tuple[str, ...],
) -> None:
    """Recorded daily net-worth snapshots, oldest first. Offline: no prices are fetched."""
    if since and until and since > until:
        raise click.UsageError("--since must be on or before --until.")
    if as_json and as_csv:
        raise click.UsageError("Choose one output format: --json or --csv.")
    forward_page = sort_by is not None or descending or offset is not None or page_info
    if page_info and not as_json:
        raise click.UsageError("--page-info requires --json.")
    if changed_only and unchanged_only:
        raise click.UsageError("Choose one of --changed-only or --unchanged-only.")
    if sum((increases_only, decreases_only, unchanged_only, unknown_change_only)) > 1:
        raise click.UsageError("Choose only one change direction or --unknown-change-only.")
    if unknown_change_only and (changed_only or min_change is not None or max_change is not None):
        raise click.UsageError("--unknown-change-only cannot be combined with known-change filters.")
    for field, minimum, maximum in (
        ("book", min_book, max_book),
        ("contributions", min_contributions, max_contributions),
        ("change", min_change, max_change),
    ):
        if minimum is not None and maximum is not None and minimum > maximum:
            raise click.UsageError(f"--min-{field} must be at most --max-{field}.")
    if min_net_worth is not None and max_net_worth is not None and min_net_worth > max_net_worth:
        raise click.UsageError("--min-net-worth must be at most --max-net-worth.")
    if year is not None and month is not None and month[:4] != f"{year:04d}":
        raise click.UsageError("--year and --month must refer to the same year.")
    if latest and forward_page:
        raise click.UsageError("--latest cannot be combined with ordering or pagination options.")
    if count_only and forward_page:
        raise click.UsageError("--count cannot be combined with ordering or pagination options.")
    if count_only and (as_json or as_csv or latest or limit is not None):
        raise click.UsageError("--count cannot be combined with --json, --csv, --latest or --limit.")
    if latest and limit is not None:
        raise click.UsageError("--latest cannot be combined with --limit.")
    ccy = currency.strip().upper() if currency is not None else None
    if ccy == "":
        raise click.UsageError("--currency cannot be blank.")

    every = app.store.snapshots()
    changes = _changes(every)
    excluded = set(excluded_dates)
    rows = [
        s
        for s in every
        if (not since or s.date >= since)
        and (not until or s.date <= until)
        and (ccy is None or s.currency == ccy)
        and (year is None or s.date[:4] == f"{year:04d}")
        and (month is None or s.date[:7] == month)
        and (min_net_worth is None or s.net_worth >= min_net_worth)
        and (max_net_worth is None or s.net_worth <= max_net_worth)
        and (not changed_only or changes[s.date] not in (None, 0))
        and (not unchanged_only or changes[s.date] == 0)
        and (min_book is None or s.book >= min_book)
        and (max_book is None or s.book <= max_book)
        and (min_contributions is None or s.contributions >= min_contributions)
        and (max_contributions is None or s.contributions <= max_contributions)
        and (min_change is None or ((change := changes[s.date]) is not None and change >= min_change))
        and (max_change is None or ((change := changes[s.date]) is not None and change <= max_change))
        and (not increases_only or ((change := changes[s.date]) is not None and change > 0))
        and (not decreases_only or ((change := changes[s.date]) is not None and change < 0))
        and (not unknown_change_only or changes[s.date] is None)
        and s.date not in excluded
    ]
    if count_only:
        click.echo(len(rows))
        return
    total = len(rows)
    if forward_page:
        field = (sort_by or "date").replace("-", "_")
        if field == "change":
            known = [s for s in rows if changes[s.date] is not None]
            unknown = [s for s in rows if changes[s.date] is None]
            known.sort(key=lambda s: (changes[s.date], s.date), reverse=descending)
            rows = known + sorted(unknown, key=lambda s: s.date, reverse=descending)
        else:
            rows.sort(key=lambda s: (getattr(s, field), s.date), reverse=descending)
        start = offset or 0
        rows = rows[start : start + limit if limit is not None else None]
    if latest:
        if not rows:
            fail("No matching snapshots." if every else "No snapshots recorded yet.")
        rows = rows[-1:]
    elif limit is not None and not forward_page:
        rows = rows[-limit:]

    if as_json:
        records = [_record(s, changes[s.date]) for s in rows]
        payload = (
            {"rows": records, "total": total, "offset": offset or 0, "limit": limit}
            if page_info
            else (records[0] if latest else records)
        )
        click.echo(json.dumps(payload, ensure_ascii=False))
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
