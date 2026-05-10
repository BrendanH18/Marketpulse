"""Rich terminal UI rendering for MarketPulse."""
from datetime import datetime
from typing import Optional
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.align import Align
from rich import box
from rich.style import Style
from .models import Quote, Portfolio, Position

console = Console()


# ── Colour helpers ────────────────────────────────────────────────────────────

def _sign_color(value: float) -> str:
    if value > 0:
        return "bright_green"
    elif value < 0:
        return "bright_red"
    return "white"


def _fmt_change(value: float, pct: float, currency: str = "") -> Text:
    color = _sign_color(value)
    arrow = "▲" if value >= 0 else "▼"
    prefix = "+" if value >= 0 else ""
    label = f"{arrow} {prefix}{value:,.2f} ({prefix}{pct:.2f}%)"
    if currency:
        label = f"{arrow} {prefix}{value:,.2f} {currency} ({prefix}{pct:.2f}%)"
    return Text(label, style=color)


def _fmt_price(price: float, currency: str = "") -> str:
    if currency:
        return f"{price:,.2f} {currency}"
    return f"{price:,.2f}"


def _sparkline(series: pd.Series, width: int = 20) -> Text:
    """Render a tiny ASCII sparkline from a pandas Series."""
    bars = "▁▂▃▄▅▆▇█"
    if series.empty or series.isna().all():
        return Text("─" * width, style="dim")
    mn, mx = series.min(), series.max()
    rng = mx - mn
    if rng == 0:
        return Text("─" * width, style="dim white")
    # Downsample/upsample to `width` points
    resampled = series.dropna()
    indices = [int(i * (len(resampled) - 1) / (width - 1)) for i in range(width)]
    sampled = [resampled.iloc[i] for i in indices]
    chars = [bars[min(int((v - mn) / rng * (len(bars) - 1)), len(bars) - 1)] for v in sampled]
    first, last = sampled[0], sampled[-1]
    color = _sign_color(last - first)
    return Text("".join(chars), style=color)


# ── Quote card ────────────────────────────────────────────────────────────────

def quote_panel(quote: Quote) -> Panel:
    """Render a single quote as a rich Panel."""
    color = _sign_color(quote.change)
    title = Text(f" {quote.ticker} ", style=f"bold {color}")
    name_line = Text(f"{quote.name}  [{quote.exchange}]", style="dim")
    price_line = Text(f"{quote.price:,.2f} {quote.currency}", style=f"bold {color} underline")
    change_line = _fmt_change(quote.change, quote.change_pct)

    low_high = Text(
        f"L {_fmt_price(quote.day_low)}  ──  H {_fmt_price(quote.day_high)}",
        style="dim"
    )
    vol_text = Text(f"Vol: {quote.volume:,}", style="dim")
    mcap_text = Text(
        f"Mkt Cap: {_humanize(quote.market_cap)}" if quote.market_cap else "",
        style="dim"
    )
    week52_text = Text(
        f"52W  {_fmt_price(quote.week52_low)}  ──  {_fmt_price(quote.week52_high)}"
        if quote.week52_high and quote.week52_low else "",
        style="dim"
    )
    timestamp = Text(
        f"  {quote.timestamp.strftime('%H:%M:%S')}",
        style="dim italic"
    )

    lines = [name_line, price_line, change_line, low_high, vol_text]
    if mcap_text.plain:
        lines.append(mcap_text)
    if week52_text.plain:
        lines.append(week52_text)
    lines.append(timestamp)

    from rich.console import Group
    group = Group(*lines)
    return Panel(group, title=title, border_style=color, expand=False, padding=(0, 1))


def _humanize(n: Optional[float]) -> str:
    if n is None:
        return "N/A"
    if n >= 1e12:
        return f"{n/1e12:.2f}T"
    if n >= 1e9:
        return f"{n/1e9:.2f}B"
    if n >= 1e6:
        return f"{n/1e6:.2f}M"
    return f"{n:,.0f}"


# ── Watchlist table ───────────────────────────────────────────────────────────

def watchlist_table(quotes: dict[str, Quote], failed: list[str] = None) -> Table:
    """Render a compact watchlist table."""
    t = Table(
        title="[bold]Watchlist[/bold]",
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold cyan",
        expand=True,
    )
    t.add_column("Ticker", style="bold", width=10)
    t.add_column("Name", style="dim", max_width=30)
    t.add_column("Price", justify="right")
    t.add_column("Change", justify="right")
    t.add_column("Change %", justify="right")
    t.add_column("Volume", justify="right", style="dim")
    t.add_column("Mkt Cap", justify="right", style="dim")
    t.add_column("Currency", justify="center", style="dim")

    for ticker, quote in sorted(quotes.items()):
        color = _sign_color(quote.change)
        sign = "+" if quote.change >= 0 else ""
        t.add_row(
            Text(quote.ticker, style=f"bold {color}"),
            Text(quote.name[:28] + "…" if len(quote.name) > 28 else quote.name, style="dim"),
            Text(f"{quote.price:,.2f}", style=f"bold {color}"),
            Text(f"{sign}{quote.change:,.2f}", style=color),
            Text(f"{sign}{quote.change_pct:.2f}%", style=color),
            Text(f"{quote.volume:,}", style="dim"),
            Text(_humanize(quote.market_cap), style="dim"),
            Text(quote.currency, style="dim"),
        )

    if failed:
        for ticker in failed:
            t.add_row(
                Text(ticker, style="bold red"),
                Text("Fetch failed", style="red dim"),
                "—", "—", "—", "—", "—", "—",
            )
    return t


# ── Portfolio table ───────────────────────────────────────────────────────────

def portfolio_table(portfolio: Portfolio, quotes: dict[str, Quote]) -> Table:
    """Render a portfolio holdings table with live P&L."""
    t = Table(
        title=f"[bold]Portfolio: {portfolio.name}[/bold]  [dim]({portfolio.currency})[/dim]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        expand=True,
        show_footer=True,
    )
    t.add_column("Ticker", style="bold", footer="TOTAL")
    t.add_column("Name", style="dim", max_width=28)
    t.add_column("Shares", justify="right")
    t.add_column("Avg Cost", justify="right", style="dim")
    t.add_column("Price", justify="right")
    t.add_column("Day Chg%", justify="right")
    t.add_column("Mkt Value", justify="right")
    t.add_column("Book Value", justify="right", style="dim")
    t.add_column("Gain / Loss", justify="right")
    t.add_column("G/L %", justify="right")
    t.add_column("Note", style="dim italic")

    total_market = 0.0
    total_book = 0.0

    for ticker, pos in sorted(portfolio.positions.items()):
        quote = quotes.get(ticker.upper())
        if quote is None:
            t.add_row(
                Text(ticker, style="bold red"),
                Text("N/A", style="red dim"),
                f"{pos.shares:,.4f}", f"{pos.avg_cost:,.2f}",
                "—", "—", "—", f"{pos.book_value:,.2f}", "—", "—", pos.note,
            )
            total_book += pos.book_value
            continue

        mv = pos.market_value(quote.price)
        gl = pos.gain_loss(quote.price)
        gl_pct = pos.gain_loss_pct(quote.price)
        total_market += mv
        total_book += pos.book_value
        color = _sign_color(gl)
        day_color = _sign_color(quote.change)
        sign = "+" if gl >= 0 else ""
        day_sign = "+" if quote.change_pct >= 0 else ""

        t.add_row(
            Text(ticker, style=f"bold {color}"),
            Text(quote.name[:26] + "…" if len(quote.name) > 26 else quote.name, style="dim"),
            f"{pos.shares:,.4f}",
            f"{pos.avg_cost:,.2f}",
            Text(f"{quote.price:,.2f}", style="bold"),
            Text(f"{day_sign}{quote.change_pct:.2f}%", style=day_color),
            Text(f"{mv:,.2f}", style=f"bold {color}"),
            f"{pos.book_value:,.2f}",
            Text(f"{sign}{gl:,.2f}", style=color),
            Text(f"{sign}{gl_pct:.2f}%", style=color),
            pos.note,
        )

    total_gl = total_market - total_book
    total_gl_pct = (total_gl / total_book * 100) if total_book else 0
    gl_color = _sign_color(total_gl)
    sign = "+" if total_gl >= 0 else ""

    t.columns[6].footer = Text(f"{total_market:,.2f}", style=f"bold {gl_color}")
    t.columns[7].footer = Text(f"{total_book:,.2f}", style="dim")
    t.columns[8].footer = Text(f"{sign}{total_gl:,.2f}", style=f"bold {gl_color}")
    t.columns[9].footer = Text(f"{sign}{total_gl_pct:.2f}%", style=f"bold {gl_color}")

    return t


# ── History chart ─────────────────────────────────────────────────────────────

def history_panel(ticker: str, history: "pd.DataFrame", period: str) -> Panel:
    """Render a text-based price chart using block characters."""
    close = history["Close"].dropna()
    if close.empty:
        return Panel(Text("No history data.", style="red"), title=f"{ticker} History")

    width = min(console.width - 6, 100)
    height = 12

    mn, mx = close.min(), close.max()
    rng = mx - mn or 1

    # Downsample to width points
    indices = [int(i * (len(close) - 1) / max(width - 1, 1)) for i in range(width)]
    sampled = [float(close.iloc[i]) for i in indices]

    # Build the 2D grid
    grid = [[" " for _ in range(width)] for _ in range(height)]
    for col, val in enumerate(sampled):
        row = height - 1 - int((val - mn) / rng * (height - 1))
        row = max(0, min(height - 1, row))
        grid[row][col] = "●"

    start_price = sampled[0]
    end_price = sampled[-1]
    color = _sign_color(end_price - start_price)

    lines = []
    for r, row in enumerate(grid):
        price_at_row = mx - (r / (height - 1)) * rng
        label = f"{price_at_row:>9.2f} │"
        lines.append(Text(label, style="dim") + Text("".join(row), style=color))

    lines.append(Text(
        f"{'─' * 10}┼{'─' * width}  {period}  "
        f"{close.index[0].strftime('%Y-%m-%d')} → {close.index[-1].strftime('%Y-%m-%d')}",
        style="dim"
    ))

    from rich.console import Group
    spark_label = Text("  spark: ", style="dim") + _sparkline(close, width=min(60, width))
    lines.append(spark_label)

    pct_change = (end_price - start_price) / start_price * 100
    sign = "+" if pct_change >= 0 else ""
    summary = Text(
        f"  {ticker}  {start_price:,.2f} → {end_price:,.2f}  ({sign}{pct_change:.2f}%)",
        style=f"bold {color}"
    )
    lines.append(summary)

    return Panel(Group(*lines), title=f"[bold]{ticker}[/bold] Price History [{period}]", border_style=color)


# ── Header banner ─────────────────────────────────────────────────────────────

def header() -> Panel:
    now = datetime.now().strftime("%A, %B %d  %H:%M:%S")
    content = Align.center(
        Text(f"⚡  MarketPulse  •  {now}", style="bold bright_cyan"),
    )
    return Panel(content, style="bright_cyan", padding=(0, 2))
