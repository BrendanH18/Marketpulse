"""Your data: snapshot backfill, CSV import and export, and backups."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.text import Text

from .. import render
from ..brokers import PROFILE_NAMES
from ..models import Account
from .base import App, date_callback, fail, pass_app
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


def _import_default(
    app: App, account: str | None, path: Path, profile: str, *, create_default: bool = True
) -> Account | None:
    """Account for rows without one. A file whose rows name their own account gets no default,
    so rows are never silently filed into whichever account happens to be first."""
    from ..brokers import names_accounts, resolve
    from ..csvio import read_headers

    if account:
        return app.account(account)
    headers = read_headers(path.read_text(encoding="utf-8-sig"))
    if names_accounts(resolve(profile, headers), headers):
        return None
    if not create_default and not app.store.accounts():
        fail("No active account. Create one with `marketpulse accounts add` or use a CSV with account names.")
    return app.account(None)


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
@click.option(
    "--json", "as_json", is_flag=True, help="Full import report as JSON (unmasked, including all row issues)."
)
@pass_app
def import_cmd(app: App, path: Path, account, profile, dry_run, no_create_accounts, as_json: bool) -> None:
    """Import transactions from a broker or MarketPulse CSV.

    \b
    Profiles:
      questrade     Questrade account activity export
      wealthsimple  Wealthsimple monthly statement CSV
      generic       common column names (any other file)
    """
    from ..csvio import import_transactions

    try:
        default = _import_default(app, account, path, profile, create_default=not (dry_run or as_json))
        result = import_transactions(
            app.store,
            path,
            default_account=default,
            create_accounts=not no_create_accounts,
            dry_run=dry_run,
            profile=profile,
        )
    except (OSError, UnicodeError, ValueError) as e:
        fail(str(e))
    if as_json:
        payload = asdict(result)
        payload["backup"] = str(result.backup) if result.backup is not None else None
        payload["dry_run"] = dry_run
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
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
    with path.open("w", newline="", encoding="utf-8") as f:
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
@click.option("--json", "as_json", is_flag=True, help="Print the created backup metadata as unmasked JSON.")
@pass_app
def backup_now(app: App, path: Path | None, as_json: bool = False) -> None:
    """Back up now (to PATH, or to the backups directory)."""
    dest = app.store.backup(reason="manual", dest=path)
    if as_json:
        click.echo(json.dumps(_backup_metadata(dest), ensure_ascii=False))
    else:
        app.ok(f"Backed up to {dest}")


def _backup_metadata(path: Path) -> dict:
    from ..db import Store

    taken = Store.backup_time(path)
    return {
        "file": path.name,
        "path": str(path.resolve()),
        "reason": Store.backup_reason(path),
        "size_bytes": path.stat().st_size,
        "taken_at": taken.isoformat() if taken is not None else None,
    }


@backup.command("list")
@click.option("--json", "as_json", is_flag=True, help="Backup paths, reasons, sizes and timestamps as JSON.")
@click.option("--reason", help="Exact backup reason, ignoring case.")
@click.option("--since", callback=date_callback, help="Taken on or after this date (from the filename).")
@click.option("--until", callback=date_callback, help="Taken on or before this date (from the filename).")
@click.option("--limit", type=click.IntRange(min=1), help="Maximum number of matching backups.")
@click.option("--offset", type=click.IntRange(min=0), default=0, help="Skip matching backups before listing.")
@click.option("--oldest-first", is_flag=True, help="Reverse the default newest-first filename order.")
@click.option("--search", default="", help="Find backup filenames containing this text, ignoring case.")
@pass_app
def backup_list(app: App, as_json: bool, reason, since, until, limit, offset, oldest_first, search) -> None:
    """List backups, newest first. Filters apply before pagination."""
    if since and until and since > until:
        raise click.UsageError("--since must be on or before --until.")
    items = app.store.backups()
    if oldest_first:
        items.reverse()
    payload = [_backup_metadata(path) for path in items]
    payload = [
        item
        for item in payload
        if (not reason or item["reason"].casefold() == reason.casefold())
        and search.casefold() in item["file"].casefold()
        and (not since or (item["taken_at"] is not None and item["taken_at"][:10] >= since))
        and (not until or (item["taken_at"] is not None and item["taken_at"][:10] <= until))
    ]
    payload = payload[offset:] if limit is None else payload[offset : offset + limit]
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if not payload:
        if not items:
            app.warn(f"No backups yet in {app.store.backup_dir}")
        else:
            app.warn("No matching backups.")
        return
    t = render.table("File", "Reason", ("Size", "right"), title=str(app.store.backup_dir))
    for item in payload:
        size = Text(f"{item['size_bytes'] / 1024:,.0f} KB")
        t.add_row(Text(item["file"]), Text(item["reason"], style="muted"), size)
    app.console.print(t)


def _backup_source(app: App, path: str) -> Path:
    source = Path(path).expanduser()
    if path == source.name and (app.store.backup_dir / path).exists():
        source = app.store.backup_dir / path
    if not source.is_file():
        fail(f"Backup file not found: {path}")
    return source


@backup.command("show")
@click.argument("path", type=click.Path(dir_okay=False))
@click.option("--json", "as_json", is_flag=True, help="Print unmasked file metadata as JSON.")
@pass_app
def backup_show(app: App, path: str, as_json: bool) -> None:
    """Inspect backup file metadata without opening or restoring its database."""
    try:
        payload = _backup_metadata(_backup_source(app, path))
    except OSError as error:
        fail(str(error))
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    table = render.table("Field", "Value")
    table.columns[0].min_width = 10
    for field, value in payload.items():
        table.add_row(Text(field), Text(str(value) if value is not None else "—"))
    app.console.print(table)


@backup.command("verify")
@click.argument("path", type=click.Path(dir_okay=False))
@click.option("--json", "as_json", is_flag=True, help="Print validation status as JSON; invalid files exit 1.")
@pass_app
def backup_verify(app: App, path: str, as_json: bool) -> None:
    """Check integrity and schema compatibility without replacing the ledger.

    Uses the restore preflight with a temporary copy; the source is opened read-only.
    Does not check financial correctness or restore the backup.
    """
    from tempfile import TemporaryDirectory

    from ..db import RestoreError, _stage_restore

    source = _backup_source(app, path)
    error = None
    try:
        with TemporaryDirectory(prefix="marketpulse-verify-") as scratch:
            _stage_restore(source, Path(scratch) / "checked.db")
    except (RestoreError, OSError) as problem:
        error = str(problem)
    if as_json:
        click.echo(json.dumps({"ok": error is None, "path": str(source.resolve()), "error": error}, ensure_ascii=False))
    elif error is None:
        app.ok(f"Backup verified: {source.name}")
    else:
        app.warn(error)
    if error is not None:
        raise click.exceptions.Exit(1)


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
