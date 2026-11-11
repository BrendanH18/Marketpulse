"""Offline position and cash reports, derived from the local ledger without fetching prices."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import click
from rich.text import Text

from .. import fmt, render
from ..ledger import Holding
from ..models import EPSILON, Account
from .base import App, date_callback, fail, pass_app
from .root import main

POSITION_FIELDS = ["account_id", "account", "symbol", "quantity", "book", "average_cost", "currency", "first_date"]
CASH_FIELDS = ["account_id", "account", "currency", "balance"]
SORTS = ["account", "symbol", "quantity", "book", "first-date"]
OFFLINE_NOTE = "Cost basis from the local ledger; prices are not fetched. Run `marketpulse holdings` for market values."


def _active_account(app: App, ref: str | None) -> Account | None:
    """Resolve -a/--account; archived accounts are reported exactly like unknown ones."""
    if not ref:
        return None
    acct = app.store.get_account(ref)
    if acct is None or acct.archived:
        fail(f"No active account '{ref}'.")
    return acct


def _check_outputs(as_json: bool, as_csv: bool, count_only: bool = False) -> None:
    if (as_json and as_csv) or (count_only and (as_json or as_csv)):
        raise click.UsageError("Choose one output format; --count cannot be combined with --json or --csv.")


def _emit_csv(fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    click.echo(stream.getvalue(), nl=False)


@main.command()
@click.option("-a", "--account", default=None, help="Only this active account (name, id or type).")
@click.option("--symbol", help="Match symbols containing this text, ignoring case.")
@click.option("--currency", help="Only positions held in this currency, ignoring case.")
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(SORTS, case_sensitive=False),
    default="account",
    show_default=True,
    help="Order rows by this field (ties fall back to account, then symbol).",
)
@click.option("--descending", is_flag=True, help="Reverse the selected order.")
@click.option("--json", "as_json", is_flag=True, help="Print raw, unmasked positions as JSON.")
@click.option("--csv", "as_csv", is_flag=True, help="Print raw, unmasked positions as CSV to stdout.")
@click.option("--count", "count_only", is_flag=True, help="Print only the number of matching positions.")
@click.option("--limit", type=click.IntRange(min=1), help="Show at most N matching positions.")
@click.option("--offset", type=click.IntRange(min=0), help="Skip N matching positions after sorting.")
@click.option("--page-info", is_flag=True, help="Include total, offset and limit in a JSON envelope; requires --json.")
@click.option("--held-since", callback=date_callback, help="Only holdings first opened on or after this date.")
@click.option("--held-until", callback=date_callback, help="Only holdings first opened on or before this date.")
@pass_app
def positions(
    app: App,
    account: str | None,
    symbol: str | None,
    currency: str | None,
    sort_by: str,
    descending: bool,
    as_json: bool,
    as_csv: bool,
    count_only: bool,
    limit: int | None,
    offset: int | None,
    page_info: bool,
    held_since: str | None,
    held_until: str | None,
) -> None:
    """Open positions at cost from the ledger, offline (no quotes, no snapshot)."""
    _check_outputs(as_json, as_csv, count_only)
    if count_only and (limit is not None or offset is not None or page_info):
        raise click.UsageError("--count cannot be combined with --limit, --offset or --page-info.")
    if page_info and not as_json:
        raise click.UsageError("--page-info requires --json.")
    if held_since and held_until and held_since > held_until:
        raise click.UsageError("--held-since must be on or before --held-until.")
    acct = _active_account(app, account)
    accounts = app.store.account_map()
    held = [
        h
        for h in app.store.ledger().open_holdings(acct.saved_id if acct else None)
        if h.account_id in accounts and not accounts[h.account_id].archived
    ]
    needle = symbol.strip().casefold() if symbol is not None else None
    wanted = currency.strip().upper() if currency is not None else None
    matches = [
        h
        for h in held
        if (needle is None or needle in h.symbol.casefold())
        and (wanted is None or h.currency.upper() == wanted)
        and (not held_since or h.first_date >= held_since)
        and (not held_until or h.first_date <= held_until)
    ]

    def account_key(h: Holding) -> tuple[str, int, str]:
        return (accounts[h.account_id].name.casefold(), h.account_id, h.symbol)

    keys = {
        "account": account_key,
        "symbol": lambda h: (h.symbol, *account_key(h)),
        "quantity": lambda h: (h.quantity, *account_key(h)),
        "book": lambda h: (h.book, *account_key(h)),
        "first-date": lambda h: (h.first_date, *account_key(h)),
    }
    matches.sort(key=keys[sort_by.lower()], reverse=descending)
    if count_only:
        click.echo(len(matches))
        return
    total = len(matches)
    offset = offset or 0
    matches = matches[offset : offset + limit if limit is not None else None]
    rows: list[dict[str, Any]] = [
        {
            "account_id": h.account_id,
            "account": accounts[h.account_id].name,
            "symbol": h.symbol,
            "quantity": h.quantity,
            "book": h.book,
            "average_cost": h.avg_cost,
            "currency": h.currency,
            "first_date": h.first_date,
        }
        for h in matches
    ]
    if as_csv:
        _emit_csv(POSITION_FIELDS, rows)
        return
    if as_json:
        payload = {"rows": rows, "total": total, "offset": offset, "limit": limit} if page_info else rows
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if not rows:
        message = "No positions match these filters." if held else "No open positions yet."
        app.console.print(Text(message, style="muted"))
        return
    privacy = app.privacy
    table = render.table(
        "Account",
        "Symbol",
        ("Quantity", "right"),
        ("Book cost", "right"),
        ("Avg cost", "right"),
        "Ccy",
        "Held since",
        title="Open positions (at cost)",
    )
    for row in rows:
        table.add_row(
            Text(str(row["account"]), style="muted"),
            Text(str(row["symbol"]), style="bright"),
            Text(fmt.MASK if privacy else fmt.qty(row["quantity"])),
            Text(fmt.money(row["book"], privacy=privacy)),
            Text(fmt.MASK if privacy else fmt.price(row["average_cost"]), style="muted"),
            Text(str(row["currency"]), style="muted"),
            Text(str(row["first_date"]) or "—", style="muted"),
        )
    app.console.print(table)
    app.console.print(Text(OFFLINE_NOTE, style="muted"))


@main.command()
@click.option("-a", "--account", default=None, help="Only this active account (name, id or type).")
@click.option("--currency", help="Only balances in this currency, ignoring case.")
@click.option("--negative", is_flag=True, help="Show only overdrawn balances; exit 1 if any exist.")
@click.option("--count", "count_only", is_flag=True, help="Print only the number of matching cash balances.")
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(["account", "currency", "balance"], case_sensitive=False),
    default="account",
    show_default=True,
    help="Order cash balances by this field.",
)
@click.option("--descending", is_flag=True, help="Reverse the selected cash balance order.")
@click.option("--nonzero", is_flag=True, help="Exclude zero cash balances, ignoring ledger float residue.")
@click.option("--search", help="Match account names containing this text, ignoring case.")
@click.option("--json", "as_json", is_flag=True, help="Print raw, unmasked balances as JSON.")
@click.option("--csv", "as_csv", is_flag=True, help="Print raw, unmasked balances as CSV to stdout.")
@pass_app
def cash(
    app: App,
    account: str | None,
    currency: str | None,
    negative: bool,
    count_only: bool,
    sort_by: str,
    descending: bool,
    nonzero: bool,
    search: str | None,
    as_json: bool,
    as_csv: bool,
) -> None:
    """Cash balances from the ledger for accounts that track cash, offline.

    With --negative, exits 1 when any listed balance is overdrawn so scripts can alert on it."""
    _check_outputs(as_json, as_csv, count_only)
    acct = _active_account(app, account)
    accounts = app.store.account_map()
    wanted = currency.strip().upper() if currency is not None else None
    needle = search.strip().casefold() if search is not None else None
    rows: list[dict[str, Any]] = []
    for (account_id, ccy), balance in sorted(app.store.ledger().cash.items()):
        owner = accounts.get(account_id)
        if owner is None or owner.archived or not owner.track_cash:
            continue
        if needle is not None and needle not in owner.name.casefold():
            continue
        if acct is not None and account_id != acct.saved_id:
            continue
        if wanted is not None and ccy.upper() != wanted:
            continue
        balance = 0.0 if abs(balance) < EPSILON else balance  # float residue from replay
        if nonzero and balance == 0:
            continue
        if negative and balance >= 0:
            continue
        rows.append({"account_id": account_id, "account": owner.name, "currency": ccy, "balance": balance})

    def account_key(row: dict[str, Any]) -> tuple[str, int, str]:
        return (str(row["account"]).casefold(), row["account_id"], row["currency"])

    keys = {
        "account": account_key,
        "currency": lambda row: (row["currency"], *account_key(row)),
        "balance": lambda row: (row["balance"], *account_key(row)),
    }
    rows.sort(key=keys[sort_by.lower()], reverse=descending)
    if count_only:
        click.echo(len(rows))
    elif as_csv:
        _emit_csv(CASH_FIELDS, rows)
    elif as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
    elif not rows:
        if acct is not None and not acct.track_cash:
            message = f"Account '{acct.name}' doesn't track cash."
        elif negative:
            message = "No overdrawn cash balances."
        elif wanted is not None or needle is not None or nonzero:
            message = "No cash balances match these filters."
        else:
            message = "No cash balances yet. Only accounts that track cash have one."
        app.console.print(Text(message, style="muted"))
    else:
        privacy = app.privacy
        table = render.table("Account", "Ccy", ("Balance", "right"), title="Cash (ledger)")
        for row in rows:
            overdrawn = row["balance"] < 0 and not privacy  # the style alone would reveal the sign
            table.add_row(
                Text(str(row["account"]), style="muted"),
                Text(str(row["currency"]), style="muted"),
                Text(fmt.money(row["balance"], privacy=privacy), style="down" if overdrawn else ""),
            )
        app.console.print(table)
    if negative and rows:
        raise click.exceptions.Exit(1)
