"""Price alerts and desktop notifications."""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime

from .models import Alert, Quote


def evaluate(alerts: list[Alert], quotes: dict[str, Quote], now: str | None = None) -> tuple[list[Alert], list[Alert]]:
    """Return (fired, changed). An alert fires once when its condition
    becomes true and re-arms after the condition is false again. Stale
    (offline-cache) quotes never fire alerts."""
    now = now or datetime.now().isoformat(timespec="seconds")
    fired, changed = [], []
    for alert in alerts:
        if not alert.active:
            continue
        q = quotes.get(alert.symbol)
        if q is None or q.stale:
            continue
        met = alert.is_met(q)
        if met and not alert.triggered_at:
            alert.triggered_at = now
            fired.append(alert)
            changed.append(alert)
        elif not met and alert.triggered_at:
            alert.triggered_at = ""
            changed.append(alert)
    return fired, changed


def _applescript_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title: str, message: str, subtitle: str = "") -> bool:
    """Best-effort desktop notification (macOS Notification Center or notify-send)."""
    try:
        if sys.platform == "darwin":
            script = f"display notification {_applescript_string(message)} with title {_applescript_string(title)}"
            if subtitle:
                script += f" subtitle {_applescript_string(subtitle)}"
            script += ' sound name "Glass"'
            subprocess.run(["osascript", "-e", script], check=False, capture_output=True, timeout=5)
            return True
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", title, f"{subtitle}\n{message}".strip()], check=False, timeout=5)
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    return False
