"""The capital gains tax report, and ways to inspect its dispositions."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TextIO

import click
from rich.text import Text

from .. import fmt, render
from ..analytics import TaxYear, disposition_note
from ..ledger import LedgerIssue
from ..models import EPSILON, Account
from ..tax import Disposition
from .base import App, fail, pass_app
from .root import main

KINDS = ["sale", "roc", "deemed"]
SORTS = ["date", "symbol", "account", "proceeds", "acb", "gain", "denied"]
NOTE = Text(
    "\nEstimates only — confirm figures against your broker slips (T5008/T3/T5) before filing."
    "\nPurchases by a spouse or a corporation you control can also make a loss superficial;"
    " MarketPulse can't see those.",
    style="muted",
)


@dataclass
class _Row:
    """A disposition with its tax year and its place in the report (ledger order)."""

    year: int
    index: int
    d: Disposition


def _amount_key(value: Callable[[Disposition], float]) -> Callable[[_Row], tuple]:
    return lambda row: (value(row.d), row.d.date, row.index)


def _sort(rows: list[_Row], sort_by: str, descending: bool, accounts: dict[int, Account]) -> list[_Row]:
    """Order rows; rows missing an FX rate have no amounts, so they stay last when sorting by one."""

    def account_key(row: _Row) -> tuple:
        acct = accounts.get(row.d.account_id)
        hidden = acct is None or acct.archived  # never ordered by an archived account's name
        return (hidden, "" if hidden or acct is None else acct.name.casefold(), row.d.account_id, row.d.date, row.index)

    keys: dict[str, Callable[[_Row], tuple]] = {
        "date": lambda row: (row.d.date, row.index),
        "symbol": lambda row: (row.d.symbol, row.d.date, row.index),
        "account": account_key,
        "proceeds": _amount_key(lambda d: d.proceeds),
        "acb": _amount_key(lambda d: d.acb),
        "gain": _amount_key(lambda d: d.allowed_gain),
        "denied": _amount_key(lambda d: d.denied),
    }
    key = keys[sort_by]
    if sort_by == "account":  # archived accounts stay last in either direction
        hidden = [r for r in rows if account_key(r)[0]]
        shown = [r for r in rows if not account_key(r)[0]]
        return sorted(shown, key=key, reverse=descending) + sorted(hidden, key=key, reverse=descending)
    if sort_by in ("date", "symbol"):
        return sorted(rows, key=key, reverse=descending)
    known = sorted((r for r in rows if r.d.complete), key=key, reverse=descending)
    return known + [r for r in rows if not r.d.complete]


def _json_row(row: _Row, accounts: dict[int, Account]) -> dict[str, Any]:
    from ..desktop import disposition_row

    return {"year": row.year, **disposition_row(row.d, accounts)}


def _summary(years: list[TaxYear], rows: list[_Row]) -> list[TaxYear]:
    """Per-year totals of the selected rows, summed by TaxYear exactly as the report's own totals
    (rows missing an FX rate are counted but left out of every amount). Newest year first."""
    by_year = {y.year: TaxYear(year=y.year, inclusion_rate=y.inclusion_rate) for y in years}
    for row in rows:
        by_year[row.year].rows.append(row.d)
    return [y for y in sorted(by_year.values(), key=lambda y: y.year, reverse=True) if y.rows]


def _summary_json(y: TaxYear) -> dict[str, Any]:
    return {
        "year": y.year,
        "dispositions": len(y.rows),
        "proceeds": y.proceeds,
        "acb": y.cost,
        "denied": y.denied,
        "net_gain": y.net_gain,
        "taxable": y.taxable,
        "inclusion_rate": y.inclusion_rate,
        "missing_fx": len(y.missing_fx),
        "superficial": sum(1 for r in y.rows if r.superficial),
    }


def _write_csv(stream: TextIO, rows: list[_Row], accounts: dict[int, Account], base: str, **kw) -> None:
    from ..csvio import capital_gains_header, capital_gains_row

    writer = csv.writer(stream, **kw)
    writer.writerow(capital_gains_header(base))
    for row in rows:
        writer.writerow(capital_gains_row(row.year, row.d, accounts))


def _check_options(
    *,
    stdout_csv: bool,
    csv_file: bool,
    as_json: bool,
    count_only: bool,
    summary: bool,
    issues: bool,
    room: bool,
    exit_code: bool,
    year: int | None,
    page_info: bool,
    paged: bool,
    ordered: bool,
    filtered: bool,
    gains_only: bool,
    losses_only: bool,
    denied: bool,
    incomplete: bool,
) -> None:
    usage = click.UsageError
    if as_json and (stdout_csv or csv_file):
        raise usage("Choose one output format: --json or --csv.")
    if count_only and (as_json or stdout_csv or csv_file):
        raise usage("--count cannot be combined with --json or --csv.")
    if count_only and (paged or page_info):
        raise usage("--count cannot be combined with --limit, --offset or --page-info.")
    if sum((summary, issues, room)) > 1:
        raise usage("Choose one of --summary, --issues or --room.")
    if (summary or issues or room) and (count_only or stdout_csv or csv_file):
        raise usage("--summary, --issues and --room cannot be combined with --count or --csv.")
    if (summary or issues or room) and (paged or page_info or ordered):
        raise usage("--summary, --issues and --room cannot be combined with --sort, --descending or paging.")
    if (issues or room) and filtered:
        raise usage("--issues and --room cannot be combined with disposition filters.")
    if room and year is not None:
        raise usage("--room cannot be combined with --year.")
    if exit_code and not issues:
        raise usage("--exit-code requires --issues.")
    if page_info and not as_json:
        raise usage("--page-info requires --json.")
    if gains_only and losses_only:
        raise usage("Choose either --gains-only or --losses-only.")
    if incomplete and (gains_only or losses_only or denied):
        raise usage("--incomplete cannot be combined with --gains-only, --losses-only or --denied.")


@main.command()
@click.option("-y", "--year", type=int, default=None)
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(dir_okay=False, allow_dash=True, path_type=Path),
    default=None,
    help="Write the dispositions (the --year's, or every year's) to this CSV file instead of showing the report;"
    " '-' prints them to stdout.",
)
@click.option("--json", "as_json", is_flag=True, help="Print raw, unmasked dispositions as JSON.")
@click.option("--symbol", "symbols", multiple=True, help="Symbols containing this text, ignoring case; repeat for any.")
@click.option("-a", "--account", default=None, help="Only dispositions in this active account (name, id or type).")
@click.option("--kind", "kinds", multiple=True, type=click.Choice(KINDS, case_sensitive=False), help="Repeat for any.")
@click.option("--gains-only", is_flag=True, help="Only dispositions with a capital gain.")
@click.option("--losses-only", is_flag=True, help="Only dispositions with a capital loss (denied or not).")
@click.option("--denied", is_flag=True, help="Only dispositions with a denied loss (superficial or registered).")
@click.option("--incomplete", is_flag=True, help="Only dispositions missing an FX rate (left out of totals).")
@click.option("--sort", "sort_by", type=click.Choice(SORTS, case_sensitive=False), help="Order dispositions.")
@click.option("--descending", is_flag=True, help="Reverse the order (date order without --sort).")
@click.option("--count", "count_only", is_flag=True, help="Print only the number of matching dispositions.")
@click.option("--limit", type=click.IntRange(min=1), help="Show at most N matching dispositions.")
@click.option("--offset", type=click.IntRange(min=0), help="Skip N matching dispositions after sorting.")
@click.option("--page-info", is_flag=True, help="Wrap --json rows with total, offset and limit.")
@click.option("--summary", is_flag=True, help="Per-year totals of the matching dispositions.")
@click.option("--issues", is_flag=True, help="Only the tax report's own issues (as plain `tax` shows them).")
@click.option("--exit-code", is_flag=True, help="With --issues, exit 1 when there are any.")
@click.option("--room", is_flag=True, help="Only the contribution room table (no FX history is fetched).")
@pass_app
def tax(
    app: App,
    year: int | None,
    csv_path: Path | None,
    as_json: bool,
    symbols: tuple[str, ...],
    account: str | None,
    kinds: tuple[str, ...],
    gains_only: bool,
    losses_only: bool,
    denied: bool,
    incomplete: bool,
    sort_by: str | None,
    descending: bool,
    count_only: bool,
    limit: int | None,
    offset: int | None,
    page_info: bool,
    summary: bool,
    issues: bool,
    exit_code: bool,
    room: bool,
) -> None:
    """Capital gains (pooled ACB, trade-date FX), superficial losses and contribution room.

    \b
    Filters select rows from the full report: pooled ACB and gains never change with them."""
    stdout_csv = csv_path is not None and str(csv_path) == "-"
    csv_file = csv_path is not None and not stdout_csv
    if any(not s.strip() for s in symbols):
        raise click.UsageError("--symbol cannot be blank.")
    filtered = bool(symbols or account or kinds or gains_only or losses_only or denied or incomplete)
    ordered = sort_by is not None or descending
    paged = limit is not None or offset is not None
    _check_options(
        stdout_csv=stdout_csv,
        csv_file=csv_file,
        as_json=as_json,
        count_only=count_only,
        summary=summary,
        issues=issues,
        room=room,
        exit_code=exit_code,
        year=year,
        page_info=page_info,
        paged=paged,
        ordered=ordered,
        filtered=filtered,
        gains_only=gains_only,
        losses_only=losses_only,
        denied=denied,
        incomplete=incomplete,
    )
    tr = app.tracker
    if room:
        _show_room(app, as_json)
        return
    acct = None
    if account:
        acct = app.store.get_account(account)
        if acct is None or acct.archived:  # archived accounts are reported exactly like unknown ones
            fail(f"No active account '{account}'.")
    selecting = filtered or ordered or paged
    if csv_file and not selecting:
        assert csv_path is not None
        _export_file(app, csv_path, year)  # the accountant file, exactly as before
        return
    if not (as_json or stdout_csv or csv_file or count_only or summary or issues or selecting):
        _default_report(app, year)
        return

    with app.busy("Building tax report…"):
        years, report = tr.tax_years()
    accounts = tr.store.account_map()
    if issues:
        _show_issues(app, report.issues, year, as_json, exit_code)
        return
    if csv_file and year is not None and not any(y.year == year for y in years):
        fail(f"No capital gains or losses in {year}.")

    # The full report first, then a selection of its rows: nothing below changes a figure.
    needles = [s.strip().casefold() for s in symbols]
    wanted_kinds = {k.lower() for k in kinds}

    def keep(row: _Row) -> bool:
        d = row.d
        return (
            (year is None or row.year == year)
            and (not needles or any(n in d.symbol.casefold() for n in needles))
            and (acct is None or d.account_id == acct.saved_id)
            and (not wanted_kinds or d.kind in wanted_kinds)
            and (not gains_only or (d.complete and d.gain > EPSILON))
            and (not losses_only or (d.complete and d.gain < -EPSILON))
            and (not denied or (d.complete and d.denied > EPSILON))
            and (not incomplete or not d.complete)
        )

    every = [_Row(y.year, i, d) for y in sorted(years, key=lambda y: y.year) for i, d in enumerate(y.rows)]
    rows = [r for r in every if keep(r)]
    if summary:
        _show_summary(app, _summary(years, rows), as_json, filtered, tr.base)
        if not as_json:
            _warn_issues(app, _issue_dicts(report.issues, year), "these totals")
        return
    rows = _sort(rows, (sort_by or "date").lower(), descending, accounts)
    if count_only:
        click.echo(len(rows))
        return
    total = len(rows)
    start = offset or 0
    rows = rows[start : start + limit if limit is not None else None]
    if as_json:
        out = [_json_row(r, accounts) for r in rows]
        payload: Any = {"rows": out, "total": total, "offset": start, "limit": limit} if page_info else out
        click.echo(json.dumps(payload, ensure_ascii=False))
    elif stdout_csv:
        stream = io.StringIO()
        _write_csv(stream, rows, accounts, tr.base, lineterminator="\n")
        click.echo(stream.getvalue(), nl=False)
        for issue in report.issues:  # stdout stays pure CSV
            click.echo(f"! {issue.date} {issue.message}", err=True)
    elif csv_file:
        assert csv_path is not None
        try:
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                _write_csv(f, rows, accounts, tr.base)
        except OSError as e:
            fail(f"Couldn't write {csv_path}: {e.strerror or e}")
        app.ok(f"Exported {len(rows)} disposition(s) to {csv_path}")
        _warn_issues(app, [{"date": i.date, "message": i.message} for i in report.issues])
    else:
        _show_rows(app, rows, accounts, tr.base, total=total, start=start, paged=paged, any_rows=bool(every))
        _warn_issues(app, _issue_dicts(report.issues, year), "this report")


def _issue_dicts(found: list[LedgerIssue], year: int | None) -> list[dict]:
    return [{"date": i.date, "message": i.message} for i in found if year is None or i.date[:4] == str(year)]


def _warn_issues(app: App, issues: list[dict], what: str = "this file") -> None:
    if issues:
        # E.g. a transfer into a TFSA with no price: its deemed sale can't be in the file.
        app.warn(f"{len(issues)} issue(s) may leave sales out of {what}:")
        for issue in issues:
            app.warn(f"  {issue['date']} {issue['message']}")


def _export_file(app: App, csv_path: Path, year: int | None) -> None:
    from ..desktop import write_tax_csv

    try:
        with app.busy("Building tax report…"):
            result = write_tax_csv(app.tracker, csv_path, year)
    except ValueError as e:
        fail(str(e))
    app.ok(f"Exported {result['exported']} disposition(s) to {csv_path}")
    _warn_issues(app, result["issues"])


def _default_report(app: App, year: int | None) -> None:
    tr = app.tracker
    with app.busy("Building tax report…"):
        years, report = tr.tax_years()
        rooms = tr.room()
    app.title("Tax")
    app.console.print(
        render.tax_group(years, report, rooms, tr.store.account_map(), tr.base, privacy=app.privacy, year=year)
    )
    app.console.print(NOTE)


def _show_room(app: App, as_json: bool) -> None:
    rooms = app.tracker.room()
    if as_json:
        payload = [{**asdict(status), "accounts": [a.name for a in members]} for status, members in rooms]
        click.echo(json.dumps(payload, ensure_ascii=False))
    elif not rooms:
        app.console.print(
            Text(
                "No contribution room recorded. Set it with `marketpulse accounts room TYPE YEAR AMOUNT`.",
                style="muted",
            )
        )
    else:
        app.console.print(render.room_table(rooms, privacy=app.privacy))


def _show_issues(app: App, found: list[LedgerIssue], year: int | None, as_json: bool, exit_code: bool) -> None:
    from ..desktop import issue_row

    selected = [i for i in found if year is None or i.date[:4] == str(year)]
    if as_json:
        click.echo(json.dumps([issue_row(i) for i in selected], ensure_ascii=False))
    elif not selected:
        app.console.print(Text("No ledger issues affect the tax report.", style="muted"))
    else:
        for issue in selected:
            app.warn(f"{issue.date} {issue.message}")
    if exit_code and selected:
        raise click.exceptions.Exit(1)


def _money(value: float, privacy: bool, *, sign: bool = False) -> Text:
    # Under privacy the colour would reveal the sign, so it's dropped with the figure.
    style = "" if privacy or not sign else fmt.trend_style(value)
    return Text(fmt.money(value, sign=sign, privacy=privacy), style=style)


def _show_summary(app: App, years: list[TaxYear], as_json: bool, filtered: bool, base: str) -> None:
    if as_json:
        click.echo(json.dumps([_summary_json(y) for y in years], ensure_ascii=False))
        return
    if not years:
        message = "No dispositions match these filters." if filtered else "No realized gains in taxable accounts."
        app.console.print(Text(message, style="muted"))
        return
    privacy = app.privacy
    app.title("Tax")
    t = render.table(
        "Year",
        ("Rows", "right"),
        ("Proceeds", "right"),
        ("ACB", "right"),
        ("Denied", "right"),
        ("Net gain", "right"),
        ("Taxable", "right"),
        ("Missing FX", "right"),
        title=f"Capital gains summary{' — selected dispositions' if filtered else ''} ({base})",
    )
    for y in years:
        t.add_row(
            Text(str(y.year), style="bright"),
            Text(str(len(y.rows)), style="muted"),
            _money(y.proceeds, privacy),
            Text(fmt.money(y.cost, privacy=privacy), style="muted"),
            Text(fmt.money(y.denied, privacy=privacy) if y.denied else "—", style="warn" if y.denied else "muted"),
            _money(y.net_gain, privacy, sign=True),
            Text(f"{fmt.money(y.taxable, privacy=privacy)}  ({y.inclusion_rate:.0%})"),
            Text(str(len(y.missing_fx)) if y.missing_fx else "—", style="down" if y.missing_fx else "muted"),
        )
    app.console.print(t)
    if filtered:
        app.console.print(
            Text("Totals cover only the selected dispositions; rows missing an FX rate are left out.", style="muted")
        )
    app.console.print(NOTE)


def _show_rows(
    app: App,
    rows: list[_Row],
    accounts: dict[int, Account],
    base: str,
    *,
    total: int,
    start: int,
    paged: bool,
    any_rows: bool,
) -> None:
    app.title("Tax")
    if not rows:
        if total:
            message = "No dispositions on this page."
        elif any_rows:
            message = "No dispositions match these filters."
        else:
            message = "No realized gains in taxable accounts."
        app.console.print(Text(message, style="muted"))
        return
    privacy = app.privacy
    t = render.table(
        "Date",
        "Account",
        "Symbol",
        ("Qty", "right"),
        ("Proceeds", "right"),
        ("ACB", "right"),
        ("Gain", "right"),
        "Ccy",
        ("FX", "right"),
        "",
        title=f"Dispositions ({base})",
    )
    for row in rows:
        d = row.d
        acct = accounts.get(d.account_id)
        name = "(archived)" if acct is None or acct.archived else acct.name
        known = d.complete
        t.add_row(
            Text(d.date, style="muted"),
            Text(name, style="muted" if name == "(archived)" else ""),
            Text(d.symbol, style="bright"),
            Text(fmt.qty(d.quantity)),
            Text(fmt.money(d.proceeds, privacy=privacy)) if known else Text("—", style="muted"),
            Text(fmt.money(d.acb, privacy=privacy), style="muted") if known else Text("—", style="muted"),
            _money(d.allowed_gain, privacy, sign=True) if known else Text("—", style="muted"),
            Text(d.currency, style="muted"),
            Text(f"{d.fx:.4f}" if d.fx else "missing", style="muted" if d.fx else "down"),
            Text(disposition_note(d), style="muted" if known else "down"),
        )
    app.console.print(t)
    if paged:
        app.console.print(Text(f"Showing {start + 1}–{start + len(rows)} of {total} dispositions.", style="muted"))
    app.console.print(NOTE)
