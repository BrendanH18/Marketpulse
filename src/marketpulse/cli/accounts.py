"""Accounts and contribution room."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from dataclasses import asdict, fields

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
@click.option("--csv", "as_csv", is_flag=True, help="Print raw account metadata as CSV, offline.")
@click.option("--count", "count_only", is_flag=True, help="Count matching accounts before pagination, offline.")
@click.option("--limit", type=click.IntRange(min=1), help="Show at most this many accounts, offline.")
@click.option("--offset", type=click.IntRange(min=0), help="Skip matching accounts, offline.")
@click.option("--page-info", is_flag=True, help="With --json, include pagination metadata.")
@click.option("--archived", is_flag=True, help="Include archived accounts.")
@click.option("--offline", is_flag=True, help="Show account metadata without fetching prices or recording a snapshot.")
@click.option(
    "--json", "as_json", is_flag=True, help="Print unmasked account metadata as JSON, without fetching prices."
)
@click.option("-t", "--type", "acct_types", type=click.Choice(ACCOUNT_TYPES, case_sensitive=False), multiple=True)
@click.option(
    "--institution", "institutions", multiple=True, help="Match any listed institution exactly, ignoring case."
)
@click.option("--search", help="Find account names containing this text, ignoring case.")
@click.option(
    "--account",
    "included_accounts",
    multiple=True,
    help="Include only these account IDs, names or unique active types; offline.",
)
@click.option(
    "--exclude-type",
    "excluded_types",
    multiple=True,
    type=click.Choice(ACCOUNT_TYPES, case_sensitive=False),
    help="Exclude listed account types; offline.",
)
@click.option(
    "--exclude-currency", "excluded_currencies", multiple=True, help="Exclude listed configured currencies; offline."
)
@click.option(
    "--exclude-institution",
    "excluded_institutions",
    multiple=True,
    help="Exclude exact institutions, ignoring case; offline.",
)
@click.option(
    "--exclude-search", multiple=True, help="Exclude names containing any listed text, ignoring case; offline."
)
@click.option("--institution-search", help="Find institutions containing this text, ignoring case; offline.")
@click.option("--currency", "currencies", multiple=True, help="Match any listed configured currency, ignoring case.")
@click.option("--cash/--no-cash", default=None, help="Filter accounts by cash tracking.")
@click.option("--sort", "sort_by", type=click.Choice(["name", "type", "institution", "currency"]))
@click.option("--descending", is_flag=True, help="Reverse the selected order (default: account ID).")
@click.option(
    "--exclude-account",
    "excluded_accounts",
    multiple=True,
    help="Exclude an account by ID, name or unique active type; repeat for several.",
)
@click.option(
    "--registered/--nonregistered", default=None, help="Match registered or nonregistered account types, offline."
)
@click.option(
    "--has-institution/--no-institution",
    default=None,
    help="Match accounts with or without a nonblank institution, offline.",
)
@click.option("--min-id", type=click.IntRange(min=1), help="Minimum account ID, inclusive; offline.")
@click.option("--max-id", type=click.IntRange(min=1), help="Maximum account ID, inclusive; offline.")
@click.option(
    "--summary",
    type=click.Choice(["type", "currency", "institution", "cash", "registered"]),
    help="Count matching accounts by this field before pagination, offline.",
)
@click.option(
    "--summary-sort",
    type=click.Choice(["group", "count"]),
    default="group",
    help="Sort summaries by group or descending count.",
)
@click.option(
    "--has-positions/--no-positions",
    default=None,
    help="Match accounts with or without open ledger positions, offline.",
)
@click.option(
    "--has-transactions/--no-transactions", default=None, help="Match accounts with or without ledger entries, offline."
)
@click.option(
    "--min-transactions",
    type=click.IntRange(min=0),
    help="Minimum ledger-entry count, including incoming transfers, offline.",
)
@click.option(
    "--max-transactions",
    type=click.IntRange(min=0),
    help="Maximum ledger-entry count, including incoming transfers, offline.",
)
@click.option("--name-prefix", help="Match account name prefixes, ignoring case, offline.")
@click.option("--name-suffix", help="Match account name suffixes, ignoring case, offline.")
@pass_app
def accounts_list(
    app: App,
    archived: bool,
    as_csv: bool,
    count_only: bool,
    limit: int | None,
    offset: int | None,
    page_info: bool,
    offline: bool,
    as_json: bool,
    acct_types: tuple[str, ...],
    institutions: tuple[str, ...],
    search: str | None,
    currencies: tuple[str, ...],
    included_accounts: tuple[str, ...],
    excluded_types: tuple[str, ...],
    excluded_currencies: tuple[str, ...],
    excluded_institutions: tuple[str, ...],
    exclude_search: tuple[str, ...],
    institution_search: str | None,
    cash: bool | None,
    sort_by: str | None,
    descending: bool,
    excluded_accounts: tuple[str, ...],
    registered: bool | None,
    has_institution: bool | None,
    min_id: int | None,
    max_id: int | None,
    summary: str | None,
    summary_sort: str,
    has_positions: bool | None,
    has_transactions: bool | None,
    min_transactions: int | None,
    max_transactions: int | None,
    name_prefix: str | None,
    name_suffix: str | None,
) -> None:
    """List accounts, optionally filtering or reading metadata offline."""
    if sum((as_json, as_csv, count_only)) > 1:
        raise click.UsageError("Choose one of --json, --csv, or --count.")
    if page_info and not as_json:
        raise click.UsageError("--page-info requires --json.")
    if min_id is not None and max_id is not None and min_id > max_id:
        raise click.UsageError("--min-id must be at or below --max-id.")
    if summary and (count_only or page_info):
        raise click.UsageError("--summary cannot be combined with --count or --page-info.")
    if min_transactions is not None and max_transactions is not None and min_transactions > max_transactions:
        raise click.UsageError("--min-transactions must be at or below --max-transactions.")
    if summary_sort != "group" and not summary:
        raise click.UsageError("--summary-sort requires --summary.")
    selection = (
        bool(
            excluded_accounts
            or included_accounts
            or excluded_types
            or excluded_currencies
            or excluded_institutions
            or exclude_search
        )
        or institution_search is not None
        or any(len(values) > 1 for values in (acct_types, institutions, currencies))
    ) or any(value is not None for value in (registered, has_institution, min_id, max_id))
    selection = selection or any(
        value is not None
        for value in (has_positions, has_transactions, min_transactions, max_transactions, name_prefix, name_suffix)
    )
    offline = offline or as_csv or count_only or limit is not None or offset is not None or selection or bool(summary)
    items = app.store.accounts(include_archived=archived)
    included_ids = set()
    for ref in included_accounts:
        found = app.store.get_account(ref)
        if found is None or (found.archived and not archived):
            fail(f"No {'matching' if archived else 'active'} account '{ref}'.")
        included_ids.add(found.saved_id)
    excluded_ids = set()
    for ref in excluded_accounts:
        found = app.store.get_account(ref)
        if found is None or (found.archived and not archived):
            fail(f"No {'matching' if archived else 'active'} account '{ref}'.")
        excluded_ids.add(found.saved_id)
    excluded_currency_set = {value.strip().casefold() for value in excluded_currencies}
    excluded_institution_set = {value.strip().casefold() for value in excluded_institutions}
    items = [
        a
        for a in items
        if a.saved_id not in excluded_ids
        and (not included_accounts or a.saved_id in included_ids)
        and a.type.value not in excluded_types
        and a.currency.casefold() not in excluded_currency_set
        and a.institution.casefold() not in excluded_institution_set
        and not any(value.casefold() in a.name.casefold() for value in exclude_search)
        and (institution_search is None or institution_search.casefold() in a.institution.casefold())
        and (registered is None or a.type.registered == registered)
        and (has_institution is None or bool(a.institution.strip()) == has_institution)
        and (min_id is None or a.saved_id >= min_id)
        and (max_id is None or a.saved_id <= max_id)
    ]
    if has_positions is not None:
        positioned = {holding.account_id for holding in app.store.ledger().open_holdings()}
        items = [a for a in items if (a.saved_id in positioned) == has_positions]
    if any(value is not None for value in (has_transactions, min_transactions, max_transactions)):
        counts: Counter[int] = Counter()
        for txn in app.store.transactions():
            # A transfer belongs to both accounts, once per account.
            for account_id in {txn.account_id, txn.target_account_id} - {None}:
                if account_id is not None:
                    counts[account_id] += 1
        items = [
            a
            for a in items
            if (has_transactions is None or bool(counts[a.saved_id]) == has_transactions)
            and (min_transactions is None or counts[a.saved_id] >= min_transactions)
            and (max_transactions is None or counts[a.saved_id] <= max_transactions)
        ]
    if name_prefix is not None:
        items = [a for a in items if a.name.casefold().startswith(name_prefix.casefold())]
    if name_suffix is not None:
        items = [a for a in items if a.name.casefold().endswith(name_suffix.casefold())]
    filtered = selection or bool(acct_types or institutions or currencies) or search is not None or cash is not None
    if acct_types:
        items = [a for a in items if a.type.value in acct_types]
    if institutions:
        institution_set = {value.strip().casefold() for value in institutions}
        items = [a for a in items if a.institution.casefold() in institution_set]
    if search is not None:
        items = [a for a in items if search.casefold() in a.name.casefold()]
    if currencies:
        currency_set = {value.strip().casefold() for value in currencies}
        items = [a for a in items if a.currency.casefold() in currency_set]
    if cash is not None:
        items = [a for a in items if a.track_cash == cash]
    if summary:
        _account_summary(app, items, summary, summary_sort, as_json, as_csv)
        return
    if sort_by is not None:
        items.sort(key=lambda a: (str(getattr(a, sort_by)).casefold(), a.saved_id))
    if descending:
        items.reverse()
    total = len(items)
    if count_only:
        click.echo(total)
        return
    start = offset or 0
    items = items[start:] if limit is None else items[start : start + limit]
    if as_csv:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=[field.name for field in fields(Account)])
        writer.writeheader()
        writer.writerows(asdict(a) for a in items)
        click.echo(stream.getvalue(), nl=False)
        return
    if as_json:
        rows = [asdict(a) for a in items]
        payload = (
            {
                "total": total,
                "offset": start,
                "limit": limit,
                "returned": len(rows),
                "next_offset": start + len(rows) if start + len(rows) < total else None,
                "items": rows,
            }
            if page_info
            else rows
        )
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if not items:
        message = (
            "No accounts match these filters."
            if filtered or limit is not None or offset is not None
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


def _account_summary(app: App, items: list[Account], group: str, sort: str, as_json: bool, as_csv: bool) -> None:
    def key(account: Account) -> str:
        if group == "type":
            return account.type.value
        if group == "registered":
            return "registered" if account.type.registered else "nonregistered"
        if group == "cash":
            return "tracked" if account.track_cash else "untracked"
        return str(getattr(account, group)).strip()

    counts = Counter(key(account) for account in items)
    rows = [{"group": value, "count": count} for value, count in sorted(counts.items())]
    if sort == "count":
        rows.sort(key=lambda row: (-int(str(row["count"])), str(row["group"])))
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
    elif as_csv:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=["group", "count"])
        writer.writeheader()
        writer.writerows(rows)
        click.echo(stream.getvalue(), nl=False)
    else:
        table = render.table(group.title(), ("Accounts", "right"), title="Matching accounts")
        for row in rows:
            table.add_row(Text(str(row["group"]) or "(no institution)"), Text(str(row["count"])))
        app.console.print(table)


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
