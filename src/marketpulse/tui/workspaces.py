"""Workspaces helpers for the terminal app; Textual entry points stay on the app."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual.widgets import DataTable, Input, Static

from .. import fmt, render
from ..analytics import income_by_month, income_by_symbol
from ..models import AssetKind
from ..valuation import PositionView
from .constants import HOLDING_COLUMNS, NW_RANGES
from .widgets import Canvas, Tile, TopBar, money_tile, tile_content

if TYPE_CHECKING:
    from .app import MarketPulseApp


def render_store_views(app: MarketPulseApp) -> None:
    app.render_activity()
    app.render_accounts()
    app.render_alerts()
    app.render_tax()


def render_market_views(app: MarketPulseApp) -> None:
    app._render_topbar_status()
    app.render_dashboard()
    app.render_holdings()
    app.render_watchlist()
    app.render_accounts()
    app.render_alerts()
    app.render_income()
    app.render_position_detail()
    app.render_watch_detail()


def _render_topbar_status(app: MarketPulseApp) -> None:
    p, v = app.palette, app.view
    t = Text()
    if v is not None:
        state = {"REGULAR": ("●", p.up), "PRE": ("◐", p.warn), "POST": ("◑", p.warn), "CLOSED": ("○", p.muted)}.get(
            v.market_state
        )
        if state:
            t.append(f"{state[0]} ", style=state[1])
        t.append(fmt.money(v.net_worth, v.base, privacy=app.privacy, decimals=0), style=f"bold {p.bright}")
        t.append(
            f"  {fmt.arrow(v.day_change)} {fmt.pct(v.day_change_pct)}",
            style=f"bold {app._trend_hex(v.day_change)}",
        )
        if v.stale:
            t.append("  ◌ offline", style=p.warn)
    if app.privacy:
        t.append("  ◉ private", style=p.accent)
    bar = app.query_one(TopBar)
    bar.status = t
    bar.refresh()


def _snapshots(app: MarketPulseApp) -> list:
    today = date.today()
    since = {
        "1m": today - timedelta(days=31),
        "3m": today - timedelta(days=92),
        "6m": today - timedelta(days=183),
        "ytd": date(today.year, 1, 1),
        "1y": today - timedelta(days=366),
        "all": None,
    }[app.nw_range]
    base = app.tracker.base
    return [s for s in app.tracker.store.snapshots(since.isoformat() if since else None) if s.currency == base]


def render_dashboard(app: MarketPulseApp) -> None:
    v, p, priv = app.view, app.palette, app.privacy
    if v is None:
        app.query_one("#nw-chart", Canvas).set_builder(lambda w, h: Text("Loading portfolio…", style="muted"))
        return
    strip = render.strip_text(app.strip)
    strip.append("   ")
    strip.append_text(render.market_state_text(v.market_state))
    app.query_one("#strip", Static).update(strip)

    sub = Text(f"invested {fmt.money(v.invested, v.base, privacy=priv, decimals=0)}", style="muted")
    if v.stale:
        sub.append(f"  ◌ {render.stale_note(v).removeprefix('offline — ')}", style="warn")
    app.query_one("#tile-networth", Tile).set_builder(
        money_tile(f"net worth · {v.base}", v.net_worth, v.base, sub, privacy=priv)
    )

    def tile(label: str, value: Text, sub_text: Text | None):
        return lambda w, h: tile_content(label, value, sub_text, w)

    today_value = Text(
        f"{fmt.arrow(v.day_change)} {fmt.money(v.day_change, v.base, sign=True, privacy=priv)}",
        style=f"bold {app._trend_hex(v.day_change)}",
    )
    app.query_one("#tile-today", Tile).set_builder(
        tile("today", today_value, Text(fmt.pct(v.day_change_pct), style=app._trend_hex(v.day_change)))
    )
    unreal = Text(
        fmt.money(v.unrealized, v.base, sign=True, privacy=priv), style=f"bold {app._trend_hex(v.unrealized)}"
    )
    app.query_one("#tile-unrealized", Tile).set_builder(
        tile("unrealized", unreal, Text(fmt.pct(v.unrealized_pct), style=app._trend_hex(v.unrealized)))
    )
    income = Text(fmt.money(v.income_ytd, v.base, privacy=priv), style=f"bold {p.up if v.income_ytd else p.muted}")
    realized = Text(f"realized {fmt.money(v.realized_ytd, v.base, sign=True, privacy=priv)}", style="muted")
    app.query_one("#tile-income", Tile).set_builder(tile("income ytd", income, realized))
    perf = app.perf
    if perf is not None and perf.xirr_pct is not None:
        ret = Text(f"{fmt.pct(perf.xirr_pct)}/yr", style=f"bold {app._trend_hex(perf.xirr_pct)}")
        ret_sub = Text(f"twr {fmt.pct(perf.twr_pct)}", style="muted")
    else:
        ret = Text(fmt.pct(v.unrealized_pct), style=f"bold {app._trend_hex(v.unrealized)}")
        ret_sub = Text("simple return", style="muted")
    app.query_one("#tile-returns", Tile).set_builder(tile("returns", ret, ret_sub))

    snaps = app._snapshots()
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
            return Text("History builds daily. ctrl+p → “Backfill net worth history” rebuilds it now.", style="muted")
        change = snaps[-1].net_worth - snaps[0].net_worth
        pct = change / snaps[0].net_worth * 100 if snaps[0].net_worth else 0.0
        head = Text(
            f"{fmt.arrow(change)} {fmt.money(change, v.base, sign=True, privacy=priv)} ({fmt.pct(pct)})",
            style=app._trend_hex(change),
        )
        return Group(head, render.net_worth_chart(snaps, p, width=w, height=max(h - 2, 3), privacy=priv))

    app.query_one("#nw-chart", Canvas).set_builder(nw_chart)
    app.query_one("#pane-nw").border_subtitle = "  ".join(f"▸{r}" if r == app.nw_range else r for r in NW_RANGES)

    accounts = render.table("Account", "Type", ("Value", "right"), ("Today", "right"), "Weight", expand=True)
    acct_types = {str(a.id): a.type.label for a in app.tracker.store.accounts(include_archived=True)}
    for b in v.by_account:
        accounts.add_row(
            Text(b.label, style="bright"),
            Text(acct_types.get(b.key, ""), style="muted"),
            Text(fmt.money(b.value, v.base, privacy=priv)),
            render.trend(fmt.pct(b.day_change_pct), b.day_change),
            render.weight_cell(b.weight, 10),
        )
    app.query_one("#dash-accounts", Static).update(
        accounts if v.by_account else Text("No accounts with holdings yet.", style="muted")
    )

    breakdown = {"class": v.by_class, "account": v.by_account, "currency": v.by_currency}[app.alloc_mode]
    alloc = app.query_one("#alloc", Canvas)
    alloc.styles.height = max(len(breakdown), 1) + 1  # bar + one legend row per bucket
    alloc.set_builder(lambda w, h: render.allocation(breakdown, p, width=max(w - 1, 10), privacy=priv, base=v.base))
    app.query_one("#pane-alloc").border_subtitle = f"g ▸ {app.alloc_mode}"

    movers = Text()
    for i, pos in enumerate(v.movers(6)):
        if i:
            movers.append("\n")
        movers.append(f"{pos.symbol:<10}", style="bright")
        q = pos.quote
        if q and q.intraday:
            from ..charts import sparkline

            movers.append_text(sparkline(q.intraday, 12, app._trend_hex(q.change)))
        movers.append(
            f"  {fmt.arrow(pos.day_change_pct)} {fmt.pct(pos.day_change_pct):>8}",
            style=app._trend_hex(pos.day_change_pct),
        )
    app.query_one("#movers", Static).update(
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
    app.query_one("#perf", Static).update(grid)


def render_holdings(app: MarketPulseApp) -> None:
    v = app.view
    table = app.query_one("#holdings-table", DataTable)
    if v is None:
        return
    selected = app._selected_key(table)
    table.clear()
    positions = [p for p in v.positions if app.account_filter is None or p.account.id == app.account_filter]
    p = app.palette
    for pos in sorted(positions, key=lambda x: (x.account.name, -(x.value_base or 0))):
        cells = render.position_cells(pos, v.base, privacy=app.privacy)
        direction = app.flash.get(pos.symbol)
        if direction and pos.price is not None:
            cells[5] = Text(cells[5].plain, style=f"bold {p.background} on {p.up if direction > 0 else p.down}")
        row = app._justify([cells[i] for i in HOLDING_COLUMNS], range(2, 8))
        table.add_row(*row, key=f"{pos.account.id}:{pos.symbol}")
    for c in v.cash:
        if app.account_filter is not None and c.account.id != app.account_filter:
            continue
        cash_value = fmt.money(c.amount, privacy=app.privacy) + (f" {c.currency}" if c.currency != v.base else "")
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
        row = app._justify([cells[i] for i in HOLDING_COLUMNS], range(2, 8))
        table.add_row(*row, key=f"cash:{c.account.id}:{c.currency}")
    app._restore_cursor(table, selected)
    scope = "all accounts"
    if app.account_filter is not None:
        acct = app.tracker.store.get_account(app.account_filter)
        scope = acct.name if acct else scope
    total = sum(x.value_base or 0 for x in positions)
    if table.row_count == 0:
        subtitle = "No holdings yet — b to buy" if app.account_filter is None else f"f ▸ {scope} · nothing held"
    else:
        money = fmt.money(total, v.base, privacy=app.privacy, decimals=0)
        subtitle = f"f ▸ {scope} · {len(positions)} positions · {money}"
        if v.excluded:
            subtitle += f" · ⚠ {len(v.excluded)} excluded"
    app.query_one("#pane-holdings").border_subtitle = subtitle
    if app._detail_key is None and positions:
        first = app._selected_key(table)
        if first and not first.startswith("cash:"):
            app._show_position(first)


def render_watchlist(app: MarketPulseApp) -> None:
    table = app.query_one("#watch-table", DataTable)
    selected = app._selected_key(table)
    table.clear()
    p = app.palette
    for sym in app.watch_symbols:
        q = app.watch_quotes.get(sym)
        if q is None:
            cells = render.missing_quote_cells(sym, app.watch_errors.get(sym, "loading…"))
        else:
            cells = render.quote_cells(q, spark_width=18)
            direction = app.flash.get(sym)
            if direction:
                cells[2] = Text(cells[2].plain, style=f"bold {p.background} on {p.up if direction > 0 else p.down}")
        table.add_row(*app._justify(cells, range(2, 5)), key=sym)
    app._restore_cursor(table, selected)
    app.query_one("#pane-watch").border_subtitle = (
        f"{len(app.watch_symbols)} symbols" if app.watch_symbols else "Empty — a to add a symbol"
    )
    if app._watch_key is None and app.watch_symbols:
        app._show_watch(app.watch_symbols[0])


def render_activity(app: MarketPulseApp) -> None:
    table = app.query_one("#activity-table", DataTable)
    selected = app._selected_key(table)
    table.clear()
    store = app.tracker.store
    accounts = store.account_map()
    needle = app.query_one("#activity-filter", Input).value.strip().lower()
    txns = sorted(store.transactions(), key=lambda t: (t.date, t.id or 0), reverse=True)
    shown = 0
    for t in txns:
        cells = render.activity_cells(t, accounts, privacy=app.privacy)
        if needle and needle not in " ".join(c.plain.lower() for c in cells):
            continue
        table.add_row(*app._justify(cells, (0, 5, 6, 7, 8)), key=str(t.id))
        shown += 1
    app._restore_cursor(table, selected)
    issues = store.ledger().issues
    subtitle = f"{shown} of {len(txns)} transactions" if txns else "No transactions — n to add one"
    if issues:
        subtitle += f" · ⚠ {len(issues)} ledger issue(s)"
    app.query_one("#pane-activity").border_subtitle = subtitle


def render_accounts(app: MarketPulseApp) -> None:
    table = app.query_one("#accounts-table", DataTable)
    selected = app._selected_key(table)
    table.clear()
    values = {b.key: b for b in app.view.by_account} if app.view else {}
    base = app.tracker.base
    for a in app.tracker.store.accounts(include_archived=True):
        b = values.get(str(a.id))
        # Currency and cash tracking live in the edit form (e) to keep this pane narrow
        cells = [
            Text(str(a.id), style="muted"),
            Text(a.name + (" (archived)" if a.archived else ""), style="bright"),
            Text(a.type.label, style="accent" if a.type.registered else ""),
            Text(fmt.money(b.value, base, privacy=app.privacy)) if b else render.dash(),
            render.trend(fmt.pct(b.day_change_pct), b.day_change) if b else render.dash(),
        ]
        table.add_row(*app._justify(cells, (0, 3, 4)), key=str(a.id))
    app._restore_cursor(table, selected)


def render_alerts(app: MarketPulseApp) -> None:
    table = app.query_one("#alerts-table", DataTable)
    selected = app._selected_key(table)
    table.clear()
    quotes = {**(app.view.quotes if app.view else {}), **app.watch_quotes}
    alerts = app.tracker.store.alerts()
    app.query_one("#pane-alerts").border_subtitle = (
        f"{sum(a.active for a in alerts)} armed of {len(alerts)}" if alerts else "No alerts — A to add one"
    )
    for a in alerts:
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
    app._restore_cursor(table, selected)


def render_position_detail(app: MarketPulseApp) -> None:
    key, v = app._detail_key, app.view
    target = app.query_one("#holding-detail", Static)
    if not key or v is None:
        target.update(Text("Select a holding.", style="muted"))
        return
    acct_id, sym = key.split(":", 1)
    pos: PositionView | None = next((x for x in v.positions if str(x.account.id) == acct_id and x.symbol == sym), None)
    if pos is None:
        target.update(Text("Position closed.", style="muted"))
        return
    priv = app.privacy
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
                style=app._trend_hex(pos.day_change_pct),
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
    bars = app._detail_bars.get(sym)
    if bars:
        parts += [
            Text(""),
            Text("3 MONTHS", style="muted"),
            render.price_chart(sym, bars, "3mo", app.palette, width=width, height=7),
        ]
    txns = [t for t in app.tracker.store.transactions(symbol=sym) if t.account_id == pos.account.id][-6:]
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


def render_watch_detail(app: MarketPulseApp) -> None:
    target = app.query_one("#watch-detail", Static)
    sym = app._watch_key
    q = app.watch_quotes.get(sym) if sym else None
    if q is None:
        target.update(Text("Select a symbol.", style="muted"))
        return
    parts: list[RenderableType] = [render.quote_card(q)]
    bars = app._detail_bars.get(q.symbol)
    if bars:
        parts += [
            Text(""),
            Text("3 MONTHS", style="muted"),
            render.price_chart(q.symbol, bars, "3mo", app.palette, width=max(target.size.width, 30), height=8),
        ]
    held = [x for x in (app.view.positions if app.view else []) if x.symbol == q.symbol]
    if held:
        qty = sum(x.quantity for x in held)
        parts.append(
            Text(
                f"\nYou hold {fmt.MASK if app.privacy else fmt.qty(qty)} across {len(held)} account(s).",
                style="accent",
            )
        )
    target.update(Group(*parts))


def render_income(app: MarketPulseApp) -> None:
    v = app.view
    if v is None:
        return
    state = app.tracker.store.ledger()
    months = income_by_month(state, v.fx.convert)
    sources = income_by_symbol(state, v.fx.convert, date.today().year)
    body = render.income_group(months, sources, app._income_forecast, v, privacy=app.privacy)
    if app._income_forecast is None:
        body = Group(body, Text("\nForward estimate loads when you open this workspace.", style="muted"))
    app.query_one("#income-view", Static).update(body)


def render_tax(app: MarketPulseApp) -> None:
    target = app.query_one("#tax-view", Static)
    if app._tax is None:
        target.update(Text("Building tax report…", style="muted"))
        return
    years, report, rooms = app._tax
    tr = app.tracker
    body = render.tax_group(years, report, rooms, tr.store.account_map(), tr.base, privacy=app.privacy)
    target.update(Group(body, Text("\nEstimates only — confirm against broker slips (T5008/T3/T5).", style="muted")))
