"""Portfolio views: status, summary, holdings, performance and income."""

from __future__ import annotations

import contextlib
import csv
import io
import json
import math
from collections.abc import Callable
from datetime import date
from typing import Any

import click
from rich.text import Text

from .. import fmt, render
from ..valuation import PortfolioView, PositionView
from .base import App, fail, pass_app
from .root import main

HOLDING_FIELDS = [
    "account_id",
    "account",
    "symbol",
    "name",
    "asset_class",
    "kind",
    "currency",
    "quantity",
    "average_cost",
    "price",
    "book",
    "market_value",
    "unrealized",
    "unrealized_pct",
    "day_change",
    "day_change_pct",
    "base_currency",
    "fx_rate",
    "value_base",
    "book_base",
    "unrealized_base",
    "day_change_base",
    "weight",
    "priced",
    "stale",
    "first_date",
]
# Sort metrics; positions without one (no price or FX rate) always come last.
HOLDING_SORTS: dict[str, Callable[[PositionView], float | None]] = {
    "value": lambda p: p.value_base,
    "weight": lambda p: p.weight if p.priced else None,
    "gain": lambda p: p.gain_base,
    "gain-pct": lambda p: p.gain_pct if p.priced else None,
    "day": lambda p: p.day_change_base,
    "day-pct": lambda p: p.day_change_pct if p.priced else None,
}
EXCLUDED_REASONS = {
    "unpriced": "no price or FX rate",
    "unconverted_cash": "no FX rate for this cash balance",
    "archived_holding": "archived account holding with no price or FX rate",
    "archived_cash": "archived account cash with no FX rate",
    "archived_account": "archived account still holds value; snapshots paused",
}
PERF_METRICS = {
    "since": "since",
    "days": "days",
    "net-contributions": "net_contributions",
    "total-gain": "total_gain",
    "xirr": "xirr_pct",
    "twr": "twr_pct",
    "twr-annual": "twr_annual_pct",
    "max-drawdown": "max_drawdown_pct",
    "volatility": "volatility_pct",
}


def _holding_row(p: PositionView, base: str) -> dict[str, Any]:
    return {
        "account_id": p.account.id,
        "account": p.account.name,
        "symbol": p.symbol,
        "name": p.name,
        "asset_class": p.asset_class.value,
        "kind": p.kind.value,
        "currency": p.currency,
        "quantity": p.quantity,
        "average_cost": p.avg_cost,
        "price": p.price,
        "book": p.book,
        "market_value": p.market_value,
        "unrealized": p.gain,
        "unrealized_pct": p.gain_pct,
        "day_change": p.day_change,
        "day_change_pct": p.day_change_pct,
        "base_currency": base,
        "fx_rate": p.fx_rate,
        "value_base": p.value_base,
        "book_base": p.book_base,
        "unrealized_base": p.gain_base,
        "day_change_base": p.day_change_base,
        "weight": p.weight if p.priced else None,
        "priced": p.priced,
        "stale": p.stale,
        "first_date": p.first_date,
    }


def _sort_holdings(rows: list[PositionView], sort_by: str | None, descending: bool) -> list[PositionView]:
    def tie(p: PositionView) -> tuple[str, int, str]:
        return (p.account.name.casefold(), p.account.id or 0, p.symbol)

    if sort_by is None:  # the plain table's order: by account, largest first
        return sorted(rows, key=lambda p: (p.account.name, -(p.value_base or 0)))
    if sort_by == "symbol":
        return sorted(rows, key=lambda p: (p.symbol, *tie(p)), reverse=descending)
    if sort_by == "account":
        return sorted(rows, key=tie, reverse=descending)
    metric = HOLDING_SORTS[sort_by]
    present = [p for p in rows if metric(p) is not None]
    missing = sorted((p for p in rows if metric(p) is None), key=tie)
    return sorted(present, key=lambda p: (metric(p), *tie(p)), reverse=descending) + missing


def _excluded_rows(view: PortfolioView) -> list[dict[str, Any]]:
    """Everything the totals leave out, with a reason; unpriced positions name their account."""
    rows: list[dict[str, Any]] = []
    for p in view.positions:
        if not p.priced:
            detail = view.errors.get(p.symbol) or view.errors.get(f"FX {p.currency}")
            rows.append(
                {
                    "code": "unpriced",
                    "item": p.symbol,
                    "account": p.account.name,
                    "symbol": p.symbol,
                    "currency": p.currency,
                    "reason": EXCLUDED_REASONS["unpriced"],
                    "detail": detail,
                }
            )
    for text, (code, args) in zip(view.excluded, view.excluded_items, strict=True):
        if code == "unpriced":
            continue
        currency = args.get("currency")
        rows.append(
            {
                "code": code,
                "item": text,
                "account": args.get("account"),
                "symbol": args.get("symbol"),
                "currency": currency,
                "reason": EXCLUDED_REASONS.get(code, code),
                "detail": view.errors.get(f"FX {currency}") if currency else None,
            }
        )
    for name in view.archived_with_value:
        rows.append(
            {
                "code": "archived_account",
                "item": name,
                "account": name,
                "symbol": None,
                "currency": None,
                "reason": EXCLUDED_REASONS["archived_account"],
                "detail": None,
            }
        )
    return rows


def _finite_weight(ctx: click.Context, param: click.Parameter, value: float | None) -> float | None:
    if value is not None and not math.isfinite(value):
        raise click.BadParameter("Must be a finite number.")
    return value


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
@click.option("--json", "as_json", is_flag=True, help="Print raw, unmasked priced positions as JSON.")
@click.option("--csv", "as_csv", is_flag=True, help="Print raw, unmasked priced positions as CSV to stdout.")
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(["value", "weight", "gain", "gain-pct", "day", "day-pct", "symbol", "account"]),
    help="Order positions by this field; unpriced ones come last.",
)
@click.option("--descending", is_flag=True, help="Reverse the --sort order.")
@click.option("--symbol", help="Only symbols containing this text, ignoring case.")
@click.option("--currency", help="Only positions held in this currency, ignoring case.")
@click.option("--gainers", is_flag=True, help="Only positions with an unrealized gain.")
@click.option("--losers", is_flag=True, help="Only positions with an unrealized loss.")
@click.option(
    "--min-weight",
    type=click.FloatRange(min=0),
    callback=_finite_weight,
    metavar="PCT",
    help="Only priced positions weighing at least PCT% of net worth.",
)
@click.option("--stale", "stale_only", is_flag=True, help="Only positions priced from a cached (offline) quote.")
@click.option("--limit", type=click.IntRange(min=1), help="Show at most N matching positions.")
@click.option("--offset", type=click.IntRange(min=0), help="Skip N matching positions after sorting.")
@click.option("--count", "count_only", is_flag=True, help="Print only the number of matching positions.")
@click.option("--excluded", "show_excluded", is_flag=True, help="List what the totals leave out, and why.")
@pass_app
def holdings(
    app: App,
    account: str | None,
    as_json: bool,
    as_csv: bool,
    sort_by: str | None,
    descending: bool,
    symbol: str | None,
    currency: str | None,
    gainers: bool,
    losers: bool,
    min_weight: float | None,
    stale_only: bool,
    limit: int | None,
    offset: int | None,
    count_only: bool,
    show_excluded: bool,
) -> None:
    """Priced holdings with gains, day change and weights.

    Selection options (filters, --sort, --limit, --offset) show only positions:
    cash rows and portfolio totals are left out rather than summed for a subset."""
    if (as_json and as_csv) or (count_only and (as_json or as_csv)):
        raise click.UsageError("Choose one output format; --count cannot be combined with --json or --csv.")
    if count_only and (limit is not None or offset is not None):
        raise click.UsageError("--count cannot be combined with --limit or --offset.")
    if gainers and losers:
        raise click.UsageError("Choose either --gainers or --losers.")
    if descending and sort_by is None:
        raise click.UsageError("--descending requires --sort.")
    filtered = any([symbol is not None, currency is not None, gainers, losers, min_weight is not None, stale_only])
    paged = limit is not None or offset is not None
    if show_excluded and (as_csv or count_only or filtered or paged or sort_by is not None):
        raise click.UsageError("--excluded combines only with -a/--account and --json.")
    machine = as_json or as_csv or count_only
    acct = app.account(account) if account else None
    if acct is not None and acct.archived and (machine or filtered or paged or sort_by is not None or show_excluded):
        fail(f"No active account '{account}'.")  # archived accounts are reported exactly like unknown ones
    # The same valuation (and snapshot) as the plain table: options only choose what is shown.
    with contextlib.nullcontext() if machine else app.busy("Pricing holdings…"):
        view = app.tracker.valuation(account_id=acct.id if acct else None)
    if show_excluded:
        _print_excluded(app, view, as_json)
        return
    if not (machine or filtered or paged or sort_by is not None):
        if not view.positions and not view.cash:
            app.console.print(Text("No holdings yet — try `marketpulse buy XEQT.TO 10`.", style="muted"))
            return
        app.console.print(render.holdings_table(view, privacy=app.privacy, width=app.console.width))
        app.console.print(render.summary(view, privacy=app.privacy))
        for reason in sorted(set(view.errors.values())):
            app.warn(reason)
        return
    needle = symbol.strip().casefold() if symbol is not None else None
    wanted = currency.strip().upper() if currency is not None else None
    matches = [
        p
        for p in view.positions
        if (needle is None or needle in p.symbol.casefold())
        and (wanted is None or p.currency.upper() == wanted)
        and (not gainers or (p.priced and p.gain is not None and p.gain > 0))
        and (not losers or (p.priced and p.gain is not None and p.gain < 0))
        and (min_weight is None or (p.priced and p.weight >= min_weight))
        and (not stale_only or p.stale)
    ]
    if count_only:
        click.echo(len(matches))
        return
    total = len(matches)
    start = offset or 0
    rows = _sort_holdings(matches, sort_by, descending)[start : start + limit if limit is not None else None]
    if as_csv:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=HOLDING_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(_holding_row(p, view.base) for p in rows)
        click.echo(stream.getvalue(), nl=False)
        return
    if as_json:
        click.echo(json.dumps([_holding_row(p, view.base) for p in rows], ensure_ascii=False))
        return
    if not rows:
        if not view.positions:
            message = "No holdings yet — try `marketpulse buy XEQT.TO 10`."
        elif total:
            message = "No holdings on this page."
        else:
            message = "No holdings match these filters."
        app.console.print(Text(message, style="muted"))
    else:
        app.console.print(render.holdings_table(view, privacy=app.privacy, width=app.console.width, positions=rows))
        app.console.print(
            Text(
                f"Showing {len(rows)} of {len(view.positions)} positions. Cash and portfolio totals are left "
                "out of a selection; run `marketpulse holdings` for them.",
                style="muted",
            )
        )
    if view.stale:
        app.warn(f"Prices are {render.stale_note(view)}.")
    if view.excluded:
        app.warn("Some holdings have no price or FX rate; `marketpulse holdings --excluded` lists them.")
    if view.archived_with_value:
        app.warn(f"Archived {', '.join(view.archived_with_value)} still holds value, so snapshots are paused.")
    for reason in sorted(set(view.errors.values())):
        app.warn(reason)


def _print_excluded(app: App, view: PortfolioView, as_json: bool) -> None:
    rows = _excluded_rows(view)
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
        return
    if not rows:
        app.console.print(Text("Nothing is left out of the totals.", style="muted"))
        return
    table = render.table("Item", "Account", "Reason", "Detail", title="Left out of totals")
    for row in rows:
        table.add_row(
            Text(str(row["item"]), style="bright"),
            Text(row["account"] or "—", style="muted"),
            Text(str(row["reason"])),
            Text(row["detail"] or "—", style="muted"),
        )
    app.console.print(table)


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Print the raw, unmasked performance metrics as JSON.")
@click.option(
    "--metric",
    type=click.Choice(list(PERF_METRICS)),
    help="Print one raw, unmasked metric for scripts; exits 1 when it isn't available yet.",
)
@pass_app
def perf(app: App, as_json: bool, metric: str | None) -> None:
    """Returns: money-weighted, time-weighted, drawdown and volatility."""
    if as_json and metric:
        raise click.UsageError("Choose either --json or --metric.")
    tr = app.tracker
    with contextlib.nullcontext() if as_json or metric else app.busy("Calculating performance…"):
        view = tr.valuation()
        result = tr.performance(view)
    if metric:
        value = getattr(result, PERF_METRICS[metric])
        if value is None or value == "":
            raise click.ClickException(f"{metric} isn't available yet; `marketpulse perf` explains what it needs.")
        click.echo(value)
        return
    if as_json:
        payload = {
            "base_currency": view.base,
            "since": result.since or None,
            **{attr: getattr(result, attr) for attr in PERF_METRICS.values() if attr != "since"},
            "index": [{"date": day, "level": level} for day, level in result.index],
            "stale": view.stale,
            "excluded": sorted(set(view.excluded)),
        }
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    app.title("Performance")
    app.console.print(
        render.performance_group(result, view, app.palette, width=min(app.console.width - 2, 110), privacy=app.privacy)
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
