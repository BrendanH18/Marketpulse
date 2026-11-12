"""Your data: snapshot backfill, CSV import and export, and backups."""

from __future__ import annotations

import csv
import io
import json
import math
import re
import sys
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

import click
from rich.text import Text

from .. import render
from ..brokers import PROFILE_NAMES
from ..models import Account, Transaction, TxnType
from .base import App, date_callback, fail, pass_app
from .root import main

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..csvio import ImportResult, RowIssue
    from ..db import Snapshot, Store
    from ..services import Tracker


@main.command()
@click.option(
    "--dry-run", is_flag=True, help="Rebuild on a temporary copy of the ledger and report; write no snapshots."
)
@click.option(
    "--json", "as_json", is_flag=True, help="Report the snapshots written (or, with --dry-run, that would be) as JSON."
)
@pass_app
def backfill(app: App, dry_run: bool, as_json: bool) -> None:
    """Rebuild daily net-worth history from your ledger and historical prices."""
    tr = app.tracker
    if not (dry_run or as_json):
        try:
            with app.busy("Backfilling…") as spinner:
                n = tr.backfill(progress=lambda msg: spinner.update(Text(f"Backfilling · {msg}", style="accent")))
        except ValueError as e:
            fail(str(e))
        app.ok(f"Rebuilt {n:,} daily snapshots.")
        return
    existing = {s.date for s in tr.store.snapshots()}
    try:
        if as_json:
            written = _backfill_written(tr, dry_run, None)
        else:
            with app.busy("Backfilling…") as spinner:
                written = _backfill_written(
                    tr, dry_run, lambda msg: spinner.update(Text(f"Backfilling · {msg}", style="accent"))
                )
    except ValueError as e:
        fail(str(e))
    new = sum(1 for s in written if s.date not in existing)
    report = {
        "dry_run": dry_run,
        "snapshots": len(written),
        "new": new,
        "replaced": len(written) - new,
        "first": written[0].date if written else None,
        "last": written[-1].date if written else None,
        "currency": tr.base,
    }
    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False))
        return
    span = f" ({report['first']} to {report['last']})" if written else ""
    app.ok(
        f"Would rebuild {len(written):,} daily snapshots{span}: {new:,} new, {len(written) - new:,} replacing "
        "existing ones. Nothing was written."
    )


def _backfill_written(tr: Tracker, dry_run: bool, progress: Callable[[str], None] | None) -> list[Snapshot]:
    """Run the real backfill and return exactly the snapshots it writes, in date order.

    A dry run rebuilds against a throwaway copy of the ledger (as an import preview does) and
    keeps its snapshots out of even that copy; prices and FX come from the same market data."""
    from tempfile import TemporaryDirectory

    from ..db import Store
    from ..services import Tracker

    def run(target: Tracker, write: bool) -> list[Snapshot]:
        written: list[Snapshot] = []
        store = target.store
        save = store.upsert_snapshots

        def capture(snaps: list[Snapshot]) -> None:
            written.extend(snaps)
            if write:
                save(snaps)

        store.upsert_snapshots = capture  # type: ignore[method-assign]
        try:
            target.backfill(progress=progress)
        finally:
            del store.upsert_snapshots
        return sorted(written, key=lambda s: s.date)

    if not dry_run:
        return run(tr, write=True)
    with TemporaryDirectory(prefix="marketpulse-backfill-") as tmp:
        scratch = Store(tr.store.backup(dest=Path(tmp) / "preview.db"))
        try:
            return run(Tracker(scratch, tr.market, tr.config), write=False)
        finally:
            scratch.close()


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


IMPORT_SUMMARIES = ["account", "type", "symbol", "month"]


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
@click.option(
    "--summary",
    type=click.Choice(IMPORT_SUMMARIES),
    help="Count the rows imported (or, with --dry-run, that would be) by this field.",
)
@click.option("--exit-code", is_flag=True, help="Exit 1 if any row was skipped (after reporting as usual).")
@pass_app
def import_cmd(
    app: App,
    path: Path,
    account,
    profile,
    dry_run,
    no_create_accounts,
    as_json: bool,
    summary: str | None,
    exit_code: bool,
) -> None:
    """Import transactions from a broker or MarketPulse CSV.

    \b
    Profiles:
      questrade     Questrade account activity export
      wealthsimple  Wealthsimple monthly statement CSV
      generic       common column names (any other file)
    """
    from ..csvio import import_transactions

    added: list[Transaction] = []
    names: dict[int, Account] = {}
    try:
        default = _import_default(app, account, path, profile, create_default=not (dry_run or as_json))
        if summary:
            result, added, names = _import_rows(app.store, path, default, not no_create_accounts, dry_run, profile)
        else:
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
    groups = _import_summary(added, names, summary) if summary else []
    if as_json:
        payload = asdict(result)
        payload["backup"] = str(result.backup) if result.backup is not None else None
        payload["dry_run"] = dry_run
        if summary:
            payload["summary"] = groups
        click.echo(json.dumps(payload, ensure_ascii=False))
        if exit_code and result.issues:
            raise click.exceptions.Exit(1)
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
    if summary:
        title = "Would import" if dry_run else "Imported"
        table = render.table(summary.title(), ("Rows", "right"), title=title)
        for group in groups:
            table.add_row(Text(str(group["group"]) or "(no symbol)"), Text(str(group["count"])))
        app.console.print(table)
    if exit_code and result.issues:
        raise click.exceptions.Exit(1)


def _import_rows(
    store: Store, path: Path, default: Account | None, create_accounts: bool, dry_run: bool, profile: str
) -> tuple[ImportResult, list[Transaction], dict[int, Account]]:
    """Import (or preview) and return the result, the rows it added and the accounts naming them.

    A preview is still the real import against a throwaway copy of the ledger, exactly as
    `import_transactions(dry_run=True)` runs it; the copy just stays open long enough to read
    back the rows the import added."""
    from tempfile import TemporaryDirectory

    from ..csvio import import_transactions
    from ..db import Store

    def run(target: Store) -> tuple[ImportResult, list[Transaction], dict[int, Account]]:
        before = {t.id for t in target.transactions()}
        result = import_transactions(
            target, path, default_account=default, create_accounts=create_accounts, profile=profile
        )
        return result, [t for t in target.transactions() if t.id not in before], target.account_map()

    if not dry_run:
        return run(store)
    with TemporaryDirectory(prefix="marketpulse-preview-") as tmp:
        scratch = Store(store.backup(dest=Path(tmp) / "preview.db"))
        try:
            result, added, accounts = run(scratch)
        finally:
            scratch.close()
    result.backup = None  # the copy's own pre-import backup, deleted with it
    return result, added, accounts


def _import_summary(added: list[Transaction], accounts: dict[int, Account], field: str) -> list[dict]:
    def key(t: Transaction) -> str:
        if field == "account":
            return accounts[t.account_id].name if t.account_id in accounts else str(t.account_id)
        if field == "type":
            return t.type.value
        if field == "month":
            return t.date[:7]
        return t.symbol

    return [{"group": group, "count": count} for group, count in sorted(Counter(key(t) for t in added).items())]


EXPORT_TYPES = [t.value for t in TxnType]


@main.command("export")
@click.argument("path", type=click.Path(dir_okay=False, path_type=Path), required=False)
@click.option(
    "-a",
    "--account",
    "account_refs",
    multiple=True,
    help="Only rows recorded in this account (name, id or type; archived ones too); repeat for several.",
)
@click.option("-s", "--symbol", "symbols", multiple=True, help="Only this exact symbol, ignoring case; repeat.")
@click.option(
    "--type",
    "types",
    multiple=True,
    type=click.Choice(EXPORT_TYPES, case_sensitive=False),
    help="Only this transaction type; repeat for several.",
)
@click.option("--since", callback=date_callback, help="Only rows dated on or after this date.")
@click.option("--until", callback=date_callback, help="Only rows dated on or before this date.")
@click.option("--columns", help="Comma-separated columns to write, in this order (default: all, for re-import).")
@click.option("--count", "count_only", is_flag=True, help="Print the number of matching rows instead of exporting.")
@click.option("--jsonl", is_flag=True, help="Write one JSON object per row (JSON Lines) instead of CSV.")
@pass_app
def export_cmd(
    app: App,
    path: Path | None,
    account_refs: tuple[str, ...],
    symbols: tuple[str, ...],
    types: tuple[str, ...],
    since: str | None,
    until: str | None,
    columns: str | None,
    count_only: bool,
    jsonl: bool,
) -> None:
    """Export the ledger as CSV (stdout if no PATH).

    Filters keep rows of the full export, in its order, so a filtered CSV re-imports like any
    other MarketPulse CSV (a file without some columns may not)."""
    from ..csvio import export_transactions

    if not (account_refs or symbols or types or since or until or columns is not None or count_only or jsonl):
        if path is None:
            export_transactions(app.store, sys.stdout)
            return
        with path.open("w", newline="", encoding="utf-8") as f:
            n = export_transactions(app.store, f)
        app.ok(f"Exported {n} transactions to {path}")
        return
    if since and until and since > until:
        raise click.UsageError("--since must be on or before --until.")
    if count_only and (path is not None or jsonl or columns is not None):
        raise click.UsageError("--count prints a number; it takes no PATH, --jsonl or --columns.")
    wanted = {value.strip().upper() for value in symbols}
    if "" in wanted:
        raise click.UsageError("--symbol cannot be blank.")
    chosen = _export_columns(columns)
    store = app.store
    account_ids = set()
    for ref in account_refs:
        acct = store.get_account(ref)
        if acct is None:
            fail(f"No account '{ref}'.")
        account_ids.add(acct.saved_id)
    accounts = store.account_map()
    txns = [
        t
        for t in store.transactions()
        if (not account_ids or t.account_id in account_ids)
        and (not wanted or t.symbol in wanted)
        and (not types or t.type.value in types)
        and (not since or t.date >= since)
        and (not until or t.date <= until)
    ]
    if count_only:
        click.echo(len(txns))
        return
    if path is None:
        _write_export(sys.stdout, txns, accounts, chosen, jsonl)
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        n = _write_export(f, txns, accounts, chosen, jsonl)
    app.ok(f"Exported {n} transactions to {path}")


def _export_columns(columns: str | None) -> list[str]:
    from ..csvio import EXPORT_COLUMNS

    if columns is None:
        return list(EXPORT_COLUMNS)
    chosen = [name.strip().lower() for name in columns.split(",")]
    unknown = [name for name in chosen if name not in EXPORT_COLUMNS]
    if unknown:
        raise click.UsageError(f"Unknown column '{unknown[0]}'. Columns: {', '.join(EXPORT_COLUMNS)}.")
    if len(set(chosen)) != len(chosen):
        raise click.UsageError("--columns names a column more than once.")
    return chosen


def _write_export(
    out: TextIO, txns: list[Transaction], accounts: dict[int, Account], columns: list[str], jsonl: bool
) -> int:
    """Write rows formatted exactly as `csvio.export_transactions` writes them (CSV), or with
    raw values (JSON Lines: numbers as numbers, no transfer target as null)."""
    writer = csv.writer(out)
    if not jsonl:
        writer.writerow(columns)
    for t in txns:
        target = accounts.get(t.target_account_id) if t.target_account_id else None
        account: str | int = accounts[t.account_id].name if t.account_id in accounts else t.account_id
        if jsonl:
            raw: dict[str, object] = {
                "date": t.date,
                "account": account,
                "type": t.type.value,
                "symbol": t.symbol,
                "quantity": t.quantity,
                "price": t.price,
                "amount": t.amount,
                "fees": t.fees,
                "currency": t.currency,
                "note": t.note,
                "ratio": t.ratio,
                "target_account": target.name if target else None,
            }
            out.write(json.dumps({name: raw[name] for name in columns}, ensure_ascii=False) + "\n")
            continue
        row = {
            "date": t.date,
            "account": account,
            "type": t.type.value,
            "symbol": t.symbol,
            "quantity": f"{t.quantity:g}" if t.quantity else "",
            "price": f"{t.price:g}" if t.price else "",
            "amount": f"{t.amount:g}" if t.amount else "",
            "fees": f"{t.fees:g}" if t.fees else "",
            "currency": t.currency,
            "note": t.note,
            "ratio": f"{t.ratio:g}" if t.ratio else "",
            "target_account": target.name if target else "",
        }
        writer.writerow([row[name] for name in columns])
    return len(txns)


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


BACKUP_FIELDS = ["file", "path", "reason", "size_bytes", "taken_at"]


def _backup_month_callback(ctx, param, value: str | None) -> str | None:
    if value is None:
        return None
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        raise click.BadParameter("Use YYYY-MM.")
    try:
        date.fromisoformat(value + "-01")
    except ValueError as exc:
        raise click.BadParameter("Use a valid calendar month (YYYY-MM).") from exc
    return value


def _backup_dates_callback(ctx, param, values: tuple[str, ...]) -> tuple[str, ...]:
    dates = []
    for value in values:
        normalized = date_callback(ctx, param, value)
        assert normalized is not None  # Click supplies strings for a repeatable option.
        dates.append(normalized)
    return tuple(dates)


def _backup_size_callback(ctx, param, value: float | None) -> float | None:
    if value is not None and not math.isfinite(value):
        raise click.BadParameter("Must be a finite number of KB.")
    return value


def _backup_reasons(option: str, values: tuple[str, ...]) -> set[str]:
    reasons = {value.strip().casefold() for value in values}
    if "" in reasons:
        raise click.UsageError(f"{option} cannot be blank.")
    return reasons


def _backup_csv(records: list[dict], fieldnames: list[str]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows({k: "" if v is None else v for k, v in record.items()} for record in records)
    click.echo(stream.getvalue(), nl=False)


def _backup_summary(app: App, payload: list[dict], group: str, as_json: bool, as_csv: bool) -> None:
    def key(item: dict) -> str:
        if group == "reason":
            return item["reason"]
        taken = item["taken_at"]
        if taken is None:
            return "unknown"
        return taken[:4] if group == "year" else taken[:7]

    records = [{"group": value, "count": count} for value, count in sorted(Counter(key(i) for i in payload).items())]
    if as_json:
        click.echo(json.dumps(records, ensure_ascii=False))
    elif as_csv:
        _backup_csv(records, ["group", "count"])
    else:
        table = render.table(group.title(), ("Backups", "right"), title="Matching backups")
        for record in records:
            table.add_row(Text(str(record["group"])), Text(str(record["count"])))
        app.console.print(table)


def _backup_sort_key(field: str):
    if field == "size":
        return lambda item: (item["size_bytes"], item["file"])
    if field == "name":
        return lambda item: (item["file"].casefold(), item["file"])
    if field == "reason":
        return lambda item: (item["reason"].casefold(), item["taken_at"] or "", item["file"])
    # Files without a recognized timestamp sort before dated ones.
    return lambda item: (item["taken_at"] or "", item["file"])


@backup.command("list")
@click.option("--json", "as_json", is_flag=True, help="Backup paths, reasons, sizes and timestamps as JSON.")
@click.option(
    "--reason",
    "reasons",
    multiple=True,
    help="Exact backup reason, ignoring case; repeat to include several reasons.",
)
@click.option("--since", callback=date_callback, help="Taken on or after this date (from the filename).")
@click.option("--until", callback=date_callback, help="Taken on or before this date (from the filename).")
@click.option("--limit", type=click.IntRange(min=1), help="Maximum number of matching backups.")
@click.option("--offset", type=click.IntRange(min=0), help="Skip matching backups before listing.")
@click.option("--oldest-first", is_flag=True, help="Reverse the default newest-first filename order.")
@click.option("--search", default="", help="Find backup filenames containing this text, ignoring case.")
@click.option("--count", "count_only", is_flag=True, help="Print the number of matching backups.")
@click.option("--csv", "as_csv", is_flag=True, help="Print matching backup metadata as CSV to stdout.")
@click.option("--page-info", is_flag=True, help="With --json, include total and paging metadata.")
@click.option(
    "--exclude-reason",
    "excluded_reasons",
    multiple=True,
    help="Leave out this backup reason, ignoring case; repeat for several.",
)
@click.option(
    "--min-size",
    type=click.FloatRange(min=0),
    callback=_backup_size_callback,
    help="Inclusive minimum file size in KB (1 KB = 1024 bytes).",
)
@click.option(
    "--max-size",
    type=click.FloatRange(min=0),
    callback=_backup_size_callback,
    help="Inclusive maximum file size in KB (1 KB = 1024 bytes).",
)
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(["date", "size", "name", "reason"]),
    help="Order matching backups by this field, ascending.",
)
@click.option("--descending", is_flag=True, help="Reverse the selected order (default: date).")
@click.option("--year", type=click.IntRange(min=1, max=9999), help="Only backups taken in this calendar year.")
@click.option("--month", callback=_backup_month_callback, help="Only backups taken in this month (YYYY-MM).")
@click.option(
    "--on",
    "on_dates",
    multiple=True,
    callback=_backup_dates_callback,
    help="Only backups taken on this date; repeat for several dates.",
)
@click.option("--latest", is_flag=True, help="Show only the newest matching backup.")
@click.option("--earliest", is_flag=True, help="Show only the oldest matching backup.")
@click.option(
    "--summary",
    type=click.Choice(["reason", "year", "month"]),
    help="Count matching backups by this field.",
)
@pass_app
def backup_list(
    app: App,
    as_json: bool,
    reasons: tuple[str, ...],
    since: str | None,
    until: str | None,
    limit: int | None,
    offset: int | None,
    oldest_first: bool,
    search: str,
    count_only: bool,
    as_csv: bool,
    page_info: bool,
    excluded_reasons: tuple[str, ...],
    min_size: float | None,
    max_size: float | None,
    sort_by: str | None,
    descending: bool,
    year: int | None,
    month: str | None,
    on_dates: tuple[str, ...],
    latest: bool,
    earliest: bool,
    summary: str | None,
) -> None:
    """List backups, newest first. Filters apply before sorting, counting and pagination.

    Reads file names and sizes only; never opens, changes or deletes a backup.
    """
    if since and until and since > until:
        raise click.UsageError("--since must be on or before --until.")
    if as_json and as_csv:
        raise click.UsageError("Choose one output format: --json or --csv.")
    if page_info and not as_json:
        raise click.UsageError("--page-info requires --json.")
    if min_size is not None and max_size is not None and min_size > max_size:
        raise click.UsageError("--min-size must be at most --max-size.")
    if year is not None and month is not None and month[:4] != f"{year:04d}":
        raise click.UsageError("--year and --month must refer to the same year.")
    if oldest_first and (sort_by is not None or descending):
        raise click.UsageError("--oldest-first cannot be combined with --sort or --descending.")
    if latest and earliest:
        raise click.UsageError("Choose one of --earliest or --latest.")
    ordering = sort_by is not None or descending or oldest_first
    paging = limit is not None or offset is not None or page_info
    if summary and (count_only or latest or earliest or ordering or paging):
        raise click.UsageError(
            "--summary cannot be combined with counting, single-row, ordering or pagination options."
        )
    if (latest or earliest) and (count_only or ordering or paging):
        option = "--latest" if latest else "--earliest"
        raise click.UsageError(f"{option} cannot be combined with counting, ordering or pagination options.")
    if count_only and (as_json or as_csv or ordering or paging):
        raise click.UsageError("--count cannot be combined with --json, --csv, ordering or pagination options.")
    included = _backup_reasons("--reason", reasons)
    excluded = _backup_reasons("--exclude-reason", excluded_reasons)
    on = set(on_dates)

    items = app.store.backups()
    payload = [
        item
        for item in (_backup_metadata(path) for path in items)
        if (not included or item["reason"].casefold() in included)
        and item["reason"].casefold() not in excluded
        and search.casefold() in item["file"].casefold()
        and (not since or (item["taken_at"] is not None and item["taken_at"][:10] >= since))
        and (not until or (item["taken_at"] is not None and item["taken_at"][:10] <= until))
        and (year is None or (item["taken_at"] is not None and item["taken_at"][:4] == f"{year:04d}"))
        and (month is None or (item["taken_at"] is not None and item["taken_at"][:7] == month))
        and (not on or (item["taken_at"] is not None and item["taken_at"][:10] in on))
        and (min_size is None or item["size_bytes"] >= min_size * 1024)
        and (max_size is None or item["size_bytes"] <= max_size * 1024)
    ]
    if summary:
        _backup_summary(app, payload, summary, as_json, as_csv)
        return
    if count_only:
        click.echo(len(payload))
        return
    if latest or earliest:
        if not payload:
            fail("No matching backups." if items else f"No backups yet in {app.store.backup_dir}")
        payload = payload[:1] if latest else payload[-1:]
    elif sort_by is not None or descending:
        payload.sort(key=_backup_sort_key(sort_by or "date"), reverse=descending)
    elif oldest_first:
        payload.reverse()
    total = len(payload)
    start = offset or 0
    payload = payload[start:] if limit is None else payload[start : start + limit]
    if as_json:
        result = (
            {
                "total": total,
                "offset": start,
                "limit": limit,
                "returned": len(payload),
                "next_offset": start + len(payload) if start + len(payload) < total else None,
                "items": payload,
            }
            if page_info
            else (payload[0] if latest or earliest else payload)
        )
        click.echo(json.dumps(result, ensure_ascii=False))
        return
    if as_csv:
        _backup_csv(payload, BACKUP_FIELDS)
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
@click.argument("paths", nargs=-1, type=click.Path(dir_okay=False))
@click.option("--json", "as_json", is_flag=True, help="Print validation status as JSON; invalid files exit 1.")
@click.option("--latest", is_flag=True, help="Verify the backup `backup restore --latest` would restore.")
@pass_app
def backup_verify(app: App, paths: tuple[str, ...], as_json: bool, latest: bool) -> None:
    """Check integrity and schema compatibility without replacing the ledger.

    Give one or more PATHS (or file names from `backup list`), or --latest.
    Uses the restore preflight with a temporary copy; each source is opened read-only.
    Does not check financial correctness or restore the backup.
    """
    import sqlite3
    from tempfile import TemporaryDirectory

    from ..db import RestoreError, _stage_restore

    if latest == bool(paths):
        raise click.UsageError("Give one or more backups to verify, or --latest.")
    if latest:
        started = datetime.now().replace(microsecond=0)
        candidates = _restore_candidates(app.store, started)
        if not candidates:
            fail(f"No backups to verify in {app.store.backup_dir}")
        sources = candidates[:1]
    else:
        sources = [_backup_source(app, path) for path in paths]
    results: list[dict] = []
    for source in sources:
        error = None
        try:
            with TemporaryDirectory(prefix="marketpulse-verify-") as scratch:
                _stage_restore(source, Path(scratch) / "checked.db")
        except (RestoreError, OSError, sqlite3.Error) as problem:
            error = str(problem)
        results.append({"ok": error is None, "path": str(source.resolve()), "error": error})
    several = len(paths) > 1
    if as_json:
        click.echo(json.dumps(results if several else results[0], ensure_ascii=False))
    else:
        for source, result in zip(sources, results, strict=True):
            if result["ok"]:
                app.ok(f"Backup verified: {source.name}")
            else:
                app.warn(f"{source.name}: {result['error']}" if several else result["error"])
    if any(not result["ok"] for result in results):
        raise click.exceptions.Exit(1)


def _restore_candidates(store: Store, started: datetime) -> list[Path]:
    """Backups `restore --latest` may pick, newest first.

    Neither a daily backup taken since `started` (a copy of the ledger as it is now) nor a
    pre-restore one (the ledger a restore replaced) is what "go back to my latest backup" means.
    """

    def is_copy_of_current(p: Path) -> bool:
        reason = store.backup_reason(p)
        return reason == "pre-restore" or (reason == "daily" and (store.backup_time(p) or started) >= started)

    return [p for p in store.backups() if not is_copy_of_current(p)]


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
        candidates = _restore_candidates(store, started)
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
