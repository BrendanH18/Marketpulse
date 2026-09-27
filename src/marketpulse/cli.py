"""MarketPulse command line. Run with no arguments to open the TUI."""

from __future__ import annotations

import csv
import io
import json
import platform
import shutil
import sys
import time
from dataclasses import fields, replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import click
from rich.console import Console, Group
from rich.text import Text
from rich.theme import Theme as RichTheme

from . import __version__, fmt, render
from .config import Config, config_path
from .market import BARS_PER_YEAR, PERIOD_INTERVALS, PERIODS, MarketError
from .models import (
    ALERT_CONDITIONS,
    EPSILON,
    Account,
    AccountType,
    Alert,
    Asset,
    AssetClass,
    AssetKind,
    Transaction,
    TxnType,
    parse_date,
    parse_symbols,
)
from .tax import TaxReport
from .themes import OMARCHY_PALETTES, omarchy_active, pretty_name, resolve_palette, rich_styles

if TYPE_CHECKING:  # for annotations only; the real imports stay lazy
    from .db import Store
    from .services import Tracker

for _stream in (sys.stdout, sys.stderr):
    # Replace unencodable characters instead of crashing on a non-UTF-8 terminal.
    # Only real text streams can be reconfigured (pytest/CliRunner swap in others).
    if isinstance(_stream, io.TextIOWrapper):
        try:
            _stream.reconfigure(errors="replace")
        except ValueError:
            pass


class App:
    """Lazy per-invocation context: config and console are cheap, the tracker
    (database + network client) is only opened by commands that need it."""

    def __init__(self) -> None:
        self.config = Config.load()
        self.palette = resolve_palette(self.config.theme)
        self.console = Console(theme=RichTheme(rich_styles(self.palette)), highlight=False)
        self._tracker: Tracker | None = None

    @property
    def tracker(self) -> Tracker:
        if self._tracker is None:
            # Imported here so `marketpulse --help` and friends start instantly.
            from .services import Tracker

            self._tracker = Tracker.open(self.config)
        return self._tracker

    @property
    def store(self) -> Store:
        return self.tracker.store

    @property
    def privacy(self) -> bool:
        return self.config.privacy

    def busy(self, message: str):
        return self.console.status(Text(message, style="accent"), spinner="dots")

    def ok(self, message: str) -> None:
        self.console.print(Text("✓ ", style="up") + Text(message))

    def warn(self, message: str) -> None:
        self.console.print(Text("! ", style="warn") + Text(message, style="muted"))

    def title(self, message: str) -> None:
        self.console.print(Text(f"▍{message}", style="title"))

    def account(self, ref: str | None) -> Account:
        store = self.store
        if ref:
            acct = store.get_account(ref)
            if acct is None:
                names = ", ".join(a.name for a in store.accounts()) or "none yet"
                fail(f"No account '{ref}'. Accounts: {names}. Create one with `marketpulse accounts add`.")
            return acct
        if self.config.default_account:
            acct = store.get_account(self.config.default_account)
            if acct is not None:
                return acct
        accounts = store.accounts()
        if not accounts:
            acct = store.ensure_default_account(self.config.base_currency)
            self.warn(f"Created account '{acct.name}' ({acct.type.label}, {acct.currency}).")
            return acct
        if len(accounts) == 1:
            return accounts[0]
        fail(
            "Several accounts — choose one with -a/--account ("
            + ", ".join(a.name for a in accounts)
            + ") or set a default: `marketpulse config set default_account NAME`."
        )


pass_app = click.make_pass_decorator(App, ensure=True)


def fail(message: str) -> NoReturn:
    """Abort the command with a friendly error (exit code 1, no traceback).

    Typed NoReturn so the type checker knows code after `fail()` is
    unreachable, e.g. `if acct is None: fail(...)` narrows acct to Account.
    """
    raise click.ClickException(message)


def _date_callback(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """Normalize a date option to ISO up front, so a typo is a usage error rather than a traceback."""
    if value is None:
        return None
    try:
        return parse_date(value)
    except ValueError as e:
        raise click.BadParameter(str(e), ctx=ctx, param=param) from None


def txn_options(f):
    f = click.option("-m", "--note", default="", help="Free-text note.")(f)
    f = click.option(
        "-d",
        "--date",
        "when",
        default=None,
        callback=_date_callback,
        help="YYYY-MM-DD, 'yesterday' or -3d (default: today).",
    )(f)
    f = click.option("-a", "--account", default=None, help="Account name, id or type (e.g. TFSA).")(f)
    return f


# ── Root ──────────────────────────────────────────────────────────────────────


@click.group(
    invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 110}
)
@click.version_option(__version__, "-V", "--version", prog_name="MarketPulse")
@click.pass_context
def main(ctx: click.Context) -> None:
    """⚡ MarketPulse — a fast, keyboard-first investment tracker.

    \b
    Run with no command to open the TUI.
    \b
      marketpulse buy XEQT.TO 20            buy at the live price
      marketpulse sell AAPL 5 230 -a TFSA   sell at a price, in an account
      marketpulse dividend VFV.TO 42.10     record income
      marketpulse holdings                  priced holdings
      marketpulse chart NVDA -p 1y --vs QQQ braille chart with comparison
      marketpulse status --waybar           for Omarchy's Waybar
      marketpulse menubar install           macOS menu bar companion
    """
    ctx.ensure_object(App)
    if ctx.invoked_subcommand is None:
        ctx.invoke(tui)


@main.command()
@click.option("-r", "--refresh", type=int, default=None, help="Quote refresh interval in seconds.")
@click.option("-t", "--theme", default=None, help="Theme for this session (see `marketpulse theme`).")
@pass_app
def tui(app: App, refresh: int | None, theme: str | None) -> None:
    """Open the interactive TUI (default command)."""
    from .tui import run

    cfg = app.config
    if refresh is not None:
        cfg = replace(cfg, refresh_seconds=max(refresh, 5))
    if theme:
        cfg = replace(cfg, theme=_theme_slug(theme))
    run(cfg)


# ── Overview ──────────────────────────────────────────────────────────────────


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Full machine-readable payload (used by the menu bar).")
@click.option("--waybar", is_flag=True, help="Waybar custom-module JSON (text/tooltip/class).")
@click.option("--short", is_flag=True, help="One line, for tmux/sketchybar/prompt segments.")
@pass_app
def status(app: App, as_json: bool, waybar: bool, short: bool) -> None:
    """Portfolio status at a glance."""
    tr = app.tracker
    if as_json:
        click.echo(json.dumps(tr.status_payload(), ensure_ascii=False))
        return
    view = tr.valuation()
    day = f"{fmt.arrow(view.day_change)} {fmt.pct(view.day_change_pct)}"
    if waybar:
        day_money = fmt.money(view.day_change, view.base, sign=True, privacy=app.privacy)
        unrealized_money = fmt.money(view.unrealized, view.base, sign=True, privacy=app.privacy)
        tooltip = [
            f"Net worth  {fmt.money(view.net_worth, view.base, privacy=app.privacy)} {view.base}",
            f"Today      {day_money} ({fmt.pct(view.day_change_pct)})",
            f"Unrealized {unrealized_money} ({fmt.pct(view.unrealized_pct)})",
            "",
            *(
                f"{b.label:<16} {fmt.money(b.value, view.base, privacy=app.privacy):>14}  {fmt.pct(b.day_change_pct)}"
                for b in view.by_account
            ),
        ]
        click.echo(
            json.dumps(
                {
                    "text": f"󰄨 {day}",
                    "alt": fmt.compact(view.net_worth, view.base, privacy=app.privacy),
                    "tooltip": "\n".join(tooltip),
                    "class": fmt.trend_style(view.day_change),
                    "percentage": round(view.day_change_pct, 2),
                },
                ensure_ascii=False,
            )
        )
        return
    if short:
        click.echo(f"{day} · {fmt.compact(view.net_worth, view.base, privacy=app.privacy)}")
        return
    app.console.print(render.summary(view, privacy=app.privacy))


@main.command("summary")
@pass_app
def summary_cmd(app: App) -> None:
    """Dashboard: net worth, returns, allocation, movers and markets."""
    tr = app.tracker
    with app.busy("Loading markets and portfolio…"):
        view = tr.valuation()
        perf = tr.performance(view)
        strip = tr.market_strip()
        snaps = [
            s
            for s in tr.store.snapshots((date.today().replace(year=date.today().year - 1)).isoformat())
            if s.currency == view.base
        ]
    c = app.console
    c.print(render.strip_text(strip), render.market_state_text(view.market_state))
    c.print()
    c.print(render.summary(view, perf, privacy=app.privacy))
    c.print()
    app.title("Net worth · 1y")
    c.print(render.net_worth_chart(snaps, app.palette, width=min(c.width - 2, 110), privacy=app.privacy))
    c.print()
    app.title("Allocation")
    c.print(
        render.allocation(view.by_class, app.palette, width=min(c.width - 4, 80), privacy=app.privacy, base=view.base)
    )
    movers = view.movers(6)
    if movers:
        c.print()
        app.title("Today's movers")
        line = Text()
        for p in movers:
            line.append(f"{p.symbol} ", style="bright")
            line.append(
                f"{fmt.arrow(p.day_change_pct)}{abs(p.day_change_pct or 0):.2f}%   ",
                style=fmt.trend_style(p.day_change_pct),
            )
        c.print(line)


@main.command()
@click.option("-a", "--account", default=None, help="Only this account.")
@pass_app
def holdings(app: App, account: str | None) -> None:
    """Priced holdings with gains, day change and weights."""
    acct = app.account(account) if account else None
    with app.busy("Pricing holdings…"):
        view = app.tracker.valuation(account_id=acct.id if acct else None)
    if not view.positions and not view.cash:
        app.console.print(Text("No holdings yet — try `marketpulse buy XEQT.TO 10`.", style="muted"))
        return
    app.console.print(render.holdings_table(view, privacy=app.privacy, width=app.console.width))
    app.console.print(render.summary(view, privacy=app.privacy))
    for reason in sorted(set(view.errors.values())):
        app.warn(reason)


@main.command()
@pass_app
def perf(app: App) -> None:
    """Returns: money-weighted, time-weighted, drawdown and volatility."""
    tr = app.tracker
    with app.busy("Calculating performance…"):
        view = tr.valuation()
        result = tr.performance(view)
    app.title("Performance")
    app.console.print(
        render.performance_group(result, view, app.palette, width=min(app.console.width - 2, 110), privacy=app.privacy)
    )


@main.command()
@click.option("--by", type=click.Choice(["class", "account", "currency"]), default="class", show_default=True)
@click.option(
    "--target", "targets", multiple=True, metavar="CLASS=PCT", help="Set an asset-class target, e.g. --target etf=80."
)
@click.option("--clear-targets", is_flag=True, help="Remove all targets.")
@pass_app
def allocation(app: App, by: str, targets: tuple[str, ...], clear_targets: bool) -> None:
    """Allocation breakdown and rebalancing against asset-class targets."""
    from .analytics import rebalance

    store = app.store
    if clear_targets:
        store.set_targets({})
        app.ok("Targets cleared.")
    if targets:
        parsed = dict(store.targets())
        valid = {c.value for c in AssetClass}
        for item in targets:
            key, _, value = item.partition("=")
            key = key.strip().lower().replace(" ", "_")
            if key not in valid:
                fail(f"Unknown asset class '{key}'. Choose from: {', '.join(sorted(valid))}")
            try:
                parsed[key] = float(value)
            except ValueError:
                fail(f"Target for {key} must be a number.")
        total = sum(parsed.values())
        if total > 100.0001:
            fail(f"Targets add up to {total:g}% — keep them at or under 100%.")
        store.set_targets(parsed)
        app.ok(f"Targets saved ({total:g}% allocated).")
    with app.busy("Pricing holdings…"):
        view = app.tracker.valuation()
    breakdown = {"class": view.by_class, "account": view.by_account, "currency": view.by_currency}[by]
    app.title(f"Allocation by {by}")
    app.console.print(
        render.allocation(
            breakdown, app.palette, width=min(app.console.width - 4, 80), privacy=app.privacy, base=view.base
        )
    )
    current_targets = store.targets()
    if by == "class" and current_targets:
        app.console.print()
        app.console.print(
            render.rebalance_table(
                rebalance(view.by_class, current_targets, view.net_worth), view.base, privacy=app.privacy
            )
        )


# ── Market data ───────────────────────────────────────────────────────────────


@main.command()
@click.argument("symbols", nargs=-1, required=True)
@pass_app
def quote(app: App, symbols: tuple[str, ...]) -> None:
    """Live quotes. One symbol shows a detail card."""
    syms = parse_symbols(" ".join(symbols))
    with app.busy("Fetching quotes…"):
        quotes, errors = app.tracker.market.quotes(syms)
    if len(syms) == 1:
        q = quotes.get(syms[0])
        if q is None:
            fail(f"{syms[0]}: {errors.get(syms[0], 'no data')}")
        app.console.print(render.quote_card(q))
        return
    app.console.print(render.quotes_table(syms, quotes, errors, width=app.console.width))


@main.command()
@click.argument("symbol")
@click.option("-p", "--period", type=click.Choice(PERIODS), default=None, help="Default from config (chart_period).")
@click.option("--vs", "versus", multiple=True, help="Overlay other symbols as % change.")
@click.option("-H", "--height", type=int, default=16, show_default=True)
@pass_app
def chart(app: App, symbol: str, period: str | None, versus: tuple[str, ...], height: int) -> None:
    """Braille price chart, optionally compared against other symbols."""
    period = period or app.config.chart_period
    market = app.tracker.market
    try:
        with app.busy(f"Fetching {symbol.upper()} {period}…"):
            bars = market.history(symbol, period)
            others = {v.upper(): market.history(v, period) for v in versus}
            quotes, _ = market.quotes([symbol])
    except MarketError as e:
        fail(str(e))
    q = quotes.get(symbol.upper())
    if q:
        app.console.print(render.quote_card(q))
        app.console.print()
    app.console.print(
        render.price_chart(
            symbol.upper(),
            bars,
            period,
            app.palette,
            width=app.console.width - 1,
            height=height,
            quote=q,
            compare=others or None,
        )
    )


@main.command()
@click.argument("symbols", nargs=-1, required=True)
@click.option("-p", "--period", type=click.Choice(PERIODS), default="1y", show_default=True)
@pass_app
def compare(app: App, symbols: tuple[str, ...], period: str) -> None:
    """Compare returns, drawdown and volatility across symbols."""
    from .analytics import max_drawdown, period_return, volatility

    syms = parse_symbols(" ".join(symbols))
    market = app.tracker.market
    data = {}
    with app.busy(f"Fetching {len(syms)} histories…"):
        for s in syms:
            try:
                data[s] = market.history(s, period)
            except MarketError as e:
                app.warn(str(e))
    data = {k: v for k, v in data.items() if v}
    if not data:
        fail("No data retrieved.")
    first, *rest = data
    app.console.print(
        render.price_chart(
            first,
            data[first],
            period,
            app.palette,
            width=app.console.width - 1,
            compare={r: data[r] for r in rest} or None,
        )
    )
    t = render.table(
        "Symbol",
        ("Start", "right"),
        ("End", "right"),
        ("Return", "right"),
        ("Max drawdown", "right"),
        ("Volatility", "right"),
        title=f"\n{period} comparison",
    )
    for s, bars in sorted(data.items(), key=lambda kv: period_return([b.close for b in kv[1]]) or 0, reverse=True):
        closes = [b.close for b in bars]
        ret = period_return(closes)
        per_year = BARS_PER_YEAR[PERIOD_INTERVALS[period]]
        t.add_row(
            Text(s, style="bright"),
            Text(fmt.price(closes[0]), style="muted"),
            Text(fmt.price(closes[-1])),
            render.trend(fmt.pct(ret), ret),
            Text(fmt.pct(max_drawdown(closes)), style="down"),
            Text(fmt.pct(volatility(closes, per_year), sign=False), style="muted"),
        )
    app.console.print(t)


@main.command()
@click.argument("query", nargs=-1, required=True)
@pass_app
def search(app: App, query: tuple[str, ...]) -> None:
    """Find symbols by company or fund name."""
    try:
        with app.busy("Searching…"):
            results = app.tracker.market.search(" ".join(query), limit=12)
    except MarketError as e:
        fail(str(e))
    if not results:
        fail("No matches.")
    app.console.print(render.search_table(results))


# ── Recording transactions ────────────────────────────────────────────────────


def _record(app: App, txn: Transaction) -> Transaction:
    try:
        return app.tracker.add_transaction(txn)
    except ValueError as e:
        fail(str(e))


def _trade(
    app: App,
    kind: TxnType,
    symbol: str,
    quantity: float,
    price: float | None,
    account: str | None,
    fees: float,
    when: str | None,
    currency: str,
    note: str,
) -> None:
    acct = app.account(account)
    sym = symbol.upper()
    ccy = currency.upper()
    day = when or date.today().isoformat()
    if price is None or not ccy:
        with app.busy(f"Looking up {sym}…"):
            live_ccy, q = app.tracker.resolve_currency(sym, acct)
        ccy = ccy or live_ccy
        if price is None:
            if q is None:
                fail(f"No live price for {sym} — pass PRICE explicitly.")
            if day != date.today().isoformat():
                fail("A back-dated trade needs an explicit PRICE.")
            price = q.price
    txn = _record(
        app,
        Transaction(
            account_id=acct.saved_id,
            type=kind,
            date=day,
            symbol=sym,
            quantity=quantity,
            price=price,
            fees=fees,
            currency=ccy,
            note=note,
        ),
    )
    state = app.store.ledger()
    h = state.holdings.get((acct.saved_id, sym))
    verb = "Bought" if kind is TxnType.BUY else "Sold"
    msg = f"{verb} {fmt.qty(quantity)} {sym} @ {fmt.price(price)} {ccy} in {acct.name}"
    if kind is TxnType.SELL:
        gain = next((r.gain for r in reversed(state.realized) if r.txn_id == txn.id), None)
        if gain is not None:
            msg += f" — realized {fmt.money(gain, sign=True)} {ccy}"
    if h and h.quantity > EPSILON:
        msg += f" · now {fmt.qty(h.quantity)} @ avg {fmt.price(h.avg_cost)}"
    elif kind is TxnType.SELL:
        msg += " · position closed"
    app.ok(msg)


@main.command()
@click.argument("symbol")
@click.argument("quantity", type=float)
@click.argument("price", type=float, required=False)
@click.option("-f", "--fees", type=float, default=0.0, help="Commission; added to cost base.")
@click.option("-c", "--currency", default="", help="Trade currency (default: the listing's).")
@txn_options
@pass_app
def buy(app: App, symbol, quantity, price, fees, currency, account, when, note) -> None:
    """Record a buy. PRICE defaults to the live price."""
    _trade(app, TxnType.BUY, symbol, quantity, price, account, fees, when, currency, note)


@main.command()
@click.argument("symbol")
@click.argument("quantity", type=float)
@click.argument("price", type=float, required=False)
@click.option("-f", "--fees", type=float, default=0.0, help="Commission; deducted from proceeds.")
@click.option("-c", "--currency", default="", help="Trade currency (default: the listing's).")
@txn_options
@pass_app
def sell(app: App, symbol, quantity, price, fees, currency, account, when, note) -> None:
    """Record a sell (average-cost ACB). PRICE defaults to the live price."""
    _trade(app, TxnType.SELL, symbol, quantity, price, account, fees, when, currency, note)


def _cash_event(
    app: App, kind: TxnType, amount: float, symbol: str, account: str | None, when: str | None, currency: str, note: str
) -> None:
    acct = app.account(account)
    day = when or date.today().isoformat()
    txn = Transaction(
        account_id=acct.saved_id,
        type=kind,
        date=day,
        symbol=symbol.upper(),
        amount=amount,
        currency=currency.upper(),
        note=note,
    )
    _record(app, txn)
    target = f" from {txn.symbol}" if txn.symbol else ""
    app.ok(f"{kind.value.title()} {fmt.money(amount)} {txn.currency}{target} → {acct.name} on {day}")


@main.command()
@click.argument("symbol")
@click.argument("amount", type=float)
@click.option("-c", "--currency", default="")
@txn_options
@pass_app
def dividend(app: App, symbol, amount, currency, account, when, note) -> None:
    """Record a cash dividend or distribution."""
    _cash_event(app, TxnType.DIVIDEND, amount, symbol, account, when, currency, note)


@main.command()
@click.argument("symbol")
@click.argument("quantity", type=float)
@click.argument("price", type=float)
@txn_options
@pass_app
def drip(app: App, symbol, quantity, price, account, when, note) -> None:
    """Record a reinvested dividend (new shares at PRICE)."""
    acct = app.account(account)
    ccy, _ = app.tracker.resolve_currency(symbol, acct)
    _record(
        app,
        Transaction(
            account_id=acct.saved_id,
            type=TxnType.DRIP,
            date=parse_date(when),
            symbol=symbol,
            quantity=quantity,
            price=price,
            currency=ccy,
            note=note,
        ),
    )
    app.ok(f"DRIP {fmt.qty(quantity)} {symbol.upper()} @ {fmt.price(price)} {ccy} in {acct.name}")


@main.command()
@click.argument("amount", type=float)
@click.option("-c", "--currency", default="")
@txn_options
@pass_app
def deposit(app: App, amount, currency, account, when, note) -> None:
    """Record money added to an account (counts as a contribution)."""
    _cash_event(app, TxnType.DEPOSIT, amount, "", account, when, currency, note)


@main.command()
@click.argument("amount", type=float)
@click.option("-c", "--currency", default="")
@txn_options
@pass_app
def withdraw(app: App, amount, currency, account, when, note) -> None:
    """Record money taken out of an account."""
    _cash_event(app, TxnType.WITHDRAWAL, amount, "", account, when, currency, note)


@main.command()
@click.argument("amount", type=float)
@click.option("-s", "--symbol", default="", help="Security paying the interest (optional).")
@click.option("-c", "--currency", default="")
@txn_options
@pass_app
def interest(app: App, amount, symbol, currency, account, when, note) -> None:
    """Record interest income."""
    _cash_event(app, TxnType.INTEREST, amount, symbol, account, when, currency, note)


@main.command()
@click.argument("amount", type=float)
@click.option("-c", "--currency", default="")
@txn_options
@pass_app
def fee(app: App, amount, currency, account, when, note) -> None:
    """Record an account-level fee."""
    _cash_event(app, TxnType.FEE, amount, "", account, when, currency, note)


@main.command()
@click.argument("symbol")
@click.argument("ratio", type=float)
@txn_options
@pass_app
def split(app: App, symbol, ratio, account, when, note) -> None:
    """Record a stock split (RATIO new shares per old share, e.g. 4 or 0.1)."""
    acct = app.account(account)
    _record(
        app,
        Transaction(
            account_id=acct.saved_id, type=TxnType.SPLIT, date=parse_date(when), symbol=symbol, ratio=ratio, note=note
        ),
    )
    app.ok(f"Split {symbol.upper()} ×{ratio:g} in {acct.name}")


@main.command()
@click.argument("symbol")
@click.argument("quantity", type=float)
@click.option("--from", "source", required=True, help="Source account.")
@click.option("--to", "target", required=True, help="Destination account.")
@click.option(
    "-p",
    "--price",
    type=float,
    default=None,
    help="Market value per unit on the transfer date. Needed for tax when moving between "
    "a taxable and a registered account (defaults to the live price when dated today).",
)
@click.option("-d", "--date", "when", default=None, callback=_date_callback)
@click.option("-m", "--note", default="")
@pass_app
def transfer(app: App, symbol, quantity, source, target, price, when, note) -> None:
    """Move shares between accounts (e.g. in-kind to a TFSA).

    \b
    Holdings move at cost. For tax, a move from a taxable account into a
    registered one is a deemed sale at market value (a loss is denied), and
    a move out of a registered account resets the cost to market value, so
    give --price for those.
    """
    src, dst = app.account(source), app.account(target)
    day = parse_date(when)
    currency = ""
    # Only a move across the registered/taxable line has a tax effect.
    crosses = src.type.registered != dst.type.registered
    if price is None and crosses:
        if day == date.today().isoformat():
            try:
                q = app.tracker.market.quote(symbol)
                price, currency = q.price, q.currency
                app.warn(f"using the live price {fmt.price(q.price)} {q.currency} as the market value")
            except MarketError:
                pass
        if price is None:
            app.warn("no --price given: the tax report will ask for this transfer's market value")
    _record(
        app,
        Transaction(
            account_id=src.saved_id,
            type=TxnType.TRANSFER,
            date=day,
            symbol=symbol,
            quantity=quantity,
            price=price or 0.0,
            currency=currency,
            target_account_id=dst.id,
            note=note,
        ),
    )
    app.ok(f"Transferred {fmt.qty(quantity)} {symbol.upper()} {src.name} → {dst.name}")


@main.command()
@click.option("-a", "--account", default=None)
@click.option("-s", "--symbol", default=None)
@click.option("-n", "--limit", type=int, default=40, show_default=True)
@click.option("--all", "show_all", is_flag=True)
@pass_app
def activity(app: App, account, symbol, limit, show_all) -> None:
    """The transaction ledger, newest first."""
    acct = app.account(account) if account else None
    txns = app.store.transactions(account_id=acct.id if acct else None, symbol=symbol)
    if not txns:
        app.console.print(Text("No transactions yet.", style="muted"))
        return
    app.console.print(
        render.activity_table(txns, app.store.account_map(), privacy=app.privacy, limit=None if show_all else limit)
    )
    issues = app.store.ledger().issues
    for issue in issues:
        app.warn(f"#{issue.txn_id} {issue.date}: {issue.message}")


@main.command()
@click.option("-y", "--yes", is_flag=True)
@pass_app
def undo(app: App, yes: bool) -> None:
    """Delete the most recently recorded transaction."""
    txns = app.store.transactions()
    if not txns:
        fail("Nothing to undo.")
    last = max(txns, key=lambda t: t.id or 0)
    app.console.print(render.activity_table([last], app.store.account_map()))
    if yes or click.confirm("Delete this transaction?"):
        app.store.delete_transaction(last.saved_id)
        app.ok(f"Deleted transaction #{last.id}.")


@main.group()
def txn() -> None:
    """Edit or delete individual transactions (ids from `activity`)."""


@txn.command("delete")
@click.argument("txn_id", type=int)
@click.option("-y", "--yes", is_flag=True)
@pass_app
def txn_delete(app: App, txn_id: int, yes: bool) -> None:
    match = [t for t in app.store.transactions() if t.id == txn_id]
    if not match:
        fail(f"No transaction #{txn_id}.")
    app.console.print(render.activity_table(match, app.store.account_map()))
    if yes or click.confirm("Delete?"):
        app.store.delete_transaction(txn_id)
        app.ok(f"Deleted #{txn_id}.")


@txn.command("edit")
@click.argument("txn_id", type=int)
@click.option("--date", "when", callback=_date_callback)
@click.option("--account")
@click.option("--symbol")
@click.option("--quantity", type=float)
@click.option("--price", type=float)
@click.option("--amount", type=float)
@click.option("--fees", type=float)
@click.option("--currency")
@click.option("--note")
@pass_app
def txn_edit(app: App, txn_id: int, when, account, symbol, quantity, price, amount, fees, currency, note) -> None:
    match = [t for t in app.store.transactions() if t.id == txn_id]
    if not match:
        fail(f"No transaction #{txn_id}.")
    t = match[0]
    if when is not None:
        t.date = when
    if account is not None:
        t.account_id = app.account(account).saved_id
    for name, value in (
        ("symbol", symbol),
        ("quantity", quantity),
        ("price", price),
        ("amount", amount),
        ("fees", fees),
        ("currency", currency),
        ("note", note),
    ):
        if value is not None:
            setattr(t, name, value.upper() if name in ("symbol", "currency") else value)
    try:
        app.store.update_transaction(t)
    except ValueError as e:
        fail(str(e))
    app.console.print(render.activity_table([t], app.store.account_map()))
    app.ok(f"Updated #{txn_id}.")


# ── Accounts ──────────────────────────────────────────────────────────────────

ACCOUNT_TYPES = [t.value for t in AccountType]


@main.group(invoke_without_command=True)
@click.pass_context
def accounts(ctx: click.Context) -> None:
    """Accounts (TFSA, RRSP, FHSA, non-registered, crypto…) and contribution room."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(accounts_list)


@accounts.command("list")
@click.option("--archived", is_flag=True, help="Include archived accounts.")
@pass_app
def accounts_list(app: App, archived: bool) -> None:
    items = app.store.accounts(include_archived=archived)
    if not items:
        app.console.print(Text('No accounts yet — `marketpulse accounts add "My TFSA" -t TFSA`.', style="muted"))
        return
    with app.busy("Pricing accounts…"):
        view = app.tracker.valuation()
    values = {b.key: b for b in view.by_account}
    t = render.table(
        ("ID", "right"),
        "Name",
        "Type",
        "Ccy",
        "Institution",
        "Cash",
        ("Value", "right"),
        ("Today", "right"),
        ("Weight", "right"),
    )
    for a in items:
        b = values.get(str(a.id))
        t.add_row(
            Text(str(a.id), style="muted"),
            Text(a.name + (" (archived)" if a.archived else ""), style="bright"),
            Text(a.type.label, style="accent" if a.type.registered else ""),
            Text(a.currency, style="muted"),
            Text(a.institution or "—", style="muted"),
            Text("tracked" if a.track_cash else "—", style="muted"),
            Text(fmt.money(b.value, view.base, privacy=app.privacy)) if b else render.dash(),
            render.trend(fmt.pct(b.day_change_pct), b.day_change) if b else render.dash(),
            Text(fmt.pct(b.weight, sign=False), style="muted") if b else render.dash(),
        )
    app.console.print(t)


@accounts.command("add")
@click.argument("name")
@click.option(
    "-t",
    "--type",
    "acct_type",
    type=click.Choice(ACCOUNT_TYPES, case_sensitive=False),
    default="NONREG",
    show_default=True,
)
@click.option("-c", "--currency", default=None, help="Default: base currency.")
@click.option("-i", "--institution", default="")
@click.option("--track-cash", is_flag=True, help="Track a cash balance (buys debit, sells/dividends credit).")
@pass_app
def accounts_add(app: App, name, acct_type, currency, institution, track_cash) -> None:
    try:
        acct = app.store.add_account(
            Account(
                name=name,
                type=AccountType(acct_type.upper()),
                currency=(currency or app.config.base_currency).upper(),
                institution=institution,
                track_cash=track_cash,
            )
        )
    except ValueError as e:
        fail(str(e))
    app.ok(f"Added {acct.name} ({acct.type.label}, {acct.currency}) as #{acct.id}")


@accounts.command("edit")
@click.argument("ref")
@click.option("--name")
@click.option("-t", "--type", "acct_type", type=click.Choice(ACCOUNT_TYPES, case_sensitive=False))
@click.option("-c", "--currency")
@click.option("-i", "--institution")
@click.option("--track-cash/--no-track-cash", default=None)
@click.option("--archive/--unarchive", default=None)
@pass_app
def accounts_edit(app: App, ref, name, acct_type, currency, institution, track_cash, archive) -> None:
    acct = app.account(ref)
    if name:
        acct.name = name
    if acct_type:
        acct.type = AccountType(acct_type.upper())
    if currency:
        acct.currency = currency.upper()
    if institution is not None:
        acct.institution = institution
    if track_cash is not None:
        acct.track_cash = track_cash
    if archive is not None:
        acct.archived = archive
    app.store.update_account(acct)
    app.ok(f"Updated {acct.name}.")


@accounts.command("remove")
@click.argument("ref")
@click.option("-y", "--yes", is_flag=True)
@pass_app
def accounts_remove(app: App, ref, yes) -> None:
    acct = app.account(ref)
    count = len([t for t in app.store.transactions() if t.account_id == acct.id])
    if yes or click.confirm(
        f"Delete {acct.name} and its {count} transaction(s)? Consider `accounts edit {acct.name} --archive` instead."
    ):
        app.store.delete_account(acct.saved_id)
        app.ok(f"Deleted {acct.name}.")


@accounts.command("room")
@click.argument(
    "account_type", type=click.Choice(["TFSA", "RRSP", "FHSA", "RESP"], case_sensitive=False), required=False
)
@click.argument("year", type=int, required=False)
@click.argument("amount", type=float, required=False)
@pass_app
def accounts_room(app: App, account_type, year, amount) -> None:
    """Set or show contribution room.

    \b
    Give the room CRA reported as of Jan 1 of YEAR (My Account → RRSP/TFSA):
      marketpulse accounts room TFSA 2026 21500
    TFSA and FHSA roll forward automatically with new annual limits.
    """
    if account_type and year is not None and amount is not None:
        app.store.set_room(account_type.upper(), year, amount)
        app.ok(f"{account_type.upper()} room as of Jan 1 {year}: {fmt.money(amount)}")
    elif account_type:
        fail("Usage: marketpulse accounts room TYPE YEAR AMOUNT")
    rooms = app.tracker.room()
    if not rooms:
        app.console.print(Text("No contribution room recorded yet.", style="muted"))
        return
    app.console.print(
        # Room only: an empty tax report (no years, no issues) renders just the room table.
        render.tax_group([], TaxReport(), rooms, app.store.account_map(), app.config.base_currency, privacy=app.privacy)
    )


# ── Non-market assets ─────────────────────────────────────────────────────────


@main.group()
def asset() -> None:
    """GICs, bonds, real estate and other assets the market can't price."""


@asset.command("list")
@pass_app
def asset_list(app: App) -> None:
    items = app.store.assets()
    if not items:
        app.console.print(Text("No custom assets. Market symbols need no setup.", style="muted"))
        return
    t = render.table("Symbol", "Kind", "Name", "Class", "Ccy", ("Rate", "right"), "Term")
    for a in items.values():
        term = f"{a.start_date} → {a.maturity_date}" if a.kind is AssetKind.FIXED_INCOME else ""
        t.add_row(
            Text(a.symbol, style="bright"),
            Text(a.kind.value.replace("_", " "), style="accent"),
            Text(a.name),
            Text(a.asset_class.label if a.asset_class else "—", style="muted"),
            Text(a.currency or "—", style="muted"),
            Text(f"{a.rate:g}% {a.compounding}" if a.kind is AssetKind.FIXED_INCOME else "—", style="muted"),
            Text(term, style="muted"),
        )
    app.console.print(t)


@asset.command("fixed")
@click.argument("symbol")
@click.argument("principal", type=float)
@click.option("--rate", type=float, required=True, help="Annual rate in percent.")
@click.option("--start", default=None, callback=_date_callback, help="Start date (default today).")
@click.option("--maturity", required=True, callback=_date_callback, help="Maturity date.")
@click.option(
    "--compounding",
    type=click.Choice(["annual", "semiannual", "quarterly", "monthly", "simple"]),
    default="annual",
    show_default=True,
)
@click.option("--name", default="")
@click.option("-c", "--currency", default=None)
@click.option("-a", "--account", default=None)
@pass_app
def asset_fixed(app: App, symbol, principal, rate, start, maturity, compounding, name, currency, account) -> None:
    """Add a GIC / term deposit / bond held to maturity, valued by accrual."""
    acct = app.account(account)
    start_d, maturity_d = parse_date(start), parse_date(maturity)
    ccy = (currency or acct.currency).upper()
    app.store.upsert_asset(
        Asset(
            symbol=symbol,
            kind=AssetKind.FIXED_INCOME,
            name=name or symbol.upper(),
            asset_class=AssetClass.FIXED_INCOME,
            currency=ccy,
            rate=rate,
            compounding=compounding,
            start_date=start_d,
            maturity_date=maturity_d,
        )
    )
    _record(
        app,
        Transaction(
            account_id=acct.saved_id,
            type=TxnType.BUY,
            date=start_d,
            symbol=symbol,
            quantity=1,
            price=principal,
            currency=ccy,
            note=f"{rate:g}% {compounding} to {maturity_d}",
        ),
    )
    app.ok(f"Added {symbol.upper()}: {fmt.money(principal)} {ccy} at {rate:g}% until {maturity_d} in {acct.name}")


@asset.command("manual")
@click.argument("symbol")
@click.argument("value", type=float)
@click.option("--name", default="")
@click.option(
    "--class", "asset_class", type=click.Choice([c.value for c in AssetClass]), default="alternative", show_default=True
)
@click.option("-c", "--currency", default=None)
@click.option("-a", "--account", default=None)
@click.option("-d", "--date", "when", default=None, callback=_date_callback, help="Acquisition date.")
@pass_app
def asset_manual(app: App, symbol, value, name, asset_class, currency, account, when) -> None:
    """Add a manually valued asset (property, private shares, collectibles, pension…)."""
    acct = app.account(account)
    ccy = (currency or acct.currency).upper()
    app.store.upsert_asset(
        Asset(
            symbol=symbol,
            kind=AssetKind.MANUAL,
            name=name or symbol.upper(),
            asset_class=AssetClass(asset_class),
            currency=ccy,
        )
    )
    _record(
        app,
        Transaction(
            account_id=acct.saved_id,
            type=TxnType.BUY,
            date=parse_date(when),
            symbol=symbol,
            quantity=1,
            price=value,
            currency=ccy,
        ),
    )
    app.ok(
        f"Added {symbol.upper()} at {fmt.money(value)} {ccy} in {acct.name}. "
        f"Update it with `marketpulse asset value {symbol.upper()} NEW_VALUE`."
    )


@asset.command("value")
@click.argument("symbol")
@click.argument("value", type=float)
@click.option("-d", "--date", "when", default=None, callback=_date_callback)
@pass_app
def asset_value(app: App, symbol, value, when) -> None:
    """Record a new valuation for a manual asset (per unit)."""
    sym = symbol.upper()
    holders = [h for h in app.store.ledger().open_holdings() if h.symbol == sym]
    if not holders:
        fail(f"No holding of {sym}.")
    _record(
        app,
        Transaction(
            account_id=holders[0].account_id,
            type=TxnType.VALUATION,
            date=parse_date(when),
            symbol=sym,
            price=value,
            currency=holders[0].currency,
        ),
    )
    app.ok(f"{sym} valued at {fmt.money(value)} {holders[0].currency}")


@asset.command("classify")
@click.argument("symbol")
@click.argument("asset_class", type=click.Choice([c.value for c in AssetClass]))
@pass_app
def asset_classify(app: App, symbol, asset_class) -> None:
    """Override the asset class of any symbol (affects allocation)."""
    existing = app.store.assets().get(symbol.upper()) or Asset(symbol=symbol)
    existing.asset_class = AssetClass(asset_class)
    app.store.upsert_asset(existing)
    app.ok(f"{symbol.upper()} → {existing.asset_class.label}")


@asset.command("remove")
@click.argument("symbol")
@pass_app
def asset_remove(app: App, symbol) -> None:
    """Remove asset metadata (transactions are kept)."""
    app.store.delete_asset(symbol)
    app.ok(f"Removed metadata for {symbol.upper()}.")


# ── Watchlist & alerts ────────────────────────────────────────────────────────


@main.group(invoke_without_command=True)
@click.pass_context
def watch(ctx: click.Context) -> None:
    """Watchlist."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(watch_list)


@watch.command("list")
@pass_app
def watch_list(app: App) -> None:
    with app.busy("Fetching watchlist…"):
        symbols, quotes, errors = app.tracker.watchlist_quotes()
    if not symbols:
        app.console.print(Text("Watchlist is empty — `marketpulse watch add NVDA XEQT.TO`.", style="muted"))
        return
    app.console.print(render.quotes_table(symbols, quotes, errors, width=app.console.width))


@watch.command("add")
@click.argument("symbols", nargs=-1, required=True)
@pass_app
def watch_add(app: App, symbols) -> None:
    added = app.store.add_watch(parse_symbols(" ".join(symbols)))
    app.ok(f"Watching {', '.join(added)}" if added else "Already on the watchlist.")


@watch.command("rm")
@click.argument("symbols", nargs=-1, required=True)
@pass_app
def watch_rm(app: App, symbols) -> None:
    removed = app.store.remove_watch(parse_symbols(" ".join(symbols)))
    app.ok(f"Removed {', '.join(removed)}" if removed else "Nothing removed.")


@watch.command("live")
@click.option("-r", "--refresh", type=int, default=15, show_default=True)
@pass_app
def watch_live(app: App, refresh: int) -> None:
    """Continuously refreshing watchlist (Ctrl+C to stop)."""
    from rich.live import Live

    tr = app.tracker
    try:
        with Live(console=app.console, auto_refresh=False) as live:
            while True:
                symbols, quotes, errors = tr.watchlist_quotes(use_cache=False)
                footer = Text(f"updated {time.strftime('%H:%M:%S')} · every {refresh}s · ctrl+c to stop", style="muted")
                live.update(
                    Group(
                        render.strip_text(tr.market_strip()),
                        Text(""),
                        render.quotes_table(symbols, quotes, errors, width=app.console.width),
                        footer,
                    ),
                    refresh=True,
                )
                time.sleep(max(refresh, 5))
    except KeyboardInterrupt:
        pass


_CONDITION_ALIASES = {">": "above", ">=": "above", "<": "below", "<=": "below", "up": "up_pct", "down": "down_pct"}


@main.group(invoke_without_command=True)
@click.pass_context
def alerts(ctx: click.Context) -> None:
    """Price alerts with desktop notifications."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(alerts_list)


@alerts.command("list")
@pass_app
def alerts_list(app: App) -> None:
    items = app.store.alerts()
    if not items:
        app.console.print(Text("No alerts — `marketpulse alerts add NVDA above 200`.", style="muted"))
        return
    t = render.table(("ID", "right"), "Alert", "State", "Note")
    for a in items:
        state = (
            Text("● triggered", style="warn")
            if a.triggered_at
            else Text("armed" if a.active else "paused", style="muted")
        )
        t.add_row(
            Text(str(a.id), style="muted"), Text(a.describe(), style="bright"), state, Text(a.note, style="muted")
        )
    app.console.print(t)


@alerts.command("add")
@click.argument("symbol")
@click.argument("condition")
@click.argument("threshold", type=float)
@click.option("-m", "--note", default="")
@pass_app
def alerts_add(app: App, symbol, condition, threshold, note) -> None:
    """CONDITION: above | below | up_pct | down_pct (or > < up down)."""
    cond = _CONDITION_ALIASES.get(condition.lower(), condition.lower())
    if cond not in ALERT_CONDITIONS:
        fail(f"Condition must be one of: {', '.join(ALERT_CONDITIONS)}")
    alert = app.store.add_alert(Alert(symbol=symbol, condition=cond, threshold=threshold, note=note))
    app.ok(f"Alert #{alert.id}: {alert.describe()}")


@alerts.command("rm")
@click.argument("alert_id", type=int)
@pass_app
def alerts_rm(app: App, alert_id: int) -> None:
    app.store.delete_alert(alert_id)
    app.ok(f"Removed alert #{alert_id}.")


@alerts.command("check")
@click.option("-q", "--quiet", is_flag=True)
@pass_app
def alerts_check(app: App, quiet: bool) -> None:
    """Evaluate alerts now and send notifications (cron/launchd friendly)."""
    fired = app.tracker.check_alerts(notify=True)
    if not quiet:
        for a in fired:
            app.ok(f"Fired: {a.describe()}")
        if not fired:
            app.console.print(Text("No alerts fired.", style="muted"))


# ── Income & tax ──────────────────────────────────────────────────────────────


@main.command()
@click.option("--no-forecast", is_flag=True, help="Skip fetching distribution history.")
@pass_app
def income(app: App, no_forecast: bool) -> None:
    """Dividends and interest: monthly history, sources and forward estimate."""
    from .analytics import income_by_month, income_by_symbol

    tr = app.tracker
    with app.busy("Crunching income…"):
        view = tr.valuation()
        state = tr.store.ledger()
        months = income_by_month(state, view.fx.convert)
        sources = income_by_symbol(state, view.fx.convert, date.today().year)
        forecast = None if no_forecast else tr.income_forecast(view)
    app.title("Income")
    app.console.print(render.income_group(months, sources, forecast, view, privacy=app.privacy))


@main.command()
@click.option("-y", "--year", type=int, default=None)
@pass_app
def tax(app: App, year: int | None) -> None:
    """Capital gains (pooled ACB, trade-date FX), superficial losses and contribution room."""
    tr = app.tracker
    with app.busy("Building tax report…"):
        years, report = tr.tax_years()
        rooms = tr.room()
    app.title("Tax")
    app.console.print(
        render.tax_group(years, report, rooms, tr.store.account_map(), tr.base, privacy=app.privacy, year=year)
    )
    app.console.print(
        Text(
            "\nEstimates only — confirm figures against your broker slips (T5008/T3/T5) before filing."
            "\nPurchases by a spouse or a corporation you control can also make a loss superficial;"
            " MarketPulse can't see those.",
            style="muted",
        )
    )


# ── Data ──────────────────────────────────────────────────────────────────────


@main.command()
@pass_app
def backfill(app: App) -> None:
    """Rebuild daily net-worth history from your ledger and historical prices."""
    tr = app.tracker
    with app.busy("Backfilling…") as spinner:
        n = tr.backfill(progress=lambda msg: spinner.update(Text(f"Backfilling · {msg}", style="accent")))
    app.ok(f"Rebuilt {n:,} daily snapshots.")


def _import_default(app: App, account: str | None, path: Path) -> Account | None:
    """Account for rows without one. A file with its own account column gets no default,
    so rows are never silently filed into whichever account happens to be first."""
    from .csvio import map_headers

    if account:
        return app.account(account)
    with path.open(encoding="utf-8-sig", newline="") as f:
        headers = next(csv.reader(f), [])
    return None if "account" in map_headers(headers) else app.account(None)


@main.command("import")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-a", "--account", default=None, help="Account for rows without an account column.")
@click.option("--dry-run", is_flag=True)
@click.option("--no-create-accounts", is_flag=True)
@pass_app
def import_cmd(app: App, path: Path, account, dry_run, no_create_accounts) -> None:
    """Import transactions from a broker or MarketPulse CSV."""
    from .csvio import import_transactions

    default = _import_default(app, account, path)
    try:
        result = import_transactions(
            app.store, path, default_account=default, create_accounts=not no_create_accounts, dry_run=dry_run
        )
    except ValueError as e:
        fail(str(e))
    verb = "Would import" if dry_run else "Imported"
    app.ok(f"{verb} {result.added} transaction(s); {result.duplicates} duplicate(s) skipped.")
    if result.backup is not None:
        # Tell the user how to undo the whole import, not just the last row.
        app.console.print(Text(f"  pre-import backup: {result.backup}", style="muted"))
    for name in result.accounts_created:
        app.warn(f"created account {name}")
    for line, reason in result.skipped[:15]:
        app.warn(f"line {line}: {reason}")
    if len(result.skipped) > 15:
        app.warn(f"…and {len(result.skipped) - 15} more skipped rows")


@main.command("export")
@click.argument("path", type=click.Path(dir_okay=False, path_type=Path), required=False)
@pass_app
def export_cmd(app: App, path: Path | None) -> None:
    """Export the ledger as CSV (stdout if no PATH)."""
    from .csvio import export_transactions

    if path is None:
        export_transactions(app.store, sys.stdout)
        return
    with path.open("w", newline="") as f:
        n = export_transactions(app.store, f)
    app.ok(f"Exported {n} transactions to {path}")


@main.group(invoke_without_command=True)
@click.pass_context
def backup(ctx: click.Context) -> None:
    """Back up the database (run with no subcommand to back up now).

    \b
    Backups are consistent SQLite copies in ~/.marketpulse/backups/. One is
    also taken automatically each day, before every CSV import and before any
    schema upgrade. To restore, quit MarketPulse and copy a backup over
    ~/.marketpulse/marketpulse.db.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(backup_now)


@backup.command("now")
@click.argument("path", type=click.Path(dir_okay=False, path_type=Path), required=False)
@pass_app
def backup_now(app: App, path: Path | None) -> None:
    """Back up now (to PATH, or to the backups directory)."""
    dest = app.store.backup(reason="manual", dest=path)
    app.ok(f"Backed up to {dest}")


@backup.command("list")
@pass_app
def backup_list(app: App) -> None:
    """List backups, newest first."""
    items = app.store.backups()
    if not items:
        app.warn(f"No backups yet in {app.store.backup_dir}")
        return
    t = render.table("File", "Reason", ("Size", "right"), title=str(app.store.backup_dir))
    for p in items:
        size = Text(f"{p.stat().st_size / 1024:,.0f} KB")
        t.add_row(Text(p.name), Text(app.store.backup_reason(p), style="muted"), size)
    app.console.print(t)


# ── Appearance & config ───────────────────────────────────────────────────────


def _theme_slug(name: str) -> str:
    slug = name.strip().lower().replace(" ", "-")
    if slug in ("auto", "omarchy") or slug in OMARCHY_PALETTES:
        return slug
    fail(f"Unknown theme '{name}'. Run `marketpulse theme` to see them all.")


@main.group(invoke_without_command=True)
@click.pass_context
def theme(ctx: click.Context) -> None:
    """Omarchy themes. `auto` follows your active Omarchy theme."""
    if ctx.invoked_subcommand is None:
        app = ctx.ensure_object(App)
        active = omarchy_active()
        app.console.print(render.theme_table(app.palette.name))
        note = (
            f"Omarchy detected — auto follows '{pretty_name(active[0])}'."
            if active
            else "auto → Tokyo Night (no Omarchy install detected)."
        )
        app.console.print(Text(f'config: theme = "{app.config.theme}"   {note}', style="muted"))


@theme.command("set")
@click.argument("name", nargs=-1, required=True)
@pass_app
def theme_set(app: App, name: tuple[str, ...]) -> None:
    app.config.theme = _theme_slug(" ".join(name))
    app.config.save()
    app.ok(f"Theme → {pretty_name(app.config.theme)}")


@main.group(invoke_without_command=True)
@click.pass_context
def config(ctx: click.Context) -> None:
    """Show or change settings."""
    if ctx.invoked_subcommand is None:
        app = ctx.ensure_object(App)
        app.console.print(Text(str(config_path()), style="muted"))
        for f in fields(Config):
            app.console.print(Text(f"{f.name:<24}", style="accent") + Text(repr(getattr(app.config, f.name))))


@config.command("set")
@click.argument("key")
@click.argument("value", nargs=-1, required=True)
@pass_app
def config_set(app: App, key: str, value: tuple[str, ...]) -> None:
    known = {f.name: f for f in fields(Config)}
    if key not in known:
        fail(f"Unknown setting '{key}'. Known: {', '.join(known)}")
    raw = " ".join(value)
    current = getattr(app.config, key)
    parsed: object  # bool, int, float, list[str] or str, matching the setting's type
    try:
        if isinstance(current, bool):
            if raw.lower() not in ("true", "false", "yes", "no", "on", "off", "1", "0"):
                raise ValueError
            parsed = raw.lower() in ("true", "yes", "on", "1")
        elif isinstance(current, int):
            parsed = int(raw)
        elif isinstance(current, float):
            parsed = float(raw)
        elif isinstance(current, list):
            parsed = parse_symbols(raw)
        else:
            parsed = raw
    except ValueError:
        fail(f"Invalid value for {key}: {raw!r}")
    if key == "theme":
        parsed = _theme_slug(raw)
    if key == "base_currency":
        parsed = raw.upper()
        if len(parsed) != 3:
            fail("base_currency must be a 3-letter code like CAD.")
    if key == "menubar_display" and parsed not in ("day_pct", "day_change", "net_worth", "symbol"):
        fail("menubar_display must be day_pct, day_change, net_worth or symbol.")
    if key == "chart_period" and parsed not in PERIODS:
        fail(f"chart_period must be one of {', '.join(PERIODS)}")
    if key == "capital_gains_inclusion" and not (isinstance(parsed, float) and 0 < parsed <= 1):
        fail("capital_gains_inclusion is a fraction: > 0 and <= 1 (e.g. 0.5).")
    if key == "refresh_seconds" and isinstance(parsed, int) and parsed < 5:
        fail("refresh_seconds must be at least 5.")
    setattr(app.config, key, parsed)
    app.config.save()
    app.ok(f"{key} = {parsed!r}")


@config.command("path")
def config_path_cmd() -> None:
    click.echo(config_path())


@config.command("edit")
@pass_app
def config_edit(app: App) -> None:
    path = config_path()
    if not path.exists():
        app.config.save(path)
    click.edit(filename=str(path))


@main.group()
def menubar() -> None:
    """macOS menu bar companion."""


@menubar.command("install")
@pass_app
def menubar_install(app: App) -> None:
    """Build the native Swift app into ~/Applications and launch it."""
    import subprocess

    from .menubar import build_and_install

    try:
        build_and_install(log=lambda m: app.console.print(Text(m, style="muted")))
    except (RuntimeError, subprocess.CalledProcessError) as e:
        fail(str(e))
    app.ok("MarketPulse Bar is running. ⌥⌘M opens the TUI; enable Launch at Login from its settings.")


@menubar.command("uninstall")
@pass_app
def menubar_uninstall(app: App) -> None:
    from .menubar import uninstall

    app.ok("Removed." if uninstall(log=lambda m: None) else "Not installed.")


@main.command()
@pass_app
def doctor(app: App) -> None:
    """Check the installation, data, network and integrations."""
    from .menubar import app_path, cli_path

    c = app.console

    def row(label: str, value: str, ok: bool | None = True) -> None:
        mark = (
            Text("✓ ", style="up") if ok else (Text("✗ ", style="down") if ok is False else Text("• ", style="muted"))
        )
        c.print(mark + Text(f"{label:<18}", style="muted") + Text(value))

    row(
        "version",
        f"MarketPulse {__version__} · Python {platform.python_version()} · {platform.system()} {platform.release()}",
        None,
    )
    row("config", str(config_path()), config_path().exists() or None)
    tr = app.tracker
    row("database", f"{tr.store.path} (schema v{tr.store.schema_version})")
    newest = next(iter(tr.store.backups()), None)
    if newest is None:
        row("backups", "none yet — `marketpulse backup`", None)
    else:
        age_days = (time.time() - newest.stat().st_mtime) / 86400
        # Daily backups keep this under a day; a week means they're failing (full disk, permissions…).
        row("backups", f"{len(tr.store.backups())} · newest {newest.name}", age_days < 7)
    row(
        "ledger",
        f"{len(tr.store.accounts())} accounts · {len(tr.store.transactions())} transactions"
        f" · {len(tr.store.snapshots())} snapshots",
        None,
    )
    issues = tr.store.ledger().issues
    row("ledger checks", f"{len(issues)} issue(s)" if issues else "consistent", not issues)
    t0 = time.perf_counter()
    try:
        tr.market.quotes(["SPY"], use_cache=False)
        row("market data", f"Yahoo reachable ({(time.perf_counter() - t0) * 1000:.0f} ms)")
    except MarketError as e:
        row("market data", str(e), False)
    active = omarchy_active()
    row(
        "theme",
        f"{app.config.theme} → {pretty_name(app.palette.name)}" + (" (Omarchy detected)" if active else ""),
        None,
    )
    row("cli path", cli_path(), None)
    if sys.platform == "darwin":
        row("swift", shutil.which("swift") or "not found (xcode-select --install)", bool(shutil.which("swift")))
        row(
            "menu bar app",
            str(app_path()) if app_path().exists() else "not installed — `marketpulse menubar install`",
            app_path().exists() or None,
        )


if __name__ == "__main__":
    main()
