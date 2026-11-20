"""More keyboard helpers for the terminal app; Textual entry points stay on the app.

Row details, watchlist toggling, account scoping, go-to and find in tables, group
jumps, the activity date window, the chart's high/low crosshair, JSON and pane
copies, pausing automatic refresh, a symbol's alerts, stepping through ledger
issues and chart history. Like navigation.py, everything here only selects,
filters, copies or reorders what the views already show; no figure is computed
differently.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

from rich.console import Console
from rich.text import Text
from rich.theme import Theme as RichTheme
from textual.widgets import DataTable, Input, Static

from .. import fmt
from ..models import AssetKind
from ..themes import rich_styles
from . import chart, navigation, records
from .constants import ACTIVITY_FILTER_MODES, ACTIVITY_WINDOWS, ALERT_FILTER_MODES, HOLDING_FILTER_MODES, MOVERS_MODES
from .screens import DetailsScreen, PromptScreen
from .widgets import ChartView

if TYPE_CHECKING:
    from .app import MarketPulseApp


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# ── row details (P) ───────────────────────────────────────────────────────────


def row_details(app: MarketPulseApp) -> tuple[str, list[tuple[str, str]]] | None:
    """Title and (label, value) rows for the selected table row, masked like the tables in privacy mode."""
    ws, priv, store = app.workspace, app.privacy, app.tracker.store
    table = navigation.current_table(app)
    key = app._selected_key(table) if table is not None else None
    if not key:
        return None
    if ws == "holdings":
        v = app.view
        if v is None:
            return None
        if key.startswith("cash:"):
            _, acct_id, currency = key.split(":", 2)
            cash = next((c for c in v.cash if str(c.account.id) == acct_id and c.currency == currency), None)
            if cash is None:
                return None
            return f"Cash · {cash.account.name}", [
                ("Account", cash.account.name),
                ("Currency", cash.currency),
                ("Balance", fmt.money(cash.amount, cash.currency, privacy=priv)),
                (f"In {v.base}", fmt.money(cash.amount_base, v.base, privacy=priv)),
            ]
        acct_id, sym = key.split(":", 1)
        pos = next((x for x in v.positions if str(x.account.id) == acct_id and x.symbol == sym), None)
        if pos is None:
            return None
        return f"{pos.symbol} · {pos.account.name}", [
            ("Name", pos.name or "—"),
            ("Account", pos.account.name),
            ("Asset class", pos.asset_class.label),
            ("Pricing", pos.kind.value.replace("_", " ")),
            ("Currency", pos.currency),
            ("Quantity", fmt.MASK if priv else fmt.qty(pos.quantity)),
            ("Average cost", fmt.price(pos.avg_cost)),
            ("Price", fmt.price(pos.price)),
            ("Book value", fmt.money(pos.book, pos.currency, privacy=priv)),
            ("Market value", fmt.money(pos.market_value, pos.currency, privacy=priv)),
            ("Gain", f"{fmt.money(pos.gain, pos.currency, sign=True, privacy=priv)} ({fmt.pct(pos.gain_pct)})"),
            ("Today", f"{fmt.money(pos.day_change, pos.currency, sign=True, privacy=priv)}"),
            (f"Value in {v.base}", fmt.money(pos.value_base, v.base, privacy=priv)),
            ("Weight", fmt.pct(pos.weight, sign=False)),
            ("Held since", pos.first_date or "—"),
        ]
    if ws == "watchlist":
        q = app.watch_quotes.get(key)
        if q is None:
            return key, [("Quote", app.watch_errors.get(key, "loading…"))]
        rows = [
            ("Name", q.name or "—"),
            ("Price", f"{fmt.price(q.price)} {q.currency}"),
            ("Change", f"{fmt.price(q.change)} ({fmt.pct(q.change_pct)})"),
            ("Previous close", fmt.price(q.prev_close)),
            ("Day range", f"{fmt.price(q.day_low)} – {fmt.price(q.day_high)}"),
            ("52-week range", f"{fmt.price(q.week52_low)} – {fmt.price(q.week52_high)}"),
            ("Exchange", q.exchange or "—"),
            ("Type", q.instrument_type or "—"),
            ("Source", q.source + (" (offline cache)" if q.stale else "")),
        ]
        return q.symbol, rows
    if ws == "activity":
        txn = records.selected_transaction(app)
        if txn is None:
            return None
        accounts = store.account_map()
        acct = accounts.get(txn.account_id)
        rows = [
            ("Date", txn.date),
            ("Type", txn.type.value),
            ("Account", acct.name if acct else f"#{txn.account_id}"),
            ("Symbol", txn.symbol or "—"),
        ]
        if txn.target_account_id is not None:
            target = accounts.get(txn.target_account_id)
            rows.append(("To account", target.name if target else f"#{txn.target_account_id}"))
        if txn.quantity:
            rows.append(("Quantity", fmt.MASK if priv else fmt.qty(txn.quantity)))
        if txn.price:
            rows.append(("Price", fmt.price(txn.price)))
        if txn.ratio:
            rows.append(("Split ratio", f"×{txn.ratio:g}"))
        if txn.amount:
            rows.append(("Amount", fmt.money(txn.amount, privacy=priv)))
        if txn.gross_value and txn.type.uses_quantity:
            rows.append(("Gross value", fmt.money(txn.gross_value, privacy=priv)))
        if txn.fees:
            rows.append(("Fees", fmt.money(txn.fees, privacy=priv)))
        rows += [("Currency", txn.currency or "—"), ("Note", txn.note or "—")]
        issues = [i.message for i in store.ledger().issues if i.txn_id == txn.id]
        rows += [("Ledger issue", navigation._NUMBER.sub(fmt.MASK, m) if priv else m) for m in issues]
        return f"Transaction #{txn.id}", rows
    if ws == "tax":
        a = store.get_account(int(key)) if key.isdigit() else None
        if a is None:
            return None
        b = next((x for x in (app.view.by_account if app.view else []) if x.key == key), None)
        return f"Account #{a.id}", [
            ("Name", a.name),
            ("Type", a.type.label),
            ("Currency", a.currency),
            ("Institution", a.institution or "—"),
            ("Tracks cash", "yes" if a.track_cash else "no"),
            ("Archived", "yes" if a.archived else "no"),
            ("Value", fmt.money(b.value, app.tracker.base, privacy=priv) if b else "—"),
            ("Created", a.created_at[:10] or "—"),
        ]
    if ws == "alerts":
        alert = next((x for x in store.alerts() if str(x.id) == key), None)
        if alert is None:
            return None
        state = "triggered" if alert.triggered_at else ("armed" if alert.active else "paused")
        return f"Alert #{alert.id}", [
            ("Symbol", alert.symbol),
            ("Condition", alert.describe()),
            ("State", state),
            ("Triggered", alert.triggered_at or "—"),
            ("Note", alert.note or "—"),
        ]
    return None


def show_details(app: MarketPulseApp) -> None:
    details = row_details(app)
    if details is None:
        app.notify("Select a row in holdings, watchlist, activity, accounts or alerts first", timeout=3)
        return
    app.push_screen(DetailsScreen(*details))


# ── watchlist and alerts for the selected symbol (W, &) ───────────────────────


def toggle_watch(app: MarketPulseApp) -> None:
    symbol = app.context_symbol()
    if not symbol:
        app.notify("Select a row with a symbol first", timeout=3)
        return
    store = app.tracker.store
    if symbol in store.watchlist():
        store.remove_watch([symbol])
        app.watch_symbols = store.watchlist()
        if app._watch_key == symbol:
            app._watch_key = None
        app.render_watchlist()
        app.notify(f"Removed {symbol} from the watchlist (W again adds it back)", timeout=3)
        return
    store.add_watch([symbol])
    app.watch_symbols = store.watchlist()
    app.render_watchlist()
    app.notify(f"Watching {symbol}", timeout=2)
    app.load_data()


def watch_holdings(app: MarketPulseApp) -> None:
    """Palette: add every market-priced symbol you hold to the watchlist."""
    v = app.view
    if v is None:
        app.notify("Portfolio not loaded yet", timeout=3)
        return
    held = sorted({p.symbol for p in v.positions if p.kind is AssetKind.MARKET})
    added = app.tracker.store.add_watch(held)
    if not added:
        app.notify("Every held symbol is already on the watchlist", timeout=3)
        return
    app.watch_symbols = app.tracker.store.watchlist()
    app.render_watchlist()
    app.notify(f"Watching {_plural(len(added), 'more symbol')}: {', '.join(added)}", timeout=3)
    app.load_data()


def symbol_alerts(app: MarketPulseApp) -> None:
    """&: list only the selected symbol's alerts; on the alerts workspace a second press shows them all."""
    if app.workspace == "alerts" and app.alerts_symbol:
        app.alerts_symbol = None
        app.render_alerts()
        app.notify("Alerts: every symbol", timeout=2)
        return
    symbol = app.context_symbol()
    if not symbol:
        app.notify("Select a row with a symbol first", timeout=3)
        return
    app.alerts_symbol = symbol
    app.set_workspace("alerts")
    app.render_alerts()
    count = sum(a.symbol == symbol for a in app.tracker.store.alerts())
    if count:
        app.notify(f"{_plural(count, 'alert')} for {symbol} · escape shows all", timeout=2)
    else:
        app.notify(f"No alerts for {symbol} — A adds one", timeout=3)


# ── scoping, windows and modes (;, %, palette) ───────────────────────────────


def scope_account(app: MarketPulseApp) -> None:
    """;: show only the selected row's account in holdings or activity; press again for every account."""
    ws = app.workspace
    if ws == "holdings":
        key = app._selected_key(app.query_one("#holdings-table", DataTable))
        if not key:
            app.notify("Select a holding first", timeout=3)
            return
        acct_id = int(key.split(":")[1] if key.startswith("cash:") else key.split(":", 1)[0])
        target = None if app.account_filter == acct_id else acct_id
        navigation.filter_holdings_account(app, target)
        name = app.tracker.store.get_account(acct_id)
        app.notify(f"Holdings: {name.name if name and target else 'all accounts'}", timeout=2)
    elif ws == "activity":
        txn = records.selected_transaction(app)
        if txn is None:
            app.notify("Select a transaction first", timeout=3)
            return
        target = None if app.activity_account_filter == txn.account_id else txn.account_id
        navigation.filter_activity_account(app, target)
        acct = app.tracker.store.get_account(txn.account_id)
        app.notify(f"Activity: {acct.name if acct and target else 'all accounts'}", timeout=2)
    else:
        app.notify("; shows one account in holdings or activity", timeout=3)


def window_start(window: str, today: date | None = None) -> str | None:
    """The first date (ISO) the activity date window keeps, or None for every date."""
    today = today or date.today()
    start = {
        "30d": today - timedelta(days=29),
        "90d": today - timedelta(days=89),
        "ytd": date(today.year, 1, 1),
        "1y": today - timedelta(days=365),
    }.get(window)
    return start.isoformat() if start else None


def cycle_activity_window(app: MarketPulseApp) -> None:
    windows = ACTIVITY_WINDOWS
    set_activity_window(app, windows[(windows.index(app.activity_window) + 1) % len(windows)])


def set_activity_window(app: MarketPulseApp, window: str) -> None:
    if window not in ACTIVITY_WINDOWS:
        return
    app.activity_window = window
    if app.workspace != "activity":
        app.set_workspace("activity")
    app.render_activity()
    since = window_start(window)
    app.notify(f"Activity: {'every date' if since is None else f'since {since}'}", timeout=2)


def set_filter_mode(app: MarketPulseApp, ws: str, mode: str) -> None:
    """Palette target: choose a holdings, activity or alerts quick mode (or the movers metric) directly."""
    if ws == "holdings" and mode in HOLDING_FILTER_MODES:
        app.holdings_filter_mode = mode
        app.set_workspace("holdings")
        app.render_holdings()
    elif ws == "activity" and mode in ACTIVITY_FILTER_MODES:
        app.activity_filter_mode = mode
        app.set_workspace("activity")
        app.render_activity()
    elif ws == "alerts" and mode in ALERT_FILTER_MODES:
        app.alerts_filter_mode = mode
        app.set_workspace("alerts")
        app.render_alerts()
    elif ws == "dashboard" and mode in MOVERS_MODES:
        app.movers_mode = mode
        app.set_workspace("dashboard")
        app.render_dashboard()


def income_years(app: MarketPulseApp) -> list[int]:
    return sorted({int(e.date[:4]) for e in app.tracker.store.ledger().income})


def tax_years(app: MarketPulseApp) -> list[int]:
    if app._tax is None:
        return []
    return sorted({y.year for y in app._tax[0]} | {y.year for y in app._tax[3]})


# ── go to, find and groups (:, ctrl+f, ctrl+g, ( and )) ───────────────────────

_DATE_PREFIX = re.compile(r"(19|20)\d{2}(-\d{2}(-\d{2})?)?")


def _move(table: DataTable, row: int) -> None:
    table.move_cursor(row=row, animate=False)
    table.focus()


def go_to(app: MarketPulseApp, value: str) -> bool:
    """Move the cursor to row N (1-based), or in activity to the first entry dated with a prefix like 2024-03."""
    table = navigation.current_table(app)
    if table is None or table.row_count == 0:
        app.notify("No table rows here", timeout=3)
        return False
    value = value.strip()
    # In activity a year (1900-2099) or date prefix wins over a row number.
    is_date = app.workspace == "activity" and _DATE_PREFIX.fullmatch(value)
    if value.isdigit() and not is_date:
        _move(table, max(0, min(table.row_count - 1, int(value) - 1)))
        return True
    if is_date:
        dates = {str(t.id): t.date for t in app.tracker.store.transactions()}
        for index, row_key in enumerate(table.rows):
            if dates.get(str(row_key.value), "").startswith(value):
                _move(table, index)
                return True
        app.notify(f"No entry dated {value} is listed", timeout=3)
        return False
    hint = "a row number or a date like 2024-03" if app.workspace == "activity" else "a row number"
    app.notify(f"Type {hint}", timeout=3)
    return False


def prompt_go_to(app: MarketPulseApp) -> None:
    if navigation.current_table(app) is None:
        app.notify(": works on tables (holdings, watchlist, activity, accounts, alerts)", timeout=3)
        return
    hint = "A row number" + (", or a date: 2024-03-15, 2024-03 or 2024" if app.workspace == "activity" else "")

    def done(value: str | None) -> None:
        if value:
            go_to(app, value)

    app.push_screen(PromptScreen("Go to", "12", hint=hint), done)


def _row_text(table: DataTable, index: int) -> str:
    return " ".join(c.plain if isinstance(c, Text) else str(c) for c in table.get_row_at(index)).lower()


def find_next(app: MarketPulseApp, *, include_current: bool = False) -> bool:
    """Move to the next row (wrapping) whose cells, as shown, contain the find text, ignoring case."""
    needle = app.find_text.strip().lower()
    if not needle:
        prompt_find(app)
        return False
    table = navigation.current_table(app)
    if table is None or table.row_count == 0:
        app.notify("No table rows to search here", timeout=3)
        return False
    n = table.row_count
    start = table.cursor_row if include_current else table.cursor_row + 1
    for step in range(n):
        index = (start + step) % n
        if needle in _row_text(table, index):
            _move(table, index)
            app.notify(f"“{app.find_text}” · row {index + 1}/{n} · ctrl+g finds next", timeout=2)
            return True
    app.notify(f"No row contains “{app.find_text}”", timeout=3)
    return False


def prompt_find(app: MarketPulseApp) -> None:
    if navigation.current_table(app) is None:
        app.notify("ctrl+f finds rows in holdings, watchlist, activity, accounts and alerts", timeout=3)
        return

    def done(value: str | None) -> None:
        if value:
            app.find_text = value
            find_next(app, include_current=True)

    app.push_screen(
        PromptScreen("Find in table", "text in any column", app.find_text, hint="ctrl+g finds the next match"), done
    )


def _group(app: MarketPulseApp, key: str, context: dict) -> str:
    ws = app.workspace
    if ws == "holdings":
        return key.split(":")[1] if key.startswith("cash:") else key.split(":", 1)[0]
    if ws == "activity":
        return context.get(key, "")[:7]
    return context.get(key, "")


def _group_context(app: MarketPulseApp) -> tuple[dict[str, str], dict[str, str]] | None:
    """Group value per row key, plus a label per group value; None where rows don't group."""
    ws, store = app.workspace, app.tracker.store
    if ws == "holdings":
        names = {str(a.id): a.name for a in store.accounts(include_archived=True)}
        return {}, names
    if ws == "activity":
        dates = {str(t.id): t.date for t in store.transactions()}
        return dates, {}
    if ws == "alerts":
        return {str(a.id): a.symbol for a in store.alerts()}, {}
    if ws == "tax":
        return {str(a.id): a.type.label for a in store.accounts(include_archived=True)}, {}
    return None


def jump_group(app: MarketPulseApp, delta: int) -> None:
    """( / ): the first row of the next or previous group: holdings by account, activity by month,
    alerts by symbol, accounts by type."""
    table = navigation.current_table(app)
    context = _group_context(app)
    if table is None or context is None:
        app.notify("( and ) jump between groups in holdings, activity, accounts and alerts", timeout=3)
        return
    if table.row_count == 0:
        app.notify("No table rows here", timeout=3)
        return
    values, labels = context
    groups = [_group(app, str(k.value), values) for k in table.rows]
    cur = min(table.cursor_row, len(groups) - 1)
    if delta > 0:
        target = next((i for i in range(cur + 1, len(groups)) if groups[i] != groups[cur]), None)
    else:
        start = cur
        while start > 0 and groups[start - 1] == groups[cur]:
            start -= 1  # the first row of the current group
        target = None
        if start > 0:
            target = start - 1
            while target > 0 and groups[target - 1] == groups[start - 1]:
                target -= 1
    if target is None:
        app.notify("No more groups that way", timeout=2)
        return
    _move(table, target)
    app.notify(labels.get(groups[target], groups[target]) or "—", timeout=2)


# ── ledger issues (ctrl+e) ────────────────────────────────────────────────────


def next_issue(app: MarketPulseApp) -> None:
    """ctrl+e: select the next transaction a ledger issue names, clearing activity filters that hide it."""
    store = app.tracker.store
    issues = [i for i in store.ledger().issues if i.txn_id is not None]
    if not issues:
        app.notify("No ledger issues name a transaction", timeout=3)
        return
    on_activity = app.workspace == "activity"
    app.set_workspace("activity")
    table = app.query_one("#activity-table", DataTable)
    listed = {str(k.value) for k in table.rows}
    if any(str(i.txn_id) not in listed for i in issues):
        box = app.query_one("#activity-filter", Input)
        box.value = ""
        app.activity_filter_mode, app.activity_account_filter, app.activity_window = "all", None, "all"
        app.render_activity()
    order = [str(k.value) for k in table.rows]
    by_id = {str(i.txn_id): i for i in issues}
    rows = [index for index, key in enumerate(order) if key in by_id]
    if not rows:
        app.notify("No ledger issues name a listed transaction", timeout=3)
        return
    cur = table.cursor_row if on_activity else -1
    target = next((r for r in rows if r > cur), rows[0])
    _move(table, target)
    issue = by_id[order[target]]
    message = navigation._NUMBER.sub(fmt.MASK, issue.message) if app.privacy else issue.message
    app.notify(message, title=f"Ledger issue {rows.index(target) + 1} of {len(rows)}", severity="warning", timeout=5)


# ── chart (^, _, ', palette) ──────────────────────────────────────────────────


def chart_extreme(app: MarketPulseApp, high: bool) -> None:
    if not chart._chart_ready(app, "^ and _ move the crosshair"):
        return
    view = app.query_one("#chart-view", ChartView)
    bars = view.bars
    if not bars:
        app.notify("The chart is still loading", timeout=2)
        return
    if high:
        index = max(range(len(bars)), key=lambda i: bars[i].high)
        price = bars[index].high
    else:
        index = min(range(len(bars)), key=lambda i: bars[i].low)
        price = bars[index].low
    view.action_jump(index)
    app.notify(f"{app.chart_symbol} {app.chart_period} {'high' if high else 'low'} {fmt.price(price)}", timeout=2)


def remember_chart(app: MarketPulseApp, symbol: str) -> None:
    """Called before a chart opens: keep the symbol it replaces for '."""
    current = app.chart_symbol
    if current and current != symbol.upper():
        app.chart_history = [s for s in app.chart_history if s != current][-19:] + [current]


def previous_chart(app: MarketPulseApp) -> None:
    """': reopen the symbol charted before this one; pressing again flips back."""
    history = [s for s in app.chart_history if s != app.chart_symbol]
    if not history:
        app.notify("No earlier chart this session", timeout=3)
        return
    app.chart_history = history[:-1]
    app.open_chart(history[-1])


def copy_chart_csv(app: MarketPulseApp) -> None:
    """Palette: copy the open chart's bars (date or time, open, high, low, close, volume) as CSV."""
    bars = app.query_one("#chart-view", ChartView).bars
    if not app.chart_symbol or not bars:
        app.notify(chart.NO_CHART, timeout=3)
        return
    intraday = app.chart_period in ("1d", "5d")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["time" if intraday else "date", "open", "high", "low", "close", "volume"])
    for bar in bars:
        stamp = bar.local().isoformat(timespec="minutes") if intraday else bar.date
        writer.writerow([stamp, bar.open, bar.high, bar.low, bar.close, bar.volume])
    app.copy_to_clipboard(stream.getvalue())
    app.notify(f"Copied {_plural(len(bars), 'bar')} of {app.chart_symbol} {app.chart_period} as CSV", timeout=2)


# ── copies (", ctrl+t) ────────────────────────────────────────────────────────


def copy_table_json(app: MarketPulseApp) -> None:
    """Copy the visible table as a JSON array of objects keyed by column header, masks included."""
    data = navigation._table_matrix(app)
    if data is None:
        return
    headers, rows = data
    payload = [dict(zip(headers, row, strict=False)) for row in rows]
    app.copy_to_clipboard(json.dumps(payload, indent=2, ensure_ascii=False))
    app.notify(f"Copied {_plural(len(rows), 'row')} as JSON", timeout=2)


PANES = {
    "dashboard": ("#dash-accounts", "#perf"),
    "holdings": ("#holding-detail",),
    "watchlist": ("#watch-detail",),
    "chart": ("#chart-info",),
    "income": ("#income-view",),
    "tax": ("#tax-view",),
}


def pane_text(app: MarketPulseApp, selector: str) -> str:
    widget = app.query_one(selector, Static)
    console = Console(
        file=io.StringIO(),
        width=max(widget.size.width, 80),
        theme=RichTheme(rich_styles(app.palette)),
        color_system=None,
        record=True,
    )
    console.print(widget.content)
    return "\n".join(line.rstrip() for line in console.export_text().splitlines()).strip("\n")


def copy_pane(app: MarketPulseApp) -> None:
    """ctrl+t: copy the workspace's report or side pane as plain text, exactly as shown (masks included)."""
    selectors = PANES.get(app.workspace)
    if not selectors:
        app.notify("ctrl+t copies a side pane or report; Y and ctrl+y copy table rows", timeout=3)
        return
    text = "\n\n".join(t for t in (pane_text(app, s) for s in selectors) if t)
    if not text:
        app.notify("Nothing to copy yet", timeout=2)
        return
    app.copy_to_clipboard(text)
    app.notify(f"Copied {_plural(len(text.splitlines()), 'line')} of text", timeout=2)


# ── automatic refresh (ctrl+r) ────────────────────────────────────────────────


def toggle_auto_refresh(app: MarketPulseApp) -> None:
    timer = app._refresh_timer
    if timer is None:
        return
    app.auto_refresh_paused = not app.auto_refresh_paused
    if app.auto_refresh_paused:
        timer.pause()
        app.notify("Automatic refresh paused — r still refreshes, ctrl+r resumes", timeout=3)
    else:
        timer.resume()
        app.notify("Automatic refresh on", timeout=2)
        app.load_data()
    app._render_hints(app.workspace)


# ── watchlist order (ctrl+s) ──────────────────────────────────────────────────


def sorted_watch_symbols(app: MarketPulseApp) -> list[str] | None:
    """The watchlist as currently sorted, or None (with a message) when there's nothing to save."""
    if app.workspace != "watchlist":
        app.notify("ctrl+s saves the sorted watchlist as its list order (watchlist, 3)", timeout=3)
        return None
    if navigation.sort_state(app, "watchlist") == navigation.SORT_MODES["watchlist"][0]:
        app.notify("Sort the watchlist with o first; ctrl+s then saves that order", timeout=3)
        return None
    return [str(k.value) for k in app.query_one("#watch-table", DataTable).rows]


def save_watch_order(app: MarketPulseApp, symbols: list[str]) -> None:
    """Rewrite the saved list order in one transaction (runs in a worker)."""
    store = app.tracker.store
    with store.transaction():
        store.remove_watch(symbols)
        store.add_watch(symbols)


def watch_order_saved(app: MarketPulseApp, count: int) -> None:
    app.table_sort.pop("watchlist", None)
    app.watch_symbols = app.tracker.store.watchlist()
    app.render_watchlist()
    app.notify(f"Saved the watchlist order ({_plural(count, 'symbol')}); J / K reorder it again", timeout=3)
