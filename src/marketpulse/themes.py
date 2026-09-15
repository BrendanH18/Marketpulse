"""Omarchy-native theming for the TUI, CLI output and menu bar.

Every Omarchy theme ships a colors.toml; we embed the built-in palettes and,
with theme = "auto", follow whatever theme Omarchy currently has active.
"""

from __future__ import annotations

import colorsys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .themes_data import OMARCHY_PALETTES

DEFAULT_THEME = "tokyo-night"
OMARCHY_CURRENT_DIRS = (
    Path.home() / ".local" / "state" / "omarchy" / "current",
    Path.home() / ".config" / "omarchy" / "current",
)


def pretty_name(slug: str) -> str:
    return slug.replace("-", " ").title()


def theme_names() -> list[str]:
    return sorted(OMARCHY_PALETTES)


def omarchy_active(dirs: tuple[Path, ...] = OMARCHY_CURRENT_DIRS) -> tuple[str, dict[str, str]] | None:
    """The active Omarchy theme (slug, colors) if this machine runs Omarchy."""
    for base in dirs:
        colors = base / "theme" / "colors.toml"
        if not colors.is_file():
            continue
        try:
            data = tomllib.loads(colors.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            continue
        name_file = base / "theme.name"
        name = name_file.read_text().strip() if name_file.is_file() else "omarchy"
        return name, {k: v for k, v in data.items() if isinstance(v, str)}
    return None


@dataclass(frozen=True)
class Palette:
    name: str
    dark: bool
    background: str
    surface: str
    panel: str
    selection: str
    border: str
    foreground: str
    bright: str
    muted: str
    accent: str
    up: str
    down: str
    warn: str
    info: str
    series: tuple[str, ...]


def _hls(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    return hue * 360, light, sat


def distinct_hues(a: str, b: str, min_degrees: float = 60, min_saturation: float = 0.25) -> bool:
    ha, _, sa = _hls(a)
    hb, _, sb = _hls(b)
    diff = abs(ha - hb)
    return min(diff, 360 - diff) >= min_degrees and sa >= min_saturation and sb >= min_saturation


def palette_from_colors(name: str, c: dict[str, str]) -> Palette:
    dark = c.get("mode", "dark") != "light"

    def g(key: str, default: str) -> str:
        value = c.get(key)
        return value if isinstance(value, str) and value.startswith("#") and len(value) == 7 else default

    fallback_fg = "#c0caf5" if dark else "#1f2328"
    bg = g("background", "#1a1b26" if dark else "#ffffff")
    fg = g("foreground", fallback_fg)
    up, down = g("green", "#9ece6a"), g("red", "#f7768e")
    # Monochrome or single-hue themes (hackerman, vantablack, white, lumon…)
    # can't tell gains from losses; substitute a legible universal pair.
    if not distinct_hues(up, down):
        up, down = ("#7ee787", "#ff7b72") if dark else ("#1a7f37", "#cf222e")
    accent = g("accent", g("blue", fg))
    series = tuple(
        dict.fromkeys(
            x
            for x in (accent, c.get("magenta"), c.get("cyan"), c.get("yellow"), c.get("orange"), c.get("blue"))
            if isinstance(x, str) and x.startswith("#")
        )
    )
    return Palette(
        name=name,
        dark=dark,
        background=bg,
        surface=g("dark_background", bg),
        panel=g("lighter_background", bg),
        selection=g("selection", g("lighter_background", bg)),
        border=g("muted", g("dark_foreground", fg)),
        foreground=fg,
        bright=g("bright_foreground", fg),
        muted=g("dark_foreground", g("muted", fg)),
        accent=accent,
        up=up,
        down=down,
        warn=g("yellow", "#e0af68"),
        info=g("cyan", accent),
        series=series or (accent,),
    )


def resolve_palette(name: str = "auto") -> Palette:
    if name in ("auto", "omarchy", ""):
        active = omarchy_active()
        if active is not None:
            return palette_from_colors(*active)
        name = DEFAULT_THEME
    if name not in OMARCHY_PALETTES:
        name = DEFAULT_THEME
    return palette_from_colors(name, OMARCHY_PALETTES[name])


def rich_styles(p: Palette) -> dict[str, str]:
    return {
        "up": p.up,
        "down": p.down,
        "flat": p.muted,
        "accent": p.accent,
        "muted": p.muted,
        "warn": p.warn,
        "info": p.info,
        "bright": f"bold {p.bright}",
        "border": p.border,
        "title": f"bold {p.accent}",
    }


def textual_theme(p: Palette):
    from textual.theme import Theme

    return Theme(
        name=p.name,
        primary=p.accent,
        secondary=p.info,
        accent=p.accent,
        warning=p.warn,
        error=p.down,
        success=p.up,
        foreground=p.foreground,
        background=p.background,
        surface=p.background,
        panel=p.panel,
        dark=p.dark,
        variables={
            "mp-up": p.up,
            "mp-down": p.down,
            "mp-muted": p.muted,
            "mp-border": p.border,
            "mp-selection": p.selection,
            "mp-bright": p.bright,
            "mp-panel": p.panel,
            "mp-surface": p.surface,
            "block-cursor-background": p.selection,
            "block-cursor-foreground": p.bright,
            "block-cursor-text-style": "bold",
            "block-cursor-blurred-background": p.selection,
            "block-cursor-blurred-foreground": p.foreground,
            "footer-background": p.background,
            "footer-key-foreground": p.accent,
            "footer-description-foreground": p.muted,
            "input-selection-background": p.selection,
            "scrollbar": p.border,
            "scrollbar-hover": p.accent,
            "scrollbar-active": p.accent,
            "scrollbar-background": p.background,
            "border": p.accent,
            "border-blurred": p.border,
        },
    )
