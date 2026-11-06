"""Your data: snapshot backfill, CSV import and export, and backups."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.text import Text

from .. import render
from ..brokers import PROFILE_NAMES
from ..models import Account
from .base import App, fail, pass_app
from .root import main

if TYPE_CHECKING:
    from ..csvio import RowIssue


@main.command()
@pass_app
def backfill(app: App) -> None:
    """Rebuild daily net-worth history from your ledger and historical prices."""
    tr = app.tracker
    try:
        with app.busy("Backfilling…") as spinner:
            n = tr.backfill(progress=lambda msg: spinner.update(Text(f"Backfilling · {msg}", style="accent")))
    except ValueError as e:
        fail(str(e))
    app.ok(f"Rebuilt {n:,} daily snapshots.")


def _import_default(app: App, account: str | None, path: Path, profile: str) -> Account | None:
    """Account for rows without one. A file whose rows name their own account gets no default,
    so rows are never silently filed into whichever account happens to be first."""
    from ..brokers import names_accounts, resolve
    from ..csvio import read_headers

    if account:
        return app.account(account)
    headers = read_headers(path.read_text(encoding="utf-8-sig"))
    return None if names_accounts(resolve(profile, headers), headers) else app.account(None)


def _import_line(issue: RowIssue) -> str:
    where = f"line {issue.line}"
    if issue.field:
        where += f", {issue.field}" + (f" '{issue.value}'" if issue.value else "")
    return f"{where}: {issue.reason}"


@main.command("import")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-a", "--account", default=None, help="Account for rows without an account column.")
@click.option(
    "--profile",
    type=click.Choice(PROFILE_NAMES),
    default="auto",
    show_default=True,
    help="Broker export format; auto detects it from the header row.",
)
@click.option("--dry-run", is_flag=True)
@click.option("--no-create-accounts", is_flag=True)
@pass_app
def import_cmd(app: App, path: Path, account, profile, dry_run, no_create_accounts) -> None:
    """Import transactions from a broker or MarketPulse CSV.

    \b
    Profiles:
      questrade     Questrade account activity export
      wealthsimple  Wealthsimple monthly statement CSV
      generic       common column names (any other file)
    """
    from ..csvio import import_transactions

    try:
        default = _import_default(app, account, path, profile)
        result = import_transactions(
            app.store,
            path,
            default_account=default,
            create_accounts=not no_create_accounts,
            dry_run=dry_run,
            profile=profile,
        )
    except ValueError as e:
        fail(str(e))
    verb = "Would import" if dry_run else "Imported"
    app.ok(f"{verb} {result.added} transaction(s); {result.duplicates} duplicate(s) skipped. ({result.profile_label})")
    if result.backup is not None:
        # Tell the user how to undo the whole import, not just the last row.
        app.console.print(Text(f"  pre-import backup: {result.backup}", style="muted"))
    for name in result.accounts_created:
        app.warn(f"created account {name}")
    for dup in result.duplicate_rows[:5]:
        app.console.print(Text(f"  duplicate, line {dup.line}: {dup.summary}", style="muted"))
    if len(result.duplicate_rows) > 5:
        app.console.print(Text(f"  …and {len(result.duplicate_rows) - 5} more duplicates", style="muted"))
    for issue in result.issues[:15]:
        app.warn(_import_line(issue))
    if len(result.issues) > 15:
        app.warn(f"…and {len(result.issues) - 15} more skipped rows")


@main.command("export")
@click.argument("path", type=click.Path(dir_okay=False, path_type=Path), required=False)
@pass_app
def export_cmd(app: App, path: Path | None) -> None:
    """Export the ledger as CSV (stdout if no PATH)."""
    from ..csvio import export_transactions

    if path is None:
        export_transactions(app.store, sys.stdout)
        return
    with path.open("w", newline="") as f:
        n = export_transactions(app.store, f)
    app.ok(f"Exported {n} transactions to {path}")


@main.group(invoke_without_command=True)
@click.pass_context
def backup(ctx: click.Context) -> None:
    """Back up the database (run with no subcommand to back up now).

    \b
    Backups are consistent SQLite copies in ~/.marketpulse/backups/. One is
    also taken automatically each day, before every CSV import and before any
    schema upgrade. `marketpulse backup restore` puts one back.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(backup_now)


@backup.command("now")
@click.argument("path", type=click.Path(dir_okay=False, path_type=Path), required=False)
@pass_app
def backup_now(app: App, path: Path | None) -> None:
    """Back up now (to PATH, or to the backups directory)."""
    dest = app.store.backup(reason="manual", dest=path)
    app.ok(f"Backed up to {dest}")


@backup.command("list")
@pass_app
def backup_list(app: App) -> None:
    """List backups, newest first."""
    items = app.store.backups()
    if not items:
        app.warn(f"No backups yet in {app.store.backup_dir}")
        return
    t = render.table("File", "Reason", ("Size", "right"), title=str(app.store.backup_dir))
    for p in items:
        size = Text(f"{p.stat().st_size / 1024:,.0f} KB")
        t.add_row(Text(p.name), Text(app.store.backup_reason(p), style="muted"), size)
    app.console.print(t)


@backup.command("restore")
# A str, not a Path: Path("./name") drops the "./" that marks an explicit local file.
@click.argument("path", type=click.Path(dir_okay=False), required=False)
@click.option("--latest", is_flag=True, help="Restore the newest backup in the backups directory.")
@click.option("-y", "--yes", is_flag=True, help="Don't ask for confirmation.")
@pass_app
def backup_restore(app: App, path: str | None, latest: bool, yes: bool) -> None:
    """Replace the ledger with a backup (a PATH, or a file name from `backup list`).

    \b
    The backup is checked first: it must be an intact MarketPulse database
    that this version can read. Then the current ledger is saved as a
    `pre-restore` backup, so a restore can itself be undone, and the backup
    is copied in. Anything recorded after the backup was taken is replaced.
    The configuration file is not part of a backup and stays as it is.
    """
    from ..db import RestoreError

    if latest == (path is not None):
        fail("Give a backup to restore, or --latest.")
    # Opening the ledger may take the daily backup, a copy of the ledger as it is now.
    started = datetime.now().replace(microsecond=0)
    store = app.store
    if latest:
        # Neither that daily backup nor a pre-restore one (the ledger a restore replaced) is what
        # "go back to my latest backup" means.
        def is_copy_of_current(p: Path) -> bool:
            reason = store.backup_reason(p)
            return reason == "pre-restore" or (reason == "daily" and (store.backup_time(p) or started) >= started)

        candidates = [p for p in store.backups() if not is_copy_of_current(p)]
        if not candidates:
            fail(f"No backups to restore in {store.backup_dir}")
        source = candidates[0]
    else:
        assert path is not None
        source = Path(path).expanduser()
        # A bare name is one from `backup list`, even if the current folder has a file called that too.
        if path == source.name and (store.backup_dir / path).exists():
            source = store.backup_dir / path
    taken = store.backup_time(source)
    when = f" (taken {taken:%Y-%m-%d %H:%M})" if taken else ""
    # A file outside the backups folder is shown in full, so it can't pass for one in it.
    shown = source.name if source.parent == store.backup_dir else str(source.resolve())
    if not yes and not click.confirm(
        f"Replace the ledger in {store.path.parent} with {shown}{when}? The current ledger is backed up first."
    ):
        return
    try:
        safety = store.restore(source)
    except RestoreError as e:
        fail(f"{str(e).rstrip('.')}. Nothing was changed.")
    accounts, txns = len(store.accounts(include_archived=True)), len(store.transactions())
    app.ok(f"Restored {source.name}: {accounts} accounts, {txns} transactions.")
    app.console.print(Text(f"  previous ledger saved as {safety}", style="muted"))
