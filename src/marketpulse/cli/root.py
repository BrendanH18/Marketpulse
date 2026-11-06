"""The root `marketpulse` group and the TUI it opens by default."""

from __future__ import annotations

from dataclasses import replace

import click

from .. import __version__
from .base import App, pass_app, theme_slug


@click.group(
    invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 110}
)
@click.version_option(__version__, "-V", "--version", prog_name="MarketPulse")
@click.pass_context
def main(ctx: click.Context) -> None:
    """⚡ MarketPulse — a fast, keyboard-first investment tracker.

    \b
    Run with no command to open the TUI.
    \b
      marketpulse buy XEQT.TO 20            buy at the live price
      marketpulse sell AAPL 5 230 -a TFSA   sell at a price, in an account
      marketpulse dividend VFV.TO 42.10     record income
      marketpulse holdings                  priced holdings
      marketpulse chart NVDA -p 1y --vs QQQ braille chart with comparison
      marketpulse status --waybar           for Omarchy's Waybar
      marketpulse menubar install           macOS menu bar companion
    """
    ctx.ensure_object(App)
    if ctx.invoked_subcommand is None:
        ctx.invoke(tui)


@main.command()
@click.option("-r", "--refresh", type=int, default=None, help="Quote refresh interval in seconds.")
@click.option("-t", "--theme", default=None, help="Theme for this session (see `marketpulse theme`).")
@pass_app
def tui(app: App, refresh: int | None, theme: str | None) -> None:
    """Open the interactive TUI (default command)."""
    from ..tui import run

    cfg = app.config
    if refresh is not None:
        cfg = replace(cfg, refresh_seconds=max(refresh, 5))
    if theme:
        cfg = replace(cfg, theme=theme_slug(theme))
    run(cfg)
