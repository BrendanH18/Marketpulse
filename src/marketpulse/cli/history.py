"""The transaction ledger: list it, undo the latest entry, edit or delete one."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from dataclasses import asdict, fields
from datetime import date

import click
from rich.text import Text

from .. import fmt, render
from ..models import Account, AccountType, Transaction, TxnType
from .base import App, date_callback, fail, pass_app
from .root import main


@main.command()
@click.option("-a", "--account", default=None)
@click.option("-s", "--symbol", default=None)
@click.option("-n", "--limit", type=click.IntRange(min=1), default=40, show_default=True)
@click.option("--all", "show_all", is_flag=True)
@click.option("--since", callback=date_callback, help="Include transactions on or after this date.")
@click.option("--until", callback=date_callback, help="Include transactions on or before this date.")
@click.option("--type", "types", multiple=True, type=click.Choice([t.value for t in TxnType], case_sensitive=False))
@click.option("--search", default="", help="Find text in the symbol, note, or account name (case-insensitive).")
@click.option("--currency", help="Include only transactions recorded in this currency.")
@click.option("--oldest-first", is_flag=True, help="Show oldest entries first.")
@click.option("--offset", type=click.IntRange(min=0), default=0, help="Skip this many matching entries.")
@click.option("--json", "as_json", is_flag=True, help="Print raw, unmasked transaction records as JSON.")
@click.option("--csv", "as_csv", is_flag=True, help="Print raw, unmasked transaction CSV to stdout.")
@click.option("--count", "count_only", is_flag=True, help="Count all matching entries before pagination.")
@click.option(
    "--summary",
    type=click.Choice(["type", "account", "currency", "month", "symbol", "year", "day", "weekday", "institution"]),
    help="Count all matching entries by this field before pagination; supports --json or --csv.",
)
@click.option("--has-note/--no-note", default=None, help="Match entries with or without a nonblank note.")
@click.option("--min-id", type=click.IntRange(min=1), help="Include transaction IDs at or above this value.")
@click.option("--max-id", type=click.IntRange(min=1), help="Include transaction IDs at or below this value.")
@click.option(
    "--exclude-type",
    "excluded_types",
    multiple=True,
    type=click.Choice([t.value for t in TxnType], case_sensitive=False),
)
@click.option("--exclude-symbol", "excluded_symbols", multiple=True, help="Exclude a symbol; repeat for several.")
@click.option("--note", help="Find text only in transaction notes (case-insensitive).")
@click.option("--year", type=click.IntRange(min=1, max=9999), help="Include only this calendar year.")
@click.option("--on", "on_date", callback=date_callback, help="Include only this date.")
@click.option(
    "--summary-sort",
    type=click.Choice(["group", "count"]),
    default="group",
    help="Sort summaries by group or descending count.",
)
@click.option("--page-info", is_flag=True, help="With --json, wrap transactions with pagination metadata.")
@click.option("--symbols", multiple=True, help="Include any of these exact symbols; repeat for several.")
@click.option("--exclude-account", "excluded_accounts", multiple=True, help="Exclude either end of these accounts.")
@click.option("--account-type", type=click.Choice([a.value for a in AccountType], case_sensitive=False))
@click.option("--institution", help="Match the source account's institution exactly, ignoring case.")
@click.option("--has-symbol/--no-symbol", default=None, help="Match entries with or without a symbol.")
@click.option("--target-account", help="Match this transfer destination by ID, name or unique account type.")
@click.option("--quarter", type=click.IntRange(min=1, max=4), help="Include only this calendar quarter.")
@click.option("--weekday", type=click.Choice(["mon", "tue", "wed", "thu", "fri", "sat", "sun"], case_sensitive=False))
@pass_app
def activity(
    app: App,
    account,
    symbol,
    limit,
    show_all,
    since,
    until,
    types,
    search,
    currency,
    oldest_first,
    offset,
    as_json,
    as_csv,
    count_only,
    summary,
    has_note,
    min_id,
    max_id,
    excluded_types,
    excluded_symbols,
    note,
    year,
    on_date,
    summary_sort,
    page_info,
    symbols,
    excluded_accounts,
    account_type,
    institution,
    has_symbol,
    target_account,
    quarter,
    weekday,
) -> None:
    """The transaction ledger, newest first."""
    if since and until and since > until:
        raise click.UsageError("--since must be on or before --until.")
    if min_id is not None and max_id is not None and min_id > max_id:
        raise click.UsageError("--min-id must be at or below --max-id.")
    if (as_json and as_csv) or (count_only and (as_json or as_csv or summary)):
        raise click.UsageError("Choose one output format; --count cannot be combined with --summary, --json or --csv.")
    if page_info and (not as_json or summary or count_only):
        raise click.UsageError("--page-info requires --json transaction output without --summary or --count.")
    if summary_sort != "group" and not summary:
        raise click.UsageError("--summary-sort requires --summary.")
    generation = app.store.restore_id
    accounts = app.store.account_map()
    acct = app.store.get_account(account) if account else None
    if account and (acct is None or acct.archived):
        fail(f"No active account '{account}'.")

    def active_account(ref: str) -> Account:
        found = app.store.get_account(ref)
        if found is None or found.archived:
            fail(f"No active account '{ref}'.")
        return found

    excluded_account_ids = {active_account(ref).saved_id for ref in excluded_accounts}
    target = active_account(target_account) if target_account is not None else None
    included_symbols = {value.strip().upper() for value in symbols}
    weekdays = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    needle = search.casefold()
    note_needle = note.casefold() if note is not None else None
    excluded = {value.strip().upper() for value in excluded_symbols}
    txns = [
        t
        for t in app.store.transactions(account_id=acct.id if acct else None, symbol=symbol)
        if _visible(t, accounts)
        and (not included_symbols or t.symbol in included_symbols)
        and t.account_id not in excluded_account_ids
        and t.target_account_id not in excluded_account_ids
        and (account_type is None or accounts[t.account_id].type.value == account_type)
        and (institution is None or accounts[t.account_id].institution.casefold() == institution.strip().casefold())
        and (has_symbol is None or bool(t.symbol.strip()) == has_symbol)
        and (target is None or t.target_account_id == target.saved_id)
        and (quarter is None or (int(t.date[5:7]) - 1) // 3 + 1 == quarter)
        and (weekday is None or weekdays[date.fromisoformat(t.date).weekday()] == weekday)
        and (not since or t.date >= since)
        and (not until or t.date <= until)
        and (not types or t.type in types)
        and t.type not in excluded_types
        and t.symbol not in excluded
        and (note_needle is None or note_needle in t.note.casefold())
        and (year is None or t.date[:4] == f"{year:04d}")
        and (not on_date or t.date == on_date)
        and (not currency or t.currency == currency.strip().upper())
        and (has_note is None or bool(t.note.strip()) == has_note)
        and (min_id is None or t.saved_id >= min_id)
        and (max_id is None or t.saved_id <= max_id)
        and (
            not needle
            or needle
            in " ".join(
                [t.symbol, t.note, accounts[t.account_id].name]
                + ([accounts[t.target_account_id].name] if t.target_account_id is not None else [])
            ).casefold()
        )
    ]
    if count_only:
        click.echo(len(txns))
        return
    if summary:
        _activity_summary(app, txns, accounts, summary, as_json, as_csv, summary_sort)
        return
    total = len(txns)
    txns.sort(key=lambda t: (t.date, t.id or 0), reverse=not oldest_first)
    txns = txns[offset:] if show_all else txns[offset : offset + limit]
    if as_csv:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(
            stream, fieldnames=[f.name for f in fields(Transaction)] + ["account", "target_account", "revision"]
        )
        writer.writeheader()
        writer.writerows(_transaction_json(t, accounts, generation) for t in txns)
        click.echo(stream.getvalue(), nl=False)
        return
    if as_json:
        rows = [_transaction_json(t, accounts, generation) for t in txns]
        payload = (
            {
                "total": total,
                "offset": offset,
                "limit": None if show_all else limit,
                "returned": len(rows),
                "next_offset": offset + len(rows) if offset + len(rows) < total else None,
                "items": rows,
            }
            if page_info
            else rows
        )
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if not txns:
        app.console.print(
            Text("No matching transactions." if app.store.transactions() else "No transactions yet.", style="muted")
        )
        return
    table = render.table(*render.ACTIVITY_HEADERS)
    for t in txns:
        table.add_row(*render.activity_cells(t, accounts, privacy=app.privacy))
    app.console.print(table)
    shown = {t.id for t in txns}
    issues = app.store.ledger().issues
    for issue in issues:
        if issue.txn_id in shown:
            message = "Ledger issue (details hidden in privacy mode)." if app.privacy else issue.message
            app.warn(f"#{issue.txn_id} {issue.date}: {message}")


def _activity_summary(
    app: App,
    txns: list[Transaction],
    accounts: dict[int, Account],
    group: str,
    as_json: bool,
    as_csv: bool,
    sort: str,
) -> None:
    def key(t: Transaction) -> str:
        if group == "account":
            # Include the ID so identically named accounts remain distinct.
            return str(t.account_id)
        if group == "weekday":
            return ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[date.fromisoformat(t.date).weekday()]
        if group == "institution":
            return accounts[t.account_id].institution
        if group == "month":
            return t.date[:7]
        if group == "year":
            return t.date[:4]
        if group == "day":
            return t.date
        return str(getattr(t, group))

    counts = Counter(key(t) for t in txns)
    rows = [{"group": value, "count": count} for value, count in sorted(counts.items())]
    if group == "account":
        for row in rows:
            row["account"] = accounts[int(str(row["group"]))].name
    if sort == "count":
        rows.sort(key=lambda row: (-int(str(row["count"])), str(row["group"])))
    if as_csv:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=["group", "count"] + (["account"] if group == "account" else []))
        writer.writeheader()
        writer.writerows(rows)
        click.echo(stream.getvalue(), nl=False)
        return
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
        return
    table = render.table(group.title(), ("Entries", "right"), title="Matching activity")
    for row in rows:
        empty_label = "(no institution)" if group == "institution" else "(no symbol)"
        label = str(row.get("account", row["group"])) or empty_label
        table.add_row(Text(label), Text(str(row["count"])))
    app.console.print(table)


def _visible(t: Transaction, accounts: dict[int, Account]) -> bool:
    """Browsing hides entries that would disclose an archived account at either end."""
    return (
        t.account_id in accounts
        and not accounts[t.account_id].archived
        and (
            t.target_account_id is None
            or (t.target_account_id in accounts and not accounts[t.target_account_id].archived)
        )
    )


def _transaction_json(t: Transaction, accounts: dict[int, Account], generation: str) -> dict:
    return {
        **asdict(t),
        "account": accounts[t.account_id].name,
        "target_account": accounts[t.target_account_id].name if t.target_account_id is not None else None,
        "revision": t.revision(generation),
    }


@main.command()
@click.option("-y", "--yes", is_flag=True)
@pass_app
def undo(app: App, yes: bool) -> None:
    """Delete the most recently recorded transaction."""
    restore_id = app.store.restore_id
    txns = app.store.transactions()
    if not txns:
        fail("Nothing to undo.")
    last = max(txns, key=lambda t: t.id or 0)
    seen = last.revision(restore_id)  # the entry as shown; refused if it changes before the delete
    app.console.print(render.activity_table([last], app.store.account_map()))
    if yes or click.confirm("Delete this transaction?"):
        try:
            app.tracker.delete_transaction(last.saved_id, restore_id=restore_id, revision=seen)
        except ValueError as e:
            fail(str(e))
        app.ok(f"Deleted transaction #{last.id}.")


@main.group()
def txn() -> None:
    """Inspect, check, edit or delete transactions (ids from `activity`)."""


@txn.command("show")
@click.argument("txn_id", type=click.IntRange(min=1))
@click.option("--json", "as_json", is_flag=True, help="Print raw, unmasked fields and the edit revision as JSON.")
@pass_app
def txn_show(app: App, txn_id: int, as_json: bool) -> None:
    """Inspect one transaction, including its full note and revision."""
    generation = app.store.restore_id
    accounts = app.store.account_map()
    t = next((t for t in app.store.transactions() if t.id == txn_id and _visible(t, accounts)), None)
    if t is None:
        fail(f"No active transaction #{txn_id}.")
    payload = _transaction_json(t, accounts, generation)
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    table = render.table("Field", "Value", title=f"Transaction #{txn_id}")
    for field, value in payload.items():
        if app.privacy and field in ("quantity", "price", "amount", "fees", "ratio"):
            shown = fmt.MASK
        else:
            shown = "—" if value is None else str(value)
        table.add_row(Text(field), Text(shown))
    app.console.print(table)


@txn.command("check")
@click.option("--json", "as_json", is_flag=True, help="Print raw diagnostics as JSON; exit 1 if issues exist.")
@pass_app
def txn_check(app: App, as_json: bool) -> None:
    """Check the full ledger offline. Exit 1 if any inconsistencies are found."""
    accounts = app.store.account_map()
    visible = {t.id for t in app.store.transactions() if _visible(t, accounts)}
    issues = [
        asdict(issue)
        if issue.txn_id in visible
        else {
            "txn_id": None,
            "date": "",
            "message": "Issue in a hidden account.",
            "code": "hidden_account_issue",
            "args": {},
        }
        for issue in app.store.ledger().issues
    ]
    if as_json:
        click.echo(json.dumps({"ok": not issues, "issues": issues}, ensure_ascii=False))
    elif not issues:
        app.ok("Ledger is consistent.")
    else:
        app.warn(f"{len(issues)} ledger issue(s).")
        for issue in issues:
            message = "Ledger issue (details hidden in privacy mode)." if app.privacy else issue["message"]
            where = f"#{issue['txn_id']} {issue['date']}: " if issue["txn_id"] is not None else ""
            app.warn(f"{where}{message}")
    if issues:
        raise click.exceptions.Exit(1)


REVISION_HELP = "Refuse unless the entry is unchanged since it had this revision (from `desktop snapshot`)."


@txn.command("delete")
@click.argument("txn_id", type=int)
@click.option("-y", "--yes", is_flag=True)
@click.option("--revision", help=REVISION_HELP)
@pass_app
def txn_delete(app: App, txn_id: int, yes: bool, revision: str | None) -> None:
    """Delete a transaction. Refused if a later entry depends on it (a sale of the shares it bought)."""
    restore_id = app.store.restore_id
    match = [t for t in app.store.transactions() if t.id == txn_id]
    if not match:
        fail(f"No transaction #{txn_id}.")
    if revision is None:
        revision = match[0].revision(restore_id)  # the entry as shown; refused if it changes meanwhile
    app.console.print(render.activity_table(match, app.store.account_map()))
    if yes or click.confirm("Delete?"):
        try:
            app.tracker.delete_transaction(txn_id, restore_id=restore_id, revision=revision)
        except ValueError as e:
            fail(str(e))
        app.ok(f"Deleted #{txn_id}.")


@txn.command("edit")
@click.argument("txn_id", type=int)
@click.option("--date", "when", callback=date_callback)
@click.option("--account")
@click.option("--symbol")
@click.option("--quantity", type=float)
@click.option("--price", type=float)
@click.option("--amount", type=float)
@click.option("--fees", type=float)
@click.option("--currency", help="Blank to use the symbol's listing currency (or the account's for cash).")
@click.option("--note")
@click.option("--revision", help=REVISION_HELP)
@pass_app
def txn_edit(
    app: App, txn_id: int, when, account, symbol, quantity, price, amount, fees, currency, note, revision
) -> None:
    """Change a transaction's fields; its type stays the same.

    Changing the symbol without --currency works the currency out again. Refused if the
    result doesn't add up, e.g. a sale of more than was held then, or a later sale that
    would lose the shares it needs."""
    restore_id = app.store.restore_id
    match = [t for t in app.store.transactions() if t.id == txn_id]
    if not match:
        fail(f"No transaction #{txn_id}.")
    t = match[0]
    if revision is None:
        # Every field of `t` is written back, so an edit made elsewhere since it was read (while a
        # quote is looked up, say) is refused rather than overwritten.
        revision = t.revision(restore_id)
    if symbol is not None and currency is None and symbol.strip().upper() != t.symbol:
        currency = ""  # the old symbol's currency may not be the new one's
    if when is not None:
        t.date = when
    if account is not None:
        t.account_id = app.account(account).saved_id
    for name, value in (
        ("symbol", symbol),
        ("quantity", quantity),
        ("price", price),
        ("amount", amount),
        ("fees", fees),
        ("currency", currency),
        ("note", note),
    ):
        if value is not None:
            setattr(t, name, value.strip().upper() if name in ("symbol", "currency") else value)
    try:
        app.tracker.update_transaction(t, restore_id=restore_id, revision=revision)
    except ValueError as e:
        fail(str(e))
    app.console.print(render.activity_table([t], app.store.account_map()))
    app.ok(f"Updated #{txn_id}.")
