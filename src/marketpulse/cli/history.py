"""The transaction ledger: list it, undo the latest entry, edit or delete one."""

from __future__ import annotations

import click
from rich.text import Text

from .. import render
from .base import App, date_callback, fail, pass_app
from .root import main


@main.command()
@click.option("-a", "--account", default=None)
@click.option("-s", "--symbol", default=None)
@click.option("-n", "--limit", type=int, default=40, show_default=True)
@click.option("--all", "show_all", is_flag=True)
@pass_app
def activity(app: App, account, symbol, limit, show_all) -> None:
    """The transaction ledger, newest first."""
    acct = app.account(account) if account else None
    txns = app.store.transactions(account_id=acct.id if acct else None, symbol=symbol)
    if not txns:
        app.console.print(Text("No transactions yet.", style="muted"))
        return
    app.console.print(
        render.activity_table(txns, app.store.account_map(), privacy=app.privacy, limit=None if show_all else limit)
    )
    issues = app.store.ledger().issues
    for issue in issues:
        app.warn(f"#{issue.txn_id} {issue.date}: {issue.message}")


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
    """Edit or delete individual transactions (ids from `activity`)."""


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
