"""Pure-text charts: braille line charts, sparklines, bars. No dependencies beyond rich."""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text

SPARK = "▁▂▃▄▅▆▇█"
# Braille dot bits indexed [row][col] within a 2x4 cell
_BRAILLE_BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))


def resample(values: Sequence[float | None], n: int) -> list[float]:
    """Fit a series to exactly n points: last-value buckets when shrinking,
    linear interpolation when stretching."""
    vals = [float(v) for v in values if v is not None]
    if not vals or n <= 0:
        return []
    m = len(vals)
    if m == n:
        return vals
    if m == 1:
        return vals * n
    if m > n:
        return [vals[min(m - 1, round((i + 1) * m / n) - 1)] for i in range(n)]
    out = []
    for i in range(n):
        x = i * (m - 1) / (n - 1) if n > 1 else 0.0
        lo = int(x)
        hi = min(lo + 1, m - 1)
        f = x - lo
        out.append(vals[lo] * (1 - f) + vals[hi] * f)
    return out


def sparkline(values: Sequence[float | None], width: int, style: str = "") -> Text:
    vals = resample(values, width)
    if not vals:
        return Text("·" * width, style="dim")
    lo, hi = min(vals), max(vals)
    span = hi - lo
    chars = "".join(SPARK[3] if span == 0 else SPARK[round((v - lo) / span * 7)] for v in vals)
    return Text(chars, style=style)


def braille_chart(
    series: Sequence[Sequence[float | None]],
    width: int,
    height: int,
    styles: Sequence[str],
    *,
    fill_style: str | None = None,
    baseline: float | None = None,
    label_format: str = "{:,.2f}",
    axis_style: str = "dim",
    marker: float | None = None,
    marker_style: str = "reverse",
    x_labels: tuple[str, str] | None = None,
) -> Text:
    """Multi-series line chart drawn with braille dots (2x4 sub-cell resolution).

    series[0] is the primary line and draws on top. `marker` is a 0..1 x
    position for a crosshair column. `baseline` draws a dotted reference line
    (e.g. previous close).
    """
    height = max(height, 3)
    finite = [float(v) for s in series for v in s if v is not None]
    if not finite:
        return Text("no data", style=axis_style)
    lo, hi = min(finite), max(finite)
    if baseline is not None:
        lo, hi = min(lo, baseline), max(hi, baseline)
    if hi == lo:
        pad = abs(hi) * 0.01 or 1.0
        lo, hi = lo - pad, hi + pad
    pad = (hi - lo) * 0.06
    lo, hi = lo - pad, hi + pad

    labels = [label_format.format(hi - (hi - lo) * r / (height - 1)) for r in range(height)]
    gutter = max(len(x) for x in labels) + 2
    plot_w = max(width - gutter, 4)
    dots_w, dots_h = plot_w * 2, height * 4

    line = [[0] * plot_w for _ in range(height)]
    owner = [[0] * plot_w for _ in range(height)]
    fill = [[0] * plot_w for _ in range(height)]

    def y_of(v: float) -> int:
        return max(0, min(dots_h - 1, round((hi - v) / (hi - lo) * (dots_h - 1))))

    for idx in reversed(range(len(series))):
        pts = resample(series[idx], dots_w)
        if not pts:
            continue
        ys = [y_of(v) for v in pts]
        prev = ys[0]
        for x, y in enumerate(ys):
            a, b = (prev, y) if prev <= y else (y, prev)
            # join to the previous point through its midpoint so steep moves stay continuous
            if x:
                a = min(a, (prev + y) // 2) if prev < y else a
            for yy in range(a, b + 1):
                cy, cx = yy // 4, x // 2
                line[cy][cx] |= _BRAILLE_BITS[yy % 4][x % 2]
                owner[cy][cx] = idx
            if idx == 0 and fill_style and x % 2 == 0:
                # hatch the area under the primary line with the left dot column only
                for yy in range(y + 1, dots_h):
                    fill[yy // 4][x // 2] |= _BRAILLE_BITS[yy % 4][x % 2]
            prev = y

    base_row = None if baseline is None else y_of(baseline) // 4
    marker_col = None if marker is None else max(0, min(plot_w - 1, round(marker * (plot_w - 1))))
    label_rows = {0, height // 2, height - 1}

    out = Text()
    for r in range(height):
        if r:
            out.append("\n")
        label = labels[r] if r in label_rows else ""
        out.append(f"{label:>{gutter - 2}} ", style=axis_style)
        out.append("┤" if r in label_rows else "│", style=axis_style)
        run_chars: list[str] = []
        run_style: str | None = None
        for c in range(plot_w):
            if line[r][c]:
                ch, st = chr(0x2800 | line[r][c]), styles[owner[r][c] % len(styles)]
            elif fill[r][c]:
                ch, st = chr(0x2800 | fill[r][c]), fill_style
            elif r == base_row:
                ch, st = ("┈" if c % 2 == 0 else " "), axis_style
            else:
                ch, st = " ", ""
            if c == marker_col:
                ch = ch if ch.strip() else "│"
                st = f"{st} {marker_style}".strip() if line[r][c] else axis_style
            if st != run_style:
                if run_chars:
                    out.append("".join(run_chars), style=run_style or "")
                    run_chars = []
                run_style = st
            run_chars.append(ch)
        if run_chars:
            out.append("".join(run_chars), style=run_style or "")
    if x_labels:
        left, right = x_labels
        space = max(plot_w - len(left) - len(right), 1)
        out.append("\n" + " " * gutter + left + " " * space + right, style=axis_style)
    return out


def hbar(fraction: float, width: int, style: str, track_style: str = "dim") -> Text:
    """Sleek progress-style bar using heavy line glyphs with half-cell precision."""
    f = max(0.0, min(1.0, fraction))
    halves = round(f * width * 2)
    full, half = divmod(halves, 2)
    t = Text("━" * full, style=style)
    if half:
        t.append("╸", style=style)
    rest = width - full - half
    if rest > 0:
        t.append("━" * rest, style=track_style)
    return t


def stacked_bar(segments: Sequence[tuple[float, str]], width: int, gap_style: str = "dim") -> Text:
    """Allocation bar: segments of (weight, style), widths by largest remainder."""
    total = sum(max(w, 0.0) for w, _ in segments)
    if total <= 0 or width <= 0:
        return Text("━" * width, style=gap_style)
    raw = [max(w, 0.0) / total * width for w, _ in segments]
    cells = [int(x) for x in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - cells[i], reverse=True)[: width - sum(cells)]:
        cells[i] += 1
    t = Text()
    for n, (_, style) in zip(cells, segments, strict=True):
        t.append("█" * n, style=style)
    return t


def range_bar(
    low: float | None, high: float | None, value: float, width: int, style: str, track_style: str = "dim"
) -> Text:
    """Where `value` sits between low and high, e.g. a 52-week range."""
    if low is None or high is None or high <= low:
        return Text("─" * width, style=track_style)
    pos = round((value - low) / (high - low) * (width - 1))
    pos = max(0, min(width - 1, pos))
    t = Text("─" * pos, style=track_style)
    t.append("●", style=style)
    t.append("─" * (width - pos - 1), style=track_style)
    return t


def column_chart(
    values: Sequence[float],
    labels: Sequence[str],
    height: int,
    style: str,
    label_style: str = "dim",
    col_width: int = 3,
) -> Text:
    """Vertical bar chart (e.g. monthly income) with eighth-block precision."""
    blocks = " ▁▂▃▄▅▆▇█"
    top = max((v for v in values), default=0.0)
    out = Text()
    for r in range(height):
        if r:
            out.append("\n")
        row_floor = (height - r - 1) / height * top if top else 0
        for v in values:
            level = (v - row_floor) / (top / height) if top else 0
            level = max(0.0, min(1.0, level))
            ch = blocks[round(level * 8)]
            out.append((ch * (col_width - 1)) + " ", style=style)
    out.append("\n")
    for lab in labels:
        out.append(f"{lab[: col_width - 1]:<{col_width}}", style=label_style)
    return out
