"""Offline catalog adapters for the composable report command."""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any

from ..config import Config
from ..models import AccountType, AssetClass, AssetKind, TxnType
from ..themes import OMARCHY_PALETTES, palette_from_colors, pretty_name
from .base import App
from .discovery import _catalog
from .root import main

SOURCES: dict[str, tuple[str, ...]] = {
    "config": ("key", "value"),
    "config-defaults": ("key", "value"),
    "config-diff": ("key", "value"),
    "config-keys": ("key", "type"),
    "themes": ("name", "label", "mode"),
    "commands": ("command", "group", "depth", "help", "parameters"),
    "providers": ("name", "label", "role", "configured", "ok", "last_attempt", "last_success", "last_error", "quotes"),
    "account-types": ("value", "label", "registered"),
    "transaction-types": ("value", "needs_symbol", "uses_quantity", "uses_amount"),
    "asset-kinds": ("value", "label"),
    "asset-classes": ("value", "label"),
    "compounding": ("value", "periods_per_year"),
}


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    """Read one named catalog, retaining native JSON values and redacting API keys.

    Catalogs do not open the tracker, except provider status, which reads the last
    saved attempt without making a quote request. No catalog saves configuration.
    """
    if name in ("config", "config-defaults", "config-diff"):
        defaults = Config().redacted()
        values = defaults if name == "config-defaults" else app.config.redacted()
        return [
            {"key": key, "value": value}
            for key, value in values.items()
            if name != "config-diff" or value != defaults[key]
        ]
    if name == "config-keys":
        defaults_config = Config()
        return [{"key": f.name, "type": type(getattr(defaults_config, f.name)).__name__} for f in fields(Config)]
    if name == "themes":
        return [
            {
                "name": slug,
                "label": pretty_name(slug),
                "mode": "dark" if palette_from_colors(slug, colors).dark else "light",
            }
            for slug, colors in sorted(OMARCHY_PALETTES.items())
        ]
    if name == "commands":
        return _catalog(main)
    if name == "providers":
        return [asdict(status) for status in app.tracker.market.provider_status()]
    if name == "account-types":
        return [{"value": item.value, "label": item.label, "registered": item.registered} for item in AccountType]
    if name == "transaction-types":
        return [
            {
                "value": item.value,
                "needs_symbol": item.needs_symbol,
                "uses_quantity": item.uses_quantity,
                "uses_amount": item.uses_amount,
            }
            for item in TxnType
        ]
    if name == "asset-kinds":
        return [{"value": item.value, "label": item.value.replace("_", " ").title()} for item in AssetKind]
    if name == "asset-classes":
        return [{"value": item.value, "label": item.label} for item in AssetClass]
    if name == "compounding":
        return [
            {"value": value, "periods_per_year": periods}
            for value, periods in (
                ("annual", 1),
                ("semiannual", 2),
                ("quarterly", 4),
                ("monthly", 12),
                ("simple", None),
            )
        ]
    raise ValueError(f"Unknown report catalog: {name}")
