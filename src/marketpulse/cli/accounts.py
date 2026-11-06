"""Accounts and contribution room."""

from __future__ import annotations

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
@pass_app
def accounts_list(app: App, archived: bool) -> None:
    items = app.store.accounts(include_archived=archived)
    if not items:
        app.console.print(Text('No accounts yet — `marketpulse accounts add "My TFSA" -t TFSA`.', style="muted"))
        return
    with app.busy("Pricing accounts…"):
        view = app.tracker.valuation()
    values = {b.key: b for b in view.by_account}
    t = render.table(
        ("ID", "right"),
        "Name",
        "Type",
        "Ccy",
        "Institution",
        "Cash",
        ("Value", "right"),
        ("Today", "right"),
        ("Weight", "right"),
    )
    for a in items:
        b = values.get(str(a.id))
        t.add_row(
            Text(str(a.id), style="muted"),
            Text(a.name + (" (archived)" if a.archived else ""), style="bright"),
            Text(a.type.label, style="accent" if a.type.registered else ""),
            Text(a.currency, style="muted"),
            Text(a.institution or "—", style="muted"),
            Text("tracked" if a.track_cash else "—", style="muted"),
            Text(fmt.money(b.value, view.base, privacy=app.privacy)) if b else render.dash(),
            render.trend(fmt.pct(b.day_change_pct), b.day_change) if b else render.dash(),
            Text(fmt.pct(b.weight, sign=False), style="muted") if b else render.dash(),
        )
    app.console.print(t)


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
