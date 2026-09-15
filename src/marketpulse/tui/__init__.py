"""Textual TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config


def run(config: Config) -> None:
    from .app import MarketPulseApp

    MarketPulseApp(config).run()
