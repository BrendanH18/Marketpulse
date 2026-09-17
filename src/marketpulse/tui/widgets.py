"""Custom widgets: Waybar-style top bar, big-digit tiles, sized canvases and the chart."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.text import Text
from textual.binding import Binding
from textual.containers import Vertical
from textual.widget import Widget

from .. import fmt, render
from ..models import Bar, Quote

if TYPE_CHECKING:
    from ..themes import Palette

WORKSPACES: list[tuple[str, str]] = [
    ("dashboard", "dash"),
    ("holdings", "holdings"),
    ("watchlist", "watch"),
    ("chart", "chart"),
    ("activity", "activity"),
    ("income", "income"),
    ("tax", "accounts"),
    ("alerts", "alerts"),
]

# 3x3 box-drawing glyphs for the big net-worth readout
_BIG = {
    "0": ("┏━┓", "┃ ┃", "┗━┛"),
    "1": (" ┓ ", " ┃ ", " ┻ "),
    "2": ("┏━┓", "┏━┛", "┗━╸"),
    "3": ("┏━┓", " ━┫", "┗━┛"),
    "4": ("╻ ╻", "┗━┫", "  ╹"),
    "5": ("┏━╸", "┗━┓", "┗━┛"),
    "6": ("┏━╸", "┣━┓", "┗━┛"),
    "7": ("┏━┓", "  ┃", "  ╹"),
    "8": ("┏━┓", "┣━┫", "┗━┛"),
    "9": ("┏━┓", "┗━┫", "┗━┛"),
    "$": ("┏╋┓", "┗╋┓", "┗╋┛"),
    "-": ("   ", "╺━╸", "   "),
    "+": ("   ", "╺╋╸", "   "),
    ",": (" ", " ", "╻"),
    ".": (" ", " ", "•"),
    "•": ("   ", " • ", "   "),
    " ": (" ", " ", " "),
}


def big_width(s: str) -> int:
    return sum(len(_BIG[c][0]) + 1 if c in _BIG else len(c) for c in s)


def big_text(s: str, style: str) -> Text:
    """Render digits/$ , . in a 3-row box-drawing font; unknown chars go on the middle row."""
    rows = [Text(), Text(), Text()]
    for ch in s:
        glyph = _BIG.get(ch)
        if glyph is None:
            rows[0].append(" " * len(ch))
            rows[1].append(ch, style=style)
            rows[2].append(" " * len(ch))
            continue
        for i in range(3):
            rows[i].append(glyph[i] + " ", style=style)
    return Text("\n").join(rows)


class Canvas(Widget):
    """Renders whatever its builder returns for the widget's current size,
    so charts reflow on resize without explicit plumbing."""

    DEFAULT_CSS = "Canvas { height: 1fr; }"

    def __init__(self, builder: Callable[[int, int], RenderableType] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.builder = builder

    def set_builder(self, builder: Callable[[int, int], RenderableType] | None) -> None:
        self.builder = builder
        self.refresh()

    def render(self) -> RenderableType:
        if self.builder is None or self.size.width <= 0:
            return ""
        return self.builder(self.size.width, self.size.height)


class Tile(Canvas):
    DEFAULT_CSS = """
    Tile { width: 1fr; height: 100%; border: solid $mp-border; padding: 0 1; }
    """


def pane(*children: Widget, title: str, id: str | None = None, classes: str = "") -> Vertical:
    container = Vertical(*children, id=id, classes=f"pane {classes}".strip())
    container.border_title = title
    return container


class TopBar(Widget):
    """Waybar-inspired status line: workspaces left, clock center, portfolio right."""

    DEFAULT_CSS = "TopBar { dock: top; height: 1; }"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.active = "dashboard"
        self.status = Text()
        self.loading = False

    def render(self) -> RenderableType:
        p: Palette = self.app.palette  # type: ignore[attr-defined]
        width = self.size.width
        left = Text()
        left.append(" ◆ marketpulse ", style=f"bold {p.background} on {p.accent}")
        left.append(" ")
        for i, (key, label) in enumerate(WORKSPACES, 1):
            if key == self.active:
                left.append(f" {i} {label} ", style=f"bold {p.accent} on {p.panel}")
            else:
                left.append(f" {i} ", style=p.muted)
        center = Text(datetime.now().strftime("%a %d %b  %H:%M:%S"), style=p.foreground)
        right = self.status.copy()
        if self.loading:
            right.append("  ⟳", style=p.accent)
        right.append(" ")
        gap_total = width - left.cell_len - center.cell_len - right.cell_len
        if gap_total < 2:
            center = Text("")
            gap_total = width - left.cell_len - right.cell_len
        left_gap = max(gap_total // 2, 1)
        right_gap = max(gap_total - left_gap, 1)
        line = Text()
        line.append_text(left)
        line.append(" " * left_gap)
        line.append_text(center)
        line.append(" " * right_gap)
        line.append_text(right)
        line.truncate(width)
        return line


class ChartView(Widget, can_focus=True):
    """Interactive braille chart: ←/→ move a crosshair, shift for bigger steps."""

    DEFAULT_CSS = "ChartView { height: 1fr; }"
    BINDINGS = [
        Binding("left,h", "move(-1)", "◀", show=False),
        Binding("right,l", "move(1)", "▶", show=False),
        Binding("shift+left,H", "move(-10)", show=False),
        Binding("shift+right,L", "move(10)", show=False),
        Binding("home", "jump(0)", show=False),
        Binding("end", "jump(-1)", show=False),
        Binding("escape", "clear_marker", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.symbol = ""
        self.period = "3mo"
        self.bars: list[Bar] = []
        self.compare: dict[str, list[Bar]] = {}
        self.quote: Quote | None = None
        self.marker: int | None = None
        self.message = "Type a symbol above, or press / to search."

    def set_data(
        self, symbol: str, period: str, bars: list[Bar], quote: Quote | None, compare: dict[str, list[Bar]]
    ) -> None:
        self.symbol, self.period, self.bars, self.quote, self.compare = symbol, period, bars, quote, compare
        if self.marker is not None and self.marker >= len(bars):
            self.marker = None
        self.refresh()

    def set_message(self, message: str) -> None:
        self.message = message
        self.bars = []
        self.refresh()

    def render(self) -> RenderableType:
        if not self.bars:
            return Text(self.message, style="muted")
        width, height = self.size.width, self.size.height
        n = len(self.bars)
        position = None if self.marker is None or n < 2 else self.marker / (n - 1)
        chart_height = max(height - (4 if position is not None else 3), 4)
        chart = render.price_chart(
            self.symbol,
            self.bars,
            self.period,
            self.app.palette,  # type: ignore[attr-defined]
            width=width,
            height=chart_height,
            quote=self.quote,
            compare=self.compare or None,
            marker=position,
        )
        if position is None:
            return chart
        return Group(render.crosshair_text(self.bars, position, self.period), chart)

    def action_move(self, delta: int) -> None:
        if not self.bars:
            return
        n = len(self.bars)
        if self.marker is None:
            self.marker = n - 1 if delta < 0 else 0
        else:
            self.marker = max(0, min(n - 1, self.marker + delta))
        self.refresh()

    def action_jump(self, index: int) -> None:
        if self.bars:
            self.marker = index % len(self.bars)
            self.refresh()

    def action_clear_marker(self) -> None:
        self.marker = None
        self.refresh()


def tile_content(label: str, value: Text, sub: Text | None, width: int) -> RenderableType:
    head = Text(label.upper(), style="muted")
    parts: list[RenderableType] = [head, value]
    if sub is not None:
        parts.append(sub)
    del width
    return Group(*parts)


def money_tile(label: str, amount: float, currency: str, sub: Text | None, *, privacy: bool, style: str = "bright"):
    """Tile builder that uses the big font when there's room."""

    def build(width: int, height: int) -> RenderableType:
        inner = width - 2
        full = fmt.money(amount, currency, privacy=privacy, decimals=0)
        compact = fmt.compact(amount, currency, privacy=privacy)
        head = Text(label.upper(), style="muted")
        if height >= 5:
            for candidate in (full, compact):
                if big_width(candidate) <= inner:
                    return Group(head, big_text(candidate, style), *([sub] if sub is not None else []))
        return Group(
            head, Text(full if len(full) <= inner else compact, style=f"bold {style}"), *([sub] if sub else [])
        )

    return build
