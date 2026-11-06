"""`marketpulse doctor`: check the installation, data, network and integrations."""

from __future__ import annotations

import platform
import shutil
import sys
import time

from rich.text import Text

from .. import __version__
from ..config import config_path
from ..market import PRIMARY
from ..providers import provider_label
from ..themes import omarchy_active, pretty_name
from .base import App, pass_app
from .root import main


@main.command()
@pass_app
def doctor(app: App) -> None:
    """Check the installation, data, network and integrations."""
    from ..menubar import app_path, cli_path

    c = app.console

    def row(label: str, value: str, ok: bool | None = True) -> None:
        mark = (
            Text("✓ ", style="up") if ok else (Text("✗ ", style="down") if ok is False else Text("• ", style="muted"))
        )
        c.print(mark + Text(f"{label:<18}", style="muted") + Text(value))

    row(
        "version",
        f"MarketPulse {__version__} · Python {platform.python_version()} · {platform.system()} {platform.release()}",
        None,
    )
    row("config", str(config_path()), config_path().exists() or None)
    tr = app.tracker
    row("database", f"{tr.store.path} (schema v{tr.store.schema_version})")
    newest = next(iter(tr.store.backups()), None)
    if newest is None:
        row("backups", "none yet — `marketpulse backup`", None)
    else:
        age_days = (time.time() - newest.stat().st_mtime) / 86400
        # Daily backups keep this under a day; a week means they're failing (full disk, permissions…).
        row("backups", f"{len(tr.store.backups())} · newest {newest.name}", age_days < 7)
    row(
        "ledger",
        f"{len(tr.store.accounts())} accounts · {len(tr.store.transactions())} transactions"
        f" · {len(tr.store.snapshots())} snapshots",
        None,
    )
    issues = tr.store.ledger().issues
    row("ledger checks", f"{len(issues)} issue(s)" if issues else "consistent", not issues)
    t0 = time.perf_counter()
    quotes, errors = tr.market.quotes(["SPY"], use_cache=False)
    spy = quotes.get("SPY")
    if spy is not None and not spy.stale and spy.source == PRIMARY:
        row("market data", f"Yahoo reachable ({(time.perf_counter() - t0) * 1000:.0f} ms)")
    else:
        # `quotes` doesn't raise when Yahoo is down: it falls back, then serves cached prices.
        yahoo = tr.market.provider_status()[0]
        row("market data", f"Yahoo unreachable: {yahoo.last_error or errors.get('SPY', 'no data')}", False)
    fallback = tr.market.fallback
    if fallback is not None:
        st = tr.market.provider_status()[-1]
        state = "not used yet" if st.ok is None else ("ok" if st.ok else f"failing: {st.last_error}")
        row("fallback quotes", f"{fallback.label} ({state})", st.ok)
    elif app.config.quote_provider:
        row("fallback quotes", f"{provider_label(app.config.quote_provider)}: no key set", False)
    active = omarchy_active()
    row(
        "theme",
        f"{app.config.theme} → {pretty_name(app.palette.name)}" + (" (Omarchy detected)" if active else ""),
        None,
    )
    row("cli path", cli_path(), None)
    if sys.platform == "darwin":
        row("swift", shutil.which("swift") or "not found (xcode-select --install)", bool(shutil.which("swift")))
        row(
            "menu bar app",
            str(app_path()) if app_path().exists() else "not installed — `marketpulse menubar install`",
            app_path().exists() or None,
        )
