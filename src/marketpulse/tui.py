"""Textual TUI for MarketPulse — interactive watchlist, portfolio, and charts."""
from datetime import datetime

from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Static,
    TabbedContent,
    TabPane,
)

from .display import (
    PORTFOLIO_COLUMNS,
    WATCHLIST_COLUMNS,
    _portfolio_totals,
    history_panel,
    portfolio_row,
    portfolio_summary,
    portfolio_totals_line,
    quote_panel,
    transactions_table,
    watchlist_failed_row,
    watchlist_row,
)
from .fetcher import fetch_fx_rates, fetch_history, fetch_quotes
from .models import FxRates, Portfolio, Quote, parse_tickers
from .storage import get_or_create_portfolio, load_portfolio, save_portfolio

CHART_PERIODS = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"]
DEFAULT_CHART_PERIOD = "3mo"


# ── Modal screens ─────────────────────────────────────────────────────────────

class SetupScreen(ModalScreen["Portfolio | None"]):
    """First-run wizard: choose watchlist tickers and optionally add positions."""

    BINDINGS = [Binding("escape", "skip", "Skip")]

    def __init__(self, portfolio_name: str, default_watchlist: list[str]):
        super().__init__()
        self._portfolio = Portfolio(name=portfolio_name)
        self._defaults = default_watchlist

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box", id="setup-box"):
            yield Label("⚡ Welcome to MarketPulse — first-time setup", classes="modal-title")
            yield Label(
                "Everything can be changed later in-app ('a' add / 'd' remove) "
                "or with 'marketpulse setup'.",
                classes="modal-hint",
            )
            yield Label("Watchlist tickers (space-separated):")
            yield Input(value=" ".join(self._defaults), id="setup-watchlist")
            yield Label("Positions (optional) — type TICKER SHARES AVG_COST, Enter to add each:")
            yield Input(placeholder="e.g.  XEQT.TO 100 28.50", id="setup-position")
            yield Static(Text("No positions added yet.", style="dim"), id="setup-positions-list")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save & Start", variant="success", id="setup-save")
                yield Button("Skip", id="setup-skip")

    @on(Input.Submitted, "#setup-watchlist")
    def _watchlist_entered(self) -> None:
        self.query_one("#setup-position", Input).focus()

    @on(Input.Submitted, "#setup-position")
    def _position_entered(self, event: Input.Submitted) -> None:
        parts = event.value.split()
        listing = self.query_one("#setup-positions-list", Static)
        if len(parts) != 3:
            listing.update(Text("Expected exactly: TICKER SHARES AVG_COST", style="red"))
            return
        try:
            shares, avg_cost = float(parts[1]), float(parts[2])
        except ValueError:
            listing.update(Text("Shares and avg cost must be numbers.", style="red"))
            return
        self._portfolio.add_position(parts[0], shares, avg_cost)
        event.input.value = ""
        lines = [
            Text(f"  {p.ticker}  {p.shares:,.4f} @ {p.avg_cost:,.2f}", style="green")
            for p in self._portfolio.positions.values()
        ]
        listing.update(Group(*lines))

    @on(Button.Pressed, "#setup-save")
    def _save(self) -> None:
        self._portfolio.watchlist = parse_tickers(self.query_one("#setup-watchlist", Input).value)
        self.dismiss(self._portfolio)

    @on(Button.Pressed, "#setup-skip")
    def action_skip(self) -> None:
        self.dismiss(None)


class AddTickerScreen(ModalScreen["list[str] | None"]):
    """Prompt for one or more tickers to append to the watchlist."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label("Add tickers to watchlist", classes="modal-title")
            yield Input(placeholder="AAPL MSFT XEQT.TO", id="add-ticker-input")
            with Horizontal(classes="modal-buttons"):
                yield Button("Add", variant="success", id="add-ticker-ok")
                yield Button("Cancel", id="add-ticker-cancel")

    @on(Input.Submitted, "#add-ticker-input")
    @on(Button.Pressed, "#add-ticker-ok")
    def _submit(self) -> None:
        tickers = parse_tickers(self.query_one("#add-ticker-input", Input).value)
        self.dismiss(tickers or None)

    @on(Button.Pressed, "#add-ticker-cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class TradeScreen(ModalScreen["tuple[str, str, float, float, float, str] | None"]):
    """Form for recording a buy or sell.

    Dismisses with (action, ticker, shares, price, fees, note) or None.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, action: str = "BUY", ticker: str = "", max_shares: float | None = None):
        super().__init__()
        self._action = action
        self._ticker = ticker
        self._max_shares = max_shares

    def compose(self) -> ComposeResult:
        buying = self._action == "BUY"
        with Vertical(classes="modal-box"):
            if buying:
                yield Label("Buy / add to position", classes="modal-title")
                yield Label("Buying a ticker you already hold blends the average cost.", classes="modal-hint")
            else:
                held = f" — {self._max_shares:,.4f} held" if self._max_shares is not None else ""
                yield Label(f"Sell {self._ticker}{held}", classes="modal-title")
                yield Label("Realized P&L uses the average-cost method.", classes="modal-hint")
            yield Input(value=self._ticker, placeholder="Ticker  e.g. XEQT.TO", id="trade-ticker")
            yield Input(placeholder="Shares  e.g. 100", id="trade-shares")
            yield Input(placeholder="Price per share  e.g. 28.50", id="trade-price")
            yield Input(placeholder="Fees (optional)  e.g. 4.95", id="trade-fees")
            yield Input(placeholder="Note (optional)", id="trade-note")
            yield Label("", id="trade-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Buy" if buying else "Sell", variant="success" if buying else "error", id="trade-ok")
                yield Button("Cancel", id="trade-cancel")

    def on_mount(self) -> None:
        if self._ticker:
            self.query_one("#trade-shares", Input).focus()

    @on(Input.Submitted, "#trade-ticker")
    @on(Input.Submitted, "#trade-shares")
    @on(Input.Submitted, "#trade-price")
    @on(Input.Submitted, "#trade-fees")
    def _next_field(self) -> None:
        self.focus_next()

    @on(Input.Submitted, "#trade-note")
    @on(Button.Pressed, "#trade-ok")
    def _submit(self) -> None:
        ticker = self.query_one("#trade-ticker", Input).value.strip().upper()
        error = self.query_one("#trade-error", Label)
        if not ticker:
            error.update(Text("Ticker is required.", style="red"))
            return
        try:
            shares = float(self.query_one("#trade-shares", Input).value)
            price = float(self.query_one("#trade-price", Input).value)
            fees = float(self.query_one("#trade-fees", Input).value or 0)
        except ValueError:
            error.update(Text("Shares, price, and fees must be numbers.", style="red"))
            return
        if shares <= 0 or price < 0 or fees < 0:
            error.update(Text("Shares must be positive; price and fees non-negative.", style="red"))
            return
        if self._action == "SELL" and self._max_shares is not None and shares > self._max_shares + 1e-9:
            error.update(Text(f"Only {self._max_shares:,.4f} shares held.", style="red"))
            return
        note = self.query_one("#trade-note", Input).value.strip()
        self.dismiss((self._action, ticker, shares, price, fees, note))

    @on(Button.Pressed, "#trade-cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class HistoryScreen(ModalScreen[None]):
    """Scrollable transaction ledger for the portfolio."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("h", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    def __init__(self, portfolio: Portfolio):
        super().__init__()
        self._portfolio = portfolio

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box", id="history-box"):
            yield VerticalScroll(Static(transactions_table(self._portfolio)))
            yield Label("esc to close", classes="modal-hint")

    def action_close(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    """Yes/no confirmation dialog."""

    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
        Binding("escape", "no", "No"),
    ]

    def __init__(self, message: str):
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label(self._message, classes="modal-title")
            with Horizontal(classes="modal-buttons"):
                yield Button("Yes", variant="error", id="confirm-yes")
                yield Button("No", id="confirm-no")

    @on(Button.Pressed, "#confirm-yes")
    def action_yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#confirm-no")
    def action_no(self) -> None:
        self.dismiss(False)


class QuoteDetailScreen(ModalScreen[None]):
    """Full quote card for the selected ticker."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("i", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    def __init__(self, quote: Quote):
        super().__init__()
        self._quote = quote

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box", id="detail-box"):
            yield Static(quote_panel(self._quote))
            yield Label("esc to close", classes="modal-hint")

    def action_close(self) -> None:
        self.dismiss(None)


# ── Main app ──────────────────────────────────────────────────────────────────

class MarketPulseApp(App):
    """Single-window TUI: launch once, browse everything."""

    TITLE = "⚡ MarketPulse"

    CSS = """
    TabPane {
        padding: 1 2;
    }
    DataTable {
        height: 1fr;
    }
    .status {
        height: auto;
        padding: 0 1;
    }
    #portfolio-extra {
        height: auto;
        padding: 0 1;
    }
    #chart-input {
        margin-bottom: 1;
        max-width: 60;
    }
    .view {
        height: auto;
    }

    SetupScreen, AddTickerScreen, TradeScreen, ConfirmScreen, QuoteDetailScreen, HistoryScreen {
        align: center middle;
    }
    .modal-box {
        background: $surface;
        border: thick $primary;
        padding: 1 2;
        width: 76;
        height: auto;
    }
    #detail-box {
        width: auto;
    }
    #history-box {
        width: auto;
        max-width: 110;
    }
    #history-box VerticalScroll {
        height: auto;
        max-height: 30;
    }
    .modal-box Input {
        margin-bottom: 1;
    }
    .modal-title {
        text-style: bold;
        margin-bottom: 1;
    }
    .modal-hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    .modal-buttons {
        height: auto;
        margin-top: 1;
    }
    .modal-buttons Button {
        margin-right: 2;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "show_tab('watchlist')", "Watchlist", show=False),
        Binding("2", "show_tab('portfolio')", "Portfolio", show=False),
        Binding("3", "show_tab('chart')", "Chart", show=False),
        Binding("a", "add_item", "Add/Buy"),
        Binding("s", "sell_item", "Sell"),
        Binding("d", "remove_item", "Remove"),
        Binding("i", "details", "Details"),
        Binding("h", "history", "History"),
        Binding("left_square_bracket", "cycle_period(-1)", "Period -"),
        Binding("right_square_bracket", "cycle_period(1)", "Period +"),
    ]

    def __init__(self, portfolio_name: str = "default", default_watchlist: list[str] | None = None,
                 refresh_seconds: int = 30):
        super().__init__()
        self.portfolio_name = portfolio_name
        self.default_watchlist = default_watchlist or []
        self.refresh_seconds = refresh_seconds
        self.last_chart_query: tuple[str, str] | None = None
        self.chart_period = DEFAULT_CHART_PERIOD
        self.quotes: dict[str, Quote] = {}
        self._last_failed: set[str] = set()
        self._last_fx_failed: set[str] = set()

    # ── Layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="watchlist"):
            with TabPane("Watchlist [1]", id="watchlist"):
                yield DataTable(id="watchlist-table")
                yield Static(id="watchlist-status", classes="status")
            with TabPane("Portfolio [2]", id="portfolio"):
                yield DataTable(id="portfolio-table")
                yield Static(id="portfolio-extra")
                yield Static(id="portfolio-status", classes="status")
            with TabPane("Chart [3]", id="chart"):
                yield Input(placeholder="TICKER [PERIOD]   e.g.  SPY 1y   XEQT.TO 6mo", id="chart-input")
                yield Static(id="chart-label", classes="status")
                yield VerticalScroll(Static(id="chart-view", classes="view"))
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"portfolio: {self.portfolio_name}  •  auto-refresh {self.refresh_seconds}s"
        for table_id, columns in (
            ("#watchlist-table", WATCHLIST_COLUMNS),
            ("#portfolio-table", PORTFOLIO_COLUMNS),
        ):
            table = self.query_one(table_id, DataTable)
            table.cursor_type = "row"
            table.add_columns(*columns)
        self.query_one("#chart-view", Static).update(
            Text(
                "Type a ticker above, or press Enter on a watchlist/portfolio row.\n"
                "Use [ and ] to cycle the chart period.",
                style="dim",
            )
        )
        if load_portfolio(self.portfolio_name) is None:
            self.push_screen(
                SetupScreen(self.portfolio_name, self.default_watchlist), self._setup_done
            )
        else:
            self._start()

    def _setup_done(self, result: Portfolio | None) -> None:
        if result is None:
            result = Portfolio(
                name=self.portfolio_name,
                watchlist=[t.upper() for t in self.default_watchlist],
            )
        save_portfolio(result)
        self.notify(
            f"Portfolio '{result.name}' saved — {len(result.positions)} positions, "
            f"{len(result.watchlist)} watchlist tickers."
        )
        self._start()

    def _start(self) -> None:
        self.action_refresh()
        self.set_interval(self.refresh_seconds, self._auto_refresh)

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_show_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab
        if tab == "chart":
            self.query_one("#chart-input", Input).focus()
        elif tab == "watchlist":
            self.query_one("#watchlist-table", DataTable).focus()
        elif tab == "portfolio":
            self.query_one("#portfolio-table", DataTable).focus()

    def action_refresh(self) -> None:
        self.load_watchlist()
        self.load_portfolio_view()
        if self.last_chart_query:
            self.load_chart(*self.last_chart_query)

    def _auto_refresh(self) -> None:
        # Quotes go stale; charts only change on demand
        self.load_watchlist()
        self.load_portfolio_view()

    def action_add_item(self) -> None:
        tab = self.query_one(TabbedContent).active
        if tab == "watchlist":
            self.push_screen(AddTickerScreen(), self._add_tickers_done)
        elif tab == "portfolio":
            self.push_screen(TradeScreen("BUY"), self._trade_done)
        else:
            self.query_one("#chart-input", Input).focus()

    def action_sell_item(self) -> None:
        if self.query_one(TabbedContent).active != "portfolio":
            return
        ticker = self._selected_ticker("#portfolio-table")
        if ticker is None:
            return
        p = load_portfolio(self.portfolio_name)
        pos = p.positions.get(ticker) if p else None
        if pos is None:
            self.notify(f"No position in {ticker}.", severity="warning")
            return
        self.push_screen(TradeScreen("SELL", ticker=ticker, max_shares=pos.shares), self._trade_done)

    def action_history(self) -> None:
        p = load_portfolio(self.portfolio_name)
        if p is None or not p.transactions:
            self.notify("No transactions recorded yet.", severity="information")
            return
        self.push_screen(HistoryScreen(p))

    def _add_tickers_done(self, tickers: list[str] | None) -> None:
        if not tickers:
            return
        p = get_or_create_portfolio(self.portfolio_name)
        added = [t for t in tickers if t not in p.watchlist]
        if not added:
            self.notify("Already on the watchlist.", severity="information")
            return
        p.watchlist.extend(added)
        save_portfolio(p)
        self.notify(f"Added to watchlist: {', '.join(added)}")
        self.load_watchlist()

    def _trade_done(self, result: tuple[str, str, float, float, float, str] | None) -> None:
        if result is None:
            return
        action, ticker, shares, price, fees, note = result
        p = get_or_create_portfolio(self.portfolio_name)
        try:
            if action == "BUY":
                # Currency is left blank: display falls back to the live quote's
                # currency, and the CLI 'buy' command can set it explicitly.
                pos, blended = p.buy(ticker, shares, price, fees=fees, note=note)
                verb = "Updated (blended)" if blended else "Opened"
                msg = f"{verb} {pos.ticker}: {pos.shares:,.4f} @ avg {pos.avg_cost:,.2f}"
            else:
                realized, pos = p.sell(ticker, shares, price, fees=fees, note=note)
                sign = "+" if realized >= 0 else ""
                remaining = "position closed" if pos is None else f"{pos.shares:,.4f} shares remain"
                msg = f"Sold {shares:,.4f} {ticker}: realized {sign}{realized:,.2f} — {remaining}"
        except ValueError as e:
            self.notify(str(e), severity="error")
            return
        save_portfolio(p)
        self.notify(msg)
        self.load_portfolio_view()
        self.load_watchlist()

    def action_remove_item(self) -> None:
        tab = self.query_one(TabbedContent).active
        if tab == "watchlist":
            ticker = self._selected_ticker("#watchlist-table")
            if ticker is None:
                return
            p = load_portfolio(self.portfolio_name)
            if p and ticker in p.watchlist:
                p.watchlist.remove(ticker)
                save_portfolio(p)
                self.notify(f"Removed {ticker} from watchlist.")
                self.load_watchlist()
            elif p and ticker in p.positions:
                self.notify(
                    f"{ticker} is a portfolio position — remove it from the Portfolio tab [2].",
                    severity="warning",
                )
            else:
                self.notify(f"{ticker} is not in your saved watchlist.", severity="warning")
        elif tab == "portfolio":
            ticker = self._selected_ticker("#portfolio-table")
            if ticker is None:
                return

            def _confirmed(yes: bool) -> None:
                if not yes:
                    return
                p = load_portfolio(self.portfolio_name)
                if p and ticker in p.positions:
                    del p.positions[ticker]
                    save_portfolio(p)
                    self.notify(f"Removed position {ticker}.")
                    self.load_portfolio_view()
                    self.load_watchlist()

            self.push_screen(ConfirmScreen(f"Remove position {ticker}?"), _confirmed)

    def action_details(self) -> None:
        tab = self.query_one(TabbedContent).active
        table_id = {"watchlist": "#watchlist-table", "portfolio": "#portfolio-table"}.get(tab)
        if table_id is None:
            return
        ticker = self._selected_ticker(table_id)
        if ticker is None:
            return
        quote = self.quotes.get(ticker)
        if quote is None:
            self.notify(f"No quote data for {ticker} yet.", severity="warning")
            return
        self.push_screen(QuoteDetailScreen(quote))

    def action_cycle_period(self, delta: int) -> None:
        if self.query_one(TabbedContent).active != "chart" or not self.last_chart_query:
            return
        ticker, period = self.last_chart_query
        period = CHART_PERIODS[(CHART_PERIODS.index(period) + delta) % len(CHART_PERIODS)]
        self.chart_period = period
        self._open_chart(ticker, period, switch_tab=False)

    @on(DataTable.RowSelected)
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        ticker = event.row_key.value
        if ticker:
            self._open_chart(ticker, self.chart_period)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "chart-input":
            return
        parts = event.value.split()
        if not parts:
            return
        ticker = parts[0].upper()
        period = parts[1].lower() if len(parts) > 1 else self.chart_period
        if period not in CHART_PERIODS:
            self.query_one("#chart-view", Static).update(
                Text(f"Invalid period '{period}'. Choose from: {', '.join(CHART_PERIODS)}", style="red")
            )
            return
        self.chart_period = period
        self._open_chart(ticker, period, switch_tab=False)

    def _open_chart(self, ticker: str, period: str, switch_tab: bool = True) -> None:
        self.last_chart_query = (ticker, period)
        if switch_tab:
            self.query_one(TabbedContent).active = "chart"
        self.query_one("#chart-label", Static).update(
            Text(f"  {ticker} · {period}   ([ / ] to change period)", style="bold cyan")
        )
        self.query_one("#chart-view", Static).update(
            Text(f"Fetching {ticker} ({period})…", style="cyan")
        )
        self.load_chart(ticker, period)

    def _selected_ticker(self, table_id: str) -> str | None:
        table = self.query_one(table_id, DataTable)
        if table.row_count == 0:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

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
        self.call_from_thread(self._set_status, "#watchlist-status", Text("  Updating…", style="cyan"))
        quotes, errors = fetch_quotes(tickers)
        self.call_from_thread(self._render_watchlist, quotes, errors)

    def _render_watchlist(self, quotes: dict[str, Quote], errors: dict[str, str]) -> None:
        self.quotes.update(quotes)
        table = self.query_one("#watchlist-table", DataTable)
        selected = self._selected_ticker("#watchlist-table")
        table.clear()
        keys = []
        for ticker, quote in sorted(quotes.items()):
            table.add_row(*watchlist_row(quote), key=ticker)
            keys.append(ticker)
        for ticker, reason in sorted(errors.items()):
            table.add_row(*watchlist_failed_row(ticker, reason), key=ticker)
            keys.append(ticker)
        if selected in keys:
            table.move_cursor(row=keys.index(selected))
        if not keys:
            status = Text("  Watchlist empty — press 'a' to add tickers.", style="dim")
        else:
            status = Text(
                f"  {len(quotes)} quotes  •  {len(errors)} failed  •  updated {_now()}"
                f"   (Enter chart · a add · d remove · i details)",
                style="dim",
            )
        self._set_status("#watchlist-status", status)
        self._notify_failures(errors)

    @work(thread=True, exclusive=True, group="portfolio")
    def load_portfolio_view(self) -> None:
        p = load_portfolio(self.portfolio_name)
        if p is None or not p.positions:
            self.call_from_thread(self._render_portfolio_empty)
            return
        self.call_from_thread(self._set_status, "#portfolio-status", Text("  Updating…", style="cyan"))
        quotes, errors = fetch_quotes(list(p.positions.keys()))
        currencies = {q.currency for q in quotes.values()}
        currencies.update(pos.currency for pos in p.positions.values() if pos.currency)
        fx, fx_errors = fetch_fx_rates(currencies, p.currency)
        self.call_from_thread(self._render_portfolio, p, quotes, errors, fx, fx_errors)

    def _render_portfolio_empty(self) -> None:
        self.query_one("#portfolio-table", DataTable).clear()
        self.query_one("#portfolio-extra", Static).update(
            Panel(
                Text(
                    f"No positions in portfolio '{self.portfolio_name}'.\n"
                    f"Press 'a' here to add one, or run:  marketpulse portfolio add <TICKER> <SHARES> <AVG_COST>",
                    style="dim",
                ),
                title=f"Portfolio: {self.portfolio_name}",
            )
        )
        self._set_status("#portfolio-status", Text(""))

    def _render_portfolio(
        self,
        p: Portfolio,
        quotes: dict[str, Quote],
        errors: dict[str, str],
        fx: FxRates,
        fx_errors: dict[str, str],
    ) -> None:
        self.quotes.update(quotes)
        table = self.query_one("#portfolio-table", DataTable)
        selected = self._selected_ticker("#portfolio-table")
        table.clear()
        totals = _portfolio_totals(p, quotes, fx)
        keys = []
        for ticker, pos in sorted(p.positions.items()):
            table.add_row(*portfolio_row(pos, quotes.get(ticker.upper()), totals.market, fx), key=ticker)
            keys.append(ticker)
        if selected in keys:
            table.move_cursor(row=keys.index(selected))
        extra = [portfolio_totals_line(p, quotes, fx)]
        if quotes:
            extra.append(portfolio_summary(p, quotes, fx))
        self.query_one("#portfolio-extra", Static).update(Group(*extra))
        self._set_status(
            "#portfolio-status",
            Text(
                f"  updated {_now()}   (Enter chart · a buy · s sell · d remove · i details · h history)",
                style="dim",
            ),
        )
        self._notify_failures(errors)
        self._notify_fx_failures(fx_errors)

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

    # ── UI-thread helpers ─────────────────────────────────────────────────────

    def _notify_failures(self, errors: dict[str, str]) -> None:
        failed = set(errors)
        if failed and failed != self._last_failed:
            self.notify(f"Failed to fetch: {', '.join(sorted(failed))}", severity="warning")
        if failed:
            self._last_failed = failed

    def _notify_fx_failures(self, fx_errors: dict[str, str]) -> None:
        failed = set(fx_errors)
        if failed and failed != self._last_fx_failed:
            self.notify(
                f"No FX rate for: {', '.join(sorted(failed))} — affected positions excluded from totals",
                severity="warning",
            )
        if failed:
            self._last_fx_failed = failed

    def _set_status(self, selector: str, renderable) -> None:
        self.query_one(selector, Static).update(renderable)

    def _update_view(self, selector: str, renderable) -> None:
        self.query_one(selector, Static).update(renderable)


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")
