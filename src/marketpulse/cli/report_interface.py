"""Offline catalogs of alert conditions, chart periods, the terminal app and the report operations."""

from __future__ import annotations

from typing import Any

from ..market import BARS_PER_YEAR, PERIOD_INTERVALS
from ..models import ALERT_CONDITIONS
from ..tui.constants import GLOBAL_KEYS, HINTS, SORT_MODES, TABLES, WORKSPACE_KEYS
from . import report_operations
from .base import App

GROUP = "reference"
SOURCES: dict[str, tuple[str, ...]] = {
    "alert-conditions": ("value", "description", "percent"),
    "chart-periods": ("period", "interval", "bars_per_year"),
    "tui-keys": ("workspace", "key", "action"),
    "workspaces": ("name", "hint", "table", "sort_modes"),
    "report-operations": ("number", "family", "operation", "commands", "syntax", "summary", "issue"),
}
DESCRIPTIONS: dict[str, str] = {
    "alert-conditions": "Alert conditions and whether their threshold is a percent.",
    "chart-periods": "Chart periods, their bar interval and bars per year.",
    "tui-keys": "Terminal app keys by workspace.",
    "workspaces": "Terminal app workspaces with their hint, table and sort columns.",
    "report-operations": "Every shared report and summary operation, with its syntax and the commands that accept it.",
}

# What each alert condition compares, and whether its threshold is a percent. Looked up by
# key, so a condition added to the engine fails here until it is described.
_CONDITIONS: dict[str, tuple[str, bool]] = {
    "above": ("Price at or above the threshold.", False),
    "below": ("Price at or below the threshold.", False),
    "up_pct": ("Day change at or above the threshold percent.", True),
    "down_pct": ("Day change at or below minus the threshold percent.", True),
}


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    """Read one built-in catalog without opening the tracker, contacting a provider or writing a file."""
    if name == "alert-conditions":
        described = [(condition, *_CONDITIONS[condition]) for condition in ALERT_CONDITIONS]
        return [
            {"value": condition, "description": description, "percent": percent}
            for condition, description, percent in described
        ]
    if name == "chart-periods":
        return [
            {"period": period, "interval": interval, "bars_per_year": BARS_PER_YEAR[interval]}
            for period, interval in PERIOD_INTERVALS.items()
        ]
    if name == "tui-keys":
        bindings = [("global", GLOBAL_KEYS), *((workspace, WORKSPACE_KEYS.get(workspace, [])) for workspace in HINTS)]
        return [
            {"workspace": workspace, "key": key, "action": action}
            for workspace, keys in bindings
            for key, action in keys
        ]
    if name == "workspaces":
        return [
            {
                "name": workspace,
                "hint": hint,
                "table": TABLES.get(workspace),
                "sort_modes": [column for column, _ in SORT_MODES.get(workspace, [])],
            }
            for workspace, hint in HINTS.items()
        ]
    if name == "report-operations":
        return report_operations.rows()
    raise KeyError(name)
