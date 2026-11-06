"""Appearance and configuration: themes and settings."""

from __future__ import annotations

from dataclasses import fields

import click
from rich.text import Text

from .. import render
from ..config import Config, config_path
from ..market import PERIODS
from ..models import parse_symbols
from ..providers import PROVIDERS
from ..themes import omarchy_active, pretty_name
from .base import App, fail, pass_app, theme_slug
from .root import main


@main.group(invoke_without_command=True)
@click.pass_context
def theme(ctx: click.Context) -> None:
    """Omarchy themes. `auto` follows your active Omarchy theme."""
    if ctx.invoked_subcommand is None:
        app = ctx.ensure_object(App)
        active = omarchy_active()
        app.console.print(render.theme_table(app.palette.name))
        note = (
            f"Omarchy detected — auto follows '{pretty_name(active[0])}'."
            if active
            else "auto → Tokyo Night (no Omarchy install detected)."
        )
        app.console.print(Text(f'config: theme = "{app.config.theme}"   {note}', style="muted"))


@theme.command("set")
@click.argument("name", nargs=-1, required=True)
@pass_app
def theme_set(app: App, name: tuple[str, ...]) -> None:
    app.config.theme = theme_slug(" ".join(name))
    app.config.save()
    app.ok(f"Theme → {pretty_name(app.config.theme)}")


@main.group(invoke_without_command=True)
@click.pass_context
def config(ctx: click.Context) -> None:
    """Show or change settings."""
    if ctx.invoked_subcommand is None:
        app = ctx.ensure_object(App)
        app.console.print(Text(str(config_path()), style="muted"))
        for name, value in app.config.redacted().items():
            app.console.print(Text(f"{name:<24}", style="accent") + Text(repr(value)))


@config.command("set")
@click.argument("key")
@click.argument("value", nargs=-1, required=True)
@pass_app
def config_set(app: App, key: str, value: tuple[str, ...]) -> None:
    known = {f.name: f for f in fields(Config)}
    if key not in known:
        fail(f"Unknown setting '{key}'. Known: {', '.join(known)}")
    if key == "quote_api_key":
        # On the command line it would sit in shell history and be visible in `ps`.
        fail("Set the key with `marketpulse provider key NAME`, which reads it from standard input.")
    raw = " ".join(value)
    current = getattr(app.config, key)
    parsed: object  # bool, int, float, list[str] or str, matching the setting's type
    try:
        if isinstance(current, bool):
            if raw.lower() not in ("true", "false", "yes", "no", "on", "off", "1", "0"):
                raise ValueError
            parsed = raw.lower() in ("true", "yes", "on", "1")
        elif isinstance(current, int):
            parsed = int(raw)
        elif isinstance(current, float):
            parsed = float(raw)
        elif isinstance(current, list):
            parsed = parse_symbols(raw)
        else:
            parsed = raw
    except ValueError:
        fail(f"Invalid value for {key}: {raw!r}")
    if key == "theme":
        parsed = theme_slug(raw)
    if key == "base_currency":
        parsed = raw.upper()
        if len(parsed) != 3:
            fail("base_currency must be a 3-letter code like CAD.")
    if key == "menubar_display" and parsed not in ("day_pct", "day_change", "net_worth", "symbol"):
        fail("menubar_display must be day_pct, day_change, net_worth or symbol.")
    if key == "chart_period" and parsed not in PERIODS:
        fail(f"chart_period must be one of {', '.join(PERIODS)}")
    if key == "capital_gains_inclusion" and not (isinstance(parsed, float) and 0 < parsed <= 1):
        fail("capital_gains_inclusion is a fraction: > 0 and <= 1 (e.g. 0.5).")
    if key == "refresh_seconds" and isinstance(parsed, int) and parsed < 5:
        fail("refresh_seconds must be at least 5.")
    if key == "quote_provider" and parsed and parsed not in PROVIDERS:
        fail(f"quote_provider must be empty or one of {', '.join(PROVIDERS)}.")
    setattr(app.config, key, parsed)
    app.config.save()
    app.ok(f"{key} = {parsed!r}")


@config.command("path")
def config_path_cmd() -> None:
    click.echo(config_path())


@config.command("edit")
@pass_app
def config_edit(app: App) -> None:
    path = config_path()
    if not path.exists():
        app.config.save(path)
    click.edit(filename=str(path))
