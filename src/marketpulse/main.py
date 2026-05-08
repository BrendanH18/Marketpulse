"""MarketPulse CLI — entry point."""
import sys
import time
import click
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich.panel import Panel
from rich import print as rprint

from .models import Position
from .storage import (
    get_or_create_portfolio,
    save_portfolio,
    load_portfolio,
    list_portfolios,
    delete_portfolio,
)
from .fetcher import fetch_quotes, fetch_quote, fetch_history
from .display import (
    console,
    header,
    watchlist_table,
    portfolio_table,
    quote_panel,
    history_panel,
)

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_PORTFOLIO = "default"
DEFAULT_WATCHLIST = ["XEQT.TO", "QQQ", "SPY", "VFV.TO", "AAPL", "NVDA", "BTC-USD"]


# ── CLI group ─────────────────────────────────────────────────────────────────

@click.group()
@click.version_option("0.1.0", prog_name="MarketPulse")
def cli():
    """⚡ MarketPulse — terminal portfolio tracker with live market data.\n
    \b
    Quick start:
      marketpulse watch                      # live watchlist
      marketpulse quote XEQT.TO AAPL        # quick quotes
      marketpulse portfolio add XEQT.TO 100 28.50
      marketpulse portfolio show
      marketpulse chart XEQT.TO --period 6mo
    """
    pass


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

    # Deduplicate while preserving order
    seen = set()
    all_tickers = [t for t in all_tickers if not (t.upper() in seen or seen.add(t.upper()))]

    def _render():
        console.print(header())
        with console.status("[cyan]Fetching quotes…[/cyan]", spinner="dots"):
            quotes = fetch_quotes(all_tickers)
        failed = [t for t in all_tickers if t.upper() not in quotes]
        console.print(watchlist_table(quotes, failed))
        console.print(Text(f"\n  {len(quotes)} quotes  •  {len(failed)} failed  •  {_now()}", style="dim"))

    if refresh > 0:
        try:
            while True:
                console.clear()
                _render()
                console.print(Text(f"\n  [Auto-refresh every {refresh}s — Ctrl+C to stop]", style="dim"))
                time.sleep(refresh)
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped.[/dim]")
    else:
        _render()


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
        if not no_live:
            with console.status("[cyan]Fetching live prices…[/cyan]", spinner="dots"):
                quotes = fetch_quotes(tickers)
        console.print(portfolio_table(p, quotes))
    else:
        console.print(Panel("[dim]No positions yet.[/dim]", title=f"Portfolio: {name}"))

    if p.watchlist:
        console.print(f"\n[dim]Watchlist:[/dim] {', '.join(p.watchlist)}")


@portfolio.command("add")
@click.argument("ticker")
@click.argument("shares", type=float)
@click.argument("avg_cost", type=float)
@click.option("--note", "-m", default="", help="Optional note")
@click.pass_context
def portfolio_add(ctx, ticker, shares, avg_cost, note):
    """Add or update a position.

    \b
    Example:
      marketpulse portfolio add XEQT.TO 100 28.50
      marketpulse portfolio add AAPL 10 175.00 --note "Core holding"
    """
    name = ctx.obj["name"]
    p = get_or_create_portfolio(name)
    ticker = ticker.upper()

    existing = p.positions.get(ticker)
    if existing:
        # Average down/up
        old_book = existing.shares * existing.avg_cost
        new_book = shares * avg_cost
        total_shares = existing.shares + shares
        new_avg = (old_book + new_book) / total_shares if total_shares else avg_cost
        p.positions[ticker] = Position(ticker=ticker, shares=total_shares, avg_cost=new_avg, note=note or existing.note)
        console.print(
            f"[green]Updated[/green] {ticker}: "
            f"{total_shares:,.4f} shares @ avg {new_avg:,.2f} (blended)"
        )
    else:
        p.positions[ticker] = Position(ticker=ticker, shares=shares, avg_cost=avg_cost, note=note)
        console.print(f"[green]Added[/green] {ticker}: {shares:,.4f} shares @ {avg_cost:,.2f}")

    save_portfolio(p)


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
    console.print(f"[green]Watchlist updated.[/green]")


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
    import pandas as pd
    from rich.table import Table
    from rich import box

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
        title=f"[bold]Performance Comparison[/bold]  [{period}]  [dim](normalized to 100)[/dim]",
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
        from .display import _sparkline, _sign_color
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


def _sign_color(value: float) -> str:
    if value > 0:
        return "bright_green"
    elif value < 0:
        return "bright_red"
    return "white"


if __name__ == "__main__":
    cli()
