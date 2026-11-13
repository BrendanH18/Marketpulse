"""Offline reference catalogs for the composable report command; none opens the tracker."""

from __future__ import annotations

from typing import Any

from ..brokers import _ALIASES, PROFILES
from ..config import DEFAULT_MARKET_STRIP
from ..ledger import TFSA_LIMITS
from ..models import _INSTRUMENT_CLASSES, _SUFFIX_CURRENCIES
from ..themes import OMARCHY_PALETTES, palette_from_colors
from . import report_derive, report_metrics
from .base import App

GROUP = "reference"
SOURCES: dict[str, tuple[str, ...]] = {
    "sources": ("source", "group", "fields", "field_count", "description"),
    "summary-operations": ("position", "operation", "takes_field", "result"),
    "derive-functions": ("position", "function", "family", "argument", "result", "description"),
    "broker-profiles": ("name", "label", "required_headers", "has_accounts", "limits"),
    "import-aliases": ("field", "position", "alias"),
    "import-type-keywords": ("position", "keyword", "type"),
    "exchange-suffixes": ("suffix", "currency"),
    "instrument-classes": ("instrument_type", "asset_class", "label"),
    "tfsa-limits": ("year", "limit"),
    "theme-colors": ("theme", "role", "color"),
    "market-strip": ("position", "symbol", "label", "default"),
}
DESCRIPTIONS: dict[str, str] = {
    "sources": "Every report dataset with its group, fields and description.",
    "summary-operations": "Summary operations accepted by summarize --metric.",
    "derive-functions": "Derived-field functions accepted by --derive.",
    "broker-profiles": "CSV import profiles and the headers that identify them.",
    "import-aliases": "CSV header names accepted for each import field.",
    "import-type-keywords": "Words that map generic CSV rows to transaction types, in matching order.",
    "exchange-suffixes": "Symbol suffixes and the trading currency assumed for each.",
    "instrument-classes": "Quote instrument types and the asset class assigned to each.",
    "tfsa-limits": "Annual TFSA dollar limits used for contribution room.",
    "theme-colors": "Palette colors of every embedded theme.",
    "market-strip": "Configured market strip symbols and their labels.",
}

# How each summary operation's result is written in JSON (docs/cli-report-summaries.md): "decimal"
# is a decimal string and "value" keeps the cell's own type. A new operation needs a line here;
# `summary-operations` raises KeyError for one that has none rather than guess.
_OPERATION_RESULTS = {
    "count": "integer",
    "present": "integer",
    "missing": "integer",
    "empty": "integer",
    "nonempty": "integer",
    "distinct": "integer",
    "duplicates": "integer",
    "first": "value",
    "last": "value",
    "first-present": "value",
    "last-present": "value",
    "mode": "value",
    "mode-count": "integer",
    "values": "list",
    "distinct-values": "list",
    "number-count": "integer",
    "number-distinct": "integer",
    "number-sum": "decimal",
    "number-min": "decimal",
    "number-max": "decimal",
    "number-mean": "decimal",
    "number-median": "decimal",
    "number-range": "decimal",
    "positive-count": "integer",
    "negative-count": "integer",
    "zero-count": "integer",
    "positive-sum": "decimal",
    "negative-sum": "decimal",
    "absolute-sum": "decimal",
    "true-count": "integer",
    "false-count": "integer",
    "string-count": "integer",
    "array-count": "integer",
    "object-count": "integer",
    "length-sum": "integer",
    "length-min": "integer",
    "length-max": "integer",
    "length-mean": "decimal",
    "text-min": "string",
    "text-max": "string",
    "date-min": "string",
    "date-max": "string",
    "date-count": "integer",
    "date-span": "integer",
    "number-variance": "decimal",
    "number-stdev": "decimal",
    "number-q1": "decimal",
    "number-q3": "decimal",
    "value-counts": "list",
    "repeated-values": "list",
}

# The single colors of a palette, in display order; its name, mode and chart series are left out.
_PALETTE_ROLES = (
    "background",
    "surface",
    "panel",
    "selection",
    "border",
    "foreground",
    "bright",
    "muted",
    "accent",
    "up",
    "down",
    "warn",
    "info",
)


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    """Read one reference catalog, retaining native JSON values.

    These catalogs describe the program rather than a portfolio: none opens the tracker,
    reads saved data, uses the network or writes anything. Only `market-strip` reads settings.
    """
    if name == "sources":
        from . import reports  # imported here because reports imports this module to register it

        return sorted(
            (
                {
                    "source": source,
                    "group": module.GROUP,
                    "fields": list(schema),
                    "field_count": len(schema),
                    "description": module.DESCRIPTIONS[source],
                }
                for module in reports.SOURCE_MODULES
                for source, schema in module.SOURCES.items()
            ),
            key=lambda row: row["source"],
        )
    if name == "summary-operations":
        return [
            {
                "position": position,
                "operation": operation,
                "takes_field": operation != "count",
                "result": _OPERATION_RESULTS[operation],
            }
            for position, operation in enumerate(report_metrics.ALL_OPERATIONS, 1)
        ]
    if name == "derive-functions":
        return [
            {
                "position": position,
                "function": function.name,
                "family": function.family,
                "argument": function.argument,
                "result": function.result,
                "description": function.description,
            }
            for position, function in enumerate(report_derive.FUNCTIONS, 1)
        ]
    if name == "broker-profiles":
        return [
            {
                "name": profile.name,
                "label": profile.label,
                "required_headers": sorted(profile.headers),
                # The generic profile decides per file, by whether an account column is present.
                "has_accounts": profile.has_accounts if profile.convert is not None else None,
                "limits": profile.limits,
            }
            for profile in PROFILES
        ]
    if name == "import-aliases":
        return [
            {"field": field, "position": position, "alias": alias}
            for field, aliases in _ALIASES.items()
            for position, alias in enumerate(aliases, 1)
        ]
    if name == "import-type-keywords":
        from ..csvio import _TYPE_KEYWORDS  # imported here so starting the CLI does not load the importer

        matching_order = [(keyword, txn_type) for keywords, txn_type in _TYPE_KEYWORDS for keyword in keywords]
        return [
            {"position": position, "keyword": keyword, "type": txn_type.value}
            for position, (keyword, txn_type) in enumerate(matching_order, 1)
        ]
    if name == "exchange-suffixes":
        return [{"suffix": suffix, "currency": currency} for suffix, currency in _SUFFIX_CURRENCIES.items()]
    if name == "instrument-classes":
        return [
            {"instrument_type": instrument_type, "asset_class": asset_class.value, "label": asset_class.label}
            for instrument_type, asset_class in _INSTRUMENT_CLASSES.items()
        ]
    if name == "tfsa-limits":
        return [{"year": year, "limit": limit} for year, limit in sorted(TFSA_LIMITS.items())]
    if name == "theme-colors":
        palettes = {slug: palette_from_colors(slug, colors) for slug, colors in sorted(OMARCHY_PALETTES.items())}
        return [
            {"theme": slug, "role": role, "color": getattr(palette, role)}
            for slug, palette in palettes.items()
            for role in _PALETTE_ROLES
        ]
    if name == "market-strip":
        from ..services import STRIP_LABELS  # imported here so starting the CLI does not load the tracker

        # Symbols are reported as configured; the dashboard strip looks its labels up in upper case.
        return [
            {
                "position": position,
                "symbol": symbol,
                "label": STRIP_LABELS.get(symbol.upper(), symbol.upper()),
                "default": symbol.upper() in DEFAULT_MARKET_STRIP,
            }
            for position, symbol in enumerate(app.config.market_strip, 1)
        ]
    raise KeyError(name)
