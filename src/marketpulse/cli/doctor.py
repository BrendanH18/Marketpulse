"""`marketpulse doctor`: check the installation, data, network and integrations."""

from __future__ import annotations

import csv
import io
import json
import platform
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from typing import Literal

import click
from rich.text import Text

from .. import __version__
from ..config import config_path
from ..market import PRIMARY
from ..providers import provider_label
from ..themes import omarchy_active, pretty_name
from .base import App, pass_app
from .root import main

Status = Literal["ok", "fail", "info", "skipped"]
MARKS: dict[str, tuple[str, str]] = {
    "ok": ("✓ ", "up"),
    "fail": ("✗ ", "down"),
    "info": ("• ", "muted"),
    "skipped": ("- ", "muted"),
}


@dataclass
class Check:
    check: str
    status: Status
    detail: str


def _status(ok: bool | None) -> Status:
    return "ok" if ok else ("fail" if ok is False else "info")


# Every check `doctor` can report, in display order. `swift` and `menu bar app` run on macOS only.
CHECKS = (
    "version",
    "config",
    "database",
    "backups",
    "ledger",
    "ledger checks",
    "market data",
    "fallback quotes",
    "theme",
    "cli path",
    "swift",
    "menu bar app",
)
STATUSES: tuple[Status, ...] = ("ok", "fail", "info", "skipped")


def _check_names(ctx, param, values: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize check names (case, `-`/`_` for spaces) and reject unknown ones."""
    names = []
    for raw in values:
        name = " ".join(raw.replace("-", " ").replace("_", " ").lower().split())
        if name not in CHECKS:
            raise click.BadParameter(f"unknown check {raw!r}. Valid checks: {', '.join(CHECKS)}.")
        if name not in names:
            names.append(name)
    return tuple(names)


@main.command()
@click.option("--offline", is_flag=True, help="Skip the network checks (market data, fallback quotes).")
@click.option("--json", "as_json", is_flag=True, help="Print every check as JSON with an overall ok flag.")
@click.option("--strict", is_flag=True, help="Exit with status 1 if any check failed.")
@click.option(
    "--only", multiple=True, callback=_check_names, help="Run only this check (repeatable), e.g. --only ledger-checks."
)
@click.option("--exclude", multiple=True, callback=_check_names, help="Skip this check (repeatable).")
@click.option("--failed-only", is_flag=True, help="Show only the checks that failed.")
@click.option("--summary", is_flag=True, help="Print how many checks ended in each status instead of every row.")
@click.option("--csv", "as_csv", is_flag=True, help="Export checks or status summary as CSV.")
@click.option(
    "--status", "statuses", multiple=True, type=click.Choice(STATUSES), help="Show checks with these statuses."
)
@click.option("--search", help="Find text in check names or details, ignoring case.")
@click.option("--count", is_flag=True, help="Count visible checks.")
@click.option("--list-checks", is_flag=True, help="List available check names without running them.")
@pass_app
def doctor(
    app: App,
    offline: bool,
    as_json: bool,
    strict: bool,
    only: tuple[str, ...],
    exclude: tuple[str, ...],
    failed_only: bool,
    summary: bool,
    as_csv: bool,
    statuses: tuple[str, ...],
    search: str | None,
    count: bool,
    list_checks: bool,
) -> None:
    """Check the installation, data, network and integrations.

    Exit status is 0 unless --strict is given and a check failed (then 1).
    --only and --exclude take check names; checks that aren't selected don't run.
    """
    if sum((as_json, as_csv, count)) > 1:
        raise click.UsageError("Choose one of --json, --csv or --count.")
    if count and summary:
        raise click.UsageError("--count cannot be combined with --summary.")
    if list_checks:
        if only or exclude or failed_only or summary or statuses or search or strict:
            raise click.UsageError("--list-checks cannot be combined with execution or result filters.")
        if as_json:
            click.echo(json.dumps(list(CHECKS)))
        elif as_csv:
            click.echo("check")
            for name in CHECKS:
                click.echo(name)
        elif count:
            click.echo(len(CHECKS))
        else:
            click.echo("\n".join(CHECKS))
        return
    if only and exclude:
        raise click.UsageError("Choose one of --only or --exclude.")
    if failed_only and summary:
        raise click.UsageError("--failed-only cannot be combined with --summary.")
    selected = set(only) if only else set(CHECKS) - set(exclude)
    checks = _collect(app, offline=offline, selected=selected)
    failed = any(c.status == "fail" for c in checks)
    if failed_only:
        checks = [c for c in checks if c.status == "fail"]
    if statuses:
        checks = [c for c in checks if c.status in statuses]
    if search:
        checks = [c for c in checks if search.casefold() in (c.check + " " + c.detail).casefold()]
    if count:
        click.echo(len(checks))
    elif as_csv:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        if summary:
            writer.writerow(["status", "count"])
            writer.writerows((s, sum(c.status == s for c in checks)) for s in STATUSES)
        else:
            writer.writerow(["check", "status", "detail"])
            writer.writerows((c.check, c.status, c.detail) for c in checks)
        click.echo(stream.getvalue(), nl=False)
    elif summary:
        counts = {s: sum(c.status == s for c in checks) for s in STATUSES}
        if as_json:
            click.echo(json.dumps({"ok": not failed, "summary": counts}, ensure_ascii=False))
        else:
            parts = [Text(f"{counts[s]} {s}", style=MARKS[s][1]) for s in STATUSES]
            app.console.print(Text(" · ", style="muted").join(parts))
    elif as_json:
        click.echo(json.dumps({"ok": not failed, "checks": [asdict(c) for c in checks]}, ensure_ascii=False))
    elif failed_only and not checks:
        app.console.print(Text("No failed checks.", style="muted"))
    else:
        for c in checks:
            mark, style = MARKS[c.status]
            app.console.print(Text(mark, style=style) + Text(f"{c.check:<18}", style="muted") + Text(c.detail))
    if strict and failed:
        click.get_current_context().exit(1)


def _collect(app: App, *, offline: bool, selected: set[str] | None = None) -> list[Check]:
    """Run each selected check once (all by default); the caller renders them as text or JSON.

    A check left out of `selected` never runs, so excluding `market data` makes no request.
    """
    from ..menubar import app_path, cli_path

    checks: list[Check] = []

    def want(label: str) -> bool:
        return selected is None or label in selected

    def row(label: str, value: str, ok: bool | None = True) -> None:
        checks.append(Check(label, _status(ok), value))

    def skip(label: str, value: str) -> None:
        checks.append(Check(label, "skipped", value))

    if want("version"):
        python = f"Python {platform.python_version()}"
        row("version", f"MarketPulse {__version__} · {python} · {platform.system()} {platform.release()}", None)
    if want("config"):
        row("config", str(config_path()), config_path().exists() or None)
    if want("database"):
        row("database", f"{app.tracker.store.path} (schema v{app.tracker.store.schema_version})")
    if want("backups"):
        newest = next(iter(app.tracker.store.backups()), None)
        if newest is None:
            row("backups", "none yet — `marketpulse backup`", None)
        else:
            age_days = (time.time() - newest.stat().st_mtime) / 86400
            # Daily backups keep this under a day; a week means they're failing (full disk, permissions…).
            row("backups", f"{len(app.tracker.store.backups())} · newest {newest.name}", age_days < 7)
    if want("ledger"):
        row(
            "ledger",
            f"{len(app.tracker.store.accounts())} accounts · {len(app.tracker.store.transactions())} transactions"
            f" · {len(app.tracker.store.snapshots())} snapshots",
            None,
        )
    if want("ledger checks"):
        issues = app.tracker.store.ledger().issues
        row("ledger checks", f"{len(issues)} issue(s)" if issues else "consistent", not issues)
    if want("market data"):
        if offline:
            skip("market data", "Yahoo not contacted (--offline)")
        else:
            t0 = time.perf_counter()
            quotes, errors = app.tracker.market.quotes(["SPY"], use_cache=False)
            spy = quotes.get("SPY")
            if spy is not None and not spy.stale and spy.source == PRIMARY:
                row("market data", f"Yahoo reachable ({(time.perf_counter() - t0) * 1000:.0f} ms)")
            else:
                # `quotes` doesn't raise when Yahoo is down: it falls back, then serves cached prices.
                yahoo = app.tracker.market.provider_status()[0]
                row("market data", f"Yahoo unreachable: {yahoo.last_error or errors.get('SPY', 'no data')}", False)
    if want("fallback quotes"):
        fallback = app.tracker.market.fallback
        if fallback is not None and offline:
            skip("fallback quotes", f"{fallback.label} not checked (--offline)")
        elif fallback is not None:
            st = app.tracker.market.provider_status()[-1]
            state = "not used yet" if st.ok is None else ("ok" if st.ok else f"failing: {st.last_error}")
            row("fallback quotes", f"{fallback.label} ({state})", st.ok)
        elif app.config.quote_provider:
            row("fallback quotes", f"{provider_label(app.config.quote_provider)}: no key set", False)
    if want("theme"):
        active = omarchy_active()
        row(
            "theme",
            f"{app.config.theme} → {pretty_name(app.palette.name)}" + (" (Omarchy detected)" if active else ""),
            None,
        )
    if want("cli path"):
        row("cli path", cli_path(), None)
    if sys.platform == "darwin":
        if want("swift"):
            row("swift", shutil.which("swift") or "not found (xcode-select --install)", bool(shutil.which("swift")))
        if want("menu bar app"):
            row(
                "menu bar app",
                str(app_path()) if app_path().exists() else "not installed — `marketpulse menubar install`",
                app_path().exists() or None,
            )
    return checks
