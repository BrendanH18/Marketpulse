"""MarketPulse CLI — entry point."""
import sys
import time

import click
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.text import Text

from .display import (
    _sign_color,
    _sparkline,
    console,
    header,
    history_panel,
    portfolio_summary,
    portfolio_table,
    quote_panel,
    transactions_table,
    watchlist_table,
)
from .fetcher import fetch_fx_rates, fetch_history, fetch_quote, fetch_quotes
from .models import FxRates, Portfolio, parse_tickers
from .storage import (
    delete_portfolio,
    get_or_create_portfolio,
    list_portfolios,
    load_portfolio,
    save_portfolio,
)

# Windows consoles/pipes often default to cp1252, which can't encode the
# Unicode symbols used throughout the UI — degrade to '?' instead of crashing
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_PORTFOLIO = "default"
DEFAULT_WATCHLIST = ["XEQT.TO", "QQQ", "SPY", "VFV.TO", "AAPL", "NVDA", "BTC-USD"]


# ── CLI group ─────────────────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.version_option("0.1.0", prog_name="MarketPulse")
@click.pass_context
def cli(ctx):
    """⚡ MarketPulse — terminal portfolio tracker with live market data.\n
    \b
    Run with no arguments to launch the interactive TUI.
    \b
    Quick start:
      marketpulse                            # interactive TUI
      marketpulse watch                      # live watchlist
      marketpulse quote XEQT.TO AAPL        # quick quotes
      marketpulse portfolio add XEQT.TO 100 28.50
      marketpulse portfolio show
      marketpulse chart XEQT.TO --period 6mo
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(tui)


# ── tui ───────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--portfolio", "-p", default=DEFAULT_PORTFOLIO, help="Portfolio name", show_default=True)
@click.option("--refresh", "-r", default=30, type=int, help="Auto-refresh interval in seconds", show_default=True)
def tui(portfolio, refresh):
    """Launch the interactive TUI (also runs when no command is given).

    \b
    Keys:
      1 / 2 / 3   switch between Watchlist, Portfolio, Chart
      r           refresh quotes now
      q           quit
    """
    from .tui import MarketPulseApp
    MarketPulseApp(
        portfolio_name=portfolio,
        default_watchlist=DEFAULT_WATCHLIST,
        refresh_seconds=max(refresh, 5),
    ).run()


# ── setup ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--name", "-n", default=DEFAULT_PORTFOLIO, help="Portfolio name", show_default=True)
def setup(name):
    """Interactive wizard to set up your watchlist and portfolio.

    Runs automatically inside the TUI on first launch; use this command to
    set up from the terminal or to redo the setup later.
    """
    console.print(header())
    existing = load_portfolio(name)
    if existing is not None:
        console.print(
            f"[yellow]Portfolio '{name}' already exists[/yellow] "
            f"({len(existing.positions)} positions, {len(existing.watchlist)} watchlist tickers)."
        )
        if not Confirm.ask("Edit it with the setup wizard?"):
            return
        p = existing
    else:
        p = Portfolio(name=name)

    # Watchlist
    current = " ".join(p.watchlist) if p.watchlist else " ".join(DEFAULT_WATCHLIST)
    console.print("\n[bold cyan]Watchlist[/bold cyan] — tickers to track (space-separated).")
    raw = Prompt.ask("Tickers", default=current)
    p.watchlist = parse_tickers(raw)

    # Positions
    console.print("\n[bold cyan]Portfolio positions[/bold cyan] — leave ticker blank when done.")
    while True:
        ticker = Prompt.ask("  Ticker", default="").strip()
        if not ticker:
            break
        try:
            shares = float(Prompt.ask(f"  {ticker.upper()} shares"))
            avg_cost = float(Prompt.ask(f"  {ticker.upper()} avg cost per share"))
        except ValueError:
            console.print("  [red]Shares and avg cost must be numbers — position skipped.[/red]")
            continue
        note = Prompt.ask("  Note (optional)", default="")
        pos, blended = p.add_position(ticker, shares, avg_cost, note)
        verb = "Updated (blended)" if blended else "Added"
        console.print(f"  [green]{verb}[/green] {pos.ticker}: {pos.shares:,.4f} @ {pos.avg_cost:,.2f}\n")

    save_portfolio(p)
    console.print(
        f"\n[green]Saved portfolio '{name}'[/green] — "
        f"{len(p.positions)} positions, {len(p.watchlist)} watchlist tickers."
    )
    console.print("[dim]Run [bold]marketpulse[/bold] to launch the TUI.[/dim]")


# ── watch ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("tickers", nargs=-1)
@click.option("--portfolio", "-p", default=DEFAULT_PORTFOLIO, help="Portfolio name")
@click.option("--refresh", "-r", default=0, type=int, help="Auto-refresh interval in seconds (0=off)")
def watch(tickers, portfolio, refresh):
    """Show a live watchlist table.

    Tickers default to your portfolio watchlist + DEFAULT_WATCHLIST if none are given.
    """
    p = load_portfolio(portfolio)
    all_tickers = list(tickers)

    if not all_tickers:
        if p:
            all_tickers = list(p.watchlist) + list(p.positions.keys())
        if not all_tickers:
            all_tickers = DEFAULT_WATCHLIST

    all_tickers = parse_tickers(" ".join(all_tickers))

    def _build():
        quotes, failed = fetch_quotes(all_tickers)
        from rich.console import Group
        parts = [
            header(),
            watchlist_table(quotes, failed),
            Text(f"\n  {len(quotes)} quotes  •  {len(failed)} failed  •  {_now()}", style="dim"),
        ]
        if refresh > 0:
            parts.append(Text(f"  [Auto-refresh every {refresh}s — Ctrl+C to stop]", style="dim"))
        return Group(*parts)

    if refresh > 0:
        from rich.live import Live
        try:
            # Live keeps the previous table on screen while the next fetch
            # runs, so refreshes don't flicker
            with Live(console=console, auto_refresh=False) as live:
                while True:
                    live.update(_build(), refresh=True)
                    time.sleep(refresh)
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped.[/dim]")
    else:
        with console.status("[cyan]Fetching quotes…[/cyan]", spinner="dots"):
            view = _build()
        console.print(view)


# ── quote ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("tickers", nargs=-1, required=True)
def quote(tickers):
    """Show detailed quote cards for one or more tickers.

    Examples:\n
      marketpulse quote XEQT.TO\n
      marketpulse quote AAPL MSFT NVDA\n
      marketpulse quote BTC-USD ETH-USD
    """
    from rich.columns import Columns
    panels = []
    with console.status("[cyan]Fetching…[/cyan]", spinner="dots"):
        for ticker in tickers:
            try:
                q = fetch_quote(ticker)
                panels.append(quote_panel(q))
            except RuntimeError as e:
                panels.append(Panel(Text(str(e), style="red"), title=ticker, border_style="red"))

    console.print(header())
    console.print(Columns(panels, equal=False, expand=False))


# ── chart ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("ticker")
@click.option(
    "--period", "-p", default="3mo",
    type=click.Choice(["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"], case_sensitive=False),
    show_default=True,
    help="History period",
)
def chart(ticker, period):
    """Render an ASCII price chart for a ticker.

    Example:\n
      marketpulse chart XEQT.TO --period 1y
    """
    console.print(header())
    with console.status(f"[cyan]Fetching {ticker} history ({period})…[/cyan]", spinner="dots"):
        try:
            hist = fetch_history(ticker, period)
        except RuntimeError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
    console.print(history_panel(ticker.upper(), hist, period))


# ── portfolio group ───────────────────────────────────────────────────────────

@cli.group()
@click.option("--name", "-n", default=DEFAULT_PORTFOLIO, help="Portfolio name", show_default=True)
@click.pass_context
def portfolio(ctx, name):
    """Manage your portfolio holdings and watchlist."""
    ctx.ensure_object(dict)
    ctx.obj["name"] = name


@portfolio.command("show")
@click.pass_context
@click.option("--no-live", is_flag=True, help="Skip fetching live prices")
def portfolio_show(ctx, no_live):
    """Display holdings with live P&L."""
    name = ctx.obj["name"]
    p = load_portfolio(name)
    if p is None:
        console.print(f"[yellow]No portfolio named '{name}'. Create one with:[/yellow]")
        console.print(f"  [bold]marketpulse portfolio -n {name} add <TICKER> <SHARES> <AVG_COST>[/bold]")
        return

    console.print(header())

    if p.positions:
        tickers = list(p.positions.keys())
        quotes = {}
        fx = FxRates(base=p.currency.upper(), rates={p.currency.upper(): 1.0})
        if not no_live:
            with console.status("[cyan]Fetching live prices…[/cyan]", spinner="dots"):
                quotes, errors = fetch_quotes(tickers)
                currencies = {q.currency for q in quotes.values()}
                currencies.update(pos.currency for pos in p.positions.values() if pos.currency)
                fx, fx_errors = fetch_fx_rates(currencies, p.currency)
            for reason in errors.values():
                console.print(f"[yellow]Warning:[/yellow] [dim]{reason}[/dim]")
            for reason in fx_errors.values():
                console.print(f"[yellow]Warning:[/yellow] [dim]{reason}[/dim]")
        console.print(portfolio_table(p, quotes, fx))
        if quotes:
            console.print(portfolio_summary(p, quotes, fx))
    else:
        console.print(Panel("[dim]No positions yet.[/dim]", title=f"Portfolio: {name}"))

    if p.watchlist:
        console.print(f"\n[dim]Watchlist:[/dim] {', '.join(p.watchlist)}")


@portfolio.command("buy")
@click.argument("ticker")
@click.argument("shares", type=float)
@click.argument("price", type=float)
@click.option("--fees", "-f", default=0.0, type=float, help="Commission/fees (added to cost base)")
@click.option("--date", "-d", default=None, help="Trade date YYYY-MM-DD (default: today)")
@click.option("--note", "-m", default="", help="Optional note")
@click.option("--currency", "-c", default="", help="Trade currency (default: the ticker's quote currency)")
@click.pass_context
def portfolio_buy(ctx, ticker, shares, price, fees, date, note, currency):
    """Record a buy: blends the average cost and logs a transaction.

    \b
    Example:
      marketpulse portfolio buy XEQT.TO 100 28.50
      marketpulse portfolio buy AAPL 10 175.00 --fees 4.95 --note "Core holding"
    """
    name = ctx.obj["name"]
    p = get_or_create_portfolio(name)

    ccy = currency.upper()
    if not ccy:
        try:
            ccy = fetch_quote(ticker).currency
        except RuntimeError as e:
            console.print(
                f"[yellow]Warning:[/yellow] [dim]could not fetch {ticker.upper()} ({e}); "
                f"recording trade in {p.currency}[/dim]"
            )

    try:
        pos, blended = p.buy(ticker, shares, price, fees=fees, date=date, currency=ccy, note=note)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    save_portfolio(p)

    label = f" {pos.currency}" if pos.currency else ""
    if blended:
        console.print(
            f"[green]Bought[/green] {shares:,.4f} {pos.ticker} @ {price:,.2f}{label} — "
            f"now {pos.shares:,.4f} shares @ avg {pos.avg_cost:,.2f} (blended)"
        )
    else:
        console.print(
            f"[green]Bought[/green] {shares:,.4f} {pos.ticker} @ {price:,.2f}{label} — "
            f"new position @ avg {pos.avg_cost:,.2f}"
        )


@portfolio.command("add")
@click.argument("ticker")
@click.argument("shares", type=float)
@click.argument("avg_cost", type=float)
@click.option("--note", "-m", default="", help="Optional note")
@click.pass_context
def portfolio_add(ctx, ticker, shares, avg_cost, note):
    """Add a position (deprecated alias for 'portfolio buy')."""
    console.print("[dim]note: 'portfolio add' is an alias for 'portfolio buy'.[/dim]")
    ctx.invoke(
        portfolio_buy,
        ticker=ticker, shares=shares, price=avg_cost,
        fees=0.0, date=None, note=note, currency="",
    )


@portfolio.command("sell")
@click.argument("ticker")
@click.argument("shares", type=float)
@click.argument("price", type=float)
@click.option("--fees", "-f", default=0.0, type=float, help="Commission/fees (deducted from proceeds)")
@click.option("--date", "-d", default=None, help="Trade date YYYY-MM-DD (default: today)")
@click.option("--note", "-m", default="", help="Optional note")
@click.pass_context
def portfolio_sell(ctx, ticker, shares, price, fees, date, note):
    """Record a sell: logs realized P&L using the average-cost method.

    \b
    Example:
      marketpulse portfolio sell AAPL 4 200.00 --fees 4.95
    """
    name = ctx.obj["name"]
    p = load_portfolio(name)
    if p is None:
        console.print(f"[red]No portfolio named '{name}'.[/red]")
        sys.exit(1)

    try:
        realized, pos = p.sell(ticker, shares, price, fees=fees, date=date, note=note)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    save_portfolio(p)

    ccy = p.transactions[-1].currency or p.currency
    color = _sign_color(realized)
    sign = "+" if realized >= 0 else ""
    console.print(
        f"[green]Sold[/green] {shares:,.4f} {ticker.upper()} @ {price:,.2f} — "
        f"realized [{color}]{sign}{realized:,.2f} {ccy}[/{color}]"
    )
    if pos is None:
        console.print("[dim]Position closed.[/dim]")
    else:
        console.print(f"[dim]{pos.shares:,.4f} shares remain @ avg {pos.avg_cost:,.2f}.[/dim]")


@portfolio.command("history")
@click.argument("ticker", required=False)
@click.pass_context
def portfolio_history(ctx, ticker):
    """Show the transaction ledger, optionally for one ticker."""
    name = ctx.obj["name"]
    p = load_portfolio(name)
    if p is None:
        console.print(f"[red]No portfolio named '{name}'.[/red]")
        return
    if not p.transactions:
        console.print("[dim]No transactions recorded yet.[/dim]")
        return
    console.print(transactions_table(p, ticker))


@portfolio.command("remove")
@click.argument("ticker")
@click.pass_context
def portfolio_remove(ctx, ticker):
    """Remove a position entirely."""
    name = ctx.obj["name"]
    p = load_portfolio(name)
    ticker = ticker.upper()
    if p is None or ticker not in p.positions:
        console.print(f"[red]{ticker} not found in portfolio '{name}'.[/red]")
        return
    if Confirm.ask(f"Remove {ticker} from {name}?"):
        del p.positions[ticker]
        save_portfolio(p)
        console.print(f"[green]Removed {ticker}.[/green]")


@portfolio.command("watchlist-add")
@click.argument("tickers", nargs=-1, required=True)
@click.pass_context
def watchlist_add(ctx, tickers):
    """Add tickers to portfolio watchlist."""
    name = ctx.obj["name"]
    p = get_or_create_portfolio(name)
    added = []
    for t in tickers:
        t = t.upper()
        if t not in p.watchlist:
            p.watchlist.append(t)
            added.append(t)
    save_portfolio(p)
    console.print(f"[green]Added to watchlist:[/green] {', '.join(added) or 'none (already present)'}")


@portfolio.command("watchlist-remove")
@click.argument("tickers", nargs=-1, required=True)
@click.pass_context
def watchlist_remove(ctx, tickers):
    """Remove tickers from portfolio watchlist."""
    name = ctx.obj["name"]
    p = load_portfolio(name)
    if p is None:
        console.print("[red]Portfolio not found.[/red]")
        return
    for t in tickers:
        t = t.upper()
        if t in p.watchlist:
            p.watchlist.remove(t)
    save_portfolio(p)
    console.print("[green]Watchlist updated.[/green]")


@portfolio.command("list")
def portfolio_list():
    """List all saved portfolios."""
    portfolios = list_portfolios()
    if not portfolios:
        console.print("[dim]No portfolios found. Create one with 'portfolio add'.[/dim]")
        return
    for name in portfolios:
        p = load_portfolio(name)
        n_pos = len(p.positions) if p else 0
        n_watch = len(p.watchlist) if p else 0
        console.print(f"  [bold]{name}[/bold]  [dim]{n_pos} positions, {n_watch} watchlist[/dim]")


@portfolio.command("delete")
@click.argument("name")
def portfolio_delete(name):
    """Delete a portfolio file."""
    if Confirm.ask(f"[red]Delete portfolio '{name}'?[/red]"):
        if delete_portfolio(name):
            console.print(f"[green]Deleted '{name}'.[/green]")
        else:
            console.print(f"[red]Portfolio '{name}' not found.[/red]")


# ── compare ───────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("tickers", nargs=-1, required=True)
@click.option(
    "--period", "-p", default="1y",
    type=click.Choice(["1mo", "3mo", "6mo", "1y", "2y", "5y"], case_sensitive=False),
    show_default=True,
)
def compare(tickers, period):
    """Compare normalized performance of multiple tickers.

    \b
    Example:
      marketpulse compare XEQT.TO QQQ SPY --period 1y
    """
    from rich import box
    from rich.table import Table

    console.print(header())
    data = {}

    with console.status(f"[cyan]Fetching history for {len(tickers)} tickers…[/cyan]", spinner="dots"):
        for ticker in tickers:
            try:
                hist = fetch_history(ticker, period)
                if not hist.empty:
                    data[ticker.upper()] = hist["Close"].dropna()
            except RuntimeError:
                console.print(f"[yellow]Warning: could not fetch {ticker}[/yellow]")

    if not data:
        console.print("[red]No data retrieved.[/red]")
        return

    # Normalize to 100 at start
    t = Table(
        title=f"[bold]Performance Comparison[/bold]  [{period}]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
    )
    t.add_column("Ticker", style="bold")
    t.add_column("Start", justify="right", style="dim")
    t.add_column("End", justify="right")
    t.add_column("Return", justify="right")
    t.add_column("Max Drawdown", justify="right")
    t.add_column("Sparkline", min_width=30)

    for ticker, series in sorted(data.items()):
        start_val = series.iloc[0]
        end_val = series.iloc[-1]
        ret = (end_val - start_val) / start_val * 100
        # Max drawdown
        running_max = series.cummax()
        drawdown = ((series - running_max) / running_max * 100).min()
        color = _sign_color(ret)
        sign = "+" if ret >= 0 else ""
        spark = _sparkline(series, width=30)
        t.add_row(
            Text(ticker, style=f"bold {color}"),
            Text(f"{start_val:,.2f}", style="dim"),
            Text(f"{end_val:,.2f}", style=f"bold {color}"),
            Text(f"{sign}{ret:.2f}%", style=f"bold {color}"),
            Text(f"{drawdown:.2f}%", style="red"),
            spark,
        )

    console.print(t)


# ── helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")


if __name__ == "__main__":
    cli()
