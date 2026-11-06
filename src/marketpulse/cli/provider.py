"""Quote providers: status, API keys and a test quote."""

from __future__ import annotations

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
@pass_app
def provider_status(app: App, as_json: bool) -> None:
    """Each provider's latest attempt, as the last refresh saw it."""
    rows = app.tracker.market.provider_status()
    if as_json:
        click.echo(json.dumps([asdict(r) for r in rows], ensure_ascii=False))
        return
    for r in rows:
        if r.ok is None:
            state = Text("not tried", style="muted")
        else:
            state = Text("ok", style="up") if r.ok else Text("failing", style="down")
        line = Text(f"{r.label:<16}", style="accent") + Text(f"{r.role:<10}", style="muted") + state
        if r.last_success:
            line.append(f"   last success {r.last_success}", style="muted")
        app.console.print(line)
        if r.ok is False and r.last_error:
            app.console.print(Text(f"  {r.last_error}", style="warn"))
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
