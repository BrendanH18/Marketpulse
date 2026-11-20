"""Chart helpers for the terminal app; Textual entry points stay on the app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import Input, Static

from .. import fmt
from ..market import PERIODS, MarketError
from ..models import parse_symbols
from . import extras
from .screens import PromptScreen
from .widgets import ChartView

if TYPE_CHECKING:
    from .app import MarketPulseApp


def open_chart(app: MarketPulseApp, symbol: str, *, compare: list[str] | None = None) -> None:
    if not symbol:
        return
    extras.remember_chart(app, symbol)  # ' goes back to the symbol this replaces
    app.chart_symbol = symbol.upper()
    if compare is not None:
        app.compare = compare
    app.query_one("#chart-input", Input).value = " ".join(
        [app.chart_symbol, app.chart_period, *(["vs", *app.compare] if app.compare else [])]
    )
    app.set_workspace("chart")
    app.query_one(ChartView).set_message(f"Loading {app.chart_symbol} · {app.chart_period}…")
    app.query_one(ChartView).focus()
    app.load_chart()


def _chart_submitted(app: MarketPulseApp, event: Input.Submitted) -> None:
    tokens = event.value.replace(",", " ").split()
    if not tokens:
        return
    symbol, rest = tokens[0], tokens[1:]
    if rest and rest[0].lower() in PERIODS:
        app.chart_period = rest.pop(0).lower()
    if rest and rest[0].lower() == "vs":
        rest = rest[1:]
    app.open_chart(symbol, compare=parse_symbols(" ".join(rest)))


def load_chart(app: MarketPulseApp) -> None:
    app._load_chart(app.query_one(ChartView))


def _load_chart(app: MarketPulseApp, view: ChartView) -> None:
    sym, period, others = app.chart_symbol, app.chart_period, list(app.compare)
    market = app.tracker.market
    try:
        bars = market.history(sym, period)
        compare = {o: market.history(o, period) for o in others}
        quotes, _ = market.quotes([sym])
    except MarketError as e:

        def failed(message: str) -> None:
            if (sym, period, others) == (app.chart_symbol, app.chart_period, list(app.compare)):
                view.set_message(message)
                app.render_chart_info()

        app._publish_load(failed, str(e))
        return
    app._publish_load(app._chart_loaded, sym, period, bars, quotes.get(sym), compare)


def _chart_loaded(app: MarketPulseApp, sym, period, bars, quote, compare) -> None:
    if sym != app.chart_symbol or period != app.chart_period:
        return
    app.query_one(ChartView).set_data(sym, period, bars, quote, compare)
    app.render_chart_info(quote)


def render_chart_info(app: MarketPulseApp, quote=None) -> None:
    p = app.palette
    periods = Text()
    for per in PERIODS:
        if per == app.chart_period:
            periods.append(f" {per} ", style=f"bold {p.background} on {p.accent}")
        else:
            periods.append(f" {per} ", style=p.muted)
    app.query_one("#chart-periods", Static).update(periods)
    info = Text()
    if quote is not None:
        info.append(f"{quote.symbol} ", style="title")
        info.append(f"{quote.name}  ", style="bright")
        info.append(f"{fmt.price(quote.price)} {quote.currency} ", style="bright")
        info.append(f"{fmt.arrow(quote.change)} {fmt.pct(quote.change_pct)}", style=app._trend_hex(quote.change))
    held = [x for x in (app.view.positions if app.view else []) if x.symbol == app.chart_symbol]
    if held:
        qty = sum(x.quantity for x in held)
        gain = sum(x.gain or 0 for x in held)
        info.append(f"   held {fmt.MASK if app.privacy else fmt.qty(qty)} · gain ", style="muted")
        info.append(fmt.money(gain, sign=True, privacy=app.privacy), style=app._trend_hex(gain))
    elif app.chart_symbol:
        info.append("   not held · b buy · w watch", style="muted")
    app.query_one("#chart-info", Static).update(info)
    app.query_one("#pane-chart").border_title = f"chart · {app.chart_symbol}" + (
        f" vs {', '.join(app.compare)}" if app.compare else ""
    )


NO_CHART = "Open a chart first: / searches for a symbol, v charts the selected row"


def _chart_ready(app: MarketPulseApp, what: str) -> bool:
    """True on the chart workspace with a symbol open; otherwise say why the key did nothing."""
    if app.workspace != "chart":
        app.notify(f"{what} on the chart workspace (4)", timeout=3)
        return False
    if not app.chart_symbol:
        app.notify(NO_CHART, timeout=3)
        return False
    return True


def action_period(app: MarketPulseApp, delta: int) -> None:
    if not _chart_ready(app, "[ and ] change the period"):
        return
    app.chart_period = PERIODS[(PERIODS.index(app.chart_period) + delta) % len(PERIODS)]
    app.open_chart(app.chart_symbol)


def action_compare(app: MarketPulseApp) -> None:
    if not _chart_ready(app, "c compares symbols"):
        return

    def done(value: str | None) -> None:
        if value:
            app.open_chart(app.chart_symbol, compare=list(dict.fromkeys([*app.compare, *parse_symbols(value)])))

    app.push_screen(PromptScreen("Compare with", "QQQ XEQT.TO …", hint="Overlays each symbol as % change."), done)


def action_clear_compare(app: MarketPulseApp) -> None:
    if app.compare:
        app.open_chart(app.chart_symbol, compare=[])
    else:
        app.notify("No comparisons to clear: c adds one on the chart", timeout=3)
