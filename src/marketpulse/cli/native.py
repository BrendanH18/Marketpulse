"""The macOS menu bar app, the native desktop app's JSON bridge, and background automation."""

from __future__ import annotations

import json
import time
from pathlib import Path

import click
from rich.text import Text

from ..brokers import PROFILE_NAMES
from ..requests import receipt
from .base import App, fail, pass_app
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
@click.option("--interval", type=click.IntRange(min=15), default=60, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Emit one JSON object per cycle.")
@click.option("--quiet", is_flag=True, help="Suppress desktop notifications.")
@click.pass_obj
def automation_run(app: App, once: bool, interval: int, as_json: bool, quiet: bool) -> None:
    """Run maintenance until Ctrl+C, or once for an external scheduler."""
    from ..automation import run_cycle

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
            if once:
                # Only a failed cycle is an error; an unquotable symbol is reported, not fatal.
                if report.get("failed") or report.get("errors"):
                    raise click.exceptions.Exit(1)
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
