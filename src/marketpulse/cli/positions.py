"""Offline position and cash reports, derived from the local ledger without fetching prices."""

from __future__ import annotations

import csv
import io
import json
import math
from collections import Counter
from typing import Any

import click
from rich.text import Text

from .. import fmt, render
from ..ledger import Holding
from ..models import EPSILON, Account, AccountType, Asset, AssetClass, AssetKind
from .base import App, date_callback, fail, pass_app
from .root import main

POSITION_FIELDS = ["account_id", "account", "symbol", "quantity", "book", "average_cost", "currency", "first_date"]
CASH_FIELDS = ["account_id", "account", "currency", "balance"]
SORTS = ["account", "symbol", "quantity", "book", "first-date", "average-cost"]
OFFLINE_NOTE = "Cost basis from the local ledger; prices are not fetched. Run `marketpulse holdings` for market values."


def _finite(ctx: click.Context, param: click.Parameter, value: float | None) -> float | None:
    if value is not None and not math.isfinite(value):
        raise click.BadParameter("Must be a finite number.")
    return value


def _bounds(minimum: float | None, maximum: float | None, name: str) -> None:
    if minimum is not None and maximum is not None and minimum > maximum:
        raise click.UsageError(f"--min-{name} must be at or below --max-{name}.")


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
@click.option("--search", help="Match account name, symbol or currency text, ignoring case.")
@click.option("--symbols", multiple=True, help="Include any exact symbol; repeat for several.")
@click.option(
    "--exclude-symbol", "excluded_symbols", multiple=True, help="Exclude an exact symbol; repeat for several."
)
@click.option("--account-type", type=click.Choice([a.value for a in AccountType], case_sensitive=False))
@click.option("--institution", help="Match account institution exactly, ignoring case.")
@click.option("--min-quantity", type=float, callback=_finite, help="Inclusive quantity minimum.")
@click.option("--max-quantity", type=float, callback=_finite, help="Inclusive quantity maximum.")
@click.option("--min-book", type=float, callback=_finite, help="Inclusive book-cost minimum, in recorded currency.")
@click.option("--max-book", type=float, callback=_finite, help="Inclusive book-cost maximum, in recorded currency.")
@click.option("--exclude-currency", "excluded_currencies", multiple=True, help="Exclude exact recorded currencies.")
@click.option(
    "--exclude-account", "excluded_accounts", multiple=True, help="Exclude active account IDs, names or types."
)
@click.option(
    "--min-average-cost", type=float, callback=_finite, help="Inclusive average-cost minimum, in recorded currency."
)
@click.option(
    "--max-average-cost", type=float, callback=_finite, help="Inclusive average-cost maximum, in recorded currency."
)
@click.option("--registered/--nonregistered", default=None, help="Match the account's registration status.")
@click.option("--cash-tracked/--cash-untracked", default=None, help="Match the account's cash-tracking setting.")
@click.option("--has-metadata/--no-metadata", default=None, help="Match symbols with or without saved asset metadata.")
@click.option(
    "--asset-kind",
    type=click.Choice([kind.value for kind in AssetKind], case_sensitive=False),
    help="Match saved asset kind; symbols without metadata are market assets.",
)
@click.option(
    "--asset-class",
    type=click.Choice([kind.value for kind in AssetClass], case_sensitive=False),
    help="Match the explicitly saved asset class, without looking up quotes.",
)
@click.option("--symbol-prefix", help="Match a symbol prefix, ignoring case.")
@click.option(
    "--summary",
    type=click.Choice(["account", "currency", "symbol"]),
    help="Count matching positions by this field before pagination.",
)
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
    search: str | None,
    symbols: tuple[str, ...],
    excluded_symbols: tuple[str, ...],
    account_type: str | None,
    institution: str | None,
    min_quantity: float | None,
    max_quantity: float | None,
    min_book: float | None,
    max_book: float | None,
    excluded_currencies: tuple[str, ...],
    excluded_accounts: tuple[str, ...],
    min_average_cost: float | None,
    max_average_cost: float | None,
    registered: bool | None,
    cash_tracked: bool | None,
    has_metadata: bool | None,
    asset_kind: str | None,
    asset_class: str | None,
    symbol_prefix: str | None,
    summary: str | None,
) -> None:
    """Open positions at cost from the ledger, offline (no quotes, no snapshot)."""
    _check_outputs(as_json, as_csv, count_only)
    if count_only and (limit is not None or offset is not None or page_info):
        raise click.UsageError("--count cannot be combined with --limit, --offset or --page-info.")
    if page_info and not as_json:
        raise click.UsageError("--page-info requires --json.")
    if held_since and held_until and held_since > held_until:
        raise click.UsageError("--held-since must be on or before --held-until.")
    _bounds(min_quantity, max_quantity, "quantity")
    _bounds(min_book, max_book, "book")
    _bounds(min_average_cost, max_average_cost, "average-cost")
    _check_summary(summary, count_only, page_info)
    acct = _active_account(app, account)
    accounts = app.store.account_map()
    excluded_ids = _excluded_account_ids(app, excluded_accounts)
    excluded_ccys = {value.strip().upper() for value in excluded_currencies}
    metadata = app.store.assets() if any(value is not None for value in (has_metadata, asset_kind, asset_class)) else {}
    held = [
        h
        for h in app.store.ledger().open_holdings(acct.saved_id if acct else None)
        if h.account_id in accounts and not accounts[h.account_id].archived
    ]
    needle = symbol.strip().casefold() if symbol is not None else None
    wanted = currency.strip().upper() if currency is not None else None
    search_needle = search.strip().casefold() if search is not None else None
    included = {value.strip().upper() for value in symbols}
    excluded = {value.strip().upper() for value in excluded_symbols}
    matches = [
        h
        for h in held
        if (needle is None or needle in h.symbol.casefold())
        and (wanted is None or h.currency.upper() == wanted)
        and (not held_since or h.first_date >= held_since)
        and (not held_until or h.first_date <= held_until)
        and (
            search_needle is None
            or search_needle in " ".join([accounts[h.account_id].name, h.symbol, h.currency]).casefold()
        )
        and (not included or h.symbol in included)
        and h.symbol not in excluded
        and (account_type is None or accounts[h.account_id].type.value == account_type)
        and (institution is None or accounts[h.account_id].institution.casefold() == institution.strip().casefold())
        and (min_quantity is None or h.quantity >= min_quantity)
        and (max_quantity is None or h.quantity <= max_quantity)
        and (min_book is None or h.book >= min_book)
        and (max_book is None or h.book <= max_book)
        and h.currency.upper() not in excluded_ccys
        and h.account_id not in excluded_ids
        and (min_average_cost is None or h.avg_cost >= min_average_cost)
        and (max_average_cost is None or h.avg_cost <= max_average_cost)
        and (registered is None or accounts[h.account_id].type.registered == registered)
        and (cash_tracked is None or accounts[h.account_id].track_cash == cash_tracked)
        and (has_metadata is None or (h.symbol in metadata) == has_metadata)
        and (asset_kind is None or metadata.get(h.symbol, Asset(h.symbol)).kind.value == asset_kind)
        and (asset_class is None or metadata.get(h.symbol, Asset(h.symbol)).asset_class == asset_class)
        and (symbol_prefix is None or h.symbol.casefold().startswith(symbol_prefix.strip().casefold()))
    ]

    if summary:
        values = [accounts[h.account_id].name if summary == "account" else str(getattr(h, summary)) for h in matches]
        _count_summary(app, values, summary, "Positions", as_json, as_csv)
        return

    def account_key(h: Holding) -> tuple[str, int, str]:
        return (accounts[h.account_id].name.casefold(), h.account_id, h.symbol)

    keys = {
        "account": account_key,
        "symbol": lambda h: (h.symbol, *account_key(h)),
        "quantity": lambda h: (h.quantity, *account_key(h)),
        "book": lambda h: (h.book, *account_key(h)),
        "first-date": lambda h: (h.first_date, *account_key(h)),
        "average-cost": lambda h: (h.avg_cost, *account_key(h)),
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
@click.option("--limit", type=click.IntRange(min=1), help="Show at most N matching balances.")
@click.option("--offset", type=click.IntRange(min=0), help="Skip N matching balances after sorting.")
@click.option("--page-info", is_flag=True, help="Include total, offset and limit in JSON; requires --json.")
@click.option("--min-balance", type=float, callback=_finite, help="Inclusive balance minimum, in recorded currency.")
@click.option("--max-balance", type=float, callback=_finite, help="Inclusive balance maximum, in recorded currency.")
@click.option("--positive", is_flag=True, help="Show only strictly positive balances.")
@click.option(
    "--exclude-currency", "excluded_currencies", multiple=True, help="Exclude a currency; repeat for several."
)
@click.option(
    "--exclude-account", "excluded_accounts", multiple=True, help="Exclude an active account; repeat for several."
)
@click.option("--account-type", type=click.Choice([a.value for a in AccountType], case_sensitive=False))
@click.option("--institution", help="Match account institution exactly, ignoring case.")
@click.option("--zero", is_flag=True, help="Show only zero balances, ignoring ledger float residue.")
@click.option("--registered/--nonregistered", default=None, help="Match the account's registration status.")
@click.option(
    "--summary",
    type=click.Choice(["account", "currency", "account-type", "institution"]),
    help="Count matching balances by this field before pagination.",
)
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
    limit: int | None,
    offset: int | None,
    page_info: bool,
    min_balance: float | None,
    max_balance: float | None,
    positive: bool,
    excluded_currencies: tuple[str, ...],
    excluded_accounts: tuple[str, ...],
    account_type: str | None,
    institution: str | None,
    zero: bool,
    registered: bool | None,
    summary: str | None,
) -> None:
    """Cash balances from the ledger for accounts that track cash, offline.

    With --negative, exits 1 when any matching balance is overdrawn, even outside the selected page."""
    _check_outputs(as_json, as_csv, count_only)
    if count_only and (limit is not None or offset is not None or page_info):
        raise click.UsageError("--count cannot be combined with --limit, --offset or --page-info.")
    if page_info and not as_json:
        raise click.UsageError("--page-info requires --json.")
    if sum((positive, negative, zero)) > 1 or (zero and nonzero):
        raise click.UsageError("Choose one of --positive, --negative or --zero; --zero conflicts with --nonzero.")
    _check_summary(summary, count_only, page_info)
    _bounds(min_balance, max_balance, "balance")
    acct = _active_account(app, account)
    excluded_ids = _excluded_account_ids(app, excluded_accounts)
    excluded_ccys = {value.strip().upper() for value in excluded_currencies}
    accounts = app.store.account_map()
    wanted = currency.strip().upper() if currency is not None else None
    needle = search.strip().casefold() if search is not None else None
    rows: list[dict[str, Any]] = []
    for (account_id, ccy), balance in sorted(app.store.ledger().cash.items()):
        owner = accounts.get(account_id)
        if owner is None or owner.archived or not owner.track_cash:
            continue
        if account_id in excluded_ids or ccy.upper() in excluded_ccys:
            continue
        if account_type is not None and owner.type.value != account_type:
            continue
        if institution is not None and owner.institution.casefold() != institution.strip().casefold():
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
        if positive and balance <= 0:
            continue
        if zero and balance != 0:
            continue
        if registered is not None and owner.type.registered != registered:
            continue
        if min_balance is not None and balance < min_balance:
            continue
        if max_balance is not None and balance > max_balance:
            continue
        rows.append({"account_id": account_id, "account": owner.name, "currency": ccy, "balance": balance})

    if summary:
        values = []
        for row in rows:
            owner = accounts[row["account_id"]]
            if summary == "account-type":
                values.append(owner.type.value)
            elif summary == "institution":
                values.append(owner.institution.strip())
            else:
                values.append(str(row[summary]))
        _count_summary(app, values, summary, "Balances", as_json, as_csv)
        if negative and rows:
            raise click.exceptions.Exit(1)
        return

    def account_key(row: dict[str, Any]) -> tuple[str, int, str]:
        return (str(row["account"]).casefold(), row["account_id"], row["currency"])

    keys = {
        "account": account_key,
        "currency": lambda row: (row["currency"], *account_key(row)),
        "balance": lambda row: (row["balance"], *account_key(row)),
    }
    rows.sort(key=keys[sort_by.lower()], reverse=descending)
    total = len(rows)
    offset = offset or 0
    rows = rows[offset : offset + limit if limit is not None else None]
    if count_only:
        click.echo(len(rows))
    elif as_csv:
        _emit_csv(CASH_FIELDS, rows)
    elif as_json:
        payload = {"rows": rows, "total": total, "offset": offset, "limit": limit} if page_info else rows
        click.echo(json.dumps(payload, ensure_ascii=False))
    elif not rows:
        if acct is not None and not acct.track_cash:
            message = f"Account '{acct.name}' doesn't track cash."
        elif total:
            message = "No cash balances on this page."
        elif negative:
            message = "No overdrawn cash balances."
        elif (
            wanted is not None
            or needle is not None
            or nonzero
            or positive
            or zero
            or registered is not None
            or min_balance is not None
            or max_balance is not None
            or excluded_currencies
            or excluded_accounts
            or account_type is not None
            or institution is not None
        ):
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
    if negative and total:
        raise click.exceptions.Exit(1)


def _excluded_account_ids(app: App, refs: tuple[str, ...]) -> set[int]:
    ids = set()
    for ref in refs:
        account = _active_account(app, ref)
        if account is None:
            fail(f"No active account '{ref}'.")
        ids.add(account.saved_id)
    return ids


def _check_summary(summary: str | None, count_only: bool, page_info: bool) -> None:
    if summary and (count_only or page_info):
        raise click.UsageError("--summary cannot be combined with --count or --page-info.")


def _count_summary(app: App, values: list[str], group: str, label: str, as_json: bool, as_csv: bool) -> None:
    rows = [{"group": key, "count": count} for key, count in sorted(Counter(values).items())]
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
    elif as_csv:
        _emit_csv(["group", "count"], rows)
    else:
        table = render.table(group.title(), (label, "right"), title="Matching " + label.lower())
        for row in rows:
            table.add_row(Text(str(row["group"]) or "(blank)"), Text(str(row["count"])))
        app.console.print(table)
