"""Accounts and contribution room."""

from __future__ import annotations

import json
from dataclasses import asdict

import click
from rich.text import Text

from .. import fmt, render
from ..models import Account, AccountType
from ..tax import TaxReport
from .base import App, fail, pass_app
from .root import main

ACCOUNT_TYPES = [t.value for t in AccountType]


@main.group(invoke_without_command=True)
@click.pass_context
def accounts(ctx: click.Context) -> None:
    """Accounts (TFSA, RRSP, FHSA, non-registered, crypto…) and contribution room."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(accounts_list)


@accounts.command("list")
@click.option("--archived", is_flag=True, help="Include archived accounts.")
@click.option("--offline", is_flag=True, help="Show account metadata without fetching prices or recording a snapshot.")
@click.option(
    "--json", "as_json", is_flag=True, help="Print unmasked account metadata as JSON, without fetching prices."
)
@click.option("-t", "--type", "acct_type", type=click.Choice(ACCOUNT_TYPES, case_sensitive=False))
@click.option("--institution", help="Match an institution exactly, ignoring case.")
@click.option("--search", help="Find account names containing this text, ignoring case.")
@click.option("--currency", help="Match the configured currency, ignoring case.")
@click.option("--cash/--no-cash", default=None, help="Filter accounts by cash tracking.")
@click.option("--sort", "sort_by", type=click.Choice(["name", "type", "institution", "currency"]))
@click.option("--descending", is_flag=True, help="Reverse the selected order (default: account ID).")
@pass_app
def accounts_list(
    app: App,
    archived: bool,
    offline: bool,
    as_json: bool,
    acct_type: str | None,
    institution: str | None,
    search: str | None,
    currency: str | None,
    cash: bool | None,
    sort_by: str | None,
    descending: bool,
) -> None:
    """List accounts, optionally filtering or reading metadata offline."""
    items = app.store.accounts(include_archived=archived)
    filtered = any(value is not None for value in (acct_type, institution, search, currency, cash))
    if acct_type is not None:
        items = [a for a in items if a.type.value == acct_type]
    if institution is not None:
        items = [a for a in items if a.institution.casefold() == institution.strip().casefold()]
    if search is not None:
        items = [a for a in items if search.casefold() in a.name.casefold()]
    if currency is not None:
        items = [a for a in items if a.currency.casefold() == currency.strip().casefold()]
    if cash is not None:
        items = [a for a in items if a.track_cash == cash]
    if sort_by is not None:
        items.sort(key=lambda a: (str(getattr(a, sort_by)).casefold(), a.saved_id))
    if descending:
        items.reverse()
    if as_json:
        click.echo(json.dumps([asdict(a) for a in items], ensure_ascii=False))
        return
    if not items:
        message = (
            "No accounts match these filters."
            if filtered
            else 'No accounts yet — `marketpulse accounts add "My TFSA" -t TFSA`.'
        )
        app.console.print(Text(message, style="muted"))
        return
    view = None
    if not offline:
        with app.busy("Pricing accounts…"):
            view = app.tracker.valuation()
    values = {b.key: b for b in view.by_account} if view is not None else {}
    value_columns: list[render.Column] = (
        [("Value", "right"), ("Today", "right"), ("Weight", "right")] if view is not None else []
    )
    t = render.table(
        ("ID", "right"),
        "Name",
        "Type",
        "Ccy",
        "Institution",
        "Cash",
        *value_columns,
    )
    for a in items:
        cells = [
            Text(str(a.id), style="muted"),
            Text(a.name + (" (archived)" if a.archived else ""), style="bright"),
            Text(a.type.label, style="accent" if a.type.registered else ""),
            Text(a.currency, style="muted"),
            Text(a.institution or "—", style="muted"),
            Text("tracked" if a.track_cash else "—", style="muted"),
        ]
        if view is not None:
            b = values.get(str(a.id))
            cells.extend(
                [
                    Text(fmt.money(b.value, view.base, privacy=app.privacy)) if b else render.dash(),
                    render.trend(fmt.pct(b.day_change_pct), b.day_change) if b else render.dash(),
                    Text(fmt.pct(b.weight, sign=False), style="muted") if b else render.dash(),
                ]
            )
        t.add_row(*cells)
    app.console.print(t)


@accounts.command("show")
@click.argument("ref")
@click.option("--json", "as_json", is_flag=True, help="Print unmasked account metadata as JSON.")
@pass_app
def accounts_show(app: App, ref: str, as_json: bool) -> None:
    """Inspect an active account by ID, name or unique type, without pricing."""
    account = app.store.get_account(ref)
    if account is None or account.archived:
        fail(f"No active account '{ref}'.")
    payload = asdict(account)
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    table = render.table("Field", "Value", title="Account metadata")
    for field, value in payload.items():
        table.add_row(Text(field), Text(str(value)))
    app.console.print(table)


@accounts.command("add")
@click.argument("name")
@click.option(
    "-t",
    "--type",
    "acct_type",
    type=click.Choice(ACCOUNT_TYPES, case_sensitive=False),
    default="NONREG",
    show_default=True,
)
@click.option("-c", "--currency", default=None, help="Default: base currency.")
@click.option("-i", "--institution", default="")
@click.option("--track-cash", is_flag=True, help="Track a cash balance (buys debit, sells/dividends credit).")
@pass_app
def accounts_add(app: App, name, acct_type, currency, institution, track_cash) -> None:
    try:
        acct = app.store.add_account(
            Account(
                name=name,
                type=AccountType(acct_type.upper()),
                currency=(currency or app.config.base_currency).upper(),
                institution=institution,
                track_cash=track_cash,
            )
        )
    except ValueError as e:
        fail(str(e))
    app.ok(f"Added {acct.name} ({acct.type.label}, {acct.currency}) as #{acct.id}")


@accounts.command("edit")
@click.argument("ref")
@click.option("--name")
@click.option("-t", "--type", "acct_type", type=click.Choice(ACCOUNT_TYPES, case_sensitive=False))
@click.option("-c", "--currency")
@click.option("-i", "--institution")
@click.option("--track-cash/--no-track-cash", default=None)
@click.option("--archive/--unarchive", default=None)
@click.option(
    "--revision", help="Refuse unless the account is unchanged since it had this revision (from `desktop snapshot`)."
)
@pass_app
def accounts_edit(app: App, ref, name, acct_type, currency, institution, track_cash, archive, revision) -> None:
    restore_id = app.store.restore_id
    acct = app.account(ref)
    if revision is None:
        # Every field is written back, so a change made elsewhere since it was read is refused.
        revision = acct.revision(restore_id)
    if name is not None:
        acct.name = name
    if acct_type:
        acct.type = AccountType(acct_type.upper())
    if currency:
        acct.currency = currency.upper()
    if institution is not None:
        acct.institution = institution
    if track_cash is not None:
        acct.track_cash = track_cash
    if archive is not None:
        acct.archived = archive
    try:
        app.tracker.update_account(acct, restore_id=restore_id, revision=revision)
    except ValueError as e:
        fail(str(e))
    app.ok(f"Updated {acct.name}.")


@accounts.command("remove")
@click.argument("ref")
@click.option("-y", "--yes", is_flag=True)
@pass_app
def accounts_remove(app: App, ref, yes) -> None:
    acct = app.account(ref)
    count = len([t for t in app.store.transactions() if t.account_id == acct.id])
    if yes or click.confirm(
        f"Delete {acct.name} and its {count} transaction(s)? Consider `accounts edit {acct.name} --archive` instead."
    ):
        app.store.delete_account(acct.saved_id)
        app.ok(f"Deleted {acct.name}.")


@accounts.command("room")
@click.argument(
    "account_type", type=click.Choice(["TFSA", "RRSP", "FHSA", "RESP"], case_sensitive=False), required=False
)
@click.argument("year", type=int, required=False)
@click.argument("amount", type=float, required=False)
@pass_app
def accounts_room(app: App, account_type, year, amount) -> None:
    """Set or show contribution room.

    \b
    Give the room CRA reported as of Jan 1 of YEAR (My Account → RRSP/TFSA):
      marketpulse accounts room TFSA 2026 21500
    TFSA and FHSA roll forward automatically with new annual limits.
    """
    if account_type and year is not None and amount is not None:
        app.store.set_room(account_type.upper(), year, amount)
        app.ok(f"{account_type.upper()} room as of Jan 1 {year}: {fmt.money(amount)}")
    elif account_type:
        fail("Usage: marketpulse accounts room TYPE YEAR AMOUNT")
    rooms = app.tracker.room()
    if not rooms:
        app.console.print(Text("No contribution room recorded yet.", style="muted"))
        return
    app.console.print(
        # Room only: an empty tax report (no years, no issues) renders just the room table.
        render.tax_group([], TaxReport(), rooms, app.store.account_map(), app.config.base_currency, privacy=app.privacy)
    )
