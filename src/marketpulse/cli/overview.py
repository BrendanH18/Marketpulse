"""Portfolio views: status, summary, holdings, performance, allocation and income."""

from __future__ import annotations

import json
from datetime import date

import click
from rich.text import Text

from .. import fmt, render
from ..models import AssetClass
from .base import App, fail, pass_app
from .root import main


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
@click.option("--clear-targets", is_flag=True, help="Remove all targets (with --target: replace them).")
@click.option("-q", "--quiet", is_flag=True, help="Only save targets; don't price holdings or show the allocation.")
@pass_app
def allocation(app: App, by: str, targets: tuple[str, ...], clear_targets: bool, quiet: bool) -> None:
    """Allocation breakdown and rebalancing against asset-class targets."""
    from ..analytics import rebalance

    store = app.store
    if clear_targets and not targets:
        store.set_targets({})
        app.ok("Targets cleared.")
    if targets:
        # Checked in full before anything is saved, so a rejected entry never clears the old targets.
        parsed = {} if clear_targets else dict(store.targets())
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
    if quiet:
        return
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


@main.command()
@click.option("--no-forecast", is_flag=True, help="Skip fetching distribution history.")
@pass_app
def income(app: App, no_forecast: bool) -> None:
    """Dividends and interest: monthly history, sources and forward estimate."""
    from ..analytics import income_by_month, income_by_symbol

    tr = app.tracker
    with app.busy("Crunching income…"):
        view = tr.valuation()
        state = tr.store.ledger()
        months = income_by_month(state, view.fx.convert)
        sources = income_by_symbol(state, view.fx.convert, date.today().year)
        forecast = None if no_forecast else tr.income_forecast(view)
    app.title("Income")
    app.console.print(render.income_group(months, sources, forecast, view, privacy=app.privacy))
