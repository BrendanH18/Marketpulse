"""Rich renderables shared by the CLI and the TUI.

Styles are semantic names (up, down, muted, accent…) registered from the
active Omarchy palette, so everything re-themes automatically.
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from datetime import datetime

from rich import box
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from . import charts, fmt
from .analytics import IncomeForecast, Performance, RebalanceRow, TaxYear, max_drawdown, period_return
from .ledger import RoomStatus
from .market import SearchResult
from .models import Account, Bar, Quote, Transaction, TxnType
from .tax import DENIED_REGISTERED, Disposition, TaxReport
from .themes import OMARCHY_PALETTES, Palette, palette_from_colors, pretty_name
from .valuation import Breakdown, PortfolioView, PositionView

TXN_STYLES = {
    TxnType.BUY: "accent",
    TxnType.SELL: "warn",
    TxnType.DIVIDEND: "up",
    TxnType.DRIP: "up",
    TxnType.INTEREST: "up",
    TxnType.DEPOSIT: "info",
    TxnType.WITHDRAWAL: "down",
    TxnType.FEE: "down",
    TxnType.SPLIT: "muted",
    TxnType.ROC: "muted",
    TxnType.TRANSFER: "info",
    TxnType.VALUATION: "muted",
}
DASH = "—"


def mix(fg: str, bg: str, amount: float) -> str:
    """Blend two hex colors; amount=1 is all fg."""
    a = [int(fg.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    b = [int(bg.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x * amount + y * (1 - amount)):02x}" for x, y in zip(a, b, strict=True))


def table(*headers: str | tuple[str, str], title: str | None = None, expand: bool = False) -> Table:
    t = Table(
        box=box.SIMPLE_HEAD,
        header_style="muted",
        border_style="border",
        title=title,
        title_style="title",
        title_justify="left",
        expand=expand,
        pad_edge=False,
    )
    for h in headers:
        name, justify = (h, "left") if isinstance(h, str) else h
        # Descriptive columns give up space (and wrap) first so numbers never truncate
        flexible = name in FLEX_COLUMNS
        t.add_column(name, justify=justify, no_wrap=not flexible, overflow="fold" if flexible else "ellipsis")
    return t


FLEX_COLUMNS = {"Name", "Note", "Institution", "Alert", "Source"}
NARROW_WIDTH = 110


def truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: max(n - 1, 0)] + "…"


def trend(text: str, value: float | None, *, bold: bool = False) -> Text:
    style = fmt.trend_style(value)
    return Text(text, style=f"bold {style}" if bold else style)


def dash() -> Text:
    return Text(DASH, style="muted")


def change_text(
    value: float | None, pct_value: float | None, currency: str = "", *, privacy: bool = False, decimals: int = 2
) -> Text:
    parts = [fmt.arrow(value)]
    if not privacy and value is not None:
        parts.append(fmt.money(value, currency, sign=True, decimals=decimals))
        parts.append(f"({fmt.pct(pct_value)})")
    else:
        parts.append(fmt.pct(pct_value))
    return trend(" ".join(parts), value)


# ── Quotes ────────────────────────────────────────────────────────────────────

QUOTE_HEADERS: list[str | tuple[str, str]] = [
    "Symbol",
    "Name",
    ("Price", "right"),
    ("Chg", "right"),
    ("%", "right"),
    "Today",
    "52w range",
    "Ccy",
]


def quote_cells(q: Quote, spark_width: int = 16) -> list[Text]:
    return [
        Text(q.symbol, style="bright"),
        Text(truncate(q.name, 28), style="muted"),
        Text(fmt.price(q.price) + (" ◌" if q.stale else "")),
        trend(f"{q.change:+,.2f}", q.change),
        trend(f"{fmt.arrow(q.change)} {fmt.pct(q.change_pct)}", q.change),
        charts.sparkline(q.intraday, spark_width, fmt.trend_style(q.change)),
        charts.range_bar(q.week52_low, q.week52_high, q.price, 14, "accent", "border"),
        Text(q.currency, style="muted"),
    ]


def missing_quote_cells(symbol: str, reason: str) -> list[Text]:
    return [Text(symbol, style="down"), Text(truncate(reason, 28), style="muted"), *(dash() for _ in range(6))]


def quotes_table(
    symbols: Sequence[str],
    quotes: dict[str, Quote],
    errors: dict[str, str],
    title: str | None = None,
    width: int | None = None,
) -> Table:
    # Narrow terminals drop Name and the 52-week bar
    drop = {1, 6} if width is not None and width < NARROW_WIDTH else set()

    def keep(cells: list) -> list:
        return [c for i, c in enumerate(cells) if i not in drop]

    t = table(*keep(QUOTE_HEADERS), title=title)
    for s in symbols:
        q = quotes.get(s.upper())
        cells = quote_cells(q) if q else missing_quote_cells(s.upper(), errors.get(s.upper(), "no data"))
        t.add_row(*keep(cells))
    return t


def quote_card(q: Quote) -> RenderableType:
    head = Text()
    head.append(f"{q.symbol}  ", style="title")
    head.append(q.name, style="bright")
    head.append(f"   {q.exchange} · {q.asset_class.label} · {q.currency}", style="muted")
    price = Text()
    price.append(fmt.price(q.price), style="bright")
    price.append("  ")
    price.append_text(change_text(q.change, q.change_pct))
    if q.stale:
        price.append("   ◌ offline cache", style="warn")
    grid = Table.grid(padding=(0, 3))
    for _ in range(4):
        grid.add_column()
    grid.add_row(
        Text("Day range", style="muted"),
        Text(f"{fmt.price(q.day_low)} – {fmt.price(q.day_high)}"),
        Text("Volume", style="muted"),
        Text(f"{q.volume:,}" if q.volume else DASH),
    )
    grid.add_row(
        Text("52w range", style="muted"),
        Text(f"{fmt.price(q.week52_low)} – {fmt.price(q.week52_high)}"),
        Text("Prev close", style="muted"),
        Text(fmt.price(q.prev_close)),
    )
    state = {"REGULAR": "● open", "PRE": "◐ pre-market", "POST": "◑ after hours", "CLOSED": "○ closed"}.get(
        q.market_state, ""
    )
    return Group(
        head,
        price,
        grid,
        charts.range_bar(q.week52_low, q.week52_high, q.price, 40, "accent", "border"),
        Text(state, style="up" if q.market_state == "REGULAR" else "muted"),
    )


# ── Portfolio ─────────────────────────────────────────────────────────────────

POSITION_HEADERS: list[str | tuple[str, str]] = [
    "Account",
    "Symbol",
    "Name",
    ("Qty", "right"),
    ("Avg cost", "right"),
    ("Price", "right"),
    ("Day", "right"),
    ("Value", "right"),
    ("Gain", "right"),
    ("Gain %", "right"),
    "Weight",
]


def weight_cell(weight: float, width: int = 6) -> Text:
    t = charts.hbar(weight / 100, width, "accent", "border")
    t.append(f" {weight:5.1f}%", style="muted")
    return t


def position_cells(p: PositionView, base: str, *, privacy: bool = False, show_account: bool = True) -> list[Text]:
    ccy_suffix = f" {p.currency}" if p.currency != base else ""
    cells: list[Text] = []
    if show_account:
        cells.append(Text(truncate(p.account.name, 12), style="muted"))
    cells += [
        Text(p.symbol, style="bright"),
        Text(truncate(p.name, 20), style="muted"),
        Text(fmt.MASK if privacy else fmt.qty(p.quantity)),
        Text(fmt.price(p.avg_cost), style="muted"),
        Text(fmt.price(p.price) + (" ◌" if p.stale else "")) if p.price is not None else dash(),
        trend(fmt.pct(p.day_change_pct), p.day_change_pct) if p.day_change_pct is not None else dash(),
        Text(fmt.money(p.market_value, privacy=privacy) + ccy_suffix) if p.market_value is not None else dash(),
        trend(fmt.money(p.gain, sign=True, privacy=privacy), p.gain) if p.gain is not None else dash(),
        trend(fmt.pct(p.gain_pct), p.gain) if p.gain_pct is not None else dash(),
        weight_cell(p.weight),
    ]
    return cells


def holdings_table(
    view: PortfolioView, *, privacy: bool = False, title: str | None = None, width: int | None = None
) -> Table:
    # Narrow terminals drop Name, Avg cost and Weight rather than truncating numbers
    drop = {2, 4, 10} if width is not None and width < NARROW_WIDTH else set()
    if width is not None and width < 90:
        drop.add(8)  # keep Gain % over the absolute gain

    def keep(cells: list) -> list:
        return [c for i, c in enumerate(cells) if i not in drop]

    t = table(*keep(POSITION_HEADERS), title=title)
    for p in sorted(view.positions, key=lambda p: (p.account.name, -(p.value_base or 0))):
        t.add_row(*keep(position_cells(p, view.base, privacy=privacy)))
    for c in view.cash:
        cash_value = fmt.money(c.amount, privacy=privacy) + (f" {c.currency}" if c.currency != view.base else "")
        weight = (c.amount_base or 0) / view.net_worth * 100 if view.net_worth else 0
        t.add_row(
            *keep(
                [
                    Text(truncate(c.account.name, 12), style="muted"),
                    Text("CASH", style="info"),
                    Text(f"{c.currency} balance", style="muted"),
                    *(dash() for _ in range(4)),
                    Text(cash_value),
                    dash(),
                    dash(),
                    weight_cell(weight),
                ]
            )
        )
    return t


def summary(view: PortfolioView, perf: Performance | None = None, *, privacy: bool = False) -> RenderableType:
    head = Text()
    head.append("NET WORTH  ", style="muted")
    head.append(f"{fmt.money(view.net_worth, view.base, privacy=privacy)} {view.base}", style="bright")
    head.append("    ")
    head.append_text(change_text(view.day_change, view.day_change_pct, privacy=privacy))
    head.append(" today", style="muted")
    if view.stale:
        head.append("   ◌ offline — showing cached prices", style="warn")

    tiles: list[tuple[str, Text]] = [
        ("Invested", Text(fmt.money(view.invested, view.base, privacy=privacy))),
        ("Unrealized", change_text(view.unrealized, view.unrealized_pct, privacy=privacy)),
        ("Realized", trend(fmt.money(view.realized_total, view.base, sign=True, privacy=privacy), view.realized_total)),
        (
            "Income YTD",
            Text(fmt.money(view.income_ytd, view.base, privacy=privacy), style="up" if view.income_ytd else "muted"),
        ),
    ]
    if view.cash:
        tiles.append(("Cash", Text(fmt.money(view.cash_total, view.base, privacy=privacy))))
    if perf is not None:
        if perf.xirr_pct is not None:
            tiles.append(("Money-weighted", trend(fmt.pct(perf.xirr_pct) + "/yr", perf.xirr_pct)))
        if perf.twr_pct is not None:
            tiles.append(("Time-weighted", trend(fmt.pct(perf.twr_pct), perf.twr_pct)))
    grid = Table.grid(padding=(0, 4))
    for _ in tiles:
        grid.add_column()
    grid.add_row(*(Text(label.upper(), style="muted") for label, _ in tiles))
    grid.add_row(*(value for _, value in tiles))
    parts: list[RenderableType] = [head, Text(""), grid]
    if view.excluded:
        parts.append(Text(f"excludes {', '.join(sorted(set(view.excluded)))} (no price or FX rate)", style="warn"))
    return Group(*parts)


def allocation(
    breakdown: Sequence[Breakdown], palette: Palette, *, width: int = 60, privacy: bool = False, base: str = ""
) -> RenderableType:
    if not breakdown:
        return Text("Nothing to allocate yet.", style="muted")
    colors = [palette.series[i % len(palette.series)] for i in range(len(breakdown))]
    bar = charts.stacked_bar([(b.value, c) for b, c in zip(breakdown, colors, strict=True)], width)
    legend = Table.grid(padding=(0, 2))
    for _ in range(3):
        legend.add_column()
    for b, c in zip(breakdown, colors, strict=True):
        legend.add_row(
            Text(f"■ {b.label}", style=c),
            Text(f"{b.weight:5.1f}%", style="bright"),
            Text(fmt.money(b.value, base, privacy=privacy), style="muted"),
        )
    return Group(bar, legend)


def strip_text(items: Sequence) -> Text:
    t = Text()
    for i, item in enumerate(items):
        if i:
            t.append("  │  ", style="border")
        t.append(f"{item.label} ", style="muted")
        q = item.quote
        if q is None:
            t.append(DASH, style="muted")
            continue
        t.append(fmt.price(q.price), style="bright")
        t.append(f" {fmt.arrow(q.change)}{abs(q.change_pct):.2f}%", style=fmt.trend_style(q.change))
    return t


def market_state_text(state: str) -> Text:
    label, style = {
        "REGULAR": ("● market open", "up"),
        "PRE": ("◐ pre-market", "warn"),
        "POST": ("◑ after hours", "warn"),
        "CLOSED": ("○ market closed", "muted"),
    }.get(state, ("", "muted"))
    return Text(label, style=style)


# ── Activity ──────────────────────────────────────────────────────────────────

ACTIVITY_HEADERS: list[str | tuple[str, str]] = [
    ("ID", "right"),
    "Date",
    "Account",
    "Type",
    "Symbol",
    ("Qty", "right"),
    ("Price", "right"),
    ("Amount", "right"),
    ("Fees", "right"),
    "Ccy",
    "Note",
]


def activity_cells(t: Transaction, accounts: dict[int, Account], *, privacy: bool = False) -> list[Text]:
    acct = accounts.get(t.account_id)
    name = acct.name if acct else f"#{t.account_id}"
    if t.type is TxnType.TRANSFER and t.target_account_id in accounts:
        name = f"{name} → {accounts[t.target_account_id].name}"
    qty = fmt.qty(t.quantity) if t.quantity else (f"×{t.ratio:g}" if t.ratio else DASH)
    return [
        Text(str(t.id), style="muted"),
        Text(t.date, style="muted"),
        Text(truncate(name, 22)),
        Text(t.type.value, style=TXN_STYLES.get(t.type, "")),
        Text(t.symbol or DASH, style="bright" if t.symbol else "muted"),
        Text(fmt.MASK if privacy and t.quantity else qty),
        Text(fmt.price(t.price) if t.price else DASH, style="" if t.price else "muted"),
        Text(fmt.money(t.gross_value, privacy=privacy) if t.gross_value else DASH),
        Text(fmt.money(t.fees) if t.fees else DASH, style="muted"),
        Text(t.currency or DASH, style="muted"),
        Text(truncate(t.note, 30), style="muted"),
    ]


def activity_table(
    txns: Sequence[Transaction], accounts: dict[int, Account], *, privacy: bool = False, limit: int | None = None
) -> Table:
    t = table(*ACTIVITY_HEADERS)
    rows = sorted(txns, key=lambda x: (x.date, x.id or 0), reverse=True)
    for txn in rows[:limit] if limit else rows:
        t.add_row(*activity_cells(txn, accounts, privacy=privacy))
    return t


# ── Charts ────────────────────────────────────────────────────────────────────


def _x_labels(bars: Sequence[Bar], period: str) -> tuple[str, str]:
    if period in ("1d", "5d"):
        f = "%H:%M" if period == "1d" else "%b %d %H:%M"
        return datetime.fromtimestamp(bars[0].time).strftime(f), datetime.fromtimestamp(bars[-1].time).strftime(f)
    return bars[0].date, bars[-1].date


def price_chart(
    symbol: str,
    bars: Sequence[Bar],
    period: str,
    palette: Palette,
    *,
    width: int,
    height: int = 14,
    quote: Quote | None = None,
    compare: dict[str, Sequence[Bar]] | None = None,
    marker: float | None = None,
) -> RenderableType:
    closes = [b.close for b in bars]
    if not closes:
        return Text(f"No {period} history for {symbol}.", style="muted")
    if compare:
        series, styles = [], []
        legend = Text()
        for i, (sym, bs) in enumerate([(symbol, bars), *compare.items()]):
            cs = [b.close for b in bs]
            if not cs or not cs[0]:
                continue
            series.append([(c / cs[0] - 1) * 100 for c in cs])
            color = palette.series[i % len(palette.series)]
            styles.append(color)
            legend.append(f"━━ {sym} ", style=f"bold {color}")
            legend.append(f"{fmt.pct(series[-1][-1])}    ", style=fmt.trend_style(series[-1][-1]))
        chart = charts.braille_chart(
            series,
            width,
            height,
            styles,
            baseline=0.0,
            label_format="{:+.1f}%",
            x_labels=_x_labels(bars, period),
            marker=marker,
        )
        return Group(legend, Text(""), chart)

    ret = period_return(closes) or 0.0
    color = palette.up if ret >= 0 else palette.down
    baseline = quote.prev_close if quote is not None and period == "1d" else None
    chart = charts.braille_chart(
        [closes],
        width,
        height,
        [color],
        fill_style=mix(color, palette.background, 0.22),
        baseline=baseline,
        x_labels=_x_labels(bars, period),
        marker=marker,
    )
    stats = Text()
    stats.append(f"{period}  ", style="muted")
    stats.append(f"{fmt.arrow(ret)} {fmt.pct(ret)}", style=fmt.trend_style(ret))
    stats.append(f"   high {fmt.price(max(closes))}   low {fmt.price(min(closes))}", style="muted")
    stats.append(f"   max drawdown {fmt.pct(max_drawdown(closes))}", style="muted")
    return Group(chart, stats)


def crosshair_text(bars: Sequence[Bar], position: float, period: str) -> Text:
    if not bars:
        return Text("")
    i = round(position * (len(bars) - 1))
    b = bars[i]
    when = datetime.fromtimestamp(b.time).strftime("%Y-%m-%d %H:%M" if period in ("1d", "5d", "1mo") else "%Y-%m-%d")
    first = bars[0].close
    t = Text()
    t.append(f"◆ {when}  ", style="accent")
    t.append(
        f"O {fmt.price(b.open)}  H {fmt.price(b.high)}  L {fmt.price(b.low)}  C {fmt.price(b.close)}", style="bright"
    )
    if first:
        chg = (b.close / first - 1) * 100
        t.append(f"   {fmt.pct(chg)} from start", style=fmt.trend_style(chg))
    if b.volume:
        t.append(f"   vol {b.volume:,}", style="muted")
    return t


# ── Performance, income, tax, allocation ──────────────────────────────────────


def performance_group(
    perf: Performance, view: PortfolioView, palette: Palette, *, width: int, privacy: bool = False
) -> RenderableType:
    grid = Table.grid(padding=(0, 4))
    for _ in range(2):
        grid.add_column()
    rows = [
        ("Tracking since", Text(perf.since or DASH)),
        ("Net contributions", Text(fmt.money(perf.net_contributions, view.base, privacy=privacy))),
        ("Total gain", trend(fmt.money(perf.total_gain, view.base, sign=True, privacy=privacy), perf.total_gain)),
        (
            "Money-weighted (XIRR)",
            trend(fmt.pct(perf.xirr_pct) + " /yr" if perf.xirr_pct is not None else DASH, perf.xirr_pct),
        ),
        ("Time-weighted", trend(fmt.pct(perf.twr_pct), perf.twr_pct)),
        ("Time-weighted /yr", trend(fmt.pct(perf.twr_annual_pct), perf.twr_annual_pct)),
        ("Max drawdown", Text(fmt.pct(perf.max_drawdown_pct), style="down" if perf.max_drawdown_pct else "muted")),
        ("Volatility /yr", Text(fmt.pct(perf.volatility_pct, sign=False), style="muted")),
    ]
    for label, value in rows:
        grid.add_row(Text(label, style="muted"), value)
    parts: list[RenderableType] = [grid]
    if len(perf.index) >= 2:
        series = [(v - 1) * 100 for _, v in perf.index]
        color = palette.up if series[-1] >= 0 else palette.down
        parts += [
            Text(""),
            Text("TIME-WEIGHTED GROWTH", style="muted"),
            charts.braille_chart(
                [series],
                width,
                10,
                [color],
                fill_style=mix(color, palette.background, 0.2),
                baseline=0.0,
                label_format="{:+.1f}%",
                x_labels=(perf.index[0][0], perf.index[-1][0]),
            ),
        ]
    else:
        parts.append(
            Text("\nNo history yet — run `marketpulse backfill` to rebuild it from your ledger.", style="muted")
        )
    return Group(*parts)


def net_worth_chart(
    snapshots: Sequence, palette: Palette, *, width: int, height: int = 10, privacy: bool = False
) -> RenderableType:
    values = [s.net_worth for s in snapshots]
    if len(values) < 2:
        return Text("Net worth history builds daily — or run `marketpulse backfill` to rebuild it now.", style="muted")
    ret = period_return(values) or 0.0
    color = palette.up if ret >= 0 else palette.down
    fmt_label = "{:,.0f}" if not privacy else "····"
    chart = charts.braille_chart(
        [values],
        width,
        height,
        [color],
        fill_style=mix(color, palette.background, 0.22),
        label_format=fmt_label,
        x_labels=(snapshots[0].date, snapshots[-1].date),
    )
    return chart


def income_group(
    months: Sequence[tuple[str, float]],
    by_symbol: Sequence[tuple[str, float]],
    forecast: Sequence[IncomeForecast] | None,
    view: PortfolioView,
    *,
    privacy: bool = False,
) -> RenderableType:
    values = [v for _, v in months]
    labels = [calendar.month_abbr[int(m[5:7])] for m, _ in months]
    total_12m = sum(values)
    head = Text()
    head.append("LAST 12 MONTHS  ", style="muted")
    head.append(fmt.money(total_12m, view.base, privacy=privacy), style="up bold")
    head.append("    YTD  ", style="muted")
    head.append(fmt.money(view.income_ytd, view.base, privacy=privacy), style="up")
    if forecast:
        fwd = sum(r.annual_base or 0 for r in forecast)
        head.append("    NEXT 12M EST.  ", style="muted")
        head.append(fmt.money(fwd, view.base, privacy=privacy), style="accent")
    parts: list[RenderableType] = [head, Text("")]
    if any(values):
        parts.append(charts.column_chart(values, labels, 8, "up", col_width=4))
    else:
        parts.append(Text("No dividends or interest recorded in the last 12 months.", style="muted"))
    if by_symbol:
        t = table("Source", ("This year", "right"), title="By source")
        for sym, amount in by_symbol[:12]:
            t.add_row(Text(sym, style="bright"), Text(fmt.money(amount, view.base, privacy=privacy), style="up"))
        parts += [Text(""), t]
    if forecast:
        t = table(
            "Symbol",
            ("Qty", "right"),
            ("TTM / share", "right"),
            ("Est. annual", "right"),
            ("Yield", "right"),
            ("Yield on cost", "right"),
            title="Forward income (trailing 12m distributions)",
        )
        for r in forecast:
            t.add_row(
                Text(r.symbol, style="bright"),
                Text(fmt.MASK if privacy else fmt.qty(r.quantity)),
                Text(f"{r.per_share_ttm:,.4f} {r.currency}", style="muted"),
                Text(fmt.money(r.annual_base, view.base, privacy=privacy), style="up"),
                Text(fmt.pct(r.yield_pct, sign=False)),
                Text(fmt.pct(r.yield_on_cost_pct, sign=False), style="accent"),
            )
        parts += [Text(""), t]
    return Group(*parts)


def _disposition_note(r: Disposition) -> Text:
    """Short tag explaining anything unusual about a disposition row."""
    if not r.complete:
        return Text("FX missing", style="down")
    if r.denied_reason == DENIED_REGISTERED:
        return Text("→ registered, loss denied", style="warn")
    if r.superficial:
        return Text("superficial" + (" (window open)" if r.window_open else ""), style="warn")
    if r.kind == "roc":
        return Text("ROC > ACB", style="muted")
    if r.kind == "deemed":
        return Text("→ registered", style="muted")
    return Text("")


def tax_group(
    years: Sequence[TaxYear],
    report: TaxReport,
    rooms: Sequence[tuple[RoomStatus, list[Account]]],
    accounts: dict[int, Account],
    base: str,
    *,
    privacy: bool = False,
    year: int | None = None,
) -> RenderableType:
    """The tax report: yearly totals, one year's dispositions, notes, and contribution room.

    Every money figure is already in `base` (pooled ACB, trade-date FX): see tax.py.
    """
    parts: list[RenderableType] = []
    if years:
        t = table(
            "Year",
            ("Proceeds", "right"),
            ("ACB", "right"),
            ("Denied", "right"),
            ("Net gain", "right"),
            ("Taxable", "right"),
            title=f"Capital gains — taxable accounts, pooled ACB ({base})",
        )
        for y in years:
            t.add_row(
                Text(str(y.year), style="bright"),
                Text(fmt.money(y.proceeds, privacy=privacy)),
                Text(fmt.money(y.cost, privacy=privacy), style="muted"),
                # Losses that don't count this year (superficial / moved into a TFSA or RRSP).
                Text(fmt.money(y.denied, privacy=privacy) if y.denied else "—", style="warn" if y.denied else "muted"),
                trend(fmt.money(y.net_gain, sign=True, privacy=privacy), y.net_gain),
                Text(
                    f"{fmt.money(y.taxable, privacy=privacy)}  ({y.inclusion_rate:.0%})",
                    style="warn" if y.taxable else "muted",
                ),
            )
        parts.append(t)
        focus = next((y for y in years if y.year == year), None) if year else years[0]
        if focus:
            d = table(
                "Date",
                "Account",
                "Symbol",
                ("Qty", "right"),
                ("Proceeds", "right"),
                ("ACB", "right"),
                ("Gain", "right"),
                "Ccy",
                ("FX", "right"),
                "",
                title=f"{focus.year} dispositions ({base})",
            )
            for r in focus.rows:
                acct = accounts.get(r.account_id)
                d.add_row(
                    Text(r.date, style="muted"),
                    Text(acct.name if acct else "?"),
                    Text(r.symbol, style="bright"),
                    Text(fmt.qty(r.quantity)),
                    Text(fmt.money(r.proceeds, privacy=privacy)),
                    Text(fmt.money(r.acb, privacy=privacy), style="muted"),
                    trend(fmt.money(r.allowed_gain, sign=True, privacy=privacy), r.allowed_gain),
                    Text(r.currency, style="muted"),
                    Text(f"{r.fx:.4f}" if r.fx else "missing", style="muted" if r.fx else "down"),
                    _disposition_note(r),
                )
            parts += [Text(""), d]
    else:
        parts.append(Text("No realized gains in taxable accounts.", style="muted"))

    # Explain every denied loss: how much, why, and the numbers behind it.
    superficial = [r for y in years for r in y.rows if r.superficial]
    if superficial:
        w = Text("\n⚠ Superficial losses (bought back within 30 days and still held):\n", style="warn")
        for r in superficial:
            w.append(
                f"   {r.date} {r.symbol}: {fmt.money(r.denied, privacy=privacy)} of a "
                f"{fmt.money(-r.gain, privacy=privacy)} loss denied — sold {fmt.qty(r.quantity)}, "
                f"bought {fmt.qty(r.acquired_in_window)} within 30 days, holding {fmt.qty(r.held_after_window)}"
                + (" (window still open)" if r.window_open else "")
                + "\n",
                style="muted",
            )
        w.append(
            "   The denied loss is added to the ACB of the shares you bought back in taxable accounts "
            "(and lost for shares bought back in a TFSA/RRSP).\n",
            style="muted",
        )
        parts.append(w)
    if report.issues:
        w = Text("\n⚠ Needs attention:\n", style="warn")
        for issue in report.issues:
            w.append(f"   {issue.date} {issue.message}\n", style="muted")
        parts.append(w)
    if rooms:
        r = table(
            "Type",
            ("Since", "right"),
            ("Start", "right"),
            ("+ Limits", "right"),
            ("+ Back", "right"),
            ("− Contrib.", "right"),
            ("Remaining", "right"),
            title="Contribution room",
        )
        for status, members in rooms:
            label = Text(status.account_type, style="bright")
            others = [a.name for a in members if a.name.upper() != status.account_type]
            if others:
                label.append(f"  {', '.join(others)}", style="muted")
            r.add_row(
                label,
                Text(str(status.as_of_year), style="muted"),
                Text(fmt.money(status.starting_room, privacy=privacy)),
                Text(fmt.money(status.new_limits, privacy=privacy), style="muted"),
                Text(fmt.money(status.withdrawals_added_back, privacy=privacy), style="muted"),
                Text(fmt.money(status.contributions, privacy=privacy)),
                Text(
                    fmt.money(status.remaining, privacy=privacy),
                    style="down bold" if status.remaining < 0 else "up bold",
                ),
            )
        parts += [Text(""), r]
    return Group(*parts)


def rebalance_table(rows: Sequence[RebalanceRow], base: str, *, privacy: bool = False) -> Table:
    t = table(
        "Bucket",
        ("Value", "right"),
        ("Weight", "right"),
        ("Target", "right"),
        ("Drift", "right"),
        ("To rebalance", "right"),
        title="Allocation vs target",
    )
    for r in rows:
        action = (
            DASH
            if abs(r.delta) < 1
            else f"{'buy' if r.delta > 0 else 'sell'} {fmt.money(abs(r.delta), base, privacy=privacy)}"
        )
        t.add_row(
            Text(r.label, style="bright"),
            Text(fmt.money(r.value, base, privacy=privacy)),
            Text(fmt.pct(r.weight, sign=False)),
            Text(fmt.pct(r.target, sign=False) if r.target else DASH, style="muted"),
            Text(fmt.pct(r.drift), style="warn" if abs(r.drift) >= 5 else "muted"),
            Text(action, style="accent" if r.delta > 0 else "warn"),
        )
    return t


def search_table(results: Sequence[SearchResult]) -> Table:
    t = table("Symbol", "Name", "Exchange", "Type")
    for r in results:
        t.add_row(
            Text(r.symbol, style="bright"),
            Text(truncate(r.name, 40)),
            Text(r.exchange, style="muted"),
            Text(r.type, style="muted"),
        )
    return t


def theme_table(current: str) -> Table:
    t = table("", "Theme", "Mode", "Palette")
    for name in sorted(OMARCHY_PALETTES):
        p = palette_from_colors(name, OMARCHY_PALETTES[name])
        swatch = Text()
        for color in (p.accent, *p.series[1:4], p.up, p.down):
            swatch.append("██", style=color)
        t.add_row(
            Text("●" if name == current else " ", style="accent"),
            Text(pretty_name(name), style="bright" if name == current else ""),
            Text("dark" if p.dark else "light", style="muted"),
            swatch,
        )
    return t
