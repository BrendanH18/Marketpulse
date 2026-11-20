"""MarketPulse TUI: Omarchy-styled workspaces over the Tracker service."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import replace
from datetime import date

from rich.text import Text
from rich.theme import Theme as RichTheme
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widgets import ContentSwitcher, DataTable, Input, Static
from textual.worker import Worker, get_current_worker

from .. import render
from ..config import Config
from ..market import PERIODS
from ..models import AssetKind, Transaction
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
from ..valuation import PortfolioView
from . import actions, chart, extras, navigation, records, workspaces
from .commands import PortfolioCommands
from .constants import HINTS, HOLDING_COLUMNS
from .widgets import WORKSPACES, Canvas, ChartView, Tile, TopBar, pane

AUTO_THEME = "marketpulse-auto"


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
    #holdings-filter { display: none; height: 1; border: none; padding: 0 1; }
    #holdings-filter.-shown { display: block; }
    App.-zoom .detail { display: none; }
    App.-zoom #dash-side { display: none; }

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
    BaseForm .modal { overflow-y: auto; }
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
    HelpScreen .modal, DetailsScreen .modal, WorkspaceKeysScreen .modal, ProblemsScreen .modal {
        height: 90%; max-height: 36;
    }
    App.-compact #tax { layout: vertical; }
    App.-compact #pane-accts { width: 100%; height: 7; min-width: 0; }
    App.-compact #tax .col-main { width: 100%; }
    #dashboard { overflow-y: hidden; }
    App.-compact #dashboard { overflow-y: auto; }
    App.-compact #tiles { layout: grid; grid-size: 3 2; grid-rows: 5 5; height: 10; }
    App.-compact #tile-networth { width: 1fr; column-span: 2; }
    App.-compact #dash-panes { layout: vertical; height: auto; }
    App.-compact #dash-panes .col-main { width: 100%; height: 22; }
    App.-compact #dash-side { display: block; width: 100%; height: auto; }
    App.-compact.-zoom #dash-side { display: none; }
    App.-compact #pane-perf { height: 12; }
    App.-compact #chart-input { width: 45%; }
    App.-compact #chart-periods { padding: 1 0; }
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
        # Keyboard navigation and productivity (#130); none of these keys had a binding before.
        Binding("backspace", "previous_workspace", show=False),
        Binding("left_curly_bracket", "cycle_workspace(-1)", show=False),
        Binding("right_curly_bracket", "cycle_workspace(1)", show=False),
        Binding("j", "row(1)", show=False),
        Binding("k", "row(-1)", show=False),
        Binding("less_than_sign", "row_edge(False)", show=False),
        Binding("greater_than_sign", "row_edge(True)", show=False),
        Binding("F", "filter_holdings", show=False),
        Binding("escape", "clear_filter", show=False),
        Binding("o", "sort", show=False),
        Binding("O", "sort_reverse", show=False),
        Binding("y", "copy_symbol", show=False),
        Binding("Y", "copy_row", show=False),
        Binding("v", "chart_selected", show=False),
        Binding("T", "symbol_activity", show=False),
        Binding("N", "pick_txn", show=False),
        Binding("z", "zoom", show=False),
        Binding("f1", "workspace_keys", show=False),
        # #153; none of these keys had a binding before.
        Binding("ctrl+y", "copy_table", show=False),
        Binding("dollar_sign", "toggle_cash", show=False),
        Binding("d", "duplicate", show=False),
        Binding("exclamation_mark", "problems", show=False),
        # Workflow batch (81-100); none of these keys had a binding before.
        Binding("0", "reset_sort", show=False),
        Binding("ctrl+d", "half_page(True)", show=False),
        Binding("ctrl+u", "half_page(False)", show=False),
        Binding("I", "toggle_archived", show=False),
        Binding("S", "jump_to_holding", show=False),
        Binding("number_sign", "copy_table_csv", show=False),
        Binding("X", "copy_table_markdown", show=False),
        Binding("Q", "copy_summary", show=False),
        Binding("M", "cycle_filter_mode", show=False),
        Binding("commercial_at", "cycle_activity_account", show=False),
        Binding("m", "cycle_movers", show=False),
        Binding("minus", "step_year(-1)", show=False),
        Binding("plus", "step_year(1)", show=False),
        Binding("U", "rearm_triggered", show=False),
        Binding("f2", "focus_input", show=False),
        # Second workflow batch (81-100); none of these keys had a binding before.
        Binding("P", "details", show=False),
        Binding("W", "toggle_watch", show=False),
        Binding("semicolon", "scope_account", show=False),
        Binding("colon", "go_to", show=False),
        Binding("percent_sign", "cycle_activity_window", show=False),
        Binding("circumflex_accent", "chart_extreme(True)", show=False),
        Binding("low_line", "chart_extreme(False)", show=False),
        Binding("left_parenthesis", "jump_group(-1)", show=False),
        Binding("right_parenthesis", "jump_group(1)", show=False),
        Binding("ctrl+f", "find_row", show=False),
        Binding("ctrl+g", "find_next", show=False),
        Binding("ctrl+t", "copy_pane", show=False),
        Binding("ctrl+r", "toggle_auto_refresh", show=False),
        Binding("ampersand", "symbol_alerts", show=False),
        Binding("ctrl+e", "next_issue", show=False),
        Binding("apostrophe", "previous_chart", show=False),
        Binding("quotation_mark", "copy_table_json", show=False),
        Binding("ctrl+s", "save_watch_order", show=False),
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
        self._income_ledger_changed = False
        self._income_history: tuple[list[tuple[str, float]], list[tuple[str, float]]] = ([], [])
        self._tax: tuple | None = None
        self._last_error = ""
        self.load_errors: dict[str, str] = {}
        self.last_workspace: str | None = None
        self.table_sort: dict[str, tuple[str, bool]] = {}
        self.refreshed_at: float | None = None
        self.hide_cash = False
        self.hide_archived = False
        self.holdings_filter_mode = "all"
        self.activity_filter_mode = "all"
        self.alerts_filter_mode = "all"
        self.activity_account_filter: int | None = None
        self.movers_mode = "day %"
        self.tax_year: int | None = None
        self.income_year: int | None = date.today().year
        self.activity_window = "all"
        self.alerts_symbol: str | None = None
        self.find_text = ""
        self.chart_history: list[str] = []
        self.auto_refresh_paused = False
        self._refresh_timer: Timer | None = None
        for name in theme_names():
            self.register_theme(textual_theme(palette_from_colors(name, OMARCHY_PALETTES[name])))
        if self._auto_theme:
            self.register_theme(replace(textual_theme(self.palette), name=AUTO_THEME))
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
        elif name != AUTO_THEME:
            return
        self._push_rich_theme()
        if not self._mp_ready:
            return
        if name != AUTO_THEME and self.config.theme != name:
            self.config.theme = name
            if self._auto_theme:
                self.unregister_theme(AUTO_THEME)
            self._auto_theme = False
            self.config.save()
        self.refresh_all_views()

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield TopBar(id="topbar")
        with ContentSwitcher(initial="dashboard", id="workspaces"):
            with VerticalScroll(id="dashboard"):
                yield Static(id="strip")
                with Horizontal(id="tiles"):
                    yield Tile(id="tile-networth")
                    yield Tile(id="tile-today")
                    yield Tile(id="tile-unrealized")
                    yield Tile(id="tile-income")
                    yield Tile(id="tile-returns")
                with Horizontal(id="dash-panes"):
                    with Vertical(classes="col-main"):
                        yield pane(Canvas(id="nw-chart"), title="net worth", id="pane-nw")
                        yield pane(VerticalScroll(Static(id="dash-accounts")), title="accounts", id="pane-accounts")
                    with Vertical(classes="col-side", id="dash-side"):
                        yield pane(Canvas(id="alloc"), title="allocation", id="pane-alloc")
                        yield pane(Static(id="movers"), title="movers", id="pane-movers")
                        yield pane(Static(id="perf"), title="returns", id="pane-perf")
            with Horizontal(id="holdings"):
                yield pane(
                    Input(placeholder="filter holdings by symbol, name or account…", id="holdings-filter"),
                    DataTable(id="holdings-table"),
                    title="holdings",
                    id="pane-holdings",
                    classes="col-main",
                )
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
                yield pane(Static(id="income-hint"), Static(id="income-view"), title="income", id="pane-income")
            with Horizontal(id="tax"):
                yield pane(DataTable(id="accounts-table"), title="accounts", id="pane-accts", classes="col-side")
                yield pane(VerticalScroll(Static(id="tax-view")), title="tax & contribution room", classes="col-main")
            with Vertical(id="alerts"):
                yield pane(DataTable(id="alerts-table"), title="alerts", id="pane-alerts")
        yield Static(id="hints")

    def on_mount(self) -> None:
        try:
            self.theme = AUTO_THEME if self._auto_theme else self.palette.name
        except Exception:  # pragma: no cover - theme registry failure falls back to Textual default
            pass
        for name in list(self.available_themes):
            if name not in OMARCHY_PALETTES and name != AUTO_THEME:
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
        self.set_class(self.size.width < 100, "-compact")
        self.set_workspace("dashboard")
        self.render_store_views()
        self.render_dashboard()
        self.set_interval(1.0, self._tick)
        self._refresh_timer = self.set_interval(max(self.config.refresh_seconds, 5), self.load_data)
        self.load_data()

    def on_resize(self, event) -> None:
        self.set_class(event.size.width < 130, "-narrow")
        compact = event.size.width < 100
        was_compact = self.has_class("-compact")
        self.set_class(compact, "-compact")
        if self._mp_ready and compact != was_compact and self.workspace == "dashboard":
            self.set_workspace("dashboard")

    def _tick(self) -> None:
        # Shutdown removes widgets before stopping the app's timers.
        if self.is_running:
            self.query_one(TopBar).refresh()
            self._render_hints(self.workspace)

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
            return alert.symbol if alert else (self.alerts_symbol or "")
        return ""

    def context_account(self) -> int | None:
        if self.workspace == "holdings":
            key = self._selected_key(self.query_one("#holdings-table", DataTable))
            if key and not key.startswith("cash:"):
                return int(key.split(":", 1)[0])
        if self.workspace == "activity":
            txn = records.selected_transaction(self)  # b / s / D / N prefill the selected entry's account
            if txn is not None:
                return txn.account_id
        return self.account_filter

    # ── workspaces ────────────────────────────────────────────────────────────

    def action_workspace(self, name: str) -> None:
        self.set_workspace(name)

    def set_workspace(self, name: str) -> None:
        current = self.query_one("#workspaces", ContentSwitcher).current
        if current and current != name:
            self.last_workspace = current
        self.query_one("#workspaces", ContentSwitcher).current = name
        bar = self.query_one(TopBar)
        bar.active = name
        bar.refresh()
        self._render_hints(name)
        focus = {
            "dashboard": "#dashboard" if self.has_class("-compact") else "#pane-accounts VerticalScroll",
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
        if (
            name == "income"
            and self._income_forecast is None
            and self.view is not None
            and not bar.loading
            and "portfolio" not in self.load_errors
        ):
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
        status = navigation.footer_status(self)  # row position and refresh age, only when they fit
        if width - t.cell_len - tail.cell_len - status.cell_len > 1:
            tail = status.append_text(tail)
        gap = width - t.cell_len - tail.cell_len
        if gap > 1:
            t.append(" " * gap)
            t.append_text(tail)
        self.query_one("#hints", Static).update(t)

    # ── data loading ──────────────────────────────────────────────────────────

    def _invalidate_income(self) -> None:
        self.workers.cancel_group(self, "income")
        self._income_forecast = None
        self.load_errors.pop("income", None)
        workspaces.render_income(self, refresh_history=False)

    def action_refresh(self) -> None:
        self._invalidate_income()
        self.load_data(force=True)
        if self.workspace == "tax":
            self.load_tax()
        if self.workspace == "chart" and self.chart_symbol:
            self.load_chart()

    def _publish_load(self, callback, *args) -> None:
        """An exclusive worker can finish in its thread after a retry cancelled it."""
        worker = get_current_worker()

        def publish() -> None:
            if not worker.is_cancelled:
                callback(*args)

        self.call_from_thread(publish)

    def load_data(self, force: bool = False) -> Worker:
        self._set_loading(True)
        return self._load_data(force)

    @work(thread=True, exclusive=True, group="data")
    def _load_data(self, force: bool) -> None:
        tr = self.tracker
        try:
            view = tr.valuation(use_cache=not force)
            perf = tr.performance(view)
            strip = tr.market_strip(use_cache=not force)
            watch = tr.watchlist_quotes(use_cache=not force)
            fired = tr.check_alerts({**view.quotes, **watch[1]}, notify=True)
        except Exception as e:  # keep the UI alive on any provider/database hiccup
            self._publish_load(self._load_failed, "portfolio", str(e))
            self._publish_load(self._set_loading, False)
            return
        self._publish_load(self._apply_data, view, perf, strip, watch, fired)

    def _load_failed(self, section: str, reason: str) -> None:
        self.load_errors[section] = (
            f"Could not load {'the income forecast' if section == 'income' else section}. Press r to retry."
        )
        self.notify(self.load_errors[section] if self.privacy else reason, title="Refresh failed", severity="error")
        if section == "portfolio":
            if self.view is None:
                self.render_dashboard()
            if self._income_forecast is None:
                workspaces.render_income(self, refresh_history=False)
        elif section == "tax":
            self.render_tax()
        else:
            self.query_one("#income-hint", Static).update(Text(self.load_errors[section], style="warn"))

    def _set_loading(self, loading: bool) -> None:
        bar = self.query_one(TopBar)
        bar.loading = loading
        bar.refresh()

    def _apply_data(self, view: PortfolioView, perf, strip, watch, fired) -> None:
        self.load_errors.pop("portfolio", None)
        symbols, quotes, errors = watch
        prices = {s: q.price for s, q in {**view.quotes, **quotes}.items()}
        self.flash = {
            s: (1 if price > self._prev_prices[s] else -1)
            for s, price in prices.items()
            if s in self._prev_prices and abs(price - self._prev_prices[s]) > 1e-9
        }
        self._prev_prices = prices
        self.refreshed_at = time.monotonic()
        self.view, self.perf, self.strip = view, perf, strip
        self.watch_symbols, self.watch_quotes, self.watch_errors = symbols, quotes, errors
        for alert in fired:
            self.notify(alert.note or alert.describe(), title=f"Alert · {alert.symbol}", severity="warning", timeout=12)
        problems = sorted(set(view.errors.values()))
        if view.excluded:
            problems.insert(0, f"Net worth excludes {len(view.excluded)} position(s) without a price or FX rate")
        if view.archived_with_value:
            names = ", ".join(view.archived_with_value)
            problems.insert(0, f"Net worth excludes archived {names}, which still holds value; snapshots paused")
        if problems and problems[0] != self._last_error:
            self.notify(problems[0], title="Market data", severity="warning")
        self._last_error = problems[0] if problems else ""
        self._set_loading(False)
        self._income_ledger_changed = False
        self.render_market_views()
        if self.workspace == "income" and self._income_forecast is None:
            self.load_income()  # `r` clears the forecast; reload it if the user is looking at it
        if self.flash:
            self.set_timer(1.6, self._clear_flash)

    def _clear_flash(self) -> None:
        self.flash = {}
        self.render_holdings()
        self.render_watchlist()

    def after_change(self, message: str | None = None) -> None:
        if message:
            self.notify(message)
        self.workers.cancel_group(self, "tax")
        self._tax = None
        self._income_ledger_changed = True
        self._invalidate_income()
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
        workspaces.render_store_views(self)

    def render_market_views(self) -> None:
        workspaces.render_market_views(self)

    def _render_topbar_status(self) -> None:
        workspaces._render_topbar_status(self)

    def _snapshots(self) -> list:
        return workspaces._snapshots(self)

    def render_dashboard(self) -> None:
        workspaces.render_dashboard(self)

    def render_holdings(self) -> None:
        workspaces.render_holdings(self)

    def render_watchlist(self) -> None:
        workspaces.render_watchlist(self)

    def render_activity(self) -> None:
        workspaces.render_activity(self)

    def render_accounts(self) -> None:
        workspaces.render_accounts(self)

    def render_alerts(self) -> None:
        workspaces.render_alerts(self)

    def render_position_detail(self) -> None:
        workspaces.render_position_detail(self)

    def render_watch_detail(self) -> None:
        workspaces.render_watch_detail(self)

    def render_income(self) -> None:
        workspaces.render_income(self)

    def render_tax(self) -> None:
        workspaces.render_tax(self)

    # ── lazy workers ──────────────────────────────────────────────────────────

    @work(thread=True, exclusive=True, group="income")
    def load_income(self) -> None:
        view = self.view
        if view is None:
            return
        try:
            forecast = self.tracker.income_forecast(view)
        except Exception as e:
            self._publish_load(self._load_failed, "income", str(e))
            return
        self._publish_load(self._income_loaded, forecast)

    def _income_loaded(self, forecast) -> None:
        self.load_errors.pop("income", None)
        self._income_forecast = forecast
        self.render_income()

    @work(thread=True, exclusive=True, group="tax")
    def load_tax(self) -> None:
        try:
            years, report = self.tracker.tax_years()
            rooms = self.tracker.room()
            foreign = self.tracker.foreign_property()
        except Exception as e:
            self._publish_load(self._load_failed, "tax", str(e))
            return
        self._publish_load(self._tax_loaded, (years, report, rooms, foreign))

    def _tax_loaded(self, result) -> None:
        self.load_errors.pop("tax", None)
        self._tax = result
        self.render_tax()

    def load_detail_bars(self, symbol: str) -> None:
        # Holdings and Watchlist share this cache. Each symbol needs only one request.
        if symbol not in self._detail_bars:
            self._detail_bars[symbol] = []
            self._fetch_detail_bars(symbol)

    @work(thread=True, group="detail")
    def _fetch_detail_bars(self, symbol: str) -> None:
        try:
            bars = self.tracker.market.history(symbol, "3mo")
        except Exception:
            # Discard the in-flight placeholder so selecting this symbol again can retry.
            self.call_from_thread(lambda: self._detail_bars.pop(symbol, None))
            return
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
        if sym not in assets or assets[sym].kind is AssetKind.MARKET:
            self.load_detail_bars(sym)

    def _show_watch(self, symbol: str) -> None:
        self._watch_key = symbol
        self.render_watch_detail()
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

    @on(DataTable.RowHighlighted)
    def _row_position_changed(self) -> None:
        self._render_hints(self.workspace)

    @on(Input.Changed, "#holdings-filter")
    def _holdings_filter(self) -> None:
        self._detail_key = None
        self.render_holdings()

    @on(Input.Submitted, "#holdings-filter")
    def _holdings_filter_done(self) -> None:
        navigation.holdings_filter_done(self)

    # ── chart ─────────────────────────────────────────────────────────────────

    def open_chart(self, symbol: str, *, compare: list[str] | None = None) -> None:
        chart.open_chart(self, symbol, compare=compare)

    @on(Input.Submitted, "#chart-input")
    def _chart_submitted(self, event: Input.Submitted) -> None:
        chart._chart_submitted(self, event)

    def load_chart(self) -> None:
        chart.load_chart(self)

    @work(thread=True, exclusive=True, group="chart")
    def _load_chart(self, view: ChartView) -> None:
        chart._load_chart(self, view)

    def _chart_loaded(self, sym, period, bars, quote, compare) -> None:
        chart._chart_loaded(self, sym, period, bars, quote, compare)

    def render_chart_info(self, quote=None) -> None:
        chart.render_chart_info(self, quote)

    def action_period(self, delta: int) -> None:
        chart.action_period(self, delta)

    def action_compare(self) -> None:
        chart.action_compare(self)

    def action_clear_compare(self) -> None:
        chart.action_clear_compare(self)

    # ── actions: records ──────────────────────────────────────────────────────

    def action_new(self) -> None:
        records.action_new(self)

    def action_add(self) -> None:
        records.action_add(self)

    def action_trade(self, kind: str) -> None:
        records.action_trade(self, kind)

    def _txn_done(self, txn: Transaction | None, restore_id: str | None = None, revision: str | None = None) -> None:
        records._txn_done(self, txn, restore_id, revision)

    @work(thread=True, group="write")
    def save_txn(self, txn: Transaction, restore_id: str | None = None, revision: str | None = None) -> None:
        records.save_txn(self, txn, restore_id, revision)

    def action_edit(self) -> None:
        records.action_edit(self)

    def action_delete(self) -> None:
        records.action_delete(self)

    def action_undo(self) -> None:
        records.action_undo(self)

    def _delete_txn(self, txn_id: int, restore_id: str, revision: str) -> bool:
        return records._delete_txn(self, txn_id, restore_id, revision)

    def action_new_account(self) -> None:
        records.action_new_account(self)

    def _account_done(self, account) -> None:
        records._account_done(self, account)

    def action_add_asset(self) -> None:
        records.action_add_asset(self)

    def action_value_asset(self) -> None:
        records.action_value_asset(self)

    def action_room(self) -> None:
        records.action_room(self)

    def action_alert(self) -> None:
        actions.action_alert(self)

    def action_toggle_alert(self) -> None:
        actions.action_toggle_alert(self)

    def action_watch_add(self, prompt: bool = False) -> None:
        actions.action_watch_add(self, prompt)

    def action_move_watch(self, delta: int) -> None:
        actions.action_move_watch(self, delta)

    def action_search(self) -> None:
        actions.action_search(self)

    def action_filter_account(self) -> None:
        actions.action_filter_account(self)

    def action_cycle_alloc(self) -> None:
        actions.action_cycle_alloc(self)

    def action_nw_range(self, delta: int) -> None:
        actions.action_nw_range(self, delta)

    # ── actions: data & app ───────────────────────────────────────────────────

    def action_import_csv(self) -> None:
        actions.action_import_csv(self)

    @work(thread=True, group="write")
    def import_csv(self, path: str) -> None:
        actions.import_csv(self, path)

    def action_export_csv(self) -> None:
        actions.action_export_csv(self)

    @work(thread=True, exclusive=True, group="backfill")
    def action_backfill(self) -> None:
        actions.action_backfill(self)

    def action_privacy(self) -> None:
        actions.action_privacy(self)

    def action_next_theme(self) -> None:
        actions.action_next_theme(self)

    def action_help(self) -> None:
        actions.action_help(self)

    def notify_desktop(self, title: str, message: str) -> None:
        actions.notify_desktop(self, title, message)

    # ── actions: keyboard navigation and productivity ─────────────────────────

    def action_previous_workspace(self) -> None:
        navigation.previous_workspace(self)

    def action_cycle_workspace(self, delta: int) -> None:
        navigation.cycle_workspace(self, delta)

    def action_row(self, delta: int) -> None:
        navigation.move_cursor(self, delta)

    def action_row_edge(self, last: bool) -> None:
        navigation.jump_row(self, last)

    def action_filter_holdings(self) -> None:
        navigation.show_holdings_filter(self)

    def action_clear_filter(self) -> None:
        navigation.clear_filter(self)

    def action_sort(self) -> None:
        navigation.cycle_sort(self)

    def action_sort_reverse(self) -> None:
        navigation.reverse_sort(self)

    def action_copy_symbol(self) -> None:
        navigation.copy_symbol(self)

    def action_copy_row(self) -> None:
        navigation.copy_row(self)

    def action_chart_selected(self) -> None:
        navigation.chart_selected(self)

    def action_symbol_activity(self) -> None:
        navigation.symbol_activity(self)

    def action_pick_txn(self) -> None:
        navigation.pick_transaction(self)

    def action_workspace_keys(self) -> None:
        navigation.workspace_keys(self)

    def action_zoom(self) -> None:
        navigation.toggle_zoom(self)

    def action_copy_table(self) -> None:
        navigation.copy_table(self)

    def action_toggle_cash(self) -> None:
        navigation.toggle_cash(self)

    def action_duplicate(self) -> None:
        records.action_duplicate(self)

    def action_problems(self) -> None:
        navigation.show_problems(self)

    def action_reset_sort(self) -> None:
        navigation.reset_sort(self)

    def action_half_page(self, down: bool) -> None:
        navigation.jump_half_page(self, down)

    def action_toggle_archived(self) -> None:
        navigation.toggle_archived_accounts(self)

    def action_jump_to_holding(self) -> None:
        navigation.jump_to_holding(self)

    def action_copy_table_csv(self) -> None:
        navigation.copy_table_csv(self)

    def action_copy_table_markdown(self) -> None:
        navigation.copy_table_markdown(self)

    def action_copy_summary(self) -> None:
        navigation.copy_portfolio_summary(self)

    def action_cycle_filter_mode(self) -> None:
        navigation.cycle_filter_mode(self)

    def action_cycle_activity_account(self) -> None:
        navigation.cycle_activity_account(self)

    def action_cycle_movers(self) -> None:
        navigation.cycle_movers_mode(self)

    def action_step_year(self, delta: int) -> None:
        navigation.step_year(self, delta)

    def action_rearm_triggered(self) -> None:
        self.update_alert_batch(True, rearm=True)

    def action_pause_all_alerts(self) -> None:
        self.update_alert_batch(False)

    def action_resume_all_alerts(self) -> None:
        self.update_alert_batch(True)

    @work(thread=True, group="write")
    def update_alert_batch(self, active: bool, *, rearm: bool = False) -> None:
        try:
            message = navigation.update_alert_batch(self, active, rearm=rearm)
        except (OSError, sqlite3.Error) as e:
            self.call_from_thread(self.notify, str(e), title="Alert update failed", severity="error")
            return
        self.call_from_thread(self.render_alerts)
        self.call_from_thread(self.notify, message, timeout=2)

    @work(thread=True, group="write")
    def action_create_backup(self) -> None:
        try:
            path = self.tracker.store.backup(reason="manual")
        except (OSError, sqlite3.Error) as e:
            self.call_from_thread(self.notify, str(e), title="Backup failed", severity="error")
            return
        self.call_from_thread(self.notify, f"Backup saved: {path.name}", timeout=3)

    def action_restore_auto_theme(self) -> None:
        self.config.theme = "auto"
        self.config.save()
        self._auto_theme = True
        self.palette = resolve_palette("auto")
        self.register_theme(replace(textual_theme(self.palette), name=AUTO_THEME))
        if self.theme == AUTO_THEME:
            self.mutate_reactive(MarketPulseApp.theme)
        else:
            self.theme = AUTO_THEME
        self.notify(f"Theme: Auto ({pretty_name(self.palette.name)})", timeout=2)

    def action_focus_input(self) -> None:
        navigation.focus_workspace_input(self)

    # ── actions: second workflow batch (81-100) ───────────────────────────────

    def action_details(self) -> None:
        extras.show_details(self)

    def action_toggle_watch(self) -> None:
        extras.toggle_watch(self)

    def action_watch_holdings(self) -> None:
        extras.watch_holdings(self)

    def action_scope_account(self) -> None:
        extras.scope_account(self)

    def action_go_to(self) -> None:
        extras.prompt_go_to(self)

    def action_cycle_activity_window(self) -> None:
        extras.cycle_activity_window(self)

    def action_chart_extreme(self, high: bool) -> None:
        extras.chart_extreme(self, high)

    def action_jump_group(self, delta: int) -> None:
        extras.jump_group(self, delta)

    def action_find_row(self) -> None:
        extras.prompt_find(self)

    def action_find_next(self) -> None:
        extras.find_next(self)

    def action_copy_pane(self) -> None:
        extras.copy_pane(self)

    def action_toggle_auto_refresh(self) -> None:
        extras.toggle_auto_refresh(self)

    def action_symbol_alerts(self) -> None:
        extras.symbol_alerts(self)

    def action_next_issue(self) -> None:
        extras.next_issue(self)

    def action_previous_chart(self) -> None:
        extras.previous_chart(self)

    def action_copy_table_json(self) -> None:
        extras.copy_table_json(self)

    def action_copy_chart_csv(self) -> None:
        extras.copy_chart_csv(self)

    def action_save_watch_order(self) -> None:
        symbols = extras.sorted_watch_symbols(self)
        if symbols:
            self.save_watch_order(symbols)

    @work(thread=True, group="write")
    def save_watch_order(self, symbols: list[str]) -> None:
        try:
            extras.save_watch_order(self, symbols)
        except (OSError, sqlite3.Error) as e:
            self.call_from_thread(self.notify, str(e), title="Watchlist not saved", severity="error")
            return
        self.call_from_thread(extras.watch_order_saved, self, len(symbols))
