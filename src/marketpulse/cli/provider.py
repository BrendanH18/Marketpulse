"""Quote providers: status, API keys and a test quote."""

from __future__ import annotations

import csv
import io
import json
import sys
from dataclasses import asdict

import click
from rich.text import Text

from .. import fmt
from ..market import MarketError
from ..providers import PROVIDERS, make_fallback, provider_label
from .base import App, fail, pass_app
from .root import main


@main.group()
def provider() -> None:
    """Quote providers: Yahoo, and an optional fallback that uses your own API key."""


@provider.command("status")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.option("--csv", "as_csv", is_flag=True, help="Export provider status as CSV.")
@click.option("--supported", is_flag=True, help="List supported fallback quote providers offline.")
@click.option("--name", help="Match an exact provider name, ignoring case.")
@click.option("--search", help="Match provider name, label or last error text, ignoring case.")
@click.option("--role", type=click.Choice(["primary", "fallback"]), help="Select provider role.")
@click.option("--state", type=click.Choice(["ok", "failing", "untried"]), help="Select latest attempt state.")
@click.option("--exit-code", is_flag=True, help="Exit 1 if any shown provider is failing or missing a key.")
@click.option("--count", is_flag=True, help="Count matching providers.")
@pass_app
def provider_status(
    app: App,
    as_json: bool,
    as_csv: bool,
    supported: bool,
    name: str | None,
    search: str | None,
    role: str | None,
    state: str | None,
    exit_code: bool,
    count: bool,
) -> None:
    """Each provider's latest attempt, as the last refresh saw it."""
    if sum((as_json, as_csv, count)) > 1:
        raise click.UsageError("Choose one of --json, --csv or --count.")
    if search is not None and not search.strip():
        raise click.BadParameter("Cannot be blank.", param_hint="--search")
    needle = (search or "").strip().casefold()

    def matches(provider_name: str, label: str, error: str = "") -> bool:
        return (not name or provider_name.casefold() == name.casefold()) and (
            not needle or needle in f"{provider_name} {label} {error}".casefold().strip()
        )

    if supported:
        sup_rows = [
            {
                "name": pname,
                "label": provider_label(pname),
                "configured": app.config.quote_provider == pname,
                "has_key": app.config.quote_provider == pname and bool(app.config.quote_api_key),
            }
            for pname in sorted(PROVIDERS)
            if matches(pname, provider_label(pname))
        ]
        if count:
            click.echo(len(sup_rows))
        elif as_csv:
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=["name", "label", "configured", "has_key"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(sup_rows)
            click.echo(stream.getvalue(), nl=False)
        elif as_json:
            click.echo(json.dumps(sup_rows, ensure_ascii=False))
        else:
            for sr in sup_rows:
                tag = "configured" if sr["has_key"] else ("configured (no key)" if sr["configured"] else "available")
                style = "up" if sr["has_key"] else ("warn" if sr["configured"] else "muted")
                app.console.print(
                    Text(f"{sr['name']:<16}", style="accent") + Text(f"{sr['label']:<20}") + Text(tag, style=style)
                )
        if exit_code and any(row["configured"] and not row["has_key"] for row in sup_rows):
            raise click.exceptions.Exit(1)
        return
    rows = [r for r in app.tracker.market.provider_status() if matches(r.name, r.label, r.last_error or "")]
    if role:
        rows = [r for r in rows if r.role == role]
    if state:
        rows = [r for r in rows if ("untried" if r.ok is None else "ok" if r.ok else "failing") == state]
    fallback_name = app.config.quote_provider
    missing_key = bool(
        fallback_name
        and app.tracker.market.fallback is None
        and role != "primary"
        and state is None
        and matches(fallback_name, provider_label(fallback_name))
    )
    unhealthy = any(r.ok is False for r in rows) or missing_key
    if count:
        click.echo(len(rows))
        if exit_code and unhealthy:
            raise click.exceptions.Exit(1)
        return
    if as_csv:
        from ..market import ProviderStatus

        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(ProviderStatus.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(r) for r in rows)
        click.echo(stream.getvalue(), nl=False)
        if exit_code and unhealthy:
            raise click.exceptions.Exit(1)
        return
    if as_json:
        click.echo(json.dumps([asdict(r) for r in rows], ensure_ascii=False))
        if exit_code and unhealthy:
            raise click.exceptions.Exit(1)
        return
    for r in rows:
        if r.ok is None:
            state_text = Text("not tried", style="muted")
        else:
            state_text = Text("ok", style="up") if r.ok else Text("failing", style="down")
        line = Text(f"{r.label:<16}", style="accent") + Text(f"{r.role:<10}", style="muted") + state_text
        if r.last_success:
            line.append(f"   last success {r.last_success}", style="muted")
        app.console.print(line)
        if r.ok is False and r.last_error:
            app.console.print(Text(f"  {r.last_error}", style="warn"))
    if missing_key:
        app.warn(f"{provider_label(fallback_name)} has no key yet: `marketpulse provider key NAME`.")
    elif not (fallback_name or name or search or role or state):
        names = ", ".join(PROVIDERS)
        app.console.print(
            Text(f"No fallback provider. Add one with `marketpulse provider key NAME` ({names}).", style="muted")
        )
    if exit_code and unhealthy:
        raise click.exceptions.Exit(1)


@provider.command("key")
@click.argument("name", type=click.Choice(sorted(PROVIDERS)))
@click.option("--dry-run", is_flag=True, help="Validate the key format without saving it.")
@click.option("--json", "as_json", is_flag=True, help="Print a redacted JSON receipt; supports --dry-run.")
@pass_app
def provider_key(app: App, name: str, dry_run: bool, as_json: bool) -> None:
    """Save your API key for NAME and use it as the fallback. Reads the key from standard input."""
    if sys.stdin.isatty():
        key = click.prompt(f"{provider_label(name)} API key", hide_input=True, default="", show_default=False)
    else:
        key = sys.stdin.read()
    key = key.strip()
    if not key:
        fail("No key given.")
    if any(c.isspace() or not c.isprintable() for c in key) or len(key) > 256:
        fail("That doesn't look like an API key: it has spaces or unusual characters.")
    if not dry_run:
        app.config.quote_provider = name
        app.config.quote_api_key = key
        app.config.save()
    if as_json:
        click.echo(
            json.dumps(
                {"provider": name, "label": provider_label(name), "saved": not dry_run, "key_set": True},
                ensure_ascii=False,
            )
        )
    elif dry_run:
        app.ok(f"Key looks valid for {provider_label(name)} (not saved).")
    else:
        app.ok(f"Saved. {provider_label(name)} will supply quotes when Yahoo can't be reached.")


@provider.command("clear")
@click.option("--dry-run", is_flag=True, help="Preview clearing the fallback provider without modifying config.")
@click.option("--json", "as_json", is_flag=True, help="Print a JSON receipt; supports --dry-run.")
@pass_app
def provider_clear(app: App, dry_run: bool, as_json: bool) -> None:
    """Remove the fallback provider and its key."""
    previous = app.config.quote_provider
    had_key = bool(app.config.quote_api_key)
    if not dry_run:
        app.config.quote_provider = ""
        app.config.quote_api_key = ""
        app.config.save()
    if as_json:
        click.echo(
            json.dumps(
                {"previous_provider": previous, "had_key": had_key, "cleared": not dry_run},
                ensure_ascii=False,
            )
        )
    elif dry_run:
        if previous or had_key:
            label = provider_label(previous) if previous else "configured key"
            app.ok(f"Would remove fallback quote provider ({label}; not saved).")
        else:
            app.ok("No fallback quote provider configured (dry run).")
    else:
        app.ok("Removed the fallback quote provider.")


@provider.command("test")
@click.argument("symbol", default="XEQT.TO")
@pass_app
def provider_test(app: App, symbol: str) -> None:
    """Ask the fallback provider for one quote, to check your key works."""
    fallback = make_fallback(app.config)
    if fallback is None:
        fail("No fallback provider is set up. Add one with `marketpulse provider key NAME`.")
    try:
        quotes, errors = fallback.quotes([symbol.upper()])
    except MarketError as e:
        fail(f"{fallback.label}: {e}")
    q = quotes.get(symbol.upper())
    if q is None:
        fail(f"{fallback.label}: {errors.get(symbol.upper(), 'no quote')}")
    app.ok(f"{fallback.label}: {q.symbol} {fmt.price(q.price)} {q.currency}")
