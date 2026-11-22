"""The capital gains tax report, and ways to inspect its dispositions."""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TextIO

import click
from click.core import ParameterSource
from rich.text import Text

from .. import fmt, render
from ..analytics import TaxYear, disposition_note
from ..ledger import LedgerIssue
from ..models import EPSILON, Account
from ..tax import (
    FOREIGN_PROPERTY_NOTES,
    T1135_DETAILED,
    T1135_DETAILED_THRESHOLD,
    T1135_NOT_REQUIRED,
    T1135_SIMPLIFIED,
    T1135_THRESHOLD,
    T1135_UNDETERMINED,
    Disposition,
    ForeignPropertyYear,
)
from .base import App, date_callback, fail, pass_app
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


def _finite_amount(ctx: click.Context, param: click.Parameter, value: float | None) -> float | None:
    if value is not None and not math.isfinite(value):
        raise click.BadParameter("Must be a finite number.", ctx=ctx, param=param)
    return value


def _check_options(
    *,
    stdout_csv: bool,
    csv_file: bool,
    as_json: bool,
    as_jsonl: bool,
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
    superficial: bool,
    incomplete: bool,
    since: str | None,
    until: str | None,
    min_gain: float | None,
    max_gain: float | None,
) -> None:
    usage = click.UsageError
    if sum((as_json, as_jsonl, stdout_csv or csv_file)) > 1:
        raise usage("Choose one output format: --json, --jsonl or --csv.")
    if count_only and (as_json or as_jsonl or stdout_csv or csv_file):
        raise usage("--count cannot be combined with --json, --jsonl or --csv.")
    if count_only and (paged or page_info):
        raise usage("--count cannot be combined with --limit, --offset or --page-info.")
    if sum((summary, issues, room)) > 1:
        raise usage("Choose one of --summary, --issues or --room.")
    if (summary or issues or room) and (count_only or stdout_csv or csv_file or as_jsonl):
        raise usage("--summary, --issues and --room cannot be combined with --count, --jsonl or --csv.")
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
    if incomplete and (
        gains_only or losses_only or denied or superficial or min_gain is not None or max_gain is not None
    ):
        raise usage("--incomplete cannot be combined with gain/loss filters.")
    if since is not None and until is not None and since > until:
        raise usage("--since must be on or before --until.")
    if min_gain is not None and max_gain is not None and min_gain > max_gain:
        raise usage("--min-gain must be at most --max-gain.")


@main.group(invoke_without_command=True)
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
@click.option("--jsonl", "as_jsonl", is_flag=True, help="Print raw, unmasked dispositions as JSON Lines.")
@click.option("--symbol", "symbols", multiple=True, help="Symbols containing this text, ignoring case; repeat for any.")
@click.option(
    "--exact-symbol", "exact_symbols", multiple=True, help="Exact symbol match, ignoring case; repeat for any."
)
@click.option(
    "--exclude-symbol", "excluded_symbols", multiple=True, help="Exclude symbols containing this text, ignoring case."
)
@click.option(
    "--currency", "currencies", multiple=True, help="Only dispositions in this native currency; repeat for any."
)
@click.option(
    "--exclude-currency", "excluded_currencies", multiple=True, help="Exclude dispositions in this native currency."
)
@click.option("--since", callback=date_callback, help="Only dispositions on or after YYYY-MM-DD.")
@click.option("--until", callback=date_callback, help="Only dispositions on or before YYYY-MM-DD.")
@click.option("-a", "--account", default=None, help="Only dispositions in this active account (name, id or type).")
@click.option("--kind", "kinds", multiple=True, type=click.Choice(KINDS, case_sensitive=False), help="Repeat for any.")
@click.option("--gains-only", is_flag=True, help="Only dispositions with a capital gain.")
@click.option("--losses-only", is_flag=True, help="Only dispositions with a capital loss (denied or not).")
@click.option("--denied", is_flag=True, help="Only dispositions with a denied loss (superficial or registered).")
@click.option("--superficial", is_flag=True, help="Only dispositions with a superficial loss.")
@click.option("--min-gain", type=float, callback=_finite_amount, help="Only dispositions with allowed gain >= AMOUNT.")
@click.option("--max-gain", type=float, callback=_finite_amount, help="Only dispositions with allowed gain <= AMOUNT.")
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
@click.option("--room", is_flag=True, help="Only contribution room, fetching FX history when needed for room.")
@pass_app
def tax(
    app: App,
    year: int | None,
    csv_path: Path | None,
    as_json: bool,
    as_jsonl: bool,
    symbols: tuple[str, ...],
    exact_symbols: tuple[str, ...],
    excluded_symbols: tuple[str, ...],
    currencies: tuple[str, ...],
    excluded_currencies: tuple[str, ...],
    since: str | None,
    until: str | None,
    account: str | None,
    kinds: tuple[str, ...],
    gains_only: bool,
    losses_only: bool,
    denied: bool,
    superficial: bool,
    min_gain: float | None,
    max_gain: float | None,
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
    ctx = click.get_current_context()
    if ctx.invoked_subcommand is not None:
        # `tax foreign-property` and other subcommands do their own work, with their own options.
        given = [
            p.opts[-1]
            for p in ctx.command.params
            if ctx.get_parameter_source(p.name or "") is ParameterSource.COMMANDLINE
        ]
        if given:
            raise click.UsageError(
                f"{', '.join(given)} belongs to plain `tax`; put options after `{ctx.invoked_subcommand}`."
            )
        return
    stdout_csv = csv_path is not None and str(csv_path) == "-"
    csv_file = csv_path is not None and not stdout_csv
    if any(not s.strip() for s in symbols):
        raise click.UsageError("--symbol cannot be blank.")
    if any(not s.strip() for s in exact_symbols):
        raise click.UsageError("--exact-symbol cannot be blank.")
    if any(not s.strip() for s in excluded_symbols):
        raise click.UsageError("--exclude-symbol cannot be blank.")
    if any(not c.strip() for c in currencies):
        raise click.UsageError("--currency cannot be blank.")
    if any(not c.strip() for c in excluded_currencies):
        raise click.UsageError("--exclude-currency cannot be blank.")
    filtered = bool(
        symbols
        or exact_symbols
        or excluded_symbols
        or currencies
        or excluded_currencies
        or since is not None
        or until is not None
        or account
        or kinds
        or gains_only
        or losses_only
        or denied
        or superficial
        or min_gain is not None
        or max_gain is not None
        or incomplete
    )
    ordered = sort_by is not None or descending
    paged = limit is not None or offset is not None
    _check_options(
        stdout_csv=stdout_csv,
        csv_file=csv_file,
        as_json=as_json,
        as_jsonl=as_jsonl,
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
        superficial=superficial,
        incomplete=incomplete,
        since=since,
        until=until,
        min_gain=min_gain,
        max_gain=max_gain,
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
    if not (as_json or as_jsonl or stdout_csv or csv_file or count_only or summary or issues or selecting):
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
    exact_set = {s.strip().casefold() for s in exact_symbols}
    excluded_needles = [s.strip().casefold() for s in excluded_symbols]
    wanted_currencies = {c.strip().upper() for c in currencies}
    excluded_currency_set = {c.strip().upper() for c in excluded_currencies}
    wanted_kinds = {k.lower() for k in kinds}

    def keep(row: _Row) -> bool:
        d = row.d
        sym = d.symbol.casefold()
        ccy = d.currency.upper()
        return (
            (year is None or row.year == year)
            and (since is None or d.date >= since)
            and (until is None or d.date <= until)
            and (not needles or any(n in sym for n in needles))
            and (not exact_set or sym in exact_set)
            and (not excluded_needles or not any(n in sym for n in excluded_needles))
            and (not wanted_currencies or ccy in wanted_currencies)
            and (ccy not in excluded_currency_set)
            and (acct is None or d.account_id == acct.saved_id)
            and (not wanted_kinds or d.kind in wanted_kinds)
            and (not gains_only or (d.complete and d.gain > EPSILON))
            and (not losses_only or (d.complete and d.gain < -EPSILON))
            and (not denied or (d.complete and d.denied > EPSILON))
            and (not superficial or d.superficial)
            and (min_gain is None or (d.complete and d.allowed_gain >= min_gain - EPSILON))
            and (max_gain is None or (d.complete and d.allowed_gain <= max_gain + EPSILON))
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
    elif as_jsonl:
        for r in rows:
            click.echo(json.dumps(_json_row(r, accounts), ensure_ascii=False))
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


FOREIGN_ASSESSMENTS = [T1135_NOT_REQUIRED, T1135_SIMPLIFIED, T1135_DETAILED, T1135_UNDETERMINED]
FOREIGN_YEAR_FIELDS = [
    "year",
    "as_of",
    "currency",
    "status",
    "assessment",
    "required",
    "max_cost",
    "max_cost_date",
    "year_end_cost",
    "gain",
    "incomplete",
]
FOREIGN_HOLDING_FIELDS = [
    "year",
    "symbol",
    "max_cost",
    "max_cost_date",
    "year_end_cost",
    "gain",
    "dispositions",
    "incomplete",
]


def _headroom(y: ForeignPropertyYear) -> float:
    """How far the year's highest cost stayed under the $100,000 threshold (negative: over it)."""
    return round(T1135_THRESHOLD - y.max_cost, 2)


def _foreign_holding_rows(found: list[ForeignPropertyYear]) -> list[dict[str, Any]]:
    from ..desktop import foreign_property_row

    return [{"year": y.year, **h} for y in found for h in foreign_property_row(y)["holdings"]]


def _foreign_year_rows(found: list[ForeignPropertyYear], headroom: bool) -> list[dict[str, Any]]:
    from ..desktop import foreign_property_row

    rows = []
    for y in found:
        row = foreign_property_row(y)
        if headroom:
            row["headroom"] = _headroom(y)
        rows.append(row)
    return rows


@tax.command("foreign-property")
@click.option(
    "-y", "--year", type=click.IntRange(min=1900), default=None, help="One year in detail (default: every year)."
)
@click.option("--since-year", type=click.IntRange(min=1900), default=None, help="Only this year and later ones.")
@click.option("--until-year", type=click.IntRange(min=1900), default=None, help="Only this year and earlier ones.")
@click.option(
    "--status",
    "statuses",
    multiple=True,
    type=click.Choice(FOREIGN_ASSESSMENTS, case_sensitive=False),
    help="Only years with this assessment; repeat for any.",
)
@click.option("--holdings", is_flag=True, help="One row per property per year instead of one per year.")
@click.option("--headroom", is_flag=True, help="Show how far each year's highest cost stayed under $100,000.")
@click.option("--json", "as_json", is_flag=True, help="Print raw, unmasked figures as JSON.")
@click.option("--jsonl", "as_jsonl", is_flag=True, help="Print raw, unmasked years (or --holdings) as JSON Lines.")
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(dir_okay=False, allow_dash=True, path_type=Path),
    default=None,
    help="Write years (or --holdings) to this CSV file; '-' prints them to stdout.",
)
@click.option("--count", "count_only", is_flag=True, help="Print only the number of matching years (or --holdings).")
@click.option(
    "--exit-code", is_flag=True, help="Exit 1 when T1135 may be required in any year shown (or it's undetermined)."
)
@pass_app
def tax_foreign_property(
    app: App,
    year: int | None,
    since_year: int | None,
    until_year: int | None,
    statuses: tuple[str, ...],
    holdings: bool,
    headroom: bool,
    as_json: bool,
    as_jsonl: bool,
    csv_path: Path | None,
    count_only: bool,
    exit_code: bool,
) -> None:
    """Whether foreign property cost may require form T1135 (an estimate, not tax advice).

    \b
    Totals the cost (ACB, in CAD) of property listed outside Canada held in non-registered
    accounts at the end of every day: over $100,000 at any time means T1135 is likely due."""
    usage = click.UsageError
    if sum((as_json, as_jsonl, csv_path is not None)) > 1:
        raise usage("Choose one output format: --json, --jsonl or --csv.")
    if count_only and (as_json or as_jsonl or csv_path is not None):
        raise usage("--count cannot be combined with --json, --jsonl or --csv.")
    if year is not None and (since_year is not None or until_year is not None):
        raise usage("--year cannot be combined with --since-year or --until-year.")
    if since_year is not None and until_year is not None and since_year > until_year:
        raise usage("--since-year must be at most --until-year.")
    if headroom and holdings:
        raise usage("--headroom applies to years, not --holdings.")

    with app.busy("Building foreign property report…"):
        found = app.tracker.foreign_property(year)
    wanted = {s.lower() for s in statuses}
    found = [
        y
        for y in found
        if (since_year is None or y.year >= since_year)
        and (until_year is None or y.year <= until_year)
        and (not wanted or y.assessment in wanted)
    ]
    _foreign_output(
        app,
        found,
        year=year,
        filtered=bool(statuses or since_year is not None or until_year is not None),
        holdings=holdings,
        headroom=headroom,
        as_json=as_json,
        as_jsonl=as_jsonl,
        csv_path=csv_path,
        count_only=count_only,
    )
    if exit_code and any(y.assessment != T1135_NOT_REQUIRED for y in found):
        raise click.exceptions.Exit(1)


def _foreign_output(
    app: App,
    found: list[ForeignPropertyYear],
    *,
    year: int | None,
    filtered: bool,
    holdings: bool,
    headroom: bool,
    as_json: bool,
    as_jsonl: bool,
    csv_path: Path | None,
    count_only: bool,
) -> None:
    rows = _foreign_holding_rows(found) if holdings else _foreign_year_rows(found, headroom)
    if count_only:
        click.echo(len(rows))
        return
    if as_json:
        if holdings:
            click.echo(json.dumps(rows, ensure_ascii=False))
            return
        payload = {
            "currency": "CAD",
            "threshold": T1135_THRESHOLD,
            "detailed_threshold": T1135_DETAILED_THRESHOLD,
            "years": rows,
            "notes": FOREIGN_PROPERTY_NOTES,
        }
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if as_jsonl:
        for row in rows:
            click.echo(json.dumps(row, ensure_ascii=False))
        return
    if csv_path is not None:
        fields = FOREIGN_HOLDING_FIELDS if holdings else FOREIGN_YEAR_FIELDS + (["headroom"] if headroom else [])
        _write_foreign_csv(app, csv_path, fields, rows)
        return
    app.title("Foreign property (T1135)")
    if holdings:
        _foreign_holdings(app, found)
    elif year is None:
        _foreign_years(app, found, headroom=headroom, filtered=filtered)
    elif found:
        _foreign_year(app, found[0], headroom=headroom)
    else:
        app.console.print(Text(f"{year} doesn't match these filters.", style="muted"))
    if any(y.incomplete for y in found):
        app.warn("An FX rate was missing, so some cost is left out: these totals may be too low.")
    for note in FOREIGN_PROPERTY_NOTES:
        app.console.print(Text(note, style="muted"))


def _write_foreign_csv(app: App, csv_path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    def write(stream: TextIO, **kw: Any) -> None:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", **kw)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {k: ("" if v is None else str(v).lower() if isinstance(v, bool) else v) for k, v in row.items()}
            )

    if str(csv_path) == "-":
        stream = io.StringIO()
        write(stream, lineterminator="\n")
        click.echo(stream.getvalue(), nl=False)
        return
    try:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            write(f)
    except OSError as e:
        fail(f"Couldn't write {csv_path}: {e.strerror or e}")
    app.ok(f"Exported {len(rows)} row(s) to {csv_path}")


def _headroom_text(y: ForeignPropertyYear, privacy: bool, currency: str = "") -> Text:
    """Headroom under the $100,000 threshold; negative (in the warning style) when the cost went over it."""
    room = _headroom(y)
    style = "" if privacy else "warn" if room < 0 else "muted"  # the colour would reveal the sign
    return Text(fmt.money(room, currency, privacy=privacy), style=style)


def _foreign_holdings(app: App, found: list[ForeignPropertyYear]) -> None:
    if not any(y.holdings for y in found):
        app.console.print(Text("No foreign property in non-registered accounts.", style="muted"))
        return
    privacy = app.privacy
    t = render.table(
        "Year",
        "Symbol",
        ("Highest cost", "right"),
        "On",
        ("Year-end cost", "right"),
        ("Gain", "right"),
        ("Sales", "right"),
        title="Specified foreign property by holding, cost in CAD",
    )
    for y in found:
        for h in y.holdings:
            t.add_row(
                Text(str(y.year), style="muted"),
                Text(h.symbol + (" *" if h.incomplete else ""), style="bright"),
                Text(fmt.money(h.max_cost, privacy=privacy)),
                Text(h.max_cost_date or "—", style="muted"),
                Text(fmt.money(h.year_end_cost, privacy=privacy), style="muted"),
                _money(h.gain, privacy, sign=True) if h.dispositions else Text("—", style="muted"),
                Text(str(h.dispositions) if h.dispositions else "—", style="muted"),
            )
    app.console.print(t)
    if any(h.incomplete for y in found for h in y.holdings):
        app.console.print(Text("* missing an FX rate", style="down"))


def _foreign_status(y: ForeignPropertyYear) -> Text:
    undetermined = y.incomplete and y.status == T1135_NOT_REQUIRED
    style = (
        "warn" if y.status == T1135_DETAILED or undetermined else "accent" if y.status == T1135_SIMPLIFIED else "muted"
    )
    return Text(y.label, style=style)


def _foreign_years(
    app: App, found: list[ForeignPropertyYear], *, headroom: bool = False, filtered: bool = False
) -> None:
    if not found:
        message = "No years match these filters." if filtered else "No foreign property in non-registered accounts."
        app.console.print(Text(message, style="muted"))
        return
    privacy = app.privacy
    columns: list[render.Column] = [
        "Year",
        ("Highest cost", "right"),
        "On",
        ("Year-end cost", "right"),
        ("Gain", "right"),
    ]
    if headroom:
        columns.append(("Headroom", "right"))
    t = render.table(*columns, "Status", title="Specified foreign property, cost in CAD")
    for y in found:
        cells = [
            Text(str(y.year), style="bright"),
            Text(fmt.money(y.max_cost, privacy=privacy)),
            Text(y.max_cost_date or "—", style="muted"),
            Text(fmt.money(y.year_end_cost, privacy=privacy), style="muted"),
            _money(y.gain, privacy, sign=True),
        ]
        if headroom:
            cells.append(_headroom_text(y, privacy))
        t.add_row(*cells, _foreign_status(y))
    app.console.print(t)


def _foreign_year(app: App, y: ForeignPropertyYear, *, headroom: bool = False) -> None:
    if not y.holdings:
        app.console.print(Text(f"No foreign property in non-registered accounts in {y.year}.", style="muted"))
        return
    privacy = app.privacy
    so_far = " so far" if y.as_of < f"{y.year}-12-31" else ""
    app.console.print(
        Text.assemble(
            (f"{y.year}{so_far}: highest cost ", "muted"),
            (fmt.money(y.max_cost, "CAD", privacy=privacy), "bright"),
            (f" on {y.max_cost_date}" if y.max_cost_date else "", "muted"),
            (", cost at ", "muted"),
            (y.as_of, "muted"),
            (" ", "muted"),
            (fmt.money(y.year_end_cost, "CAD", privacy=privacy), ""),
        )
    )
    app.console.print(_foreign_status(y))
    if headroom:
        app.console.print(Text.assemble(("Headroom to $100,000: ", "muted"), _headroom_text(y, privacy, "CAD")))
    t = render.table(
        "Symbol",
        ("Highest cost", "right"),
        "On",
        ("Year-end cost", "right"),
        ("Gain", "right"),
        ("Sales", "right"),
        title=f"{y.year} foreign property, cost in CAD",
    )
    for h in y.holdings:
        t.add_row(
            Text(h.symbol + (" *" if h.incomplete else ""), style="bright"),
            Text(fmt.money(h.max_cost, privacy=privacy)),
            Text(h.max_cost_date or "—", style="muted"),
            Text(fmt.money(h.year_end_cost, privacy=privacy), style="muted"),
            _money(h.gain, privacy, sign=True) if h.dispositions else Text("—", style="muted"),
            Text(str(h.dispositions) if h.dispositions else "—", style="muted"),
        )
    app.console.print(t)
    if any(h.incomplete for h in y.holdings):
        app.console.print(Text("* missing an FX rate", style="down"))


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
