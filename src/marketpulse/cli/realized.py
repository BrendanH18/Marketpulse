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
from collections import defaultdict

import click
from rich.text import Text

from .. import fmt, render
from ..ledger import IncomeEvent, RealizedGain
from ..models import Account
from .base import App, date_callback, fail, pass_app
from .root import main

NOT_TAX = "Native currency, average cost from the ledger. Not the tax report; see `marketpulse tax`."
KINDS = ("dividend", "drip", "interest")
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


def _filters(f):
    """Options shared by `realized` and `payouts`."""
    for decorator in reversed(
        [
            click.option("-a", "--account", default=None, help="Only this account (name, id or type)."),
            click.option("-s", "--symbol", default=None, help="Only this symbol (exact, case-insensitive)."),
            click.option("--year", type=click.IntRange(min=1, max=9999), help="Only this calendar year."),
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
        ]
    ):
        f = decorator(f)
    return f


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


def _in_range(day: str, year: int | None, since: str | None, until: str | None) -> bool:
    return (year is None or day[:4] == f"{year:04d}") and (not since or day >= since) and (not until or day <= until)


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


def _realized_totals(rows: list[RealizedGain]) -> dict[str, dict]:
    by_currency: dict[str, list[RealizedGain]] = defaultdict(list)
    for r in rows:
        by_currency[r.currency].append(r)
    return {
        ccy: {
            "count": len(items),
            "proceeds": math.fsum(r.proceeds for r in items),
            "cost": math.fsum(r.cost for r in items),
            "gain": math.fsum(r.gain for r in items),
        }
        for ccy, items in sorted(by_currency.items())
    }


@main.command()
@_filters
@click.option("--gains-only", is_flag=True, help="Only sales with a gain (rounded to the cent).")
@click.option("--losses-only", is_flag=True, help="Only sales with a loss (rounded to the cent).")
@pass_app
def realized(
    app: App,
    account,
    symbol,
    year,
    since,
    until,
    as_json,
    as_csv,
    gains_only,
    losses_only,
    currency,
    count_only,
    newest_first,
    limit,
    offset,
) -> None:
    """Realized gains from the ledger, oldest first, totalled per native currency (offline).

    Not the tax report: no FX conversion and no superficial-loss rules. Use `marketpulse tax` for that."""
    _check_common(since, until, as_json, as_csv)
    ccy = _browsing_currency(currency, count_only, as_json, as_csv, limit, offset, newest_first)
    if gains_only and losses_only:
        raise click.UsageError("Choose one of --gains-only or --losses-only.")
    accounts, account_id = _scope(app, account)
    wanted = symbol.strip().upper() if symbol is not None else None
    rows = [
        r
        for r in app.store.ledger().realized  # replay order: date, then same-day order
        if r.account_id in accounts
        and (account_id is None or r.account_id == account_id)
        and (wanted is None or r.symbol.upper() == wanted)
        and (ccy is None or r.currency.upper() == ccy)
        and _in_range(r.date, year, since, until)
        and (not gains_only or round(r.gain, 2) > 0)
        and (not losses_only or round(r.gain, 2) < 0)
    ]
    if count_only:
        click.echo(len(rows))
        return
    all_rows = rows
    rows = _page(sorted(rows, key=lambda r: r.date, reverse=newest_first), limit, offset)
    if as_csv:
        _echo_csv(REALIZED_FIELDS, [_realized_row(r, accounts) for r in rows])
        return
    if as_json:
        payload = {"rows": [_realized_row(r, accounts) for r in rows], "totals": _realized_totals(all_rows)}
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if not rows:
        app.console.print(Text("No matching realized gains.", style="muted"))
        return
    table = render.table(
        "Date",
        "Account",
        "Symbol",
        ("Qty", "right"),
        ("Proceeds", "right"),
        ("ACB", "right"),
        ("Gain", "right"),
        "Currency",
        title="Realized gains",
    )
    for r in rows:
        table.add_row(
            Text(r.date, style="muted"),
            Text(render.truncate(accounts[r.account_id].name, 22)),
            Text(r.symbol, style="bright"),
            Text(fmt.MASK if app.privacy else fmt.qty(r.quantity)),
            _money(app, r.proceeds, r.currency),
            _money(app, r.cost, r.currency),
            _money(app, r.gain, r.currency, sign=True),
            Text(r.currency, style="muted"),
        )
    app.console.print(table)
    totals = render.table(
        "Currency",
        ("Sales", "right"),
        ("Proceeds", "right"),
        ("ACB", "right"),
        ("Gain", "right"),
        title="Totals by currency",
    )
    for ccy, total in _realized_totals(all_rows).items():
        totals.add_row(
            Text(ccy),
            Text(str(total["count"])),
            _money(app, total["proceeds"], ccy),
            _money(app, total["cost"], ccy),
            _money(app, total["gain"], ccy, sign=True),
        )
    app.console.print(totals)
    app.console.print(Text(NOT_TAX, style="muted"))


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
@click.option(
    "--kind",
    "kinds",
    multiple=True,
    type=click.Choice(KINDS, case_sensitive=False),
    help="Only this kind of payout; repeat for several.",
)
@click.option(
    "--by",
    type=click.Choice(["month", "year", "symbol", "account"], case_sensitive=False),
    help="Show totals per group and currency instead of each payout.",
)
@pass_app
def payouts(
    app: App,
    account,
    symbol,
    year,
    since,
    until,
    as_json,
    as_csv,
    kinds,
    by,
    currency,
    count_only,
    newest_first,
    limit,
    offset,
) -> None:
    """Recorded dividend, DRIP and interest income, oldest first, per native currency (offline)."""
    _check_common(since, until, as_json, as_csv)
    ccy = _browsing_currency(currency, count_only, as_json, as_csv, limit, offset, newest_first)
    accounts, account_id = _scope(app, account)
    wanted = symbol.strip().upper() if symbol is not None else None
    chosen = {k.lower() for k in kinds}
    by = by.lower() if by else None
    rows = [
        e
        for e in app.store.ledger().income
        if e.account_id in accounts
        and (account_id is None or e.account_id == account_id)
        and (wanted is None or e.symbol.upper() == wanted)
        and (ccy is None or e.currency.upper() == ccy)
        and (not chosen or e.kind.value.lower() in chosen)
        and _in_range(e.date, year, since, until)
    ]
    if by:
        _grouped_payouts(app, rows, by, accounts, as_json, as_csv, count_only, newest_first, limit, offset)
        return
    if count_only:
        click.echo(len(rows))
        return
    all_rows = rows
    rows = _page(sorted(rows, key=lambda e: e.date, reverse=newest_first), limit, offset)
    if as_csv:
        _echo_csv(PAYOUT_FIELDS, [_payout_row(e, accounts) for e in rows])
        return
    if as_json:
        payload = {"rows": [_payout_row(e, accounts) for e in rows], "totals": _payout_totals(all_rows)}
        click.echo(json.dumps(payload, ensure_ascii=False))
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
    as_json: bool,
    as_csv: bool,
    count_only: bool,
    newest_first: bool,
    limit: int | None,
    offset: int | None,
) -> None:
    groups = _payout_groups(rows, by, accounts)
    if count_only:
        click.echo(len(groups))
        return
    groups = _page(list(reversed(groups)) if newest_first else groups, limit, offset)
    if as_csv:
        _echo_csv(["group", "currency", "count", "amount"] + (["account"] if by == "account" else []), groups)
        return
    if as_json:
        click.echo(json.dumps({"by": by, "groups": groups, "totals": _payout_totals(rows)}, ensure_ascii=False))
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
