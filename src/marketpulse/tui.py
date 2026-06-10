"""Textual TUI for MarketPulse — interactive watchlist, portfolio, and charts."""
from datetime import datetime

from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Input, Static, TabbedContent, TabPane

from .display import (
    history_panel,
    portfolio_summary,
    portfolio_table,
    watchlist_table,
)
from .fetcher import fetch_history, fetch_quotes
from .storage import load_portfolio

CHART_PERIODS = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"]


class MarketPulseApp(App):
    """Single-window TUI: launch once, browse everything."""

    TITLE = "⚡ MarketPulse"

    CSS = """
    TabPane {
        padding: 1 2;
    }
    #chart-input {
        margin-bottom: 1;
        max-width: 60;
    }
    .view {
        height: auto;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "show_tab('watchlist')", "Watchlist"),
        Binding("2", "show_tab('portfolio')", "Portfolio"),
        Binding("3", "show_tab('chart')", "Chart"),
    ]

    def __init__(self, portfolio_name: str = "default", default_watchlist: list[str] | None = None,
                 refresh_seconds: int = 30):
        super().__init__()
        self.portfolio_name = portfolio_name
        self.default_watchlist = default_watchlist or []
        self.refresh_seconds = refresh_seconds
        self.last_chart_query: tuple[str, str] | None = None

    # ── Layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="watchlist"):
            with TabPane("Watchlist [1]", id="watchlist"):
                yield VerticalScroll(Static(id="watchlist-view", classes="view"))
            with TabPane("Portfolio [2]", id="portfolio"):
                yield VerticalScroll(Static(id="portfolio-view", classes="view"))
            with TabPane("Chart [3]", id="chart"):
                yield Input(placeholder="TICKER [PERIOD]   e.g.  SPY 1y   XEQT.TO 6mo", id="chart-input")
                yield VerticalScroll(Static(id="chart-view", classes="view"))
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"portfolio: {self.portfolio_name}  •  auto-refresh {self.refresh_seconds}s"
        self.query_one("#chart-view", Static).update(
            Text("Type a ticker above and press Enter.", style="dim")
        )
        self.action_refresh()
        self.set_interval(self.refresh_seconds, self._auto_refresh)

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_show_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab
        if tab == "chart":
            self.query_one("#chart-input", Input).focus()

    def action_refresh(self) -> None:
        self.load_watchlist()
        self.load_portfolio_view()
        if self.last_chart_query:
            self.load_chart(*self.last_chart_query)

    def _auto_refresh(self) -> None:
        # Quotes go stale; charts only change on demand
        self.load_watchlist()
        self.load_portfolio_view()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "chart-input":
            return
        parts = event.value.split()
        if not parts:
            return
        ticker = parts[0].upper()
        period = parts[1].lower() if len(parts) > 1 else "3mo"
        if period not in CHART_PERIODS:
            self.query_one("#chart-view", Static).update(
                Text(f"Invalid period '{period}'. Choose from: {', '.join(CHART_PERIODS)}", style="red")
            )
            return
        self.last_chart_query = (ticker, period)
        self.query_one("#chart-view", Static).update(
            Text(f"Fetching {ticker} ({period})…", style="cyan")
        )
        self.load_chart(ticker, period)

    # ── Data workers (threads, so fetches never block the UI) ─────────────────

    def _watch_tickers(self) -> list[str]:
        p = load_portfolio(self.portfolio_name)
        tickers = []
        if p:
            tickers = list(p.watchlist) + list(p.positions.keys())
        if not tickers:
            tickers = list(self.default_watchlist)
        seen = set()
        return [t for t in tickers if not (t.upper() in seen or seen.add(t.upper()))]

    @work(thread=True, exclusive=True, group="watchlist")
    def load_watchlist(self) -> None:
        tickers = self._watch_tickers()
        quotes = fetch_quotes(tickers)
        failed = [t for t in tickers if t.upper() not in quotes]
        view = Group(
            watchlist_table(quotes, failed),
            Text(f"\n  {len(quotes)} quotes  •  {len(failed)} failed  •  updated {_now()}", style="dim"),
        )
        self.call_from_thread(self._update_view, "#watchlist-view", view)

    @work(thread=True, exclusive=True, group="portfolio")
    def load_portfolio_view(self) -> None:
        p = load_portfolio(self.portfolio_name)
        if p is None or not p.positions:
            view = Panel(
                Text(
                    f"No positions in portfolio '{self.portfolio_name}'.\n"
                    f"Add some with:  marketpulse portfolio add <TICKER> <SHARES> <AVG_COST>",
                    style="dim",
                ),
                title=f"Portfolio: {self.portfolio_name}",
            )
            self.call_from_thread(self._update_view, "#portfolio-view", view)
            return
        quotes = fetch_quotes(list(p.positions.keys()))
        parts = [portfolio_table(p, quotes)]
        if quotes:
            parts.append(portfolio_summary(p, quotes))
        parts.append(Text(f"  updated {_now()}", style="dim"))
        self.call_from_thread(self._update_view, "#portfolio-view", Group(*parts))

    @work(thread=True, exclusive=True, group="chart")
    def load_chart(self, ticker: str, period: str) -> None:
        try:
            hist = fetch_history(ticker, period)
        except RuntimeError as e:
            self.call_from_thread(
                self._update_view, "#chart-view", Text(f"Error: {e}", style="red")
            )
            return
        width = max(self.size.width - 24, 20)
        view = history_panel(ticker, hist, period, width=width)
        self.call_from_thread(self._update_view, "#chart-view", view)

    def _update_view(self, selector: str, renderable) -> None:
        self.query_one(selector, Static).update(renderable)


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")
