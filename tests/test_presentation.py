"""Charts, formatting, themes and config."""

import pytest
from rich.console import Console

from marketpulse import charts, fmt
from marketpulse.config import Config
from marketpulse.themes import (
    OMARCHY_PALETTES,
    distinct_hues,
    omarchy_active,
    palette_from_colors,
    resolve_palette,
    textual_theme,
)


def test_resample_shrinks_and_stretches():
    assert charts.resample([1, 2, 3, 4], 2) == [2, 4]
    assert charts.resample([0, 10], 3) == [0, 5, 10]
    assert charts.resample([None, 5], 3) == [5, 5, 5]
    assert charts.resample([], 3) == []


def test_sparkline_and_bars_have_exact_widths():
    assert len(charts.sparkline([1, 5, 3], 12).plain) == 12
    assert len(charts.sparkline([], 5).plain) == 5
    assert len(charts.hbar(0.33, 10, "x").plain) == 10
    assert len(charts.stacked_bar([(1, "a"), (1, "b"), (1, "c")], 10).plain) == 10
    assert charts.range_bar(0, 10, 10, 5, "x").plain == "────●"


def test_braille_chart_dimensions():
    text = charts.braille_chart(
        [[1, 3, 2, 5, 4]], 40, 6, ["red"], fill_style="blue", baseline=2, marker=0.5, x_labels=("a", "b")
    )
    lines = text.plain.split("\n")
    assert len(lines) == 7
    assert all(len(line) <= 40 for line in lines)
    assert any("⠀" <= ch <= "⣿" for ch in text.plain)
    assert charts.braille_chart([[]], 10, 3, ["red"]).plain == "no data"


def test_column_chart_renders():
    out = charts.column_chart([0, 5, 10], ["a", "b", "c"], 4, "green")
    Console(width=40, record=True).print(out)
    assert out.plain.count("\n") == 4


def test_formatting():
    assert fmt.money(1234.5, "CAD") == "$1,234.50"
    assert fmt.money(-1234.5, "EUR", decimals=0) == "-€1,234"
    assert fmt.money(12, "SEK") == "12.00 SEK"
    assert fmt.money(5, sign=True) == "+5.00"
    assert fmt.money(5, privacy=True) == fmt.MASK
    assert fmt.money(None) == "—"
    assert fmt.compact(412_500, "CAD") == "$412.5K"
    assert fmt.compact(2_300_000_000) == "2.3B"
    assert fmt.pct(1.234) == "+1.23%" and fmt.pct(-1) == "-1.00%" and fmt.pct(None) == "—"
    assert fmt.qty(10.0) == "10" and fmt.qty(0.12345) == "0.1235"
    assert fmt.price(0.01234) == "0.0123"
    assert fmt.arrow(-1) == "▼" and fmt.trend_style(0) == "flat"


def test_every_omarchy_palette_builds_distinct_gain_loss_colors():
    assert len(OMARCHY_PALETTES) >= 20
    for name, colors in OMARCHY_PALETTES.items():
        p = palette_from_colors(name, colors)
        assert distinct_hues(p.up, p.down), name
        assert p.accent.startswith("#")
        textual_theme(p)


def test_monochrome_theme_gets_fallback_colors():
    p = palette_from_colors("hackerman", OMARCHY_PALETTES["hackerman"])
    assert (p.up, p.down) == ("#7ee787", "#ff7b72")


def test_resolve_palette_defaults_and_unknown():
    assert resolve_palette("auto").name == "tokyo-night"
    assert resolve_palette("kanagawa").name == "kanagawa"
    assert resolve_palette("not-a-theme").name == "tokyo-night"


def test_omarchy_active_reads_current_theme(tmp_path):
    current = tmp_path / "current"
    (current / "theme").mkdir(parents=True)
    (current / "theme" / "colors.toml").write_text('mode = "dark"\naccent = "#ff00aa"\nbackground = "#000000"\n')
    (current / "theme.name").write_text("my-theme\n")
    name, colors = omarchy_active((current,))
    assert name == "my-theme" and colors["accent"] == "#ff00aa"
    assert omarchy_active((tmp_path / "missing",)) is None


def test_config_roundtrip_ignores_bad_values(tmp_path):
    path = tmp_path / "c.toml"
    cfg = Config(theme="nord", privacy=True, market_strip=["SPY"], capital_gains_inclusion=0.5)
    cfg.save(path)
    loaded = Config.load(path)
    assert (loaded.theme, loaded.privacy, loaded.market_strip) == ("nord", True, ["SPY"])
    path.write_text('theme = 5\nrefresh_seconds = "fast"\nprivacy = true\nunknown = 1\nbase_currency = "USD"\n')
    loaded = Config.load(path)
    assert (loaded.theme, loaded.refresh_seconds, loaded.privacy, loaded.base_currency) == ("auto", 30, True, "USD")
    path.write_text("not = [valid")
    assert Config.load(path) == Config()


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
def test_hbar_bounds(value):
    assert len(charts.hbar(value, 7, "x").plain) == 7
