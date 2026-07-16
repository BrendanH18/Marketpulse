"""Rich terminal UI rendering for MarketPulse."""

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from rich import box
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import FxRates, Portfolio, Position, Quote

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

    low_high = Text(f"L {_fmt_price(quote.day_low)}  ──  H {_fmt_price(quote.day_high)}", style="dim")
    vol_text = Text(f"Vol: {quote.volume:,}", style="dim")
    mcap_text = Text(f"Mkt Cap: {_humanize(quote.market_cap)}" if quote.market_cap else "", style="dim")
    week52_text = Text(
        f"52W  {_fmt_price(quote.week52_low)}  ──  {_fmt_price(quote.week52_high)}"
        if quote.week52_high and quote.week52_low
        else "",
        style="dim",
    )
    timestamp = Text(f"  {quote.timestamp.strftime('%H:%M:%S')}", style="dim italic")

    lines = [name_line, price_line, change_line, low_high, vol_text]
    if mcap_text.plain:
        lines.append(mcap_text)
    if week52_text.plain:
        lines.append(week52_text)
    lines.append(timestamp)

    from rich.console import Group

    group = Group(*lines)
    return Panel(group, title=title, border_style=color, expand=False, padding=(0, 1))


def _humanize(n: float | None) -> str:
    if n is None:
        return "N/A"
    if n >= 1e12:
        return f"{n / 1e12:.2f}T"
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    return f"{n:,.0f}"


# ── Watchlist table ───────────────────────────────────────────────────────────


def _short_error(reason: str, limit: int = 40) -> str:
    """Trim a fetch-error message to something table-friendly."""
    reason = reason.split("\n")[0]
    return reason[: limit - 1] + "…" if len(reason) > limit else reason


def watchlist_table(quotes: dict[str, Quote], failed: dict[str, str] = None) -> Table:
    """Render a compact watchlist table. `failed` maps ticker -> error reason."""
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

    for _ticker, quote in sorted(quotes.items()):
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
        for ticker, reason in failed.items():
            t.add_row(
                Text(ticker, style="bold red"),
                Text(_short_error(reason), style="red dim"),
                "—",
                "—",
                "—",
                "—",
                "—",
                "—",
            )
    return t


# ── DataTable row helpers (used by the Textual TUI) ───────────────────────────

WATCHLIST_COLUMNS = ["Ticker", "Name", "Price", "Change", "Change %", "Volume", "Mkt Cap", "Ccy"]
PORTFOLIO_COLUMNS = [
    "Ticker",
    "Name",
    "Shares",
    "Avg Cost",
    "Ccy",
    "Price",
    "Day Chg%",
    "Day P&L",
    "Mkt Value",
    "Book Value",
    "Gain / Loss",
    "G/L %",
    "Weight",
]


def _native_currency(pos: Position, quote: Quote | None, base: str) -> str:
    """Resolve the currency a position's prices are denominated in."""
    return pos.currency or (quote.currency if quote else "") or base


def watchlist_row(quote: Quote) -> list[Text]:
    """One watchlist row as styled Text cells, matching watchlist_table()."""
    color = _sign_color(quote.change)
    sign = "+" if quote.change >= 0 else ""
    name = quote.name[:28] + "…" if len(quote.name) > 28 else quote.name
    return [
        Text(quote.ticker, style=f"bold {color}"),
        Text(name, style="dim"),
        Text(f"{quote.price:,.2f}", style=f"bold {color}", justify="right"),
        Text(f"{sign}{quote.change:,.2f}", style=color, justify="right"),
        Text(f"{sign}{quote.change_pct:.2f}%", style=color, justify="right"),
        Text(f"{quote.volume:,}", style="dim", justify="right"),
        Text(_humanize(quote.market_cap), style="dim", justify="right"),
        Text(quote.currency, style="dim"),
    ]


def watchlist_failed_row(ticker: str, reason: str) -> list[Text]:
    """Row for a ticker whose fetch failed."""
    return [
        Text(ticker, style="bold red"),
        Text(_short_error(reason), style="red dim"),
        *(Text("—", style="dim", justify="right") for _ in range(5)),
        Text("—", style="dim"),
    ]


def portfolio_row(pos: Position, quote: Quote | None, total_market: float, fx: FxRates) -> list[Text]:
    """One portfolio row as styled Text cells, matching portfolio_table().

    Per-row figures stay in the position's native currency; `total_market`
    is in the base currency, so Weight converts the row's market value first.
    """

    def dash() -> Text:
        return Text("—", style="dim", justify="right")

    ccy = _native_currency(pos, quote, fx.base)
    fx_ok = fx.rate(ccy) is not None
    ccy_cell = Text(ccy, style="dim" if fx_ok else "bold red")

    if quote is None:
        return [
            Text(pos.ticker, style="bold red"),
            Text("N/A", style="red dim"),
            Text(f"{pos.shares:,.4f}", justify="right"),
            Text(f"{pos.avg_cost:,.2f}", style="dim", justify="right"),
            ccy_cell,
            dash(),
            dash(),
            dash(),
            dash(),
            Text(f"{pos.book_value:,.2f}", style="dim", justify="right"),
            dash(),
            dash(),
            dash(),
        ]

    mv = pos.market_value(quote.price)
    gl = pos.gain_loss(quote.price)
    gl_pct = pos.gain_loss_pct(quote.price)
    day_pl = pos.shares * quote.change
    mv_base = fx.convert(mv, ccy)
    if mv_base is not None and total_market:
        weight_cell = Text(f"{mv_base / total_market * 100:.1f}%", style="dim", justify="right")
    else:
        weight_cell = Text("n/a", style="dim", justify="right")
    color = _sign_color(gl)
    day_color = _sign_color(quote.change)
    sign = "+" if gl >= 0 else ""
    day_sign = "+" if quote.change >= 0 else ""
    name = quote.name[:18] + "…" if len(quote.name) > 18 else quote.name
    return [
        Text(pos.ticker, style=f"bold {color}"),
        Text(name, style="dim"),
        Text(f"{pos.shares:,.4f}", justify="right"),
        Text(f"{pos.avg_cost:,.2f}", style="dim", justify="right"),
        ccy_cell,
        Text(f"{quote.price:,.2f}", style="bold", justify="right"),
        Text(f"{day_sign}{quote.change_pct:.2f}%", style=day_color, justify="right"),
        Text(f"{day_sign}{day_pl:,.2f}", style=day_color, justify="right"),
        Text(f"{mv:,.2f}", style=f"bold {color}", justify="right"),
        Text(f"{pos.book_value:,.2f}", style="dim", justify="right"),
        Text(f"{sign}{gl:,.2f}", style=color, justify="right"),
        Text(f"{sign}{gl_pct:.2f}%", style=color, justify="right"),
        weight_cell,
    ]


def portfolio_totals_line(portfolio: Portfolio, quotes: dict[str, Quote], fx: FxRates) -> Text:
    """Compact TOTAL line to render under the portfolio DataTable."""
    totals = _portfolio_totals(portfolio, quotes, fx)
    total_gl = totals.market - totals.book
    total_gl_pct = (total_gl / totals.book * 100) if totals.book else 0
    gl_color = _sign_color(total_gl)
    day_color = _sign_color(totals.day)
    sign = "+" if total_gl >= 0 else ""
    day_sign = "+" if totals.day >= 0 else ""
    line = Text("  TOTAL  ", style="bold")
    line.append(f"Mkt {totals.market:,.2f} {fx.base}", style=f"bold {gl_color}")
    line.append("   ")
    line.append(f"Book {totals.book:,.2f}", style="dim")
    line.append("   ")
    line.append(f"Day {day_sign}{totals.day:,.2f}", style=f"bold {day_color}")
    line.append("   ")
    line.append(f"G/L {sign}{total_gl:,.2f} ({sign}{total_gl_pct:.2f}%)", style=f"bold {gl_color}")
    excluded = totals.missing_quotes + totals.missing_fx
    if excluded:
        line.append(f"   excludes {', '.join(excluded)}", style="dim italic")
    return line


# ── Portfolio table ───────────────────────────────────────────────────────────


@dataclass
class Totals:
    """Portfolio totals in the base currency.

    Positions without a live quote or without an FX rate into the base
    currency are excluded from all three sums and listed instead — mixed
    currencies are never silently added together.
    """

    market: float = 0.0
    book: float = 0.0
    day: float = 0.0
    missing_quotes: list[str] = field(default_factory=list)
    missing_fx: list[str] = field(default_factory=list)


def _portfolio_totals(portfolio: Portfolio, quotes: dict[str, Quote], fx: FxRates) -> Totals:
    totals = Totals()
    for ticker, pos in portfolio.positions.items():
        quote = quotes.get(ticker.upper())
        if quote is None:
            totals.missing_quotes.append(ticker)
            continue
        ccy = _native_currency(pos, quote, fx.base)
        rate = fx.rate(ccy)
        if rate is None:
            totals.missing_fx.append(ticker)
            continue
        totals.market += pos.market_value(quote.price) * rate
        totals.book += pos.book_value * rate
        totals.day += pos.shares * quote.change * rate
    return totals


def _realized_pnl_base(portfolio: Portfolio, fx: FxRates) -> tuple[float, list[str]]:
    """Convert per-currency realized P&L into the base currency.

    Returns (total, unconvertible_currencies)."""
    total = 0.0
    missing = []
    for ccy, amount in portfolio.realized_pnl().items():
        converted = fx.convert(amount, ccy)
        if converted is None:
            missing.append(ccy)
        else:
            total += converted
    return total, missing


def portfolio_table(portfolio: Portfolio, quotes: dict[str, Quote], fx: FxRates) -> Table:
    """Render a portfolio holdings table with live P&L.

    Rows are in each position's native currency; footer totals are converted
    to the portfolio base currency.
    """
    totals = _portfolio_totals(portfolio, quotes, fx)
    show_notes = any(pos.note for pos in portfolio.positions.values())

    t = Table(
        title=f"[bold]Portfolio: {portfolio.name}[/bold]  [dim]({portfolio.currency})[/dim]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        expand=True,
        show_footer=True,
    )
    t.add_column("Ticker", style="bold", footer="TOTAL")
    t.add_column("Name", style="dim", max_width=20)
    t.add_column("Shares", justify="right")
    t.add_column("Avg Cost", justify="right", style="dim")
    t.add_column("Ccy", justify="center")
    t.add_column("Price", justify="right")
    t.add_column("Day Chg%", justify="right")
    t.add_column("Day P&L", justify="right")
    t.add_column("Mkt Value", justify="right")
    t.add_column("Book Value", justify="right", style="dim")
    t.add_column("Gain / Loss", justify="right")
    t.add_column("G/L %", justify="right")
    t.add_column("Weight", justify="right", style="dim")
    if show_notes:
        t.add_column("Note", style="dim italic")

    for ticker, pos in sorted(portfolio.positions.items()):
        quote = quotes.get(ticker.upper())
        ccy = _native_currency(pos, quote, fx.base)
        fx_ok = fx.rate(ccy) is not None
        ccy_cell = Text(ccy, style="dim" if fx_ok else "bold red")
        if quote is None:
            row = [
                Text(ticker, style="bold red"),
                Text("N/A", style="red dim"),
                f"{pos.shares:,.4f}",
                f"{pos.avg_cost:,.2f}",
                ccy_cell,
                "—",
                "—",
                "—",
                "—",
                f"{pos.book_value:,.2f}",
                "—",
                "—",
                "—",
            ]
            if show_notes:
                row.append(pos.note)
            t.add_row(*row)
            continue

        mv = pos.market_value(quote.price)
        gl = pos.gain_loss(quote.price)
        gl_pct = pos.gain_loss_pct(quote.price)
        day_pl = pos.shares * quote.change
        mv_base = fx.convert(mv, ccy)
        if mv_base is not None and totals.market:
            weight_cell = f"{mv_base / totals.market * 100:.1f}%"
        else:
            weight_cell = "n/a"
        color = _sign_color(gl)
        day_color = _sign_color(quote.change)
        sign = "+" if gl >= 0 else ""
        day_sign = "+" if quote.change >= 0 else ""

        row = [
            Text(ticker, style=f"bold {color}"),
            Text(quote.name[:18] + "…" if len(quote.name) > 18 else quote.name, style="dim"),
            f"{pos.shares:,.4f}",
            f"{pos.avg_cost:,.2f}",
            ccy_cell,
            Text(f"{quote.price:,.2f}", style="bold"),
            Text(f"{day_sign}{quote.change_pct:.2f}%", style=day_color),
            Text(f"{day_sign}{day_pl:,.2f}", style=day_color),
            Text(f"{mv:,.2f}", style=f"bold {color}"),
            f"{pos.book_value:,.2f}",
            Text(f"{sign}{gl:,.2f}", style=color),
            Text(f"{sign}{gl_pct:.2f}%", style=color),
            weight_cell,
        ]
        if show_notes:
            row.append(pos.note)
        t.add_row(*row)

    total_gl = totals.market - totals.book
    total_gl_pct = (total_gl / totals.book * 100) if totals.book else 0
    gl_color = _sign_color(total_gl)
    day_color = _sign_color(totals.day)
    sign = "+" if total_gl >= 0 else ""
    day_sign = "+" if totals.day >= 0 else ""

    headers = [str(c.header) for c in t.columns]
    t.columns[headers.index("Ccy")].footer = Text(fx.base, style="dim")
    t.columns[headers.index("Day P&L")].footer = Text(f"{day_sign}{totals.day:,.2f}", style=f"bold {day_color}")
    t.columns[headers.index("Mkt Value")].footer = Text(f"{totals.market:,.2f}", style=f"bold {gl_color}")
    t.columns[headers.index("Book Value")].footer = Text(f"{totals.book:,.2f}", style="dim")
    t.columns[headers.index("Gain / Loss")].footer = Text(f"{sign}{total_gl:,.2f}", style=f"bold {gl_color}")
    t.columns[headers.index("G/L %")].footer = Text(f"{sign}{total_gl_pct:.2f}%", style=f"bold {gl_color}")

    return t


def portfolio_summary(portfolio: Portfolio, quotes: dict[str, Quote], fx: FxRates) -> Panel:
    """One-glance summary: total value, day change, unrealized and realized P&L."""
    totals = _portfolio_totals(portfolio, quotes, fx)
    total_gl = totals.market - totals.book
    total_gl_pct = (total_gl / totals.book * 100) if totals.book else 0
    prev_value = totals.market - totals.day
    day_pct = (totals.day / prev_value * 100) if prev_value else 0
    realized, realized_missing = _realized_pnl_base(portfolio, fx)

    gl_color = _sign_color(total_gl)
    day_color = _sign_color(totals.day)
    gl_sign = "+" if total_gl >= 0 else ""
    day_sign = "+" if totals.day >= 0 else ""
    day_arrow = "▲" if totals.day >= 0 else "▼"

    line = Text("  ")
    line.append(f"Total Value  {totals.market:,.2f} {fx.base}", style="bold")
    line.append("    •    ", style="dim")
    line.append(f"Today  {day_arrow} {day_sign}{totals.day:,.2f} ({day_sign}{day_pct:.2f}%)", style=f"bold {day_color}")
    line.append("    •    ", style="dim")
    line.append(f"Unrealized  {gl_sign}{total_gl:,.2f} ({gl_sign}{total_gl_pct:.2f}%)", style=f"bold {gl_color}")
    if realized or realized_missing:
        r_color = _sign_color(realized)
        r_sign = "+" if realized >= 0 else ""
        line.append("    •    ", style="dim")
        line.append(f"Realized  {r_sign}{realized:,.2f}", style=f"bold {r_color}")

    from rich.console import Group

    lines = [line]
    notes = []
    if totals.missing_quotes:
        notes.append(f"{', '.join(totals.missing_quotes)} (no live price)")
    if totals.missing_fx:
        notes.append(f"{', '.join(totals.missing_fx)} (no FX rate to {fx.base})")
    if realized_missing:
        notes.append(f"realized P&L in {', '.join(realized_missing)} (no FX rate)")
    if notes:
        lines.append(Text(f"  Excludes {'; '.join(notes)}", style="dim italic"))
    return Panel(Group(*lines), border_style=gl_color, padding=(0, 1))


def transactions_table(portfolio: Portfolio, ticker: str | None = None) -> Table:
    """Render the transaction ledger, optionally filtered to one ticker."""
    txns = portfolio.transactions
    if ticker:
        ticker = ticker.upper()
        txns = [txn for txn in txns if txn.ticker == ticker]
    suffix = f"  [dim]{ticker}[/dim]" if ticker else ""
    t = Table(
        title=f"[bold]Transactions: {portfolio.name}[/bold]{suffix}",
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold cyan",
    )
    t.add_column("Date", style="dim")
    t.add_column("Action")
    t.add_column("Ticker", style="bold")
    t.add_column("Shares", justify="right")
    t.add_column("Price", justify="right")
    t.add_column("Fees", justify="right", style="dim")
    t.add_column("Value", justify="right")
    t.add_column("Ccy", justify="center", style="dim")
    t.add_column("Note", style="dim italic")

    for txn in txns:
        color = "bright_green" if txn.action == "BUY" else "bright_red"
        t.add_row(
            txn.date or "—",
            Text(txn.action, style=f"bold {color}"),
            txn.ticker,
            f"{txn.shares:,.4f}",
            f"{txn.price:,.2f}",
            f"{txn.fees:,.2f}" if txn.fees else "—",
            Text(f"{txn.gross_value:,.2f}", style=color),
            txn.currency or "—",
            txn.note,
        )
    return t


# ── History chart ─────────────────────────────────────────────────────────────


def history_panel(ticker: str, history: "pd.DataFrame", period: str, width: int | None = None) -> Panel:
    """Render a text-based price chart using block characters."""
    close = history["Close"].dropna()
    if close.empty:
        return Panel(Text("No history data.", style="red"), title=f"{ticker} History")

    if width is None:
        # Leave room for the 11-char price gutter plus panel borders/padding
        width = console.width - 18
    width = max(min(width, 100), 20)
    height = 12

    mn, mx = close.min(), close.max()
    rng = mx - mn or 1

    # Downsample to width points
    indices = [int(i * (len(close) - 1) / max(width - 1, 1)) for i in range(width)]
    sampled = [float(close.iloc[i]) for i in indices]

    # Build the 2D grid: dots at sampled prices, vertical strokes joining
    # adjacent columns so the chart reads as a continuous line
    rows = []
    for val in sampled:
        row = height - 1 - int((val - mn) / rng * (height - 1))
        rows.append(max(0, min(height - 1, row)))

    grid = [[" " for _ in range(width)] for _ in range(height)]
    for col, row in enumerate(rows):
        grid[row][col] = "●"
        if col > 0:
            lo, hi = sorted((rows[col - 1], row))
            for r in range(lo + 1, hi):
                if grid[r][col] == " ":
                    grid[r][col] = "│"

    start_price = sampled[0]
    end_price = sampled[-1]
    color = _sign_color(end_price - start_price)

    lines = []
    for r, row in enumerate(grid):
        price_at_row = mx - (r / (height - 1)) * rng
        label = f"{price_at_row:>9.2f} │"
        lines.append(Text(label, style="dim") + Text("".join(row), style=color))

    lines.append(Text(f"{'─' * 10}┼{'─' * width}", style="dim"))
    lines.append(
        Text(f"  {period}: {close.index[0].strftime('%Y-%m-%d')} → {close.index[-1].strftime('%Y-%m-%d')}", style="dim")
    )

    from rich.console import Group

    spark_label = Text("  spark: ", style="dim") + _sparkline(close, width=min(60, width))
    lines.append(spark_label)

    pct_change = (end_price - start_price) / start_price * 100
    sign = "+" if pct_change >= 0 else ""
    summary = Text(
        f"  {ticker}  {start_price:,.2f} → {end_price:,.2f}  ({sign}{pct_change:.2f}%)", style=f"bold {color}"
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
