"""MarketPulse command line. Run with no arguments to open the TUI.

`main` is the root Click group; each module below adds one area's commands to it.
"""

from . import (  # noqa: F401  (importing a module registers its commands)
    accounts,
    allocation,
    assets,
    data,
    discovery,
    doctor,
    history,
    native,
    overview,
    positions,
    provider,
    quotes,
    realized,
    recording,
    reports,
    settings,
    snapshots,
    summaries,
    taxes,
    watchlist,
)
from .base import App, fail, pass_app
from .root import main

__all__ = ["App", "fail", "main", "pass_app"]
