"""Number formatting shared by the CLI, TUI and status payloads."""

from __future__ import annotations

MASK = "••••"

_SYMBOLS = {"CAD": "$", "USD": "$", "AUD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CHF": "₣", "INR": "₹"}


def money(
    value: float | None, currency: str = "", *, privacy: bool = False, decimals: int = 2, sign: bool = False
) -> str:
    if value is None:
        return "—"
    if privacy:
        return MASK
    prefix = "+" if sign and value > 0 else ("-" if value < 0 else "")
    sym = _SYMBOLS.get(currency.upper(), "")
    body = f"{abs(value):,.{decimals}f}"
    suffix = f" {currency.upper()}" if currency and not sym else ""
    return f"{prefix}{sym}{body}{suffix}"


def compact(value: float | None, currency: str = "", *, privacy: bool = False) -> str:
    """$412.5K style for tight spaces (menu bar, tiles)."""
    if value is None:
        return "—"
    if privacy:
        return MASK
    sym = _SYMBOLS.get(currency.upper(), "")
    v = abs(value)
    neg = "-" if value < 0 else ""
    for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= div:
            return f"{neg}{sym}{v / div:,.1f}{unit}"
    return f"{neg}{sym}{v:,.0f}"


def pct(value: float | None, *, sign: bool = True, decimals: int = 2) -> str:
    if value is None:
        return "—"
    prefix = "+" if sign and value > 0 else ""
    return f"{prefix}{value:,.{decimals}f}%"


def price(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:,.2f}"
    return f"{value:,.4f}"


def qty(value: float) -> str:
    text = f"{value:,.4f}".rstrip("0").rstrip(".")
    return text or "0"


def arrow(value: float | None) -> str:
    if value is None or value == 0:
        return "•"
    return "▲" if value > 0 else "▼"


def trend_style(value: float | None) -> str:
    """Rich style name registered by themes.rich_styles."""
    if value is None or abs(value) < 1e-12:
        return "flat"
    return "up" if value > 0 else "down"
