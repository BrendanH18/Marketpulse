"""The Mac app's portfolio palette stays legible in light and dark appearance (WCAG 2 contrast)."""

import re
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parents[1] / "macos/MarketPulseBar/Sources/MarketPulseBar/Studio.swift"
PAIR = re.compile(r'(?:static let (\w+) = )?Color\(light: "(#[0-9a-f]{6})", dark: "(#[0-9a-f]{6})"\)')


def palette() -> tuple[dict[str, tuple[str, str]], list[tuple[str, str]]]:
    named: dict[str, tuple[str, str]] = {}
    charts: list[tuple[str, str]] = []
    for name, light, dark in PAIR.findall(STUDIO.read_text()):
        if name:
            named[name] = (light, dark)
        else:
            charts.append((light, dark))
    return named, charts


def luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("mode", [0, 1], ids=["light", "dark"])
@pytest.mark.parametrize("surface", ["background", "panel"])
@pytest.mark.parametrize("ink", ["text", "muted", "mint", "red", "warn"])
def test_text_colours_meet_aa_on_every_surface(mode, surface, ink):
    named, _ = palette()
    ratio = contrast(named[ink][mode], named[surface][mode])
    assert ratio >= 4.5, f"{ink} on {surface}: {ratio:.2f}:1"


@pytest.mark.parametrize("mode", [0, 1], ids=["light", "dark"])
def test_chart_colours_stand_out_from_panels(mode):
    named, charts = palette()
    assert len(charts) == 4  # plus mint, which the text test already covers
    for colour in charts:
        assert contrast(colour[mode], named["panel"][mode]) >= 3, colour


@pytest.mark.parametrize("mode", [0, 1], ids=["light", "dark"])
def test_filled_buttons_carry_white_labels(mode):
    # Prominent buttons draw white text on their fill in both appearances.
    named, _ = palette()
    assert contrast(named["fill"][mode], "#ffffff") >= 4.5


def tint(colour: str, surface: str, alpha: float) -> str:
    """`colour.opacity(alpha)` drawn over `surface`."""
    mixed = (round(alpha * int(colour[i : i + 2], 16) + (1 - alpha) * int(surface[i : i + 2], 16)) for i in (1, 3, 5))
    return "#" + "".join(f"{c:02x}" for c in mixed)


@pytest.mark.parametrize("mode", [0, 1], ids=["light", "dark"])
@pytest.mark.parametrize("surface", ["background", "panel"])
@pytest.mark.parametrize("ink", ["mint", "red", "warn"])
def test_banners_stay_legible_on_their_own_tint(mode, surface, ink):
    # Notices and banners draw a colour's text on up to 10% of the same colour (`notice` in
    # DesktopViews.swift), and the dismissible message draws text and muted text on mint.
    named, _ = palette()
    banner = tint(named[ink][mode], named[surface][mode], 0.1)
    for fg in (ink, "text", "muted"):
        ratio = contrast(named[fg][mode], banner)
        assert ratio >= 4.5, f"{fg} on {ink} tint over {surface}: {ratio:.2f}:1"
