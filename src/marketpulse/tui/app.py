"""MarketPulse TUI: Omarchy-styled workspaces over the Tracker service."""

from __future__ import annotations

from datetime import date, timedelta
from functools import partial
from pathlib import Path

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from rich.theme import Theme as RichTheme
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import ContentSwitcher, DataTable, Input, Static

from .. import fmt, render
from ..alerts import notify as desktop_notify
from ..analytics import income_by_month, income_by_symbol
from ..config import Config
from ..market import PERIODS, MarketError
from ..models import AssetKind, Transaction, TxnType, parse_date, parse_symbols
from ..services import Tracker
from ..themes import (
    OMARCHY_PALETTES,
    palette_from_colors,
    pretty_name,
    resolve_palette,
    rich_styles,
    textual_theme,
    theme_names,
)
from ..valuation import PortfolioView, PositionView
from .screens import (
    AccountForm,
    AlertForm,
    AssetForm,
    ConfirmScreen,
    HelpScreen,
    PromptScreen,
    RoomForm,
    SearchScreen,
    TransactionForm,
)
from .widgets import WORKSPACES, Canvas, ChartView, Tile, TopBar, money_tile, pane, tile_content

NW_RANGES = ["1m", "3m", "6m", "ytd", "1y", "all"]
ALLOC_MODES = ["class", "account", "currency"]
# Holdings table keeps Account, Symbol, Qty, Price, Day, Value, Gain, Gain %, Weight;
# name and average cost live in the position pane.
HOLDING_COLUMNS = (0, 1, 3, 5, 6, 7, 8, 9, 10)
HINTS = {
    "dashboard": "n new txn · / search · g grouping · , range- · . range+ · p privacy · t theme",
    "holdings": "⏎ chart · b buy · s sell · D dividend · f account · A alert · w watch",
    "watchlist": "⏎ chart · a add · x remove · J/K reorder · b buy · A alert",
    "chart": "[/] period · c compare · C clear · ←/→ crosshair · b buy · w watch · A alert",
    "activity": "n new · e edit · x delete · u undo · / filter · i import · E export",
    "income": "D dividend · n new txn · r refresh",
    "tax": "n new account · e edit · x delete · R room · G add GIC/asset · V value asset · ⏎ holdings",
    "alerts": "n new alert · x delete · space pause/resume · ⏎ chart",
}


class PortfolioCommands(Provider):
    """Command palette entries: every action, theme and known symbol."""

    def _entries(self) -> list[tuple[str, str, object]]:
        app: MarketPulseApp = self.app  # type: ignore[assignment]
        entries: list[tuple[str, str, object]] = [
            ("Buy", "Record a buy", partial(app.action_trade, "BUY")),
            ("Sell", "Record a sell", partial(app.action_trade, "SELL")),
            ("Record dividend", "Cash dividend or distribution", partial(app.action_trade, "DIVIDEND")),
            ("Record DRIP", "Reinvested dividend", partial(app.action_trade, "DRIP")),
            ("Record deposit", "Money into an account", partial(app.action_trade, "DEPOSIT")),
            ("Record withdrawal", "Money out of an account", partial(app.action_trade, "WITHDRAWAL")),
            ("Record interest", "Interest income", partial(app.action_trade, "INTEREST")),
            ("Record split", "Stock split", partial(app.action_trade, "SPLIT")),
            ("Transfer in-kind", "Move shares between accounts", partial(app.action_trade, "TRANSFER")),
            ("New account", "TFSA, RRSP, FHSA, non-registered…", app.action_new_account),
            ("Add GIC or manual asset", "Fixed income, property, private holdings", app.action_add_asset),
            ("Update manual asset value", "Mark a manual asset", app.action_value_asset),
            ("Set contribution room", "TFSA / RRSP / FHSA", app.action_room),
            ("New price alert", "Notify on price or % move", app.action_alert),
            ("Add to watchlist", "Search and watch a symbol", app.action_watch_add),
            ("Search symbol", "Open a chart", app.action_search),
            ("Import CSV", "Broker or MarketPulse export", app.action_import_csv),
            ("Export CSV", "Full ledger", app.action_export_csv),
            ("Backfill net worth history", "Rebuild daily snapshots from your ledger", app.action_backfill),
            ("Toggle privacy mode", "Hide amounts", app.action_privacy),
            ("Refresh quotes", "Fetch fresh prices", app.action_refresh),
            ("Undo last transaction", "Delete the most recent entry", app.action_undo),
            ("Help", "Keyboard shortcuts", app.action_help),
        ]
        entries += [
            (f"Go to {label}", f"Workspace {i}", partial(app.set_workspace, key))
            for i, (key, label) in enumerate(WORKSPACES, 1)
        ]
        entries += [
            (f"Theme: {pretty_name(n)}", "Omarchy theme", partial(setattr, app, "theme", n)) for n in theme_names()
        ]
        entries += [(f"Chart {s}", "Open chart", partial(app.open_chart, s)) for s in app.known_symbols()]
        return entries

    async def discover(self) -> Hits:
        for name, help_text, callback in self._entries()[:23]:
            yield DiscoveryHit(name, callback, help=help_text)  # type: ignore[arg-type]

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, help_text, callback in self._entries():
            score = matcher.match(name)
            if score > 0:
                yield Hit(score, matcher.highlight(name), callback, help=help_text)  # type: ignore[arg-type]


class MarketPulseApp(App):
    TITLE = "MarketPulse"
    COMMANDS = App.COMMANDS | {PortfolioCommands}
    CSS = """
    Screen { background: $background; }
    #hints { dock: bottom; height: 1; background: $background; }
    #workspaces { height: 1fr; padding: 0 1; }
    #workspaces > * { height: 1fr; }

    .pane {
        border: solid $mp-border;
        border-title-color: $mp-muted;
        border-title-style: bold;
        border-subtitle-color: $mp-muted;
        border-subtitle-align: right;
        padding: 0 1;
        height: 1fr;
        background: $background;
    }
    .pane:focus-within { border: solid $accent; border-title-color: $accent; }
    .col-main { width: 2fr; }
    .col-side { width: 1fr; min-width: 38; }
    App.-narrow .detail { display: none; }
    App.-narrow #dash-side { display: none; }

    #strip { height: 1; padding: 0 1; }
    #tiles { height: 7; }
    #tile-networth { width: 2fr; }
    #pane-nw { height: 3fr; }
    #pane-accounts { height: 2fr; }
    #pane-alloc { height: auto; max-height: 16; }
    #pane-alloc Canvas { height: auto; min-height: 4; }
    #pane-movers { height: auto; max-height: 12; }
    #pane-perf { height: 1fr; }
    #pane-accts { min-width: 60; }

    DataTable { height: 1fr; background: $background; scrollbar-size-vertical: 1; }
    DataTable > .datatable--header { background: $background; color: $mp-muted; text-style: bold; }
    DataTable > .datatable--cursor { background: $mp-selection; color: $mp-bright; text-style: bold; }
    DataTable > .datatable--hover { background: $mp-selection 40%; }
    DataTable:blur > .datatable--cursor { background: $mp-selection 60%; }

    Input { background: $background; border: solid $mp-border; padding: 0 1; height: 3; }
    Input:focus { border: solid $accent; }
    Select > SelectCurrent { background: $background; border: solid $mp-border; }
    Select:focus > SelectCurrent { border: solid $accent; }

    #chart-head { height: 3; }
    #chart-input { width: 44; }
    #chart-periods { width: 1fr; padding: 1 2; }
    #chart-info { height: 1; padding: 0 1; }
    #activity-filter { margin-bottom: 0; }

    ModalScreen { align: center middle; background: $background 70%; }
    .modal {
        width: 96;
        max-width: 95%;
        height: auto;
        max-height: 92%;
        border: solid $accent;
        background: $background;
        padding: 1 2;
    }
    .modal.narrow { width: 60; }
    .modal-title { text-style: bold; color: $accent; margin-bottom: 1; }
    .field-row { height: auto; }
    .field-row > * { width: 1fr; margin-right: 1; }
    .switch-row { align-vertical: middle; }
    .switch-row > Switch { width: auto; }
    .hint { color: $mp-muted; height: auto; margin: 0 0 1 1; }
    .error { width: 1fr; height: auto; color: $error; padding-top: 1; }
    .buttons { height: auto; margin-top: 1; }
    .buttons Button { margin-left: 1; min-width: 14; }
    OptionList { height: auto; max-height: 14; background: $background; border: none; }
    HelpScreen VerticalScroll { height: auto; max-height: 30; }
    """

    BINDINGS = [
        *[Binding(str(i), f"workspace('{key}')", label, show=False) for i, (key, label) in enumerate(WORKSPACES, 1)],
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("p", "privacy", "Privacy"),
        Binding("t", "next_theme", "Theme"),
        Binding("question_mark", "help", "Help"),
        Binding("slash", "search", "Search"),
        Binding("n", "new", "New"),
        Binding("a", "add", "Add"),
        Binding("b", "trade('BUY')", "Buy"),
        Binding("s", "trade('SELL')", "Sell"),
        Binding("D", "trade('DIVIDEND')", "Dividend"),
        Binding("e", "edit", "Edit"),
        Binding("x,delete", "delete", "Delete"),
        Binding("u", "undo", "Undo"),
        Binding("w", "watch_add", "Watch"),
        Binding("A", "alert", "Alert"),
        Binding("f", "filter_account", "Account filter"),
        Binding("g", "cycle_alloc", "Grouping"),
        Binding("comma", "nw_range(-1)", show=False),
        Binding("full_stop", "nw_range(1)", show=False),
        Binding("left_square_bracket", "period(-1)", show=False),
        Binding("right_square_bracket", "period(1)", show=False),
        Binding("c", "compare", "Compare"),
        Binding("C", "clear_compare", show=False),
        Binding("J", "move_watch(1)", show=False),
        Binding("K", "move_watch(-1)", show=False),
        Binding("i", "import_csv", show=False),
        Binding("E", "export_csv", show=False),
        Binding("R", "room", show=False),
        Binding("G", "add_asset", show=False),
        Binding("V", "value_asset", show=False),
        Binding("space", "toggle_alert", show=False),
    ]

    def __init__(self, config: Config, tracker: Tracker | None = None):
        # config and palette must exist before App.__init__ asks for theme variables
        self.config = config
        self.palette = resolve_palette(config.theme)
        super().__init__()
        self.tracker = tracker or Tracker.open(config)
        self._auto_theme = config.theme in ("auto", "omarchy", "")
        self._rich_theme_pushed = False
        self._mp_ready = False
        self.view: PortfolioView | None = None
        self.perf = None
        self.strip: list = []
        self.watch_symbols: list[str] = []
        self.watch_quotes: dict = {}
        self.watch_errors: dict = {}
        self.chart_symbol = ""
        self.chart_period = config.chart_period if config.chart_period in PERIODS else "3mo"
        self.compare: list[str] = []
        self.account_filter: int | None = None
        self.alloc_mode = "class"
        self.nw_range = "1y"
        self.flash: dict[str, int] = {}
        self._prev_prices: dict[str, float] = {}
        self._detail_bars: dict[str, list] = {}
        self._detail_key: str | None = None
        self._watch_key: str | None = None
        self._income_forecast: list | None = None
        self._tax: tuple | None = None
        self._last_error = ""
        for name in theme_names():
            self.register_theme(textual_theme(palette_from_colors(name, OMARCHY_PALETTES[name])))
        if self.palette.name not in OMARCHY_PALETTES:
            self.register_theme(textual_theme(self.palette))
        self._push_rich_theme()

    # ── theme plumbing ────────────────────────────────────────────────────────

    def get_theme_variable_defaults(self) -> dict[str, str]:
        p = self.palette
        return {
            "mp-up": p.up,
            "mp-down": p.down,
            "mp-muted": p.muted,
            "mp-border": p.border,
            "mp-selection": p.selection,
            "mp-bright": p.bright,
            "mp-panel": p.panel,
            "mp-surface": p.surface,
        }

    def _push_rich_theme(self) -> None:
        if self._rich_theme_pushed:
            self.console.pop_theme()
        self.console.push_theme(RichTheme(rich_styles(self.palette)))
        self._rich_theme_pushed = True

    def watch_theme(self, name: str) -> None:
        if name in OMARCHY_PALETTES:
            self.palette = palette_from_colors(name, OMARCHY_PALETTES[name])
        elif name != self.palette.name:
            return
        self._push_rich_theme()
        if not self._mp_ready:
            return
        auto_name = resolve_palette("auto").name
        if not (self._auto_theme and name == auto_name) and self.config.theme != name:
            self.config.theme = name
            self._auto_theme = False
            self.config.save()
        self.refresh_all_views()

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield TopBar(id="topbar")
        with ContentSwitcher(initial="dashboard", id="workspaces"):
            with Vertical(id="dashboard"):
                yield Static(id="strip")
                with Horizontal(id="tiles"):
                    yield Tile(id="tile-networth")
                    yield Tile(id="tile-today")
                    yield Tile(id="tile-unrealized")
                    yield Tile(id="tile-income")
                    yield Tile(id="tile-returns")
                with Horizontal():
                    with Vertical(classes="col-main"):
                        yield pane(Canvas(id="nw-chart"), title="net worth", id="pane-nw")
                        yield pane(VerticalScroll(Static(id="dash-accounts")), title="accounts", id="pane-accounts")
                    with Vertical(classes="col-side", id="dash-side"):
                        yield pane(Canvas(id="alloc"), title="allocation", id="pane-alloc")
                        yield pane(Static(id="movers"), title="movers", id="pane-movers")
                        yield pane(Static(id="perf"), title="returns", id="pane-perf")
            with Horizontal(id="holdings"):
                yield pane(DataTable(id="holdings-table"), title="holdings", id="pane-holdings", classes="col-main")
                yield pane(VerticalScroll(Static(id="holding-detail")), title="position", classes="col-side detail")
            with Horizontal(id="watchlist"):
                yield pane(DataTable(id="watch-table"), title="watchlist", id="pane-watch", classes="col-main")
                yield pane(VerticalScroll(Static(id="watch-detail")), title="quote", classes="col-side detail")
            with Vertical(id="chart"):
                with Horizontal(id="chart-head"):
                    yield Input(placeholder="SYMBOL [period] [vs SYM…]   e.g. NVDA 1y vs QQQ", id="chart-input")
                    yield Static(id="chart-periods")
                yield pane(ChartView(id="chart-view"), title="chart", id="pane-chart")
                yield Static(id="chart-info")
            with Vertical(id="activity"):
                yield Input(placeholder="filter by symbol, account, type or note…", id="activity-filter")
                yield pane(DataTable(id="activity-table"), title="activity", id="pane-activity")
            with VerticalScroll(id="income"):
                yield pane(Static(id="income-view"), title="income", id="pane-income")
            with Horizontal(id="tax"):
                yield pane(DataTable(id="accounts-table"), title="accounts", id="pane-accts", classes="col-side")
                yield pane(VerticalScroll(Static(id="tax-view")), title="tax & contribution room", classes="col-main")
            with Vertical(id="alerts"):
                yield pane(DataTable(id="alerts-table"), title="alerts", id="pane-alerts")
        yield Static(id="hints")

    def on_mount(self) -> None:
        try:
            self.theme = self.palette.name
        except Exception:  # pragma: no cover - theme registry failure falls back to Textual default
            pass
        for name in list(self.available_themes):
            if name not in OMARCHY_PALETTES and name != self.palette.name:
                try:
                    self.unregister_theme(name)
                except Exception:
                    pass
        columns = {
            "#holdings-table": [
                h if isinstance(h, str) else h[0] for i, h in enumerate(render.POSITION_HEADERS) if i in HOLDING_COLUMNS
            ],
            "#watch-table": [h if isinstance(h, str) else h[0] for h in render.QUOTE_HEADERS],
            "#activity-table": [h if isinstance(h, str) else h[0] for h in render.ACTIVITY_HEADERS],
            "#accounts-table": ["ID", "Account", "Type", "Value", "Today"],
            "#alerts-table": ["ID", "Alert", "State", "Last", "Note"],
        }
        for selector, cols in columns.items():
            table = self.query_one(selector, DataTable)
            table.cursor_type = "row"
            table.add_columns(*cols)
        self._mp_ready = True
        self.set_class(self.size.width < 130, "-narrow")
        self.set_workspace("dashboard")
        self.render_store_views()
        self.render_dashboard()
        self.set_interval(1.0, self._tick)
        self.set_interval(max(self.config.refresh_seconds, 5), self.load_data)
        self.load_data()

    def on_resize(self, event) -> None:
        self.set_class(event.size.width < 130, "-narrow")

    def _tick(self) -> None:
        self.query_one(TopBar).refresh()

    # ── helpers ───────────────────────────────────────────────────────────────

    @property
    def workspace(self) -> str:
        return self.query_one("#workspaces", ContentSwitcher).current or "dashboard"

    @property
    def privacy(self) -> bool:
        return self.config.privacy

    def known_symbols(self) -> list[str]:
        held = {p.symbol for p in self.view.positions} if self.view else set(self.tracker.store.ledger().symbols())
        return sorted(held | set(self.tracker.store.watchlist()))

    @staticmethod
    def _selected_key(table: DataTable) -> str | None:
        if table.row_count == 0:
            return None
        try:
            return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:
            return None

    @staticmethod
    def _restore_cursor(table: DataTable, key: str | None) -> None:
        if key is None:
            return
        try:
            table.move_cursor(row=table.get_row_index(key), animate=False)
        except Exception:
            pass

    @staticmethod
    def _justify(cells: list[Text], indexes) -> list[Text]:
        for i in indexes:
            cells[i].justify = "right"
        return cells

    def _trend_hex(self, value: float | None) -> str:
        if value is None or abs(value) < 1e-12:
            return self.palette.muted
        return self.palette.up if value > 0 else self.palette.down

    def context_symbol(self) -> str:
        ws = self.workspace
        if ws == "holdings":
            key = self._selected_key(self.query_one("#holdings-table", DataTable))
            return key.split(":", 1)[1] if key and not key.startswith("cash:") else ""
        if ws == "watchlist":
            return self._selected_key(self.query_one("#watch-table", DataTable)) or ""
        if ws == "chart":
            return self.chart_symbol
        if ws == "activity":
            key = self._selected_key(self.query_one("#activity-table", DataTable))
            txn = next((t for t in self.tracker.store.transactions() if str(t.id) == key), None)
            return txn.symbol if txn else ""
        if ws == "alerts":
            key = self._selected_key(self.query_one("#alerts-table", DataTable))
            alert = next((a for a in self.tracker.store.alerts() if str(a.id) == key), None)
            return alert.symbol if alert else ""
        return ""

    def context_account(self) -> int | None:
        if self.workspace == "holdings":
            key = self._selected_key(self.query_one("#holdings-table", DataTable))
            if key and not key.startswith("cash:"):
                return int(key.split(":", 1)[0])
        return self.account_filter

    # ── workspaces ────────────────────────────────────────────────────────────

    def action_workspace(self, name: str) -> None:
        self.set_workspace(name)

    def set_workspace(self, name: str) -> None:
        self.query_one("#workspaces", ContentSwitcher).current = name
        bar = self.query_one(TopBar)
        bar.active = name
        bar.refresh()
        self._render_hints(name)
        focus = {
            "holdings": "#holdings-table",
            "watchlist": "#watch-table",
            "chart": "#chart-view",
            "activity": "#activity-table",
            "tax": "#accounts-table",
            "alerts": "#alerts-table",
        }.get(name)
        if focus:
            self.query_one(focus).focus()
        else:
            self.set_focus(None)
        if name == "income" and self._income_forecast is None and self.view is not None:
            self.load_income()
        if name == "tax" and self._tax is None:
            self.load_tax()

    def _render_hints(self, ws: str) -> None:
        p = self.palette
        t = Text(" ")
        for i, chunk in enumerate(HINTS.get(ws, "").split(" · ")):
            if i:
                t.append("   ")
            key, _, desc = chunk.partition(" ")
            t.append(key, style=f"bold {p.accent}")
            t.append(f" {desc}", style=p.muted)
        tail = Text("1-8 ", style=f"bold {p.accent}")
        tail.append("workspaces   ", style=p.muted)
        tail.append("^p ", style=f"bold {p.accent}")
        tail.append("commands   ", style=p.muted)
        tail.append("? ", style=f"bold {p.accent}")
        tail.append("help ", style=p.muted)
        width = self.size.width
        gap = width - t.cell_len - tail.cell_len
        if gap > 1:
            t.append(" " * gap)
            t.append_text(tail)
        self.query_one("#hints", Static).update(t)

    # ── data loading ──────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        self._income_forecast = None
        self.load_data(force=True)
        if self.workspace == "chart" and self.chart_symbol:
            self.load_chart()

    @work(thread=True, exclusive=True, group="data")
    def load_data(self, force: bool = False) -> None:
        tr = self.tracker
        self.call_from_thread(self._set_loading, True)
        try:
            view = tr.valuation(use_cache=not force)
            perf = tr.performance(view)
            strip = tr.market_strip(use_cache=not force)
            watch = tr.watchlist_quotes(use_cache=not force)
            fired = tr.check_alerts({**view.quotes, **watch[1]}, notify=True)
        except Exception as e:  # keep the UI alive on any provider/database hiccup
            self.call_from_thread(self.notify, str(e), title="Refresh failed", severity="error")
            self.call_from_thread(self._set_loading, False)
            return
        self.call_from_thread(self._apply_data, view, perf, strip, watch, fired)

    def _set_loading(self, loading: bool) -> None:
        bar = self.query_one(TopBar)
        bar.loading = loading
        bar.refresh()

    def _apply_data(self, view: PortfolioView, perf, strip, watch, fired) -> None:
        symbols, quotes, errors = watch
        prices = {s: q.price for s, q in {**view.quotes, **quotes}.items()}
        self.flash = {
            s: (1 if price > self._prev_prices[s] else -1)
            for s, price in prices.items()
            if s in self._prev_prices and abs(price - self._prev_prices[s]) > 1e-9
        }
        self._prev_prices = prices
        self.view, self.perf, self.strip = view, perf, strip
        self.watch_symbols, self.watch_quotes, self.watch_errors = symbols, quotes, errors
        for alert in fired:
            self.notify(alert.note or alert.describe(), title=f"Alert · {alert.symbol}", severity="warning", timeout=12)
        problems = sorted(set(view.errors.values()))
        if problems and problems[0] != self._last_error:
            self.notify(problems[0], title="Market data", severity="warning")
        self._last_error = problems[0] if problems else ""
        self._set_loading(False)
        self.render_market_views()
        if self.flash:
            self.set_timer(1.6, self._clear_flash)

    def _clear_flash(self) -> None:
        self.flash = {}
        self.render_holdings()
        self.render_watchlist()

    def after_change(self, message: str | None = None) -> None:
        if message:
            self.notify(message)
        self._tax = None
        self._income_forecast = None
        self.render_store_views()
        self.load_data()
        if self.workspace == "tax":
            self.load_tax()

    # ── rendering ─────────────────────────────────────────────────────────────

    def refresh_all_views(self) -> None:
        self._render_hints(self.workspace)
        self.render_store_views()
        self.render_market_views()
        self.query_one(ChartView).refresh()
        self.query_one(TopBar).refresh()

    def render_store_views(self) -> None:
        self.render_activity()
        self.render_accounts()
        self.render_alerts()
        self.render_tax()

    def render_market_views(self) -> None:
        self._render_topbar_status()
        self.render_dashboard()
        self.render_holdings()
        self.render_watchlist()
        self.render_accounts()
        self.render_alerts()
        self.render_income()
        self.render_position_detail()
        self.render_watch_detail()

    def _render_topbar_status(self) -> None:
        p, v = self.palette, self.view
        t = Text()
        if v is not None:
            state = {"REGULAR": ("●", p.up), "PRE": ("◐", p.warn), "POST": ("◑", p.warn), "CLOSED": ("○", p.muted)}.get(
                v.market_state
            )
            if state:
                t.append(f"{state[0]} ", style=state[1])
            t.append(fmt.money(v.net_worth, v.base, privacy=self.privacy, decimals=0), style=f"bold {p.bright}")
            t.append(
                f"  {fmt.arrow(v.day_change)} {fmt.pct(v.day_change_pct)}",
                style=f"bold {self._trend_hex(v.day_change)}",
            )
            if v.stale:
                t.append("  ◌ offline", style=p.warn)
        if self.privacy:
            t.append("  ◉ private", style=p.accent)
        bar = self.query_one(TopBar)
        bar.status = t
        bar.refresh()

    def _snapshots(self) -> list:
        today = date.today()
        since = {
            "1m": today - timedelta(days=31),
            "3m": today - timedelta(days=92),
            "6m": today - timedelta(days=183),
            "ytd": date(today.year, 1, 1),
            "1y": today - timedelta(days=366),
            "all": None,
        }[self.nw_range]
        base = self.tracker.base
        return [s for s in self.tracker.store.snapshots(since.isoformat() if since else None) if s.currency == base]

    def render_dashboard(self) -> None:
        v, p, priv = self.view, self.palette, self.privacy
        if v is None:
            self.query_one("#nw-chart", Canvas).set_builder(lambda w, h: Text("Loading portfolio…", style="muted"))
            return
        strip = render.strip_text(self.strip)
        strip.append("   ")
        strip.append_text(render.market_state_text(v.market_state))
        self.query_one("#strip", Static).update(strip)

        sub = Text(f"invested {fmt.money(v.invested, v.base, privacy=priv, decimals=0)}", style="muted")
        if v.stale:
            sub.append("  ◌ offline", style="warn")
        self.query_one("#tile-networth", Tile).set_builder(
            money_tile(f"net worth · {v.base}", v.net_worth, v.base, sub, privacy=priv)
        )

        def tile(label: str, value: Text, sub_text: Text | None):
            return lambda w, h: tile_content(label, value, sub_text, w)

        today_value = Text(
            f"{fmt.arrow(v.day_change)} {fmt.money(v.day_change, v.base, sign=True, privacy=priv)}",
            style=f"bold {self._trend_hex(v.day_change)}",
        )
        self.query_one("#tile-today", Tile).set_builder(
            tile("today", today_value, Text(fmt.pct(v.day_change_pct), style=self._trend_hex(v.day_change)))
        )
        unreal = Text(
            fmt.money(v.unrealized, v.base, sign=True, privacy=priv), style=f"bold {self._trend_hex(v.unrealized)}"
        )
        self.query_one("#tile-unrealized", Tile).set_builder(
            tile("unrealized", unreal, Text(fmt.pct(v.unrealized_pct), style=self._trend_hex(v.unrealized)))
        )
        income = Text(fmt.money(v.income_ytd, v.base, privacy=priv), style=f"bold {p.up if v.income_ytd else p.muted}")
        realized = Text(f"realized {fmt.money(v.realized_ytd, v.base, sign=True, privacy=priv)}", style="muted")
        self.query_one("#tile-income", Tile).set_builder(tile("income ytd", income, realized))
        perf = self.perf
        if perf is not None and perf.xirr_pct is not None:
            ret = Text(f"{fmt.pct(perf.xirr_pct)}/yr", style=f"bold {self._trend_hex(perf.xirr_pct)}")
            ret_sub = Text(f"twr {fmt.pct(perf.twr_pct)}", style="muted")
        else:
            ret = Text(fmt.pct(v.unrealized_pct), style=f"bold {self._trend_hex(v.unrealized)}")
            ret_sub = Text("simple return", style="muted")
        self.query_one("#tile-returns", Tile).set_builder(tile("returns", ret, ret_sub))

        snaps = self._snapshots()
        empty = not v.positions and not v.cash

        def nw_chart(w: int, h: int) -> RenderableType:
            if empty:
                return Text.assemble(
                    ("Welcome to MarketPulse.\n\n", "title"),
                    ("n ", "accent"),
                    ("record your first buy     ", "muted"),
                    ("ctrl+p ", "accent"),
                    ("new account, GIC or import CSV     ", "muted"),
                    ("/ ", "accent"),
                    ("search any symbol", "muted"),
                )
            if len(snaps) < 2:
                return Text(
                    "History builds daily. ctrl+p → “Backfill net worth history” rebuilds it now.", style="muted"
                )
            change = snaps[-1].net_worth - snaps[0].net_worth
            pct = change / snaps[0].net_worth * 100 if snaps[0].net_worth else 0.0
            head = Text(
                f"{fmt.arrow(change)} {fmt.money(change, v.base, sign=True, privacy=priv)} ({fmt.pct(pct)})",
                style=self._trend_hex(change),
            )
            return Group(head, render.net_worth_chart(snaps, p, width=w, height=max(h - 2, 3), privacy=priv))

        self.query_one("#nw-chart", Canvas).set_builder(nw_chart)
        self.query_one("#pane-nw").border_subtitle = "  ".join(f"▸{r}" if r == self.nw_range else r for r in NW_RANGES)

        accounts = render.table("Account", "Type", ("Value", "right"), ("Today", "right"), "Weight", expand=True)
        acct_types = {str(a.id): a.type.label for a in self.tracker.store.accounts(include_archived=True)}
        for b in v.by_account:
            accounts.add_row(
                Text(b.label, style="bright"),
                Text(acct_types.get(b.key, ""), style="muted"),
                Text(fmt.money(b.value, v.base, privacy=priv)),
                render.trend(fmt.pct(b.day_change_pct), b.day_change),
                render.weight_cell(b.weight, 10),
            )
        self.query_one("#dash-accounts", Static).update(
            accounts if v.by_account else Text("No accounts with holdings yet.", style="muted")
        )

        breakdown = {"class": v.by_class, "account": v.by_account, "currency": v.by_currency}[self.alloc_mode]
        alloc = self.query_one("#alloc", Canvas)
        alloc.styles.height = max(len(breakdown), 1) + 1  # bar + one legend row per bucket
        alloc.set_builder(lambda w, h: render.allocation(breakdown, p, width=max(w - 1, 10), privacy=priv, base=v.base))
        self.query_one("#pane-alloc").border_subtitle = f"g ▸ {self.alloc_mode}"

        movers = Text()
        for i, pos in enumerate(v.movers(6)):
            if i:
                movers.append("\n")
            movers.append(f"{pos.symbol:<10}", style="bright")
            q = pos.quote
            if q and q.intraday:
                from ..charts import sparkline

                movers.append_text(sparkline(q.intraday, 12, self._trend_hex(q.change)))
            movers.append(
                f"  {fmt.arrow(pos.day_change_pct)} {fmt.pct(pos.day_change_pct):>8}",
                style=self._trend_hex(pos.day_change_pct),
            )
        self.query_one("#movers", Static).update(
            movers if movers.plain else Text("No market-priced holdings.", style="muted")
        )

        grid = Table.grid(padding=(0, 2), expand=True)
        grid.add_column(ratio=1)
        grid.add_column(justify="right")
        if perf is not None:
            rows = [
                (
                    "money-weighted",
                    render.trend(f"{fmt.pct(perf.xirr_pct)}/yr" if perf.xirr_pct is not None else "—", perf.xirr_pct),
                ),
                ("time-weighted", render.trend(fmt.pct(perf.twr_pct), perf.twr_pct)),
                (
                    "max drawdown",
                    Text(fmt.pct(perf.max_drawdown_pct), style="down" if perf.max_drawdown_pct else "muted"),
                ),
                ("volatility", Text(fmt.pct(perf.volatility_pct, sign=False), style="muted")),
                (
                    "total gain",
                    render.trend(fmt.money(perf.total_gain, v.base, sign=True, privacy=priv), perf.total_gain),
                ),
            ]
            for label, value in rows:
                grid.add_row(Text(label, style="muted"), value)
        self.query_one("#perf", Static).update(grid)

    def render_holdings(self) -> None:
        v = self.view
        table = self.query_one("#holdings-table", DataTable)
        if v is None:
            return
        selected = self._selected_key(table)
        table.clear()
        positions = [p for p in v.positions if self.account_filter is None or p.account.id == self.account_filter]
        p = self.palette
        for pos in sorted(positions, key=lambda x: (x.account.name, -(x.value_base or 0))):
            cells = render.position_cells(pos, v.base, privacy=self.privacy)
            direction = self.flash.get(pos.symbol)
            if direction and pos.price is not None:
                cells[5] = Text(cells[5].plain, style=f"bold {p.background} on {p.up if direction > 0 else p.down}")
            row = self._justify([cells[i] for i in HOLDING_COLUMNS], range(2, 8))
            table.add_row(*row, key=f"{pos.account.id}:{pos.symbol}")
        for c in v.cash:
            if self.account_filter is not None and c.account.id != self.account_filter:
                continue
            cash_value = fmt.money(c.amount, privacy=self.privacy) + (f" {c.currency}" if c.currency != v.base else "")
            cells = [
                Text(render.truncate(c.account.name, 12), style="muted"),
                Text("CASH", style="info"),
                Text(f"{c.currency} balance", style="muted"),
                *(render.dash() for _ in range(4)),
                Text(cash_value),
                render.dash(),
                render.dash(),
                render.weight_cell((c.amount_base or 0) / v.net_worth * 100 if v.net_worth else 0),
            ]
            row = self._justify([cells[i] for i in HOLDING_COLUMNS], range(2, 8))
            table.add_row(*row, key=f"cash:{c.account.id}:{c.currency}")
        self._restore_cursor(table, selected)
        scope = "all accounts"
        if self.account_filter is not None:
            acct = self.tracker.store.get_account(self.account_filter)
            scope = acct.name if acct else scope
        total = sum(x.value_base or 0 for x in positions)
        self.query_one(
            "#pane-holdings"
        ).border_subtitle = (
            f"f ▸ {scope} · {len(positions)} positions · {fmt.money(total, v.base, privacy=self.privacy, decimals=0)}"
        )
        if self._detail_key is None and positions:
            first = self._selected_key(table)
            if first and not first.startswith("cash:"):
                self._show_position(first)

    def render_watchlist(self) -> None:
        table = self.query_one("#watch-table", DataTable)
        selected = self._selected_key(table)
        table.clear()
        p = self.palette
        for sym in self.watch_symbols:
            q = self.watch_quotes.get(sym)
            if q is None:
                cells = render.missing_quote_cells(sym, self.watch_errors.get(sym, "loading…"))
            else:
                cells = render.quote_cells(q, spark_width=18)
                direction = self.flash.get(sym)
                if direction:
                    cells[2] = Text(cells[2].plain, style=f"bold {p.background} on {p.up if direction > 0 else p.down}")
            table.add_row(*self._justify(cells, range(2, 5)), key=sym)
        self._restore_cursor(table, selected)
        self.query_one("#pane-watch").border_subtitle = f"{len(self.watch_symbols)} symbols"
        if self._watch_key is None and self.watch_symbols:
            self._show_watch(self.watch_symbols[0])

    def render_activity(self) -> None:
        table = self.query_one("#activity-table", DataTable)
        selected = self._selected_key(table)
        table.clear()
        store = self.tracker.store
        accounts = store.account_map()
        needle = self.query_one("#activity-filter", Input).value.strip().lower()
        txns = sorted(store.transactions(), key=lambda t: (t.date, t.id or 0), reverse=True)
        shown = 0
        for t in txns:
            cells = render.activity_cells(t, accounts, privacy=self.privacy)
            if needle and needle not in " ".join(c.plain.lower() for c in cells):
                continue
            table.add_row(*self._justify(cells, (0, 5, 6, 7, 8)), key=str(t.id))
            shown += 1
        self._restore_cursor(table, selected)
        issues = store.ledger().issues
        subtitle = f"{shown} of {len(txns)} transactions"
        if issues:
            subtitle += f" · ⚠ {len(issues)} ledger issue(s)"
        self.query_one("#pane-activity").border_subtitle = subtitle

    def render_accounts(self) -> None:
        table = self.query_one("#accounts-table", DataTable)
        selected = self._selected_key(table)
        table.clear()
        values = {b.key: b for b in self.view.by_account} if self.view else {}
        base = self.tracker.base
        for a in self.tracker.store.accounts(include_archived=True):
            b = values.get(str(a.id))
            # Currency and cash tracking live in the edit form (e) to keep this pane narrow
            cells = [
                Text(str(a.id), style="muted"),
                Text(a.name + (" (archived)" if a.archived else ""), style="bright"),
                Text(a.type.label, style="accent" if a.type.registered else ""),
                Text(fmt.money(b.value, base, privacy=self.privacy)) if b else render.dash(),
                render.trend(fmt.pct(b.day_change_pct), b.day_change) if b else render.dash(),
            ]
            table.add_row(*self._justify(cells, (0, 3, 4)), key=str(a.id))
        self._restore_cursor(table, selected)

    def render_alerts(self) -> None:
        table = self.query_one("#alerts-table", DataTable)
        selected = self._selected_key(table)
        table.clear()
        quotes = {**(self.view.quotes if self.view else {}), **self.watch_quotes}
        for a in self.tracker.store.alerts():
            q = quotes.get(a.symbol)
            state = (
                Text("● triggered", style="warn")
                if a.triggered_at
                else Text("armed" if a.active else "paused", style="muted" if a.active else "down")
            )
            last = render.trend(f"{fmt.price(q.price)} {fmt.pct(q.change_pct)}", q.change) if q else render.dash()
            table.add_row(
                Text(str(a.id), style="muted"),
                Text(a.describe(), style="bright"),
                state,
                last,
                Text(a.note, style="muted"),
                key=str(a.id),
            )
        self._restore_cursor(table, selected)

    def render_position_detail(self) -> None:
        key, v = self._detail_key, self.view
        target = self.query_one("#holding-detail", Static)
        if not key or v is None:
            target.update(Text("Select a holding.", style="muted"))
            return
        acct_id, sym = key.split(":", 1)
        pos: PositionView | None = next(
            (x for x in v.positions if str(x.account.id) == acct_id and x.symbol == sym), None
        )
        if pos is None:
            target.update(Text("Position closed.", style="muted"))
            return
        priv = self.privacy
        width = max(target.size.width, 30)
        head = Text()
        head.append(pos.symbol, style="title")
        head.append(f"  {pos.name}", style="bright")
        parts: list[RenderableType] = [
            head,
            Text(
                f"{pos.account.name} · {pos.asset_class.label} · {pos.kind.value.replace('_', ' ')} · {pos.currency}",
                style="muted",
            ),
        ]
        if pos.price is not None:
            price = Text(fmt.price(pos.price), style="bright")
            if pos.day_change_pct is not None and pos.kind is AssetKind.MARKET:
                price.append(
                    f"  {fmt.arrow(pos.day_change_pct)} {fmt.pct(pos.day_change_pct)} today",
                    style=self._trend_hex(pos.day_change_pct),
                )
            parts += [Text(""), price]
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="muted")
        grid.add_column(justify="right")
        for label, value in (
            ("Quantity", Text(fmt.MASK if priv else fmt.qty(pos.quantity))),
            ("Average cost", Text(fmt.price(pos.avg_cost))),
            ("Book value", Text(fmt.money(pos.book, privacy=priv))),
            ("Market value", Text(fmt.money(pos.market_value, privacy=priv))),
            (
                "Gain",
                render.trend(f"{fmt.money(pos.gain, sign=True, privacy=priv)} ({fmt.pct(pos.gain_pct)})", pos.gain),
            ),
            ("Today", render.trend(fmt.money(pos.day_change, sign=True, privacy=priv), pos.day_change)),
            ("Weight", Text(fmt.pct(pos.weight, sign=False))),
            ("Held since", Text(pos.first_date or "—")),
        ):
            grid.add_row(label, value)
        parts += [Text(""), grid]
        bars = self._detail_bars.get(sym)
        if bars:
            parts += [
                Text(""),
                Text("3 MONTHS", style="muted"),
                render.price_chart(sym, bars, "3mo", self.palette, width=width, height=7),
            ]
        txns = [t for t in self.tracker.store.transactions(symbol=sym) if t.account_id == pos.account.id][-6:]
        if txns:
            lines = Text("\nRECENT\n", style="muted")
            for t in reversed(txns):
                lines.append(f"{t.date}  ", style="muted")
                lines.append(f"{t.type.value:<9}", style=render.TXN_STYLES.get(t.type, ""))
                detail = (
                    f"{fmt.qty(t.quantity)} @ {fmt.price(t.price)}"
                    if t.quantity
                    else fmt.money(t.gross_value, privacy=priv)
                )
                lines.append(f" {detail}\n")
            parts.append(lines)
        target.update(Group(*parts))

    def render_watch_detail(self) -> None:
        target = self.query_one("#watch-detail", Static)
        sym = self._watch_key
        q = self.watch_quotes.get(sym) if sym else None
        if q is None:
            target.update(Text("Select a symbol.", style="muted"))
            return
        parts: list[RenderableType] = [render.quote_card(q)]
        bars = self._detail_bars.get(q.symbol)
        if bars:
            parts += [
                Text(""),
                Text("3 MONTHS", style="muted"),
                render.price_chart(q.symbol, bars, "3mo", self.palette, width=max(target.size.width, 30), height=8),
            ]
        held = [x for x in (self.view.positions if self.view else []) if x.symbol == q.symbol]
        if held:
            qty = sum(x.quantity for x in held)
            parts.append(
                Text(
                    f"\nYou hold {fmt.MASK if self.privacy else fmt.qty(qty)} across {len(held)} account(s).",
                    style="accent",
                )
            )
        target.update(Group(*parts))

    def render_income(self) -> None:
        v = self.view
        if v is None:
            return
        state = self.tracker.store.ledger()
        months = income_by_month(state, v.fx.convert)
        sources = income_by_symbol(state, v.fx.convert, date.today().year)
        body = render.income_group(months, sources, self._income_forecast, v, privacy=self.privacy)
        if self._income_forecast is None:
            body = Group(body, Text("\nForward estimate loads when you open this workspace.", style="muted"))
        self.query_one("#income-view", Static).update(body)

    def render_tax(self) -> None:
        target = self.query_one("#tax-view", Static)
        if self._tax is None:
            target.update(Text("Building tax report…", style="muted"))
            return
        years, warnings, rooms = self._tax
        tr = self.tracker
        body = render.tax_group(years, warnings, rooms, tr.store.account_map(), tr.base, privacy=self.privacy)
        target.update(
            Group(body, Text("\nEstimates only — confirm against broker slips (T5008/T3/T5).", style="muted"))
        )

    # ── lazy workers ──────────────────────────────────────────────────────────

    @work(thread=True, exclusive=True, group="income")
    def load_income(self) -> None:
        view = self.view
        if view is None:
            return
        forecast = self.tracker.income_forecast(view)
        self.call_from_thread(self._income_loaded, forecast)

    def _income_loaded(self, forecast) -> None:
        self._income_forecast = forecast
        self.render_income()

    @work(thread=True, exclusive=True, group="tax")
    def load_tax(self) -> None:
        years, warnings = self.tracker.tax_years()
        rooms = self.tracker.room()
        self.call_from_thread(self._tax_loaded, (years, warnings, rooms))

    def _tax_loaded(self, result) -> None:
        self._tax = result
        self.render_tax()

    @work(thread=True, exclusive=True, group="detail")
    def load_detail_bars(self, symbol: str) -> None:
        try:
            bars = self.tracker.market.history(symbol, "3mo")
        except MarketError:
            bars = []
        self.call_from_thread(self._detail_loaded, symbol, bars)

    def _detail_loaded(self, symbol: str, bars: list) -> None:
        self._detail_bars[symbol] = bars
        self.render_position_detail()
        self.render_watch_detail()

    # ── selection events ──────────────────────────────────────────────────────

    def _show_position(self, key: str) -> None:
        self._detail_key = key
        self.render_position_detail()
        sym = key.split(":", 1)[1]
        assets = self.tracker.store.assets()
        if sym not in self._detail_bars and (sym not in assets or assets[sym].kind is AssetKind.MARKET):
            self.load_detail_bars(sym)

    def _show_watch(self, symbol: str) -> None:
        self._watch_key = symbol
        self.render_watch_detail()
        if symbol not in self._detail_bars:
            self.load_detail_bars(symbol)

    @on(DataTable.RowHighlighted, "#holdings-table")
    def _holding_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key = event.row_key.value
        if key and not key.startswith("cash:") and key != self._detail_key:
            self._show_position(key)

    @on(DataTable.RowHighlighted, "#watch-table")
    def _watch_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key.value and event.row_key.value != self._watch_key:
            self._show_watch(event.row_key.value)

    @on(DataTable.RowSelected)
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value or ""
        table_id = event.data_table.id
        if table_id == "holdings-table" and not key.startswith("cash:"):
            self.open_chart(key.split(":", 1)[1])
        elif table_id == "watch-table":
            self.open_chart(key)
        elif table_id == "activity-table":
            self.action_edit()
        elif table_id == "accounts-table" and key.isdigit():
            self.account_filter = int(key)
            self.render_holdings()
            self.set_workspace("holdings")
        elif table_id == "alerts-table":
            self.open_chart(self.context_symbol())

    @on(Input.Changed, "#activity-filter")
    def _activity_filter(self) -> None:
        self.render_activity()

    @on(Input.Submitted, "#activity-filter")
    def _activity_filter_done(self) -> None:
        self.query_one("#activity-table", DataTable).focus()

    # ── chart ─────────────────────────────────────────────────────────────────

    def open_chart(self, symbol: str, *, compare: list[str] | None = None) -> None:
        if not symbol:
            return
        self.chart_symbol = symbol.upper()
        if compare is not None:
            self.compare = compare
        self.query_one("#chart-input", Input).value = " ".join(
            [self.chart_symbol, self.chart_period, *(["vs", *self.compare] if self.compare else [])]
        )
        self.set_workspace("chart")
        self.query_one(ChartView).set_message(f"Loading {self.chart_symbol} · {self.chart_period}…")
        self.query_one(ChartView).focus()
        self.load_chart()

    @on(Input.Submitted, "#chart-input")
    def _chart_submitted(self, event: Input.Submitted) -> None:
        tokens = event.value.replace(",", " ").split()
        if not tokens:
            return
        symbol, rest = tokens[0], tokens[1:]
        if rest and rest[0].lower() in PERIODS:
            self.chart_period = rest.pop(0).lower()
        if rest and rest[0].lower() == "vs":
            rest = rest[1:]
        self.open_chart(symbol, compare=parse_symbols(" ".join(rest)))

    @work(thread=True, exclusive=True, group="chart")
    def load_chart(self) -> None:
        sym, period, others = self.chart_symbol, self.chart_period, list(self.compare)
        market = self.tracker.market
        view = self.query_one(ChartView)
        try:
            bars = market.history(sym, period)
            compare = {o: market.history(o, period) for o in others}
            quotes, _ = market.quotes([sym])
        except MarketError as e:
            self.call_from_thread(view.set_message, str(e))
            return
        self.call_from_thread(self._chart_loaded, sym, period, bars, quotes.get(sym), compare)

    def _chart_loaded(self, sym, period, bars, quote, compare) -> None:
        if sym != self.chart_symbol or period != self.chart_period:
            return
        self.query_one(ChartView).set_data(sym, period, bars, quote, compare)
        self.render_chart_info(quote)

    def render_chart_info(self, quote=None) -> None:
        p = self.palette
        periods = Text()
        for per in PERIODS:
            if per == self.chart_period:
                periods.append(f" {per} ", style=f"bold {p.background} on {p.accent}")
            else:
                periods.append(f" {per} ", style=p.muted)
        self.query_one("#chart-periods", Static).update(periods)
        info = Text()
        if quote is not None:
            info.append(f"{quote.symbol} ", style="title")
            info.append(f"{quote.name}  ", style="bright")
            info.append(f"{fmt.price(quote.price)} {quote.currency} ", style="bright")
            info.append(f"{fmt.arrow(quote.change)} {fmt.pct(quote.change_pct)}", style=self._trend_hex(quote.change))
        held = [x for x in (self.view.positions if self.view else []) if x.symbol == self.chart_symbol]
        if held:
            qty = sum(x.quantity for x in held)
            gain = sum(x.gain or 0 for x in held)
            info.append(f"   held {fmt.MASK if self.privacy else fmt.qty(qty)} · gain ", style="muted")
            info.append(fmt.money(gain, sign=True, privacy=self.privacy), style=self._trend_hex(gain))
        elif self.chart_symbol:
            info.append("   not held · b buy · w watch", style="muted")
        self.query_one("#chart-info", Static).update(info)
        self.query_one("#pane-chart").border_title = f"chart · {self.chart_symbol}" + (
            f" vs {', '.join(self.compare)}" if self.compare else ""
        )

    def action_period(self, delta: int) -> None:
        if self.workspace != "chart" or not self.chart_symbol:
            return
        self.chart_period = PERIODS[(PERIODS.index(self.chart_period) + delta) % len(PERIODS)]
        self.open_chart(self.chart_symbol)

    def action_compare(self) -> None:
        if self.workspace != "chart" or not self.chart_symbol:
            return

        def done(value: str | None) -> None:
            if value:
                self.open_chart(self.chart_symbol, compare=list(dict.fromkeys([*self.compare, *parse_symbols(value)])))

        self.push_screen(PromptScreen("Compare with", "QQQ XEQT.TO …", hint="Overlays each symbol as % change."), done)

    def action_clear_compare(self) -> None:
        if self.compare:
            self.open_chart(self.chart_symbol, compare=[])

    # ── actions: records ──────────────────────────────────────────────────────

    def action_new(self) -> None:
        ws = self.workspace
        if ws == "tax":
            self.action_new_account()
        elif ws == "alerts":
            self.action_alert()
        else:
            self.action_trade("BUY")

    def action_add(self) -> None:
        ws = self.workspace
        if ws == "watchlist":
            self.action_watch_add(prompt=True)
        elif ws in ("tax", "alerts"):
            self.action_new()

    def action_trade(self, kind: str) -> None:
        form = TransactionForm(
            self.tracker,
            kind=TxnType(kind),
            symbol=self.context_symbol() if TxnType(kind).needs_symbol else "",
            account_id=self.context_account(),
            symbols=self.known_symbols(),
        )
        self.push_screen(form, self._txn_done)

    def _txn_done(self, txn: Transaction | None) -> None:
        if txn is not None:
            self.save_txn(txn)

    @work(thread=True, group="write")
    def save_txn(self, txn: Transaction) -> None:
        tr = self.tracker
        try:
            if txn.id is not None:
                tr.store.update_transaction(txn)
                message = f"Updated transaction #{txn.id}"
            else:
                saved = tr.add_transaction(txn)
                acct = tr.store.get_account(saved.account_id)
                what = (
                    f"{fmt.qty(saved.quantity)} {saved.symbol} @ {fmt.price(saved.price)}"
                    if saved.quantity
                    else f"{fmt.money(saved.gross_value)} {saved.symbol}".strip()
                )
                message = f"{saved.type.value.title()} {what} {saved.currency} → {acct.name if acct else ''}"
        except (ValueError, MarketError) as e:
            self.call_from_thread(self.notify, str(e), title="Not saved", severity="error")
            return
        self.call_from_thread(self.after_change, message)

    def action_edit(self) -> None:
        ws = self.workspace
        if ws == "activity":
            key = self._selected_key(self.query_one("#activity-table", DataTable))
            txn = next((t for t in self.tracker.store.transactions() if str(t.id) == key), None)
            if txn:
                self.push_screen(TransactionForm(self.tracker, txn=txn, symbols=self.known_symbols()), self._txn_done)
        elif ws == "tax":
            key = self._selected_key(self.query_one("#accounts-table", DataTable))
            acct = self.tracker.store.get_account(int(key)) if key else None
            if acct:
                self.push_screen(AccountForm(acct, self.tracker.base), self._account_done)

    def action_delete(self) -> None:
        ws, store = self.workspace, self.tracker.store
        if ws == "activity":
            key = self._selected_key(self.query_one("#activity-table", DataTable))
            txn = next((t for t in store.transactions() if str(t.id) == key), None)
            if txn is None:
                return
            detail = " ".join(c.plain for c in render.activity_cells(txn, store.account_map())[1:8] if c.plain != "—")

            def done(yes: bool) -> None:
                if yes:
                    store.delete_transaction(txn.id)
                    self.after_change(f"Deleted transaction #{txn.id}")

            self.push_screen(ConfirmScreen(f"Delete transaction #{txn.id}?", detail), done)
        elif ws == "watchlist":
            sym = self.context_symbol()
            if sym:
                store.remove_watch([sym])
                self._watch_key = None
                self.watch_symbols = [s for s in self.watch_symbols if s != sym]
                self.render_watchlist()
                self.notify(f"Removed {sym} from watchlist")
        elif ws == "alerts":
            key = self._selected_key(self.query_one("#alerts-table", DataTable))
            if key:
                store.delete_alert(int(key))
                self.render_alerts()
                self.notify("Alert removed")
        elif ws == "tax":
            key = self._selected_key(self.query_one("#accounts-table", DataTable))
            acct = store.get_account(int(key)) if key else None
            if acct is None:
                return
            count = len([t for t in store.transactions() if t.account_id == acct.id])

            def confirmed(yes: bool) -> None:
                if yes:
                    store.delete_account(acct.id)
                    self.after_change(f"Deleted {acct.name}")

            self.push_screen(
                ConfirmScreen(
                    f"Delete {acct.name}?", f"This removes {count} transaction(s). Archiving (e → edit) keeps history."
                ),
                confirmed,
            )

    def action_undo(self) -> None:
        store = self.tracker.store
        txns = store.transactions()
        if not txns:
            self.notify("Nothing to undo.")
            return
        last = max(txns, key=lambda t: t.id or 0)
        detail = " ".join(c.plain for c in render.activity_cells(last, store.account_map())[1:8] if c.plain != "—")

        def done(yes: bool) -> None:
            if yes:
                store.delete_transaction(last.id)
                self.after_change(f"Undid transaction #{last.id}")

        self.push_screen(ConfirmScreen("Undo the last transaction?", detail), done)

    def action_new_account(self) -> None:
        self.push_screen(AccountForm(None, self.tracker.base), self._account_done)

    def _account_done(self, account) -> None:
        if account is None:
            return
        store = self.tracker.store
        try:
            if account.id is None:
                store.add_account(account)
                message = f"Added account {account.name}"
            else:
                store.update_account(account)
                message = f"Updated {account.name}"
        except ValueError as e:
            self.notify(str(e), severity="error")
            return
        self.after_change(message)

    def action_add_asset(self) -> None:
        accounts = self.tracker.store.accounts() or [self.tracker.store.ensure_default_account(self.tracker.base)]

        def done(result) -> None:
            if result is None:
                return
            asset, txn = result
            self.tracker.store.upsert_asset(asset)
            try:
                self.tracker.add_transaction(txn)
            except ValueError as e:
                self.notify(str(e), severity="error")
                return
            self.after_change(f"Added {asset.name}")

        self.push_screen(AssetForm(accounts), done)

    def action_value_asset(self) -> None:
        manual = [a.symbol for a in self.tracker.store.assets().values() if a.kind is AssetKind.MANUAL]
        if not manual:
            self.notify("No manual assets yet — ctrl+p → Add GIC or manual asset.")
            return

        def done(value: str | None) -> None:
            if not value:
                return
            parts = value.split()
            try:
                sym, amount = parts[0].upper(), float(parts[1].replace(",", ""))
                when = parse_date(parts[2] if len(parts) > 2 else None)
            except (IndexError, ValueError):
                self.notify("Use: SYMBOL VALUE [DATE]", severity="error")
                return
            holders = [h for h in self.tracker.store.ledger().open_holdings() if h.symbol == sym]
            if not holders:
                self.notify(f"No holding of {sym}.", severity="error")
                return
            self.tracker.store.add_transaction(
                Transaction(
                    account_id=holders[0].account_id,
                    type=TxnType.VALUATION,
                    date=when,
                    symbol=sym,
                    price=amount,
                    currency=holders[0].currency,
                )
            )
            self.after_change(f"{sym} valued at {fmt.money(amount)}")

        self.push_screen(
            PromptScreen(
                "Update manual asset value",
                "SYMBOL VALUE [DATE]",
                manual[0] + " ",
                hint=f"Manual assets: {', '.join(manual)}",
            ),
            done,
        )

    def action_room(self) -> None:
        def done(result) -> None:
            if result:
                self.tracker.store.set_room(*result)
                self.after_change(f"{result[0]} room saved")

        self.push_screen(RoomForm(), done)

    def action_alert(self) -> None:
        def done(alert) -> None:
            if alert is not None:
                self.tracker.store.add_alert(alert)
                self.render_alerts()
                self.notify(f"Alert set: {alert.describe()}")

        self.push_screen(AlertForm(self.context_symbol()), done)

    def action_toggle_alert(self) -> None:
        if self.workspace != "alerts":
            return
        key = self._selected_key(self.query_one("#alerts-table", DataTable))
        alert = next((a for a in self.tracker.store.alerts() if str(a.id) == key), None)
        if alert:
            alert.active = not alert.active
            alert.triggered_at = ""
            self.tracker.store.update_alert(alert)
            self.render_alerts()

    def action_watch_add(self, prompt: bool = False) -> None:
        sym = "" if prompt else self.context_symbol()

        def add(symbol: str | None) -> None:
            if not symbol:
                return
            added = self.tracker.store.add_watch([symbol])
            self.notify(f"Watching {symbol}" if added else f"{symbol} is already on the watchlist")
            if added:
                self.watch_symbols = self.tracker.store.watchlist()
                self.render_watchlist()
                self.load_data()

        if sym:
            add(sym)
        else:
            self.push_screen(SearchScreen(self.tracker, self.known_symbols(), "Add to watchlist"), add)

    def action_move_watch(self, delta: int) -> None:
        if self.workspace != "watchlist":
            return
        sym = self.context_symbol()
        if sym:
            self.tracker.store.move_watch(sym, delta)
            self.watch_symbols = self.tracker.store.watchlist()
            self.render_watchlist()

    def action_search(self) -> None:
        if self.workspace == "activity":
            self.query_one("#activity-filter", Input).focus()
            return
        self.push_screen(
            SearchScreen(self.tracker, self.known_symbols(), "Open chart"), lambda s: s and self.open_chart(s)
        )

    def action_filter_account(self) -> None:
        ids = [None, *(a.id for a in self.tracker.store.accounts())]
        self.account_filter = (
            ids[(ids.index(self.account_filter) + 1) % len(ids)] if self.account_filter in ids else None
        )
        self._detail_key = None
        self.render_holdings()
        if self.workspace != "holdings":
            self.set_workspace("holdings")

    def action_cycle_alloc(self) -> None:
        self.alloc_mode = ALLOC_MODES[(ALLOC_MODES.index(self.alloc_mode) + 1) % len(ALLOC_MODES)]
        self.render_dashboard()

    def action_nw_range(self, delta: int) -> None:
        if self.workspace != "dashboard":
            return
        self.nw_range = NW_RANGES[max(0, min(len(NW_RANGES) - 1, NW_RANGES.index(self.nw_range) + delta))]
        self.render_dashboard()

    # ── actions: data & app ───────────────────────────────────────────────────

    def action_import_csv(self) -> None:
        def done(path: str | None) -> None:
            if path:
                self.import_csv(path)

        self.push_screen(
            PromptScreen(
                "Import transactions from CSV",
                "~/Downloads/activities.csv",
                hint="Recognizes common broker columns; duplicates are skipped.",
            ),
            done,
        )

    @work(thread=True, group="write")
    def import_csv(self, path: str) -> None:
        from ..csvio import import_transactions

        store = self.tracker.store
        try:
            result = import_transactions(
                store, Path(path).expanduser(), default_account=(store.accounts() or [None])[0]
            )
        except (OSError, ValueError) as e:
            self.call_from_thread(self.notify, str(e), title="Import failed", severity="error")
            return
        message = f"Imported {result.added} · {result.duplicates} duplicates · {len(result.skipped)} skipped"
        if result.backup is not None:
            # Same safety net as the CLI: name the file that undoes this import.
            message += f"\nbackup: {result.backup.name}"
        self.call_from_thread(self.after_change, message)

    def action_export_csv(self) -> None:
        default = str(Path.home() / f"marketpulse-{date.today():%Y%m%d}.csv")

        def done(path: str | None) -> None:
            if not path:
                return
            from ..csvio import export_transactions

            target = Path(path).expanduser()
            try:
                with target.open("w", newline="") as f:
                    n = export_transactions(self.tracker.store, f)
            except OSError as e:
                self.notify(str(e), severity="error")
                return
            self.notify(f"Exported {n} transactions → {target}")

        self.push_screen(PromptScreen("Export ledger to CSV", default, default), done)

    @work(thread=True, exclusive=True, group="backfill")
    def action_backfill(self) -> None:
        self.call_from_thread(self.notify, "Rebuilding history from your ledger…", title="Backfill")
        try:
            n = self.tracker.backfill()
        except Exception as e:
            self.call_from_thread(self.notify, str(e), title="Backfill failed", severity="error")
            return
        self.call_from_thread(self.after_change, f"Rebuilt {n:,} daily snapshots")

    def action_privacy(self) -> None:
        self.config.privacy = not self.config.privacy
        self.config.save()
        self.refresh_all_views()
        self.notify("Privacy mode on — amounts hidden" if self.privacy else "Privacy mode off")

    def action_next_theme(self) -> None:
        names = theme_names()
        current = self.theme if self.theme in names else names[0]
        self.theme = names[(names.index(current) + 1) % len(names)]
        self.notify(pretty_name(self.theme), title="Theme", timeout=2)

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def notify_desktop(self, title: str, message: str) -> None:
        desktop_notify(title, message)
