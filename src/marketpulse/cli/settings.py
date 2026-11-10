"""Appearance and configuration: themes and settings."""

from __future__ import annotations

import json
import math
import tomllib
from dataclasses import fields, replace

import click
from rich.text import Text

from .. import render
from ..config import Config, config_path
from ..market import PERIODS
from ..models import parse_symbols
from ..providers import PROVIDERS
from ..themes import OMARCHY_PALETTES, omarchy_active, pretty_name
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
@click.option("--json", "as_json", is_flag=True, help="Print settings as JSON; API keys stay redacted.")
@click.pass_context
def config(ctx: click.Context, as_json: bool) -> None:
    """Show or change settings."""
    if as_json and ctx.invoked_subcommand is not None:
        raise click.UsageError("Use config --json without a subcommand.")
    if ctx.invoked_subcommand is None:
        app = ctx.ensure_object(App)
        if as_json:
            _print_settings(app, app.config.redacted(), True)
            return
        app.console.print(Text(str(config_path()), style="muted"))
        for name, value in app.config.redacted().items():
            app.console.print(Text(f"{name:<24}", style="accent") + Text(repr(value)))


@config.command("set")
@click.argument("key")
@click.argument("value", nargs=-1, required=True)
@click.option("--dry-run", is_flag=True, help="Validate and preview the setting without saving.")
@pass_app
def config_set(app: App, key: str, value: tuple[str, ...], dry_run: bool) -> None:
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
    if error := _setting_error(key, parsed):
        fail(error)
    if dry_run:
        app.ok(f"Would set {key} = {parsed!r} (not saved).")
        return
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


_TERMINALS = ("auto", "ghostty", "iterm", "terminal", "kitty", "wezterm")


def _setting_error(key: str, value: object) -> str | None:
    """Domain checks shared by writes and read-only raw-file diagnostics."""
    if isinstance(value, float) and not math.isfinite(value):
        return f"{key} must be finite."
    if key == "base_currency" and (
        not isinstance(value, str) or len(value) != 3 or not value.isascii() or not value.isalpha()
    ):
        return "base_currency must be a 3-letter code like CAD."
    if key == "menubar_display" and value not in ("day_pct", "day_change", "net_worth", "symbol"):
        return "menubar_display must be day_pct, day_change, net_worth or symbol."
    if key == "chart_period" and value not in PERIODS:
        return f"chart_period must be one of {', '.join(PERIODS)}"
    if key == "capital_gains_inclusion" and not (isinstance(value, int | float) and 0 < value <= 1):
        return "capital_gains_inclusion is a fraction: > 0 and <= 1 (e.g. 0.5)."
    if key == "refresh_seconds" and isinstance(value, int | float) and value < 5:
        return "refresh_seconds must be at least 5."
    if key == "quote_provider" and value and value not in PROVIDERS:
        return f"quote_provider must be empty or one of {', '.join(PROVIDERS)}."
    if key == "terminal" and value not in _TERMINALS:
        return f"terminal must be one of {', '.join(_TERMINALS)}."
    if key == "theme" and value not in ("auto", "omarchy", *OMARCHY_PALETTES):
        return "theme must be a known theme; see `marketpulse theme`."
    return None


def _known_key(key: str) -> None:
    if key not in {f.name for f in fields(Config)}:
        fail(f"Unknown setting '{key}'.")


def _print_settings(app: App, values: dict, as_json: bool) -> None:
    if as_json:
        # JSON cannot represent invalid legacy Infinity/NaN values.
        safe = {
            key: None if isinstance(value, float) and not math.isfinite(value) else value
            for key, value in values.items()
        }
        click.echo(json.dumps(safe, ensure_ascii=False, allow_nan=False))
    else:
        for key, value in values.items():
            app.console.print(Text(f"{key:<24}", style="accent") + Text(repr(value)))


@config.command("get")
@click.argument("key")
@click.option("--json", "as_json", is_flag=True)
@pass_app
def config_get(app: App, key: str, as_json: bool) -> None:
    """Inspect one setting (API keys remain redacted)."""
    _known_key(key)
    _print_settings(app, {key: app.config.redacted()[key]}, as_json)


@config.command("defaults")
@click.option("--json", "as_json", is_flag=True)
@pass_app
def config_defaults(app: App, as_json: bool) -> None:
    """Show factory defaults without modifying the saved configuration."""
    _print_settings(app, Config().redacted(), as_json)


@config.command("diff")
@click.option("--json", "as_json", is_flag=True)
@pass_app
def config_diff(app: App, as_json: bool) -> None:
    """Show effective settings that differ from factory defaults; API keys stay redacted."""
    defaults = Config().redacted()
    changed = {key: value for key, value in app.config.redacted().items() if value != defaults[key]}
    _print_settings(app, changed, as_json)
    if not changed and not as_json:
        app.ok("All settings match defaults.")


@config.command("keys")
def config_keys() -> None:
    """List accepted setting names, one per line."""
    click.echo("\n".join(f.name for f in fields(Config)))


@config.command("reset")
@click.argument("key")
@pass_app
def config_reset(app: App, key: str) -> None:
    """Reset one non-secret setting to its factory default."""
    _known_key(key)
    if key == "quote_api_key":
        fail("Manage API keys with `marketpulse provider key` or `marketpulse provider clear`.")
    value = getattr(Config(), key)
    updated = replace(app.config, **{key: value})
    updated.save()
    app.ok(f"Reset {key} = {value!r}.")


@config.command("validate")
@click.option("--json", "as_json", is_flag=True, help="Print diagnostics; exit 1 if the file is invalid.")
@pass_app
def config_validate(app: App, as_json: bool) -> None:
    """Check the raw TOML file, setting names, types and values without writing it."""
    issues: list[dict[str, str]] = []
    path = config_path()
    raw: dict = {}
    try:
        if path.exists():
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        # TOML parser exceptions can include source text holding the API key.
        issues.append({"key": "", "message": "Cannot read configuration as UTF-8 TOML."})
    defaults = Config()
    for key, value in raw.items():
        if key not in {f.name for f in fields(Config)}:
            # Unknown names can contain user data, so do not echo them.
            issues.append({"key": "", "message": "Unknown setting in configuration."})
            continue
        default = getattr(defaults, key)
        if isinstance(default, float):
            valid_type = isinstance(value, int | float) and not isinstance(value, bool)
        elif isinstance(default, list):
            valid_type = isinstance(value, list) and all(isinstance(v, str) for v in value)
        else:
            valid_type = type(value) is type(default)
        error = _setting_error(key, value) if valid_type else "Incorrect value type."
        if error:
            issues.append({"key": key, "message": error})
    if as_json:
        click.echo(json.dumps({"ok": not issues, "issues": issues}, ensure_ascii=False))
    elif issues:
        for issue in issues:
            app.warn(f"{issue['key'] + ': ' if issue['key'] else ''}{issue['message']}")
    else:
        app.ok("Configuration is valid.")
    if issues:
        raise click.exceptions.Exit(1)
