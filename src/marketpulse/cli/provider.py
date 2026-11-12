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
@click.option("--name", help="Match an exact provider name, ignoring case.")
@click.option("--role", type=click.Choice(["primary", "fallback"]), help="Select provider role.")
@click.option("--state", type=click.Choice(["ok", "failing", "untried"]), help="Select latest attempt state.")
@click.option("--count", is_flag=True, help="Count matching providers.")
@pass_app
def provider_status(
    app: App, as_json: bool, as_csv: bool, name: str | None, role: str | None, state: str | None, count: bool
) -> None:
    """Each provider's latest attempt, as the last refresh saw it."""
    if sum((as_json, as_csv, count)) > 1:
        raise click.UsageError("Choose one of --json, --csv or --count.")
    rows = app.tracker.market.provider_status()
    if name:
        rows = [r for r in rows if r.name.casefold() == name.casefold()]
    if role:
        rows = [r for r in rows if r.role == role]
    if state:
        rows = [r for r in rows if ("untried" if r.ok is None else "ok" if r.ok else "failing") == state]
    if count:
        click.echo(len(rows))
        return
    if as_csv:
        from ..market import ProviderStatus

        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(ProviderStatus.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(r) for r in rows)
        click.echo(stream.getvalue(), nl=False)
        return
    if as_json:
        click.echo(json.dumps([asdict(r) for r in rows], ensure_ascii=False))
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
    if name or role or state:
        return
    if app.config.quote_provider and app.tracker.market.fallback is None:
        app.warn(f"{provider_label(app.config.quote_provider)} has no key yet: `marketpulse provider key NAME`.")
    elif not app.config.quote_provider:
        names = ", ".join(PROVIDERS)
        app.console.print(
            Text(f"No fallback provider. Add one with `marketpulse provider key NAME` ({names}).", style="muted")
        )


@provider.command("key")
@click.argument("name", type=click.Choice(sorted(PROVIDERS)))
@pass_app
def provider_key(app: App, name: str) -> None:
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
    app.config.quote_provider = name
    app.config.quote_api_key = key
    app.config.save()
    app.ok(f"Saved. {provider_label(name)} will supply quotes when Yahoo can't be reached.")


@provider.command("clear")
@pass_app
def provider_clear(app: App) -> None:
    """Remove the fallback provider and its key."""
    app.config.quote_provider = ""
    app.config.quote_api_key = ""
    app.config.save()
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
