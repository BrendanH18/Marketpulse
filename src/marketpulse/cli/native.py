"""The macOS menu bar app, the native desktop app's JSON bridge, and background automation."""

from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path

import click
from rich.text import Text

from .. import render
from ..brokers import PROFILE_NAMES
from ..db import AutomationRun
from ..requests import receipt
from .base import App, date_callback, fail, pass_app
from .root import main


@main.group()
def menubar() -> None:
    """macOS menu bar companion."""


@menubar.command("install")
@pass_app
def menubar_install(app: App) -> None:
    """Build the native Swift app into ~/Applications and launch it."""
    import subprocess

    from ..menubar import build_and_install

    try:
        build_and_install(log=lambda m: app.console.print(Text(m, style="muted")))
    except (RuntimeError, subprocess.CalledProcessError) as e:
        fail(str(e))
    app.ok("MarketPulse Bar is running. ⌥⌘M opens the TUI; enable Launch at Login from its settings.")


@menubar.command("uninstall")
@pass_app
def menubar_uninstall(app: App) -> None:
    from ..menubar import uninstall

    app.ok("Removed." if uninstall(log=lambda m: None) else "Not installed.")


@main.group()
def desktop() -> None:
    """Native macOS portfolio app and its versioned JSON bridge."""


@desktop.command("transaction-status")
@click.argument("request_id", type=click.UUID)
@pass_app
def desktop_transaction_status(app: App, request_id) -> None:
    """Check a save receipt without replaying the ledger or requesting market data."""
    saved = receipt(app.store, str(request_id))
    click.echo(json.dumps({"recorded": saved is not None, "transaction_id": saved.transaction_id if saved else None}))


@desktop.command("snapshot")
@click.option("--fresh", is_flag=True, help="Bypass in-process quote cache.")
@click.option("--demo", is_flag=True, help="Fictional read-only portfolio; no real ledger or network access.")
@click.pass_obj
def desktop_snapshot(app: App, fresh: bool, demo: bool) -> None:
    """JSON portfolio state; includes a refresh, alert check, and safety backup."""
    from ..desktop import demo_snapshot, snapshot

    try:
        payload = demo_snapshot() if demo else snapshot(app.tracker, fresh=fresh)
        click.echo(json.dumps(payload, allow_nan=False))
    except (ValueError, OSError) as e:
        fail(str(e))


@desktop.command("restore-preview")
@click.argument("path", type=click.Path(dir_okay=False, path_type=Path))
def desktop_restore_preview(path: Path) -> None:
    """Compare a backup with the current ledger without opening the tracker or restoring."""
    from dataclasses import asdict

    from ..config import data_dir
    from ..db import RestoreError, preview_restore

    try:
        preview = preview_restore(data_dir(create=False) / "marketpulse.db", path, require_ready=True)
    except RestoreError as e:
        fail(str(e))
    click.echo(json.dumps({"version": 1, **asdict(preview)}))


@desktop.command("tax")
@click.option("--demo", is_flag=True, help="The fictional demo portfolio's report; no real ledger or network access.")
@click.pass_obj
def desktop_tax(app: App, demo: bool) -> None:
    """JSON capital gains for every year, superficial losses, and contribution room."""
    from ..desktop import demo_tax, tax_report

    try:
        payload = demo_tax() if demo else tax_report(app.tracker)
        click.echo(json.dumps(payload, allow_nan=False))
    except (ValueError, OSError) as e:
        fail(str(e))


@desktop.command("tax-csv")
@click.option("-y", "--year", type=int, default=None, help="Only this year's dispositions.")
@click.argument("path", type=click.Path(dir_okay=False, path_type=Path))
@click.pass_obj
def desktop_tax_csv(app: App, year: int | None, path: Path) -> None:
    """Write the tax CSV and return JSON: how many rows, and issues that may leave sales out."""
    from ..desktop import write_tax_csv

    try:
        click.echo(json.dumps(write_tax_csv(app.tracker, path, year), allow_nan=False))
    except (ValueError, OSError) as e:
        fail(str(e))


@desktop.command("install")
@click.pass_obj
def desktop_install(app: App) -> None:
    """Build and install the native app from an editable source checkout."""
    from ..menubar import build_and_install

    try:
        build_and_install(log=click.echo, desktop=True)
    except (RuntimeError, OSError) as e:
        fail(str(e))


@desktop.command("import")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--account", type=str)
@click.option("--profile", type=click.Choice(PROFILE_NAMES), default="auto")
@click.option("--dry-run", is_flag=True)
@click.option("--expect-fingerprint", help="Commit only if nothing changed since the preview that returned this.")
@click.pass_obj
def desktop_import(
    app: App, path: Path, account: str | None, profile: str, dry_run: bool, expect_fingerprint: str | None
) -> None:
    """Preview or import CSV, returning a structured result for the app."""
    from dataclasses import asdict

    from ..brokers import names_accounts, resolve
    from ..csvio import import_transactions, read_headers

    try:
        # Preview must never create a default account in the user's ledger.
        headers = read_headers(path.read_text(encoding="utf-8-sig"))
        default = app.store.get_account(account) if account else None
        if account and default is None:
            raise ValueError("Selected account no longer exists.")
        if not account and not names_accounts(resolve(profile, headers), headers):
            accounts = app.store.accounts()
            if not accounts:
                raise ValueError("Create an account first, or use a CSV with an account column.")
            if len(accounts) != 1:
                raise ValueError("Select an account for CSV files without an account column.")
            default = accounts[0]
        result = asdict(
            import_transactions(
                app.store,
                path,
                default_account=default,
                dry_run=dry_run,
                expect_fingerprint=expect_fingerprint,
                profile=profile,
            )
        )
        if result["backup"] is not None:
            result["backup"] = str(result["backup"])
        click.echo(json.dumps(result, allow_nan=False))
    except (ValueError, OSError) as e:
        fail(str(e))


@main.group()
def automation() -> None:
    """Refresh quotes, record snapshots, check alerts, and take daily backups."""


@automation.command("run")
@click.option("--once", is_flag=True, help="Run one cycle and exit (for launchd or cron).")
@click.option(
    "--cycles",
    type=click.IntRange(min=1),
    default=None,
    help="Run this many cycles, --interval apart, then exit (1 if any failed).",
)
@click.option("--interval", type=click.IntRange(min=15), default=60, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Emit one JSON object per cycle.")
@click.option("--quiet", is_flag=True, help="Suppress desktop notifications.")
@click.option(
    "--strict", is_flag=True, help="With --once or --cycles, also exit 1 when a symbol or FX rate couldn't be quoted."
)
@click.pass_obj
def automation_run(
    app: App, once: bool, cycles: int | None, interval: int, as_json: bool, quiet: bool, strict: bool
) -> None:
    """Run maintenance until Ctrl+C, or once for an external scheduler."""
    from ..automation import run_cycle

    if once and cycles is not None:
        raise click.UsageError("Choose either --once or --cycles.")
    if strict and not once and cycles is None:
        raise click.UsageError("--strict requires --once or --cycles.")
    remaining = 1 if once else cycles
    bad = False
    try:
        while True:
            try:
                report = run_cycle(app.tracker, fresh=True, notify=not quiet).report
            except Exception as e:
                # A provider/disk failure should be visible and retried on the next tick.
                report = {"errors": [str(e)], "failed": True}
            if as_json:
                click.echo(json.dumps(report, allow_nan=False))
            else:
                click.echo(json.dumps(report, indent=2, allow_nan=False))
            # Only a failed cycle is an error; an unquotable symbol is reported, not fatal (unless --strict).
            bad = bad or bool(report.get("failed") or report.get("errors"))
            bad = bad or (strict and bool(report.get("quote_errors")))
            if remaining is not None:
                remaining -= 1
                if remaining == 0:
                    if bad:
                        raise click.exceptions.Exit(1)
                    break
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


def _history_item(run: AutomationRun) -> dict:
    report = run.report
    return {
        "id": run.id,
        "ran_at": run.ran_at,
        "failed": run.failed,
        "errors": list(report.get("errors") or []),
        "quote_error_count": len(report.get("quote_errors") or []),
        "stale_count": report.get("stale_count"),
        "fired": list(report.get("fired") or []),
        "report": report,
    }


HISTORY_CSV_FIELDS = ["id", "ran_at", "failed", "errors", "quote_error_count", "stale_count", "fired"]


def _history_summary(items: list[dict]) -> dict:
    """Totals over the selected runs (newest first)."""
    failures = [i for i in items if i["failed"]]
    return {
        "runs": len(items),
        "failed": len(failures),
        "succeeded": len(items) - len(failures),
        "quote_errors": sum(i["quote_error_count"] for i in items),
        "alerts_fired": sum(len(i["fired"]) for i in items),
        "first_run": items[-1]["ran_at"] if items else None,
        "last_run": items[0]["ran_at"] if items else None,
        "last_failure": failures[0]["ran_at"] if failures else None,
    }


def _show_history_summary(app: App, summary: dict) -> None:
    app.title("Automation runs")
    if not summary["runs"]:
        app.console.print(Text("No automation runs match.", style="muted"))
        return
    lines = [
        ("Runs", str(summary["runs"]), ""),
        ("Succeeded", str(summary["succeeded"]), "up" if summary["succeeded"] else "muted"),
        ("Failed", str(summary["failed"]), "down" if summary["failed"] else "muted"),
        ("Quote errors", str(summary["quote_errors"]), "warn" if summary["quote_errors"] else "muted"),
        ("Alerts fired", str(summary["alerts_fired"]), ""),
        ("First run", summary["first_run"].replace("T", " "), "muted"),
        ("Last run", summary["last_run"].replace("T", " "), "muted"),
        (
            "Last failure",
            (summary["last_failure"] or "—").replace("T", " "),
            "down" if summary["last_failure"] else "muted",
        ),
    ]
    for label, value, style in lines:
        app.console.print(Text.assemble((f"{label:<13}", "muted"), (value, style)))


@automation.command("history")
@click.option("--failures", "failures_only", is_flag=True, help="Only runs that recorded errors.")
@click.option("--successes", "successes_only", is_flag=True, help="Only runs that recorded no errors.")
@click.option("--with-alerts", is_flag=True, help="Only runs that fired at least one alert.")
@click.option("--since", callback=date_callback, help="Only runs on or after YYYY-MM-DD (or today, -7d).")
@click.option("--until", callback=date_callback, help="Only runs on or before YYYY-MM-DD.")
@click.option("--limit", type=click.IntRange(min=1), help="Show at most this many runs.")
@click.option("--json", "as_json", is_flag=True, help="Runs as JSON, newest first, with each full report.")
@click.option("--jsonl", "as_jsonl", is_flag=True, help="Runs as JSON Lines, newest first, with each full report.")
@click.option("--csv", "as_csv", is_flag=True, help="Runs as CSV on stdout (without the full reports).")
@click.option("--count", "count_only", is_flag=True, help="Print only the number of matching runs.")
@click.option("--summary", is_flag=True, help="Totals over the matching runs (with --json for raw figures).")
@click.option("--exit-code", is_flag=True, help="Exit 1 when any matching run failed.")
@pass_app
def automation_history(
    app: App,
    failures_only: bool,
    successes_only: bool,
    with_alerts: bool,
    since: str | None,
    until: str | None,
    limit: int | None,
    as_json: bool,
    as_jsonl: bool,
    as_csv: bool,
    count_only: bool,
    summary: bool,
    exit_code: bool,
) -> None:
    """Recent automation runs, newest first (the newest 50 are kept). Offline."""
    if failures_only and successes_only:
        raise click.UsageError("Choose either --failures or --successes.")
    if sum((as_json, as_jsonl, as_csv)) > 1:
        raise click.UsageError("Choose one output format: --json, --jsonl or --csv.")
    if count_only and (as_json or as_jsonl or as_csv or summary):
        raise click.UsageError("--count cannot be combined with --json, --jsonl, --csv or --summary.")
    if summary and (as_jsonl or as_csv):
        raise click.UsageError("--summary cannot be combined with --jsonl or --csv.")
    if since is not None and until is not None and since > until:
        raise click.UsageError("--since must be on or before --until.")
    selecting = successes_only or with_alerts or since is not None or until is not None
    runs = app.store.automation_runs(failures_only=failures_only, limit=None if selecting else limit)
    items = [
        item
        for item in (_history_item(run) for run in runs)
        if (not successes_only or not item["failed"])
        and (not with_alerts or item["fired"])
        and (since is None or item["ran_at"][:10] >= since)
        and (until is None or item["ran_at"][:10] <= until)
    ][:limit]
    _print_history(
        app,
        items,
        failures_only=failures_only,
        selecting=selecting,
        as_json=as_json,
        as_jsonl=as_jsonl,
        as_csv=as_csv,
        count_only=count_only,
        summary=summary,
    )
    if exit_code and any(item["failed"] for item in items):
        raise click.exceptions.Exit(1)


def _print_history(
    app: App,
    items: list[dict],
    *,
    failures_only: bool,
    selecting: bool,
    as_json: bool,
    as_jsonl: bool,
    as_csv: bool,
    count_only: bool,
    summary: bool,
) -> None:
    if count_only:
        click.echo(len(items))
        return
    if summary:
        totals = _history_summary(items)
        if as_json:
            click.echo(json.dumps(totals, ensure_ascii=False, allow_nan=False))
        else:
            _show_history_summary(app, totals)
        return
    if as_json:
        click.echo(json.dumps(items, ensure_ascii=False, allow_nan=False))
        return
    if as_jsonl:
        for item in items:
            click.echo(json.dumps(item, ensure_ascii=False, allow_nan=False))
        return
    if as_csv:
        stream = io.StringIO()
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(HISTORY_CSV_FIELDS)
        for item in items:
            writer.writerow(
                [
                    item["id"],
                    item["ran_at"],
                    "true" if item["failed"] else "false",
                    "; ".join(item["errors"]),
                    item["quote_error_count"],
                    "" if item["stale_count"] is None else item["stale_count"],
                    "; ".join(item["fired"]),
                ]
            )
        click.echo(stream.getvalue(), nl=False)
        return
    if not items:
        if selecting:
            app.warn("No automation runs match these filters.")
        else:
            app.warn("No failed automation runs recorded." if failures_only else "No automation runs recorded yet.")
        return
    narrow = app.console.width < render.NARROW_WIDTH
    t = render.table(
        "Time",
        "Result",
        "Errors",
        ("Quote errors", "right"),
        ("Stale", "right"),
        "Alerts fired",
        title="Automation runs",
    )
    for item in items:
        when = item["ran_at"].replace("T", " ")[:16]
        if narrow:
            when = when[5:]  # MM-DD HH:MM
        failed = item["failed"]
        result = (
            Text("✗" if narrow else "✗ failed", style="down") if failed else Text("✓" if narrow else "✓ ok", style="up")
        )
        stale = item["stale_count"]
        t.add_row(
            Text(when),
            result,
            Text("; ".join(item["errors"]) or "—", style="down" if failed else "muted"),
            Text(str(item["quote_error_count"]), style="warn" if item["quote_error_count"] else "muted"),
            Text("—" if stale is None else str(stale), style="warn" if stale else "muted"),
            Text(", ".join(item["fired"]) or "—", style="" if item["fired"] else "muted"),
        )
    app.console.print(t)
