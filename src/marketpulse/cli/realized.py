"""Offline logs of realized gains and income payouts, straight from the ledger replay.

Amounts stay in each trade's native currency and are only totalled within one currency.
Nothing here looks up quotes or FX, and this is not the tax report: `marketpulse tax`
converts at trade-date FX and applies the superficial-loss rules.
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import TypeVar

import click
from rich.text import Text

from .. import fmt, render
from ..ledger import IncomeEvent, RealizedGain
from ..models import Account, AccountType
from .base import App, date_callback, fail, pass_app
from .root import main

NOT_TAX = "Native currency, average cost from the ledger. Not the tax report; see `marketpulse tax`."
KINDS = ("dividend", "drip", "interest")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
Row = TypeVar("Row", RealizedGain, IncomeEvent)
KIND_LABELS = {"dividend": "Dividend", "drip": "DRIP", "interest": "Interest"}
REALIZED_FIELDS = [
    "date",
    "account_id",
    "account",
    "symbol",
    "quantity",
    "proceeds",
    "cost",
    "gain",
    "currency",
    "txn_id",
]
PAYOUT_FIELDS = ["date", "account_id", "account", "symbol", "kind", "amount", "currency"]
RETURN_FIELD = "return_pct"
MONEY_FIELDS = {"proceeds", "cost", "gain", "amount", "gains", "losses"}
GROUPINGS = ("year", "quarter", "month", "account", "symbol", "currency")


def _filters(f):
    """Options shared by `realized` and `payouts`."""
    for decorator in reversed(
        [
            click.option("-a", "--account", default=None, help="Only this account (name, id or type)."),
            click.option("-s", "--symbol", default=None, help="Only this symbol (exact, case-insensitive)."),
            click.option("--year", type=click.IntRange(min=1, max=9999), help="Only this calendar year."),
            click.option("--month", type=click.IntRange(min=1, max=12), help="Only this calendar month, across years."),
            click.option(
                "--quarter", type=click.IntRange(min=1, max=4), help="Only this calendar quarter, across years."
            ),
            click.option(
                "--exclude-account",
                "excluded_accounts",
                multiple=True,
                help="Exclude an active account by ID, name or unique type; repeat for several.",
            ),
            click.option("--since", callback=date_callback, help="On or after this date."),
            click.option("--until", callback=date_callback, help="On or before this date."),
            click.option("--currency", help="Only this native currency (case-insensitive)."),
            click.option("--count", "count_only", is_flag=True, help="Print the number of matching rows or groups."),
            click.option(
                "--newest-first",
                is_flag=True,
                help="Newest dates first; with --by, reverse the group order.",
            ),
            click.option("--limit", type=click.IntRange(min=1), help="Show at most N matching rows or groups."),
            click.option("--offset", type=click.IntRange(min=0), help="Skip N matching rows or groups before --limit."),
            click.option("--json", "as_json", is_flag=True, help="Print raw, unmasked rows and totals as JSON."),
            click.option("--csv", "as_csv", is_flag=True, help="Print raw, unmasked rows as CSV to stdout."),
            click.option(
                "--symbols",
                multiple=True,
                callback=_normalized_items,
                help="Include exact symbols; repeat for several.",
            ),
            click.option("--account-type", type=click.Choice([a.value for a in AccountType], case_sensitive=False)),
            click.option(
                "--institution", callback=_nonblank, help="Match the account's institution exactly, ignoring case."
            ),
            click.option("--registered/--nonregistered", default=None, help="Match account registration status."),
            click.option("--cash-tracked/--cash-untracked", default=None, help="Match account cash-tracking status."),
            click.option(
                "--exclude-currency",
                "excluded_currencies",
                multiple=True,
                callback=_normalized_items,
                help="Exclude native currencies; repeat for several.",
            ),
            click.option(
                "--on",
                "included_dates",
                multiple=True,
                callback=_dates,
                help="Include exact dates; repeat for several.",
            ),
            click.option(
                "--exclude-date",
                "excluded_dates",
                multiple=True,
                callback=_dates,
                help="Exclude exact dates; repeat for several.",
            ),
            click.option(
                "--weekday",
                "weekdays",
                multiple=True,
                type=click.Choice(WEEKDAYS, case_sensitive=False),
                help="Include weekdays; repeat for several.",
            ),
            click.option(
                "--symbol-prefix", callback=_nonblank, help="Match the start of recorded symbols, ignoring case."
            ),
            click.option("--jsonl", "as_jsonl", is_flag=True, help="Print raw, unmasked rows or groups as JSON Lines."),
            click.option(
                "--markdown", "as_markdown", is_flag=True, help="Print rows or groups as a Markdown table (masked)."
            ),
            click.option(
                "--fields",
                callback=_field_list,
                metavar="LIST",
                help="Comma-separated row fields to output, in order (with --json, --csv, --jsonl or --markdown).",
            ),
            click.option(
                "--last-days",
                type=click.IntRange(min=1),
                metavar="N",
                help="Only rows dated in the last N days (today and the N-1 days before it).",
            ),
        ]
    ):
        f = decorator(f)
    return f


def _nonblank(ctx, param, value):
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise click.BadParameter("Cannot be blank.")
    return value


def _normalized_items(ctx, param, values):
    return tuple(_nonblank(ctx, param, value).upper() for value in values)


def _dates(ctx, param, values):
    return tuple(date_callback(ctx, param, value) for value in values)


def _field_list(ctx, param, value):
    if value is None:
        return None
    names = [name.strip().lower() for name in value.split(",")]
    if not all(names):
        raise click.BadParameter("List field names separated by commas, e.g. date,symbol,gain.")
    if len(set(names)) != len(names):
        raise click.BadParameter("A field is listed twice.")
    return tuple(names)


def _check_fields(fields: tuple[str, ...] | None, allowed: list[str]) -> None:
    unknown = [name for name in fields or () if name not in allowed]
    if unknown:
        raise click.BadParameter(
            f"Unknown field {unknown[0]!r}. Choose from: {', '.join(allowed)}.", param_hint="'--fields'"
        )


def _output_mode(as_json: bool, as_csv: bool, as_jsonl: bool, as_markdown: bool) -> str | None:
    chosen = [
        name for name, on in (("json", as_json), ("csv", as_csv), ("jsonl", as_jsonl), ("markdown", as_markdown)) if on
    ]
    if len(chosen) > 1:
        raise click.UsageError("Choose one output format: --json, --csv, --jsonl or --markdown.")
    return chosen[0] if chosen else None


def _last_days_since(last_days: int | None, since: str | None) -> str | None:
    if last_days is None:
        return since
    if since is not None:
        raise click.UsageError("--last-days cannot be combined with --since.")
    return (date.today() - timedelta(days=last_days - 1)).isoformat()


def _markdown_cell(app: App, key: str, value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and key in MONEY_FIELDS | {RETURN_FIELD, "quantity"}:
        if app.privacy:
            return fmt.MASK
        return fmt.qty(value) if key == "quantity" else f"{value:.2f}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _emit(app: App, mode: str, fieldnames: list[str], records: list[dict]) -> None:
    """Print plain records as --csv, --jsonl or --markdown, keeping only `fieldnames` in order."""
    picked = [{name: record.get(name) for name in fieldnames} for record in records]
    if mode == "csv":
        _echo_csv(fieldnames, picked)
    elif mode == "jsonl":
        for record in picked:
            click.echo(json.dumps(record, ensure_ascii=False))
    else:
        click.echo("| " + " | ".join(fieldnames) + " |")
        click.echo("|" + "|".join(" --- " for _ in fieldnames) + "|")
        for record in picked:
            click.echo("| " + " | ".join(_markdown_cell(app, k, v) for k, v in record.items()) + " |")


def _selection(
    rows: list[Row],
    accounts: dict[int, Account],
    symbols: tuple[str, ...],
    account_type: str | None,
    institution: str | None,
    registered: bool | None,
    cash_tracked: bool | None,
    excluded_currencies: tuple[str, ...],
    included_dates: tuple[str, ...],
    excluded_dates: tuple[str, ...],
    weekdays: tuple[str, ...],
    symbol_prefix: str | None,
) -> list[Row]:
    return [
        row
        for row in rows
        if (not symbols or row.symbol.upper() in symbols)
        and (account_type is None or accounts[row.account_id].type.value == account_type)
        and (institution is None or accounts[row.account_id].institution.casefold() == institution.casefold())
        and (registered is None or accounts[row.account_id].type.registered == registered)
        and (cash_tracked is None or accounts[row.account_id].track_cash == cash_tracked)
        and row.currency.upper() not in excluded_currencies
        and (not included_dates or row.date in included_dates)
        and row.date not in excluded_dates
        and (not weekdays or WEEKDAYS[date.fromisoformat(row.date).weekday()] in weekdays)
        and (symbol_prefix is None or row.symbol.casefold().startswith(symbol_prefix.casefold()))
    ]


def _realized_summary(
    app: App, rows: list[RealizedGain], accounts: dict[int, Account], by: str, mode: str | None
) -> None:
    def key(row: RealizedGain) -> str:
        if by == "year":
            return row.date[:4]
        if by == "month":
            return row.date[:7]
        if by == "account":
            return accounts[row.account_id].name
        return row.symbol

    records = [{"group": group, "count": count} for group, count in sorted(Counter(key(row) for row in rows).items())]
    if mode == "json":
        click.echo(json.dumps(records, ensure_ascii=False))
    elif mode is not None:
        _emit(app, mode, ["group", "count"], records)
    else:
        table = render.table(by.title(), ("Sales", "right"), title="Matching realized sales")
        for record in records:
            table.add_row(Text(str(record["group"])), Text(str(record["count"])))
        app.console.print(table)


def _check_common(since: str | None, until: str | None, as_json: bool, as_csv: bool) -> None:
    if since and until and since > until:
        raise click.UsageError("--since must be on or before --until.")
    if as_json and as_csv:
        raise click.UsageError("Choose one output format: --json or --csv.")


def _browsing_currency(currency, count_only, as_json, as_csv, limit, offset, newest_first) -> str | None:
    if count_only and (as_json or as_csv or limit is not None or offset is not None or newest_first):
        raise click.UsageError("--count cannot be combined with --json, --csv, --limit, --offset or --newest-first.")
    wanted = currency.strip().upper() if currency is not None else None
    if wanted == "":
        raise click.UsageError("--currency cannot be blank.")
    return wanted


def _finite(ctx, param, value):
    if value is not None and not math.isfinite(value):
        raise click.BadParameter("Must be a finite number.")
    return value


def _amount_range(minimum, maximum, label):
    if minimum is not None and maximum is not None and minimum > maximum:
        raise click.UsageError(f"--min-{label} must be at most --max-{label}.")


def _page_metadata(total, rows, limit, offset):
    start = offset or 0
    return {
        "total": total,
        "offset": start,
        "limit": limit,
        "returned": len(rows),
        "next_offset": start + len(rows) if start + len(rows) < total else None,
    }


def _page(rows, limit, offset):
    start = offset or 0
    return rows[start : start + limit if limit is not None else None]


def _scope(app: App, account: str | None) -> tuple[dict[int, Account], int | None]:
    """Visible accounts and the optional account filter. Archived accounts are never shown."""
    accounts = {k: a for k, a in app.store.account_map().items() if not a.archived}
    if account is None:
        return accounts, None
    acct = app.account(account)
    if acct.archived:
        fail(f"No active account '{account}'.")
    return accounts, acct.saved_id


def _in_range(
    day: str,
    year: int | None,
    since: str | None,
    until: str | None,
    month: int | None = None,
    quarter: int | None = None,
) -> bool:
    return (
        (year is None or day[:4] == f"{year:04d}")
        and (not since or day >= since)
        and (not until or day <= until)
        and (month is None or int(day[5:7]) == month)
        and (quarter is None or (int(day[5:7]) - 1) // 3 + 1 == quarter)
    )


def _excluded_account_ids(app: App, references: tuple[str, ...]) -> set[int]:
    result = set()
    for ref in references:
        if not ref.strip():
            raise click.UsageError("--exclude-account cannot be blank.")
        account = app.account(ref)
        if account.archived:
            fail(f"No active account '{ref}'.")
        result.add(account.saved_id)
    return result


def _echo_csv(fieldnames: list[str], rows: list[dict]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    click.echo(stream.getvalue(), nl=False)


def _money(app: App, value: float, currency: str, *, sign: bool = False) -> Text:
    text = fmt.money(value, currency, privacy=app.privacy, sign=sign)
    # A coloured mask would still reveal whether the amount is a gain or a loss.
    return Text(text) if app.privacy or not sign else render.trend(text, value)


# ── realized gains ────────────────────────────────────────────────────────────


def _realized_row(r: RealizedGain, accounts: dict[int, Account]) -> dict:
    return {
        "date": r.date,
        "account_id": r.account_id,
        "account": accounts[r.account_id].name,
        "symbol": r.symbol,
        "quantity": r.quantity,
        "proceeds": r.proceeds,
        "cost": r.cost,
        "gain": r.gain,
        "currency": r.currency,
        "txn_id": r.txn_id,
    }


def _realized_totals(rows: list[RealizedGain], *, gross: bool = False) -> dict[str, dict]:
    by_currency: dict[str, list[RealizedGain]] = defaultdict(list)
    for r in rows:
        by_currency[r.currency].append(r)
    totals: dict[str, dict] = {}
    for ccy, items in sorted(by_currency.items()):
        entry = {
            "count": len(items),
            "proceeds": math.fsum(r.proceeds for r in items),
            "cost": math.fsum(r.cost for r in items),
            "gain": math.fsum(r.gain for r in items),
        }
        if gross:  # --gross: the gains and the losses that net to `gain`
            entry["gains"] = math.fsum(r.gain for r in items if r.gain > 0)
            entry["losses"] = math.fsum(r.gain for r in items if r.gain < 0)
        totals[ccy] = entry
    return totals


def _return_pct(r: RealizedGain) -> float | None:
    """Gain as a percentage of the ACB sold; none when the ACB is zero."""
    return r.gain / r.cost * 100 if r.cost > 1e-9 else None


def _realized_record(r: RealizedGain, accounts: dict[int, Account], with_return: bool) -> dict:
    row = _realized_row(r, accounts)
    if with_return:
        row[RETURN_FIELD] = _return_pct(r)
    return row


def _realized_key(r: RealizedGain, by: str) -> str:
    if by == "year":
        return r.date[:4]
    if by == "quarter":
        return f"{r.date[:4]}-Q{(int(r.date[5:7]) - 1) // 3 + 1}"
    if by == "month":
        return r.date[:7]
    if by == "account":
        return str(r.account_id)  # the id keeps identically named accounts apart
    if by == "currency":
        return r.currency
    return r.symbol


def _realized_groups(rows: list[RealizedGain], by: str, accounts: dict[int, Account]) -> list[dict]:
    grouped: dict[tuple[str, str], list[RealizedGain]] = defaultdict(list)
    for r in rows:
        grouped[(_realized_key(r, by), r.currency)].append(r)
    groups: list[dict] = []
    for (group, ccy), items in sorted(grouped.items()):
        entry: dict = {
            "group": group,
            "currency": ccy,
            "count": len(items),
            "proceeds": math.fsum(r.proceeds for r in items),
            "cost": math.fsum(r.cost for r in items),
            "gain": math.fsum(r.gain for r in items),
        }
        if by == "account":
            entry["account"] = accounts[int(group)].name
        groups.append(entry)
    return groups


def _print_realized_totals(app: App, rows: list[RealizedGain], gross: bool) -> None:
    columns: list[render.Column] = [
        "Currency",
        ("Sales", "right"),
        ("Proceeds", "right"),
        ("ACB", "right"),
        ("Gain", "right"),
    ]
    if gross:
        columns += [("Gains", "right"), ("Losses", "right")]
    totals = render.table(*columns, title="Totals by currency")
    for ccy, total in _realized_totals(rows, gross=gross).items():
        cells = [
            Text(ccy),
            Text(str(total["count"])),
            _money(app, total["proceeds"], ccy),
            _money(app, total["cost"], ccy),
            _money(app, total["gain"], ccy, sign=True),
        ]
        if gross:
            cells += [_money(app, total["gains"], ccy, sign=True), _money(app, total["losses"], ccy, sign=True)]
        totals.add_row(*cells)
    app.console.print(totals)
    app.console.print(Text(NOT_TAX, style="muted"))


def _grouped_realized(
    app: App,
    rows: list[RealizedGain],
    by: str,
    accounts: dict[int, Account],
    mode: str | None,
    count_only: bool,
    newest_first: bool,
    limit: int | None,
    offset: int | None,
    page_info: bool,
    gross: bool,
) -> None:
    """`realized --by`: proceeds, ACB and gain per group and native currency."""
    groups = _realized_groups(rows, by, accounts)
    if count_only:
        click.echo(len(groups))
        return
    total = len(groups)
    groups = _page(list(reversed(groups)) if newest_first else groups, limit, offset)
    fieldnames = ["group", "currency", "count", "proceeds", "cost", "gain"] + (["account"] if by == "account" else [])
    if mode == "json":
        payload = {"by": by, "groups": groups, "totals": _realized_totals(rows, gross=gross)}
        if page_info:
            payload.update(_page_metadata(total, groups, limit, offset))
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if mode is not None:
        _emit(app, mode, fieldnames, groups)
        return
    if not groups:
        app.console.print(Text("No matching realized gains.", style="muted"))
        return
    table = render.table(
        by.title(),
        "Currency",
        ("Sales", "right"),
        ("Proceeds", "right"),
        ("ACB", "right"),
        ("Gain", "right"),
        title=f"Realized gains by {by}",
    )
    for g in groups:
        table.add_row(
            Text(g.get("account", g["group"])),
            Text(g["currency"]),
            Text(str(g["count"])),
            _money(app, g["proceeds"], g["currency"]),
            _money(app, g["cost"], g["currency"]),
            _money(app, g["gain"], g["currency"], sign=True),
        )
    app.console.print(table)
    _print_realized_totals(app, rows, gross)


@main.command()
@_filters
@click.option("--search", help="Find symbol or account text, ignoring case.")
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(["date", "account", "symbol", "quantity", "proceeds", "cost", "gain", "currency"]),
)
@click.option("--descending", is_flag=True, help="Reverse the selected sort (default: date).")
@click.option("--min-gain", type=float, callback=_finite, help="Inclusive native-currency gain minimum.")
@click.option("--max-gain", type=float, callback=_finite, help="Inclusive native-currency gain maximum.")
@click.option("--exclude-symbol", "excluded_symbols", multiple=True, help="Exclude exact symbols; repeat for several.")
@click.option("--min-proceeds", type=float, callback=_finite, help="Inclusive native-currency proceeds minimum.")
@click.option("--max-proceeds", type=float, callback=_finite, help="Inclusive native-currency proceeds maximum.")
@click.option("--min-quantity", type=click.FloatRange(min=0), callback=_finite, help="Inclusive sold quantity minimum.")
@click.option("--max-quantity", type=click.FloatRange(min=0), callback=_finite, help="Inclusive sold quantity maximum.")
@click.option("--page-info", is_flag=True, help="With --json, include pagination metadata.")
@click.option("--gains-only", is_flag=True, help="Only sales with a gain (rounded to the cent).")
@click.option("--losses-only", is_flag=True, help="Only sales with a loss (rounded to the cent).")
@click.option("--min-cost", type=float, callback=_finite, help="Inclusive native-currency cost minimum.")
@click.option("--max-cost", type=float, callback=_finite, help="Inclusive native-currency cost maximum.")
@click.option("--min-txn-id", type=click.IntRange(min=1), help="Include sales at or above this transaction ID.")
@click.option("--max-txn-id", type=click.IntRange(min=1), help="Include sales at or below this transaction ID.")
@click.option("--breakeven-only", is_flag=True, help="Only sales with a zero gain rounded to the cent.")
@click.option(
    "--summary",
    type=click.Choice(["year", "month", "account", "symbol"]),
    help="Count all matching sales by this field; no monetary totals.",
)
@click.option(
    "--by",
    type=click.Choice(GROUPINGS, case_sensitive=False),
    help="Show proceeds, ACB and gain per group and currency instead of each sale.",
)
@click.option("--gross", is_flag=True, help="Split each currency's total gain into gains and losses.")
@click.option(
    "--return", "with_return", is_flag=True, help="Add each sale's gain as a percentage of its ACB (return_pct)."
)
@click.option("--totals-only", is_flag=True, help="Print only the totals by currency.")
@pass_app
def realized(
    app: App,
    account,
    symbol,
    year,
    month,
    quarter,
    excluded_accounts,
    since,
    until,
    as_json,
    as_csv,
    search,
    sort_by,
    descending,
    min_gain,
    max_gain,
    gains_only,
    losses_only,
    excluded_symbols,
    min_proceeds,
    max_proceeds,
    min_quantity,
    max_quantity,
    page_info,
    currency,
    count_only,
    newest_first,
    limit,
    offset,
    symbols,
    account_type,
    institution,
    registered,
    cash_tracked,
    excluded_currencies,
    included_dates,
    excluded_dates,
    weekdays,
    symbol_prefix,
    min_cost,
    max_cost,
    min_txn_id,
    max_txn_id,
    breakeven_only,
    summary,
    as_jsonl,
    as_markdown,
    fields,
    last_days,
    by,
    gross,
    with_return,
    totals_only,
) -> None:
    """Realized gains from the ledger, oldest first, totalled per native currency (offline).

    Not the tax report: no FX conversion and no superficial-loss rules. Use `marketpulse tax` for that."""
    since = _last_days_since(last_days, since)
    _check_common(since, until, as_json, as_csv)
    mode = _output_mode(as_json, as_csv, as_jsonl, as_markdown)
    ccy = _browsing_currency(currency, count_only, as_json, as_csv, limit, offset, newest_first)
    _check_new_outputs(count_only, as_jsonl, as_markdown, fields, mode)
    _check_fields(fields, REALIZED_FIELDS + [RETURN_FIELD])
    by = by.lower() if by else None
    if by and (summary or sort_by is not None or descending):
        raise click.UsageError("--by cannot be combined with --summary, --sort or --descending.")
    if totals_only and (
        by
        or summary
        or count_only
        or newest_first
        or sort_by is not None
        or descending
        or limit is not None
        or offset is not None
        or page_info
    ):
        raise click.UsageError(
            "--totals-only cannot be combined with grouping, counting, ordering or pagination options."
        )
    if gross and summary:
        raise click.UsageError("--summary has no monetary totals for --gross to split.")
    if with_return and (by or summary or totals_only):
        raise click.UsageError("--return adds a column to each sale; omit --by, --summary and --totals-only.")
    if fields and (by or summary or totals_only):
        raise click.UsageError("--fields picks sale fields; omit --by, --summary and --totals-only.")
    _amount_range(min_gain, max_gain, "gain")
    _amount_range(min_proceeds, max_proceeds, "proceeds")
    _amount_range(min_quantity, max_quantity, "quantity")
    if page_info and not as_json:
        raise click.UsageError("--page-info requires --json.")
    excluded = {value.strip().upper() for value in excluded_symbols}
    if "" in excluded:
        raise click.UsageError("--exclude-symbol cannot be blank.")
    if newest_first and (sort_by is not None or descending):
        raise click.UsageError("--newest-first cannot be combined with --sort or --descending.")
    if count_only and (sort_by is not None or descending):
        raise click.UsageError("--count cannot be combined with --sort or --descending.")
    if sum((gains_only, losses_only, breakeven_only)) > 1:
        raise click.UsageError("Choose one of --gains-only, --losses-only or --breakeven-only.")
    _amount_range(min_cost, max_cost, "cost")
    _amount_range(min_txn_id, max_txn_id, "txn-id")
    if summary and (
        count_only
        or newest_first
        or sort_by is not None
        or descending
        or limit is not None
        or offset is not None
        or page_info
    ):
        raise click.UsageError("--summary cannot be combined with counting, ordering or pagination options.")
    accounts, account_id = _scope(app, account)
    excluded_ids = _excluded_account_ids(app, excluded_accounts)
    wanted = symbol.strip().upper() if symbol is not None else None
    rows = [
        r
        for r in app.store.ledger().realized  # replay order: date, then same-day order
        if r.account_id in accounts
        and r.account_id not in excluded_ids
        and r.symbol.upper() not in excluded
        and (min_proceeds is None or r.proceeds >= min_proceeds)
        and (max_proceeds is None or r.proceeds <= max_proceeds)
        and (min_quantity is None or r.quantity >= min_quantity)
        and (max_quantity is None or r.quantity <= max_quantity)
        and (account_id is None or r.account_id == account_id)
        and (wanted is None or r.symbol.upper() == wanted)
        and (ccy is None or r.currency.upper() == ccy)
        and _in_range(r.date, year, since, until, month, quarter)
        and (
            search is None
            or search.casefold() in r.symbol.casefold()
            or search.casefold() in accounts[r.account_id].name.casefold()
        )
        and (min_gain is None or r.gain >= min_gain)
        and (max_gain is None or r.gain <= max_gain)
        and (not gains_only or round(r.gain, 2) > 0)
        and (not losses_only or round(r.gain, 2) < 0)
        and (not breakeven_only or round(r.gain, 2) == 0)
        and (min_cost is None or r.cost >= min_cost)
        and (max_cost is None or r.cost <= max_cost)
        and (min_txn_id is None or r.txn_id >= min_txn_id)
        and (max_txn_id is None or r.txn_id <= max_txn_id)
    ]
    rows = _selection(
        rows,
        accounts,
        symbols,
        account_type,
        institution,
        registered,
        cash_tracked,
        excluded_currencies,
        included_dates,
        excluded_dates,
        weekdays,
        symbol_prefix,
    )
    if summary:
        _realized_summary(app, rows, accounts, summary, mode)
        return
    if by:
        _grouped_realized(app, rows, by, accounts, mode, count_only, newest_first, limit, offset, page_info, gross)
        return
    if totals_only:
        _realized_totals_only(app, rows, mode, gross)
        return
    if count_only:
        click.echo(len(rows))
        return
    all_rows = rows
    field = sort_by or "date"
    rows = sorted(
        rows,
        key=lambda r: accounts[r.account_id].name.casefold() if field == "account" else getattr(r, field),
        reverse=descending or newest_first,
    )
    rows = _page(rows, limit, offset)
    with_return = with_return or RETURN_FIELD in (fields or ())
    columns = list(fields) if fields else REALIZED_FIELDS + ([RETURN_FIELD] if with_return else [])
    if mode == "csv" and not fields and not with_return:
        _echo_csv(REALIZED_FIELDS, [_realized_row(r, accounts) for r in rows])
        return
    if mode == "json":
        records = [_realized_record(r, accounts, with_return) for r in rows]
        if fields:
            records = [{name: record[name] for name in fields} for record in records]
        payload = {"rows": records, "totals": _realized_totals(all_rows, gross=gross)}
        if page_info:
            payload.update(_page_metadata(len(all_rows), rows, limit, offset))
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if mode is not None:
        _emit(app, mode, columns, [_realized_record(r, accounts, with_return) for r in rows])
        return
    if not rows:
        app.console.print(Text("No matching realized gains.", style="muted"))
        return
    headers: list[render.Column] = [
        "Date",
        "Account",
        "Symbol",
        ("Qty", "right"),
        ("Proceeds", "right"),
        ("ACB", "right"),
        ("Gain", "right"),
    ]
    headers += [("Return", "right")] if with_return else []
    table = render.table(*headers, "Currency", title="Realized gains")
    for r in rows:
        cells = [
            Text(r.date, style="muted"),
            Text(render.truncate(accounts[r.account_id].name, 22)),
            Text(r.symbol, style="bright"),
            Text(fmt.MASK if app.privacy else fmt.qty(r.quantity)),
            _money(app, r.proceeds, r.currency),
            _money(app, r.cost, r.currency),
            _money(app, r.gain, r.currency, sign=True),
        ]
        if with_return:
            cells.append(_return_cell(app, _return_pct(r)))
        table.add_row(*cells, Text(r.currency, style="muted"))
    app.console.print(table)
    _print_realized_totals(app, all_rows, gross)


def _return_cell(app: App, value: float | None) -> Text:
    if value is None:
        return Text(render.DASH, style="muted")
    if app.privacy:  # a coloured or signed figure would still reveal a gain or a loss
        return Text(fmt.MASK)
    return render.trend(fmt.pct(value), value)


def _realized_totals_only(app: App, rows: list[RealizedGain], mode: str | None, gross: bool) -> None:
    """`realized --totals-only`: just the per-currency totals."""
    totals = _realized_totals(rows, gross=gross)
    if mode == "json":
        click.echo(json.dumps({"totals": totals}, ensure_ascii=False))
        return
    if mode is not None:
        names = ["currency", "count", "proceeds", "cost", "gain"] + (["gains", "losses"] if gross else [])
        _emit(app, mode, names, [{"currency": ccy, **total} for ccy, total in totals.items()])
        return
    _print_realized_totals(app, rows, gross)


def _check_new_outputs(
    count_only: bool, as_jsonl: bool, as_markdown: bool, fields: tuple[str, ...] | None, mode: str | None
) -> None:
    if count_only and (as_jsonl or as_markdown or fields):
        raise click.UsageError("--count cannot be combined with --jsonl, --markdown or --fields.")
    if fields and mode is None:
        raise click.UsageError("--fields needs --json, --csv, --jsonl or --markdown.")


# ── income payouts ────────────────────────────────────────────────────────────


def _payout_row(e: IncomeEvent, accounts: dict[int, Account]) -> dict:
    return {
        "date": e.date,
        "account_id": e.account_id,
        "account": accounts[e.account_id].name,
        "symbol": e.symbol,
        "kind": e.kind.value.lower(),
        "amount": e.amount,
        "currency": e.currency,
    }


def _payout_totals(rows: list[IncomeEvent]) -> dict[str, dict]:
    by_currency: dict[str, list[float]] = defaultdict(list)
    for e in rows:
        by_currency[e.currency].append(e.amount)
    return {ccy: {"count": len(amounts), "amount": math.fsum(amounts)} for ccy, amounts in sorted(by_currency.items())}


def _group_key(e: IncomeEvent, by: str) -> str:
    if by == "month":
        return e.date[:7]
    if by == "year":
        return e.date[:4]
    if by == "quarter":
        return f"{e.date[:4]}-Q{(int(e.date[5:7]) - 1) // 3 + 1}"
    if by == "kind":
        return e.kind.value.lower()
    if by == "currency":
        return e.currency
    if by == "account":
        return str(e.account_id)  # the id keeps identically named accounts apart
    return e.symbol


def _payout_groups(rows: list[IncomeEvent], by: str, accounts: dict[int, Account]) -> list[dict]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for e in rows:
        grouped[(_group_key(e, by), e.currency)].append(e.amount)
    groups: list[dict] = []
    for (group, ccy), amounts in sorted(grouped.items()):
        entry: dict = {"group": group, "currency": ccy, "count": len(amounts), "amount": math.fsum(amounts)}
        if by == "account":
            entry["account"] = accounts[int(group)].name
        groups.append(entry)
    return groups


@main.command()
@_filters
@click.option("--search", help="Find symbol or account text, ignoring case.")
@click.option("--has-symbol/--no-symbol", default=None, help="Only payouts with or without a recorded symbol.")
@click.option("--min-amount", type=float, callback=_finite, help="Inclusive native-currency payout minimum.")
@click.option("--max-amount", type=float, callback=_finite, help="Inclusive native-currency payout maximum.")
@click.option("--exclude-symbol", "excluded_symbols", multiple=True, help="Exclude exact symbols; repeat for several.")
@click.option("--page-info", is_flag=True, help="With --json, include row or group pagination metadata.")
@click.option(
    "--kind",
    "kinds",
    multiple=True,
    type=click.Choice(KINDS, case_sensitive=False),
    help="Only this kind of payout; repeat for several.",
)
@click.option(
    "--by",
    type=click.Choice(["month", "year", "symbol", "account", "quarter", "kind", "currency"], case_sensitive=False),
    help="Show totals per group and currency instead of each payout.",
)
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(["date", "account", "symbol", "kind", "amount", "currency"]),
    help="Order individual payout rows by this field.",
)
@click.option("--descending", is_flag=True, help="Reverse individual row order (default: date).")
@click.option(
    "--exclude-kind",
    "excluded_kinds",
    multiple=True,
    type=click.Choice(KINDS, case_sensitive=False),
    help="Exclude income kinds; repeat for several.",
)
@click.option(
    "--group-sort",
    type=click.Choice(["group", "amount", "count"], case_sensitive=False),
    help="With --by, order groups by name, or by amount or count, largest first.",
)
@pass_app
def payouts(
    app: App,
    account,
    symbol,
    year,
    month,
    quarter,
    excluded_accounts,
    since,
    until,
    as_json,
    as_csv,
    search,
    min_amount,
    max_amount,
    has_symbol,
    excluded_symbols,
    page_info,
    kinds,
    by,
    currency,
    count_only,
    newest_first,
    limit,
    offset,
    symbols,
    account_type,
    institution,
    registered,
    cash_tracked,
    excluded_currencies,
    included_dates,
    excluded_dates,
    weekdays,
    symbol_prefix,
    sort_by,
    descending,
    excluded_kinds,
    as_jsonl,
    as_markdown,
    fields,
    last_days,
    group_sort,
) -> None:
    """Recorded dividend, DRIP and interest income, oldest first, per native currency (offline)."""
    since = _last_days_since(last_days, since)
    _check_common(since, until, as_json, as_csv)
    mode = _output_mode(as_json, as_csv, as_jsonl, as_markdown)
    ccy = _browsing_currency(currency, count_only, as_json, as_csv, limit, offset, newest_first)
    _check_new_outputs(count_only, as_jsonl, as_markdown, fields, mode)
    _check_fields(fields, PAYOUT_FIELDS)
    if group_sort and not by:
        raise click.UsageError("--group-sort needs --by.")
    if newest_first and group_sort in ("amount", "count"):
        raise click.UsageError(f"--newest-first cannot be combined with --group-sort {group_sort}.")
    if fields and by:
        raise click.UsageError("--fields picks payout fields; omit --by.")
    _amount_range(min_amount, max_amount, "amount")
    if newest_first and (sort_by is not None or descending):
        raise click.UsageError("--newest-first cannot be combined with --sort or --descending.")
    if count_only and (sort_by is not None or descending):
        raise click.UsageError("--count cannot be combined with --sort or --descending.")
    if by and (sort_by is not None or descending):
        raise click.UsageError("--sort and --descending order individual rows; omit --by.")
    if page_info and not as_json:
        raise click.UsageError("--page-info requires --json.")
    excluded = {symbol.strip().upper() for symbol in excluded_symbols}
    if "" in excluded:
        raise click.UsageError("--exclude-symbol cannot be blank.")
    accounts, account_id = _scope(app, account)
    excluded_ids = _excluded_account_ids(app, excluded_accounts)
    wanted = symbol.strip().upper() if symbol is not None else None
    chosen = {k.lower() for k in kinds}
    by = by.lower() if by else None
    rows = [
        e
        for e in app.store.ledger().income
        if e.account_id in accounts
        and e.account_id not in excluded_ids
        and (has_symbol is None or bool(e.symbol.strip()) == has_symbol)
        and (account_id is None or e.account_id == account_id)
        and (wanted is None or e.symbol.upper() == wanted)
        and (ccy is None or e.currency.upper() == ccy)
        and (
            search is None
            or search.casefold() in e.symbol.casefold()
            or search.casefold() in accounts[e.account_id].name.casefold()
        )
        and (min_amount is None or e.amount >= min_amount)
        and (max_amount is None or e.amount <= max_amount)
        and e.symbol.upper() not in excluded
        and (not chosen or e.kind.value.lower() in chosen)
        and e.kind.value.lower() not in excluded_kinds
        and _in_range(e.date, year, since, until, month, quarter)
    ]
    rows = _selection(
        rows,
        accounts,
        symbols,
        account_type,
        institution,
        registered,
        cash_tracked,
        excluded_currencies,
        included_dates,
        excluded_dates,
        weekdays,
        symbol_prefix,
    )
    if by:
        _grouped_payouts(app, rows, by, accounts, mode, count_only, newest_first, limit, offset, page_info, group_sort)
        return
    if count_only:
        click.echo(len(rows))
        return
    all_rows = rows

    def sort_key(event: IncomeEvent):
        field = sort_by or "date"
        if field == "account":
            return accounts[event.account_id].name.casefold()
        if field == "kind":
            return event.kind.value.lower()
        value = getattr(event, field)
        return value.casefold() if isinstance(value, str) else value

    rows = _page(sorted(rows, key=sort_key, reverse=descending or newest_first), limit, offset)
    if mode == "csv" and not fields:
        _echo_csv(PAYOUT_FIELDS, [_payout_row(e, accounts) for e in rows])
        return
    if mode == "json":
        records = [_payout_row(e, accounts) for e in rows]
        if fields:
            records = [{name: record[name] for name in fields} for record in records]
        payload = {"rows": records, "totals": _payout_totals(all_rows)}
        if page_info:
            payload.update(_page_metadata(len(all_rows), rows, limit, offset))
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if mode is not None:
        _emit(app, mode, list(fields) if fields else PAYOUT_FIELDS, [_payout_row(e, accounts) for e in rows])
        return
    if not rows:
        app.console.print(Text("No matching payouts.", style="muted"))
        return
    table = render.table("Date", "Account", "Symbol", "Kind", ("Amount", "right"), "Currency", title="Payouts")
    for e in rows:
        table.add_row(
            Text(e.date, style="muted"),
            Text(render.truncate(accounts[e.account_id].name, 22)),
            Text(e.symbol or render.DASH, style="bright" if e.symbol else "muted"),
            Text(KIND_LABELS[e.kind.value.lower()]),
            _money(app, e.amount, e.currency),
            Text(e.currency, style="muted"),
        )
    app.console.print(table)
    _print_payout_totals(app, all_rows)


def _grouped_payouts(
    app: App,
    rows: list[IncomeEvent],
    by: str,
    accounts: dict[int, Account],
    mode: str | None,
    count_only: bool,
    newest_first: bool,
    limit: int | None,
    offset: int | None,
    page_info: bool,
    group_sort: str | None = None,
) -> None:
    groups = _payout_groups(rows, by, accounts)
    if count_only:
        click.echo(len(groups))
        return
    if group_sort and group_sort.lower() != "group":
        key = group_sort.lower()  # largest first; ties keep the group order
        groups = sorted(groups, key=lambda g: g[key], reverse=True)
    total = len(groups)
    groups = _page(list(reversed(groups)) if newest_first else groups, limit, offset)
    if mode == "json":
        payload = {"by": by, "groups": groups, "totals": _payout_totals(rows)}
        if page_info:
            payload.update(_page_metadata(total, groups, limit, offset))
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if mode is not None:
        _emit(app, mode, ["group", "currency", "count", "amount"] + (["account"] if by == "account" else []), groups)
        return
    if not groups:
        app.console.print(Text("No matching payouts.", style="muted"))
        return
    table = render.table(by.title(), "Currency", ("Payouts", "right"), ("Amount", "right"), title=f"Payouts by {by}")
    for g in groups:
        label = g.get("account", g["group"]) or render.DASH
        table.add_row(Text(label), Text(g["currency"]), Text(str(g["count"])), _money(app, g["amount"], g["currency"]))
    app.console.print(table)
    _print_payout_totals(app, rows)


def _print_payout_totals(app: App, rows: list[IncomeEvent]) -> None:
    totals = render.table("Currency", ("Payouts", "right"), ("Amount", "right"), title="Totals by currency")
    for ccy, total in _payout_totals(rows).items():
        totals.add_row(Text(ccy), Text(str(total["count"])), _money(app, total["amount"], ccy))
    app.console.print(totals)
    app.console.print(Text("Native currency, as recorded in the ledger. Nothing is converted.", style="muted"))
