"""Portfolio views: status, summary, holdings, performance and income."""

from __future__ import annotations

import calendar
import contextlib
import csv
import io
import json
import math
import shlex
import string
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any

import click
from rich.text import Text

from .. import fmt, render
from ..models import AssetClass, AssetKind
from ..valuation import Breakdown, PortfolioView, PositionView
from .base import App, fail, pass_app
from .root import main

if TYPE_CHECKING:  # annotations only; the CLI imports these lazily
    from ..analytics import IncomeForecast, Performance
    from ..db import Snapshot
    from ..ledger import IncomeEvent
    from ..services import StripItem

# `status --field`: one raw, unmasked value (money rounded to cents, percentages to 4 places, like `--json`).
STATUS_FIELDS: dict[str, Callable[[PortfolioView], object]] = {
    "net-worth": lambda v: round(v.net_worth, 2),
    "day-change": lambda v: round(v.day_change, 2),
    "day-change-pct": lambda v: round(v.day_change_pct, 4),
    "unrealized": lambda v: round(v.unrealized, 2),
    "unrealized-pct": lambda v: round(v.unrealized_pct, 4),
    "invested": lambda v: round(v.invested, 2),
    "cash": lambda v: round(v.cash_total, 2),
    "realized": lambda v: round(v.realized_total, 2),
    "income-ytd": lambda v: round(v.income_ytd, 2),
    "base": lambda v: v.base,
    "market-state": lambda v: v.market_state,
    "stale": lambda v: v.stale,
}
TEMPLATE_PLACEHOLDERS = (
    "net_worth",
    "net_worth_compact",
    "day_change",
    "day_change_pct",
    "arrow",
    "unrealized",
    "unrealized_pct",
    "invested",
    "cash",
    "realized",
    "income_ytd",
    "base",
    "market_state",
    "stale",
)
SUMMARY_SECTIONS = ("markets", "totals", "chart", "allocation", "movers")
ALLOCATION_GROUPS = {"class": "by_class", "account": "by_account", "currency": "by_currency"}
INCOME_KINDS = ("dividend", "drip", "interest")
INCOME_KIND_LABELS = {"dividend": "Dividend", "drip": "DRIP", "interest": "Interest"}
INCOME_GROUPS = ("month", "symbol", "account", "kind")
FORECAST_SORTS = ("annual", "yield", "yield-on-cost", "symbol")
FORECAST_FIELDS = [
    "symbol",
    "name",
    "quantity",
    "per_share_ttm",
    "currency",
    "annual",
    "base_currency",
    "annual_base",
    "yield_pct",
    "yield_on_cost_pct",
]

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


def _iso_date(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """A YYYY-MM-DD date, returned in canonical ISO form."""
    if value is None:
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise click.BadParameter("Use a YYYY-MM-DD date.") from None


def _holding_fields(ctx: click.Context, param: click.Parameter, value: str | None) -> list[str] | None:
    """`holdings --fields`: comma-separated JSON/CSV columns, in the order given, without repeats."""
    if value is None:
        return None
    names = [name.strip() for name in value.split(",") if name.strip()]
    unknown = [name for name in names if name not in HOLDING_FIELDS]
    if not names or unknown:
        shown = ", ".join(unknown) if unknown else "nothing"
        raise click.BadParameter(f"Unknown field {shown}. Choose from: {', '.join(HOLDING_FIELDS)}.")
    return list(dict.fromkeys(names))


def _moved(view: PortfolioView, threshold: float) -> bool:
    """Whether today's portfolio move reaches the threshold; cached (stale) prices never count as a move."""
    return not view.stale and abs(view.day_change_pct or 0.0) >= threshold


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Full machine-readable payload (used by the menu bar).")
@click.option("--waybar", is_flag=True, help="Waybar custom-module JSON (text/tooltip/class).")
@click.option("--short", is_flag=True, help="One line, for tmux/sketchybar/prompt segments.")
@click.option(
    "--field",
    "field_name",
    type=click.Choice(list(STATUS_FIELDS)),
    help="Print one raw, unmasked value for scripts.",
)
@click.option(
    "--format",
    "template",
    metavar="TEMPLATE",
    help="One line from a template such as '{arrow} {day_change_pct} · {net_worth_compact}'; amounts honour privacy.",
)
@click.option("-a", "--account", default=None, help="Only this active account (not with --json or --waybar).")
@click.option("--accounts", "show_accounts", is_flag=True, help="Follow the summary with a table of each account.")
@click.option("--exit-code", is_flag=True, help="Exit 1 when prices are stale or the totals leave something out.")
@click.option("--env", "as_env", is_flag=True, help="Every --field as shell-quoted MARKETPULSE_* assignments for eval.")
@click.option(
    "--change-since",
    callback=_iso_date,
    metavar="DATE",
    help="Add the net worth change since the last snapshot on or before DATE (plain status only).",
)
@click.option(
    "--fail-on-move",
    type=click.FloatRange(min=0),
    callback=_finite_weight,
    metavar="PCT",
    help="Exit 1 when today's portfolio move is at least PCT% either way; cached prices never count.",
)
@pass_app
def status(
    app: App,
    as_json: bool,
    waybar: bool,
    short: bool,
    field_name: str | None,
    template: str | None,
    account: str | None,
    show_accounts: bool,
    exit_code: bool,
    as_env: bool,
    change_since: str | None,
    fail_on_move: float | None,
) -> None:
    """Portfolio status at a glance."""
    modes = [as_json, waybar, short, field_name is not None, template is not None, as_env]
    if sum(modes) > 1:
        raise click.UsageError("Choose one of --json, --waybar, --short, --field, --format or --env.")
    if account is not None and (as_json or waybar):
        raise click.UsageError("-a/--account cannot be combined with --json or --waybar.")
    if show_accounts and any(modes):
        raise click.UsageError("--accounts only adds to the plain status.")
    if change_since is not None and (any(modes) or account is not None):
        raise click.UsageError("--change-since only adds to the plain, whole-portfolio status.")
    if template is not None:
        _check_template(template)
    tr = app.tracker
    if as_json:
        if not exit_code and fail_on_move is None:
            click.echo(json.dumps(tr.status_payload(), ensure_ascii=False))
            return
        view = tr.valuation()
        click.echo(json.dumps(tr.status_payload(view), ensure_ascii=False))
        _status_exit(view, exit_code, fail_on_move)
        return
    if account is not None:
        acct = app.account(account)
        if acct.archived:
            fail(f"No active account '{account}'.")  # archived accounts are reported exactly like unknown ones
        view = tr.valuation(account_id=acct.saved_id)
    else:
        # Pick the baseline before valuing: valuation records today's snapshot, which must not be its own baseline.
        baseline = _snapshot_on_or_before(app, change_since) if change_since is not None else None
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
    elif short:
        click.echo(f"{day} · {fmt.compact(view.net_worth, view.base, privacy=app.privacy)}")
    elif field_name is not None:
        click.echo(_status_field(view, field_name))
    elif template is not None:
        click.echo(template.format_map(_template_values(view, app.privacy)))
    elif as_env:
        for name in STATUS_FIELDS:
            click.echo(f"MARKETPULSE_{name.upper().replace('-', '_')}={shlex.quote(_status_field(view, name))}")
    else:
        app.console.print(render.summary(view, privacy=app.privacy))
        if change_since is not None:
            _print_change_since(app, view, change_since, baseline)
        if show_accounts:
            _print_status_accounts(app, view)
    _status_exit(view, exit_code, fail_on_move)


def _status_exit(view: PortfolioView, exit_code: bool, fail_on_move: float | None) -> None:
    if exit_code:
        _exit_if_incomplete(view)
    if fail_on_move is not None and _moved(view, fail_on_move):
        click.get_current_context().exit(1)


def _snapshot_on_or_before(app: App, since: str) -> Snapshot | None:
    """The last recorded base-currency snapshot on or before `since`."""
    base = app.tracker.base
    earlier = [s for s in app.tracker.store.snapshots() if s.currency == base and s.date <= since]
    return earlier[-1] if earlier else None


def _print_change_since(app: App, view: PortfolioView, since: str, snap: Snapshot | None) -> None:
    """Net worth now against the last recorded snapshot (in the base currency) on or before `since`."""
    if snap is None:
        app.console.print(Text(f"No net worth snapshot on or before {since} to compare with.", style="muted"))
        return
    change = view.net_worth - snap.net_worth
    pct = change / snap.net_worth * 100 if snap.net_worth else None
    line = Text(f"Since {snap.date}  ", style="muted")
    line.append_text(render.trend(fmt.money(change, view.base, sign=True, privacy=app.privacy), change))
    line.append_text(render.trend(f" ({fmt.pct(pct)})", pct))
    line.append(f"  from {fmt.money(snap.net_worth, view.base, privacy=app.privacy)} {view.base}", style="muted")
    app.console.print(line)
    if view.excluded or view.archived_with_value:
        app.warn("Today's totals leave something out, so this change is incomplete.")


def _status_field(view: PortfolioView, name: str) -> str:
    value = STATUS_FIELDS[name](view)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _template_values(view: PortfolioView, privacy: bool) -> dict[str, str]:
    base = view.base
    return {
        "net_worth": fmt.money(view.net_worth, base, privacy=privacy),
        "net_worth_compact": fmt.compact(view.net_worth, base, privacy=privacy),
        "day_change": fmt.money(view.day_change, base, sign=True, privacy=privacy),
        "day_change_pct": fmt.pct(view.day_change_pct),
        "arrow": fmt.arrow(view.day_change),
        "unrealized": fmt.money(view.unrealized, base, sign=True, privacy=privacy),
        "unrealized_pct": fmt.pct(view.unrealized_pct),
        "invested": fmt.money(view.invested, base, privacy=privacy),
        "cash": fmt.money(view.cash_total, base, privacy=privacy),
        "realized": fmt.money(view.realized_total, base, sign=True, privacy=privacy),
        "income_ytd": fmt.money(view.income_ytd, base, privacy=privacy),
        "base": base,
        "market_state": view.market_state,
        "stale": "◌" if view.stale else "",
    }


def _check_template(template: str) -> None:
    """Allow only the known placeholders (no attribute or index access) and well-formed braces."""
    try:
        fields = [(name, spec, conv) for _, name, spec, conv in string.Formatter().parse(template) if name is not None]
    except ValueError as e:
        raise click.UsageError(f"Invalid --format template: {e}.") from None
    for name, spec, conv in fields:
        if spec or conv:
            raise click.UsageError(f"Placeholders take no format spec or conversion: {{{name}}} is already formatted.")
        if name not in TEMPLATE_PLACEHOLDERS:
            known = ", ".join("{" + a + "}" for a in TEMPLATE_PLACEHOLDERS)
            raise click.UsageError(f"Unknown placeholder {{{name}}}. Use: {known}.")


def _exit_if_incomplete(view: PortfolioView) -> None:
    """Exit 1 when the figures can't be fully trusted: cached prices, or something left out of the totals."""
    if view.stale or view.excluded or view.archived_with_value:
        click.get_current_context().exit(1)


def _print_status_accounts(app: App, view: PortfolioView) -> None:
    app.console.print()
    if not view.by_account:
        app.console.print(Text("No accounts hold anything yet.", style="muted"))
        return
    table = render.table(
        "Account", ("Value", "right"), ("Today", "right"), ("Day %", "right"), ("Weight", "right"), title="Accounts"
    )
    for b in view.by_account:
        table.add_row(
            Text(b.label, style="bright"),
            Text(fmt.money(b.value, view.base, privacy=app.privacy)),
            render.trend(fmt.money(b.day_change, view.base, sign=True, privacy=app.privacy), b.day_change),
            render.trend(fmt.pct(b.day_change_pct), b.day_change_pct),
            Text(fmt.pct(b.weight, sign=False), style="muted"),
        )
    app.console.print(table)


@main.command("summary")
@click.option("--json", "as_json", is_flag=True, help="Print the dashboard's figures as raw, unmasked JSON.")
@click.option(
    "--section",
    "sections",
    multiple=True,
    type=click.Choice(SUMMARY_SECTIONS),
    help="Show only this section; repeat for several. Market quotes are fetched only when shown.",
)
@click.option("--top", type=click.IntRange(min=1), help="Show up to N of today's movers (default 6).")
@click.option("--months", type=click.IntRange(1, 120), help="Net worth history window in months (default 12).")
@click.option(
    "--allocation-by",
    type=click.Choice(list(ALLOCATION_GROUPS)),
    help="Group the allocation by asset class (default), account or currency.",
)
@click.option(
    "--exclude-section",
    "excluded_sections",
    multiple=True,
    type=click.Choice(SUMMARY_SECTIONS),
    help="Show every section except this one; repeat for several.",
)
@click.option(
    "--min-move",
    type=click.FloatRange(min=0),
    callback=_finite_weight,
    metavar="PCT",
    help="Only movers up or down at least PCT% today.",
)
@pass_app
def summary_cmd(
    app: App,
    as_json: bool,
    sections: tuple[str, ...],
    top: int | None,
    months: int | None,
    allocation_by: str | None,
    excluded_sections: tuple[str, ...],
    min_move: float | None,
) -> None:
    """Dashboard: net worth, returns, allocation, movers and markets."""
    if sections and excluded_sections:
        raise click.UsageError("Choose either --section or --exclude-section.")
    if sections:
        shown = [s for s in SUMMARY_SECTIONS if s in sections]
    else:
        shown = [s for s in SUMMARY_SECTIONS if s not in excluded_sections]
        if not shown:
            raise click.UsageError("--exclude-section leaves no section to show.")
    top = 6 if top is None else top
    months = 12 if months is None else months
    allocation_by = allocation_by or "class"
    tr = app.tracker
    with contextlib.nullcontext() if as_json else app.busy("Loading markets and portfolio…"):
        view = tr.valuation()
        perf = tr.performance(view)
        strip = tr.market_strip() if "markets" in shown else []
        since = _months_before(date.today(), months).isoformat()
        snaps = [s for s in tr.store.snapshots(since) if s.currency == view.base]
    breakdown: list[Breakdown] = getattr(view, ALLOCATION_GROUPS[allocation_by])
    if min_move is None:
        movers = view.movers(top)
    else:
        movers = [p for p in view.movers(len(view.positions)) if abs(p.day_change_pct or 0) >= min_move][:top]
    if as_json:
        payload = _summary_payload(view, perf, strip, snaps, breakdown, allocation_by, movers, shown)
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    c = app.console
    blocks: list[Callable[[], None]] = []
    if "markets" in shown:
        blocks.append(lambda: c.print(render.strip_text(strip), render.market_state_text(view.market_state)))
    if "totals" in shown:
        blocks.append(lambda: c.print(render.summary(view, perf, privacy=app.privacy)))
    if "chart" in shown:

        def chart() -> None:
            app.title(f"Net worth · {_window_label(months)}")
            c.print(render.net_worth_chart(snaps, app.palette, width=min(c.width - 2, 110), privacy=app.privacy))

        blocks.append(chart)
    if "allocation" in shown:

        def allocation() -> None:
            app.title("Allocation" if allocation_by == "class" else f"Allocation by {allocation_by}")
            width = min(c.width - 4, 80)
            c.print(render.allocation(breakdown, app.palette, width=width, privacy=app.privacy, base=view.base))

        blocks.append(allocation)
    if "movers" in shown and movers:

        def movers_line() -> None:
            app.title("Today's movers")
            line = Text()
            for p in movers:
                line.append(f"{p.symbol} ", style="bright")
                line.append(
                    f"{fmt.arrow(p.day_change_pct)}{abs(p.day_change_pct or 0):.2f}%   ",
                    style=fmt.trend_style(p.day_change_pct),
                )
            c.print(line)

        blocks.append(movers_line)
    for i, block in enumerate(blocks):
        if i:
            c.print()
        block()
    if not blocks:
        c.print(Text("No movers today.", style="muted"))


def _months_before(day: date, months: int) -> date:
    """The same day `months` calendar months earlier, clamped to the end of a shorter month."""
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def _window_label(months: int) -> str:
    return f"{months // 12}y" if months % 12 == 0 else f"{months}m"


def _summary_payload(
    view: PortfolioView,
    perf: Performance,
    strip: list[StripItem],
    snaps: list[Snapshot],
    breakdown: list[Breakdown],
    allocation_by: str,
    movers: list[PositionView],
    shown: list[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {"base_currency": view.base, "stale": view.stale}
    if "markets" in shown:
        payload["market_state"] = view.market_state or None
        payload["markets"] = [
            {
                "symbol": item.symbol,
                "label": item.label,
                "price": q.price if q else None,
                "change": q.change if q else None,
                "change_pct": q.change_pct if q else None,
                "currency": q.currency if q else None,
                "stale": q.stale if q else None,
            }
            for item in strip
            for q in [item.quote]
        ]
    if "totals" in shown:
        payload.update(
            {
                "net_worth": view.net_worth,
                "day_change": view.day_change,
                "day_change_pct": view.day_change_pct,
                "invested": view.invested,
                "unrealized": view.unrealized,
                "unrealized_pct": view.unrealized_pct,
                "realized": view.realized_total,
                "income_ytd": view.income_ytd,
                "cash": view.cash_total,
                "returns": {"since": perf.since or None, "xirr_pct": perf.xirr_pct, "twr_pct": perf.twr_pct},
            }
        )
    if "chart" in shown:
        payload["history"] = [{"date": s.date, "net_worth": s.net_worth} for s in snaps]
    if "allocation" in shown:
        payload["allocation"] = {
            "by": allocation_by,
            "rows": [{"key": b.key, "label": b.label, "value": b.value, "weight": b.weight} for b in breakdown],
        }
    if "movers" in shown:
        payload["movers"] = [
            {
                "symbol": p.symbol,
                "name": p.name,
                "price": p.price,
                "currency": p.currency,
                "day_change_pct": p.day_change_pct,
            }
            for p in movers
        ]
    payload["excluded"] = sorted(set(view.excluded))
    payload["archived_with_value"] = list(view.archived_with_value)
    return payload


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
@click.option(
    "--asset-class",
    "asset_classes",
    multiple=True,
    type=click.Choice([c.value for c in AssetClass], case_sensitive=False),
    help="Only this asset class; repeat for several.",
)
@click.option(
    "--kind",
    "kinds",
    multiple=True,
    type=click.Choice([k.value for k in AssetKind], case_sensitive=False),
    help="Only this pricing kind (market, fixed_income, manual, cash); repeat for several.",
)
@click.option(
    "--min-value",
    type=click.FloatRange(min=0),
    callback=_finite_weight,
    metavar="AMOUNT",
    help="Only priced positions worth at least AMOUNT in the base currency.",
)
@click.option(
    "--day-move",
    type=click.FloatRange(min=0),
    callback=_finite_weight,
    metavar="PCT",
    help="Only positions up or down at least PCT% today.",
)
@click.option(
    "--opened-since", callback=_iso_date, metavar="DATE", help="Only positions first bought on or after DATE."
)
@click.option(
    "--fields",
    callback=_holding_fields,
    metavar="LIST",
    help="Comma-separated columns for --json or --csv, in this order.",
)
@click.option("--markdown", is_flag=True, help="Print the matching positions as a Markdown table; honours privacy.")
@click.option("--symbols-only", is_flag=True, help="Print each matching symbol once per line, for scripts.")
@click.option("--subtotal", is_flag=True, help="Follow the selection with the shown priced positions' totals.")
@click.option(
    "--concentration-limit",
    type=click.FloatRange(min=0, max=100, min_open=True),
    callback=_finite_weight,
    metavar="PCT",
    help="Name positions weighing more than PCT% of net worth and exit 1 when there are any.",
)
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
    asset_classes: tuple[str, ...],
    kinds: tuple[str, ...],
    min_value: float | None,
    day_move: float | None,
    opened_since: str | None,
    fields: list[str] | None,
    markdown: bool,
    symbols_only: bool,
    subtotal: bool,
    concentration_limit: float | None,
) -> None:
    """Priced holdings with gains, day change and weights.

    Selection options (filters, --sort, --limit, --offset) show only positions:
    cash rows and portfolio totals are left out rather than summed for a subset."""
    if (as_json and as_csv) or (count_only and (as_json or as_csv)):
        raise click.UsageError("Choose one output format; --count cannot be combined with --json or --csv.")
    if sum([as_json, as_csv, count_only, markdown, symbols_only]) > 1:
        raise click.UsageError("Choose one output format: --json, --csv, --count, --markdown or --symbols-only.")
    if count_only and (limit is not None or offset is not None):
        raise click.UsageError("--count cannot be combined with --limit or --offset.")
    if gainers and losers:
        raise click.UsageError("Choose either --gainers or --losers.")
    if descending and sort_by is None:
        raise click.UsageError("--descending requires --sort.")
    if fields is not None and not (as_json or as_csv):
        raise click.UsageError("--fields applies only to --json or --csv.")
    if subtotal and (as_json or as_csv or count_only or markdown or symbols_only):
        raise click.UsageError("--subtotal only adds to the table.")
    filtered = any(
        [
            symbol is not None,
            currency is not None,
            gainers,
            losers,
            min_weight is not None,
            stale_only,
            bool(asset_classes),
            bool(kinds),
            min_value is not None,
            day_move is not None,
            opened_since is not None,
        ]
    )
    paged = limit is not None or offset is not None
    extra_output = markdown or symbols_only or fields is not None or subtotal or concentration_limit is not None
    if show_excluded and (as_csv or count_only or filtered or paged or sort_by is not None or extra_output):
        raise click.UsageError("--excluded combines only with -a/--account and --json.")
    machine = as_json or as_csv or count_only or markdown or symbols_only
    selecting = machine or filtered or paged or sort_by is not None or subtotal
    acct = app.account(account) if account else None
    if acct is not None and acct.archived and (selecting or show_excluded or concentration_limit is not None):
        fail(f"No active account '{account}'.")  # archived accounts are reported exactly like unknown ones
    # The same valuation (and snapshot) as the plain table: options only choose what is shown.
    with contextlib.nullcontext() if machine else app.busy("Pricing holdings…"):
        view = app.tracker.valuation(account_id=acct.id if acct else None)
    if show_excluded:
        _print_excluded(app, view, as_json)
        return
    if not selecting:
        if not view.positions and not view.cash:
            app.console.print(Text("No holdings yet — try `marketpulse buy XEQT.TO 10`.", style="muted"))
        else:
            app.console.print(render.holdings_table(view, privacy=app.privacy, width=app.console.width))
            app.console.print(render.summary(view, privacy=app.privacy))
            for reason in sorted(set(view.errors.values())):
                app.warn(reason)
        _check_concentration(app, view.positions, concentration_limit, quiet=False)
        return
    needle = symbol.strip().casefold() if symbol is not None else None
    wanted = currency.strip().upper() if currency is not None else None
    classes = {c.lower() for c in asset_classes}
    kind_set = {k.lower() for k in kinds}
    matches = [
        p
        for p in view.positions
        if (needle is None or needle in p.symbol.casefold())
        and (wanted is None or p.currency.upper() == wanted)
        and (not gainers or (p.priced and p.gain is not None and p.gain > 0))
        and (not losers or (p.priced and p.gain is not None and p.gain < 0))
        and (min_weight is None or (p.priced and p.weight >= min_weight))
        and (not stale_only or p.stale)
        and (not classes or p.asset_class.value in classes)
        and (not kind_set or p.kind.value in kind_set)
        and (min_value is None or (p.value_base is not None and p.value_base >= min_value))
        and (day_move is None or (p.day_change_pct is not None and abs(p.day_change_pct) >= day_move))
        and (opened_since is None or (p.first_date or "") >= opened_since)
    ]
    if count_only:
        click.echo(len(matches))
        _check_concentration(app, matches, concentration_limit, quiet=True)
        return
    total = len(matches)
    start = offset or 0
    rows = _sort_holdings(matches, sort_by, descending)[start : start + limit if limit is not None else None]
    columns = fields or HOLDING_FIELDS
    if as_csv or as_json or markdown or symbols_only:
        if as_csv:
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(_holding_row(p, view.base) for p in rows)
            click.echo(stream.getvalue(), nl=False)
        elif as_json:
            data = [{k: row[k] for k in columns} for row in (_holding_row(p, view.base) for p in rows)]
            click.echo(json.dumps(data, ensure_ascii=False))
        elif markdown:
            click.echo(_holdings_markdown(rows, view.base, app.privacy))
        else:
            for name in dict.fromkeys(p.symbol for p in rows):
                click.echo(name)
        _check_concentration(app, matches, concentration_limit, quiet=True)
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
        if subtotal:
            app.console.print(_subtotal_text(rows, view.base, app.privacy))
    if view.stale:
        app.warn(f"Prices are {render.stale_note(view)}.")
    if view.excluded:
        app.warn("Some holdings have no price or FX rate; `marketpulse holdings --excluded` lists them.")
    if view.archived_with_value:
        app.warn(f"Archived {', '.join(view.archived_with_value)} still holds value, so snapshots are paused.")
    for reason in sorted(set(view.errors.values())):
        app.warn(reason)
    _check_concentration(app, matches, concentration_limit, quiet=False)


def _check_concentration(app: App, positions: list[PositionView], limit: float | None, *, quiet: bool) -> None:
    """`--concentration-limit`: name each priced position over the limit (on stderr for machine output), exit 1."""
    if limit is None:
        return
    over = sorted((p for p in positions if p.priced and p.weight > limit), key=lambda p: (-p.weight, p.symbol))
    for p in over:
        message = f"{p.symbol} in {p.account.name} is {fmt.pct(p.weight, sign=False)} of net worth, over {limit:g}%."
        if quiet:
            click.echo(f"! {message}", err=True)
        else:
            app.warn(message)
    if over:
        click.get_current_context().exit(1)


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|")


def _holdings_markdown(rows: list[PositionView], base: str, privacy: bool) -> str:
    lines = [
        f"| Account | Symbol | Quantity | Price | Value ({base}) | Unrealized ({base}) | Gain % | Weight |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for p in rows:
        cells = [
            _md_cell(p.account.name),
            _md_cell(p.symbol),
            fmt.MASK if privacy else fmt.qty(p.quantity),
            f"{fmt.price(p.price, privacy=privacy and p.kind is not AssetKind.MARKET)} {p.currency}"
            if p.price is not None
            else "—",
            fmt.money(p.value_base, base, privacy=privacy),
            fmt.money(p.gain_base, base, sign=True, privacy=privacy),
            fmt.pct(p.gain_pct if p.priced else None),
            fmt.pct(p.weight if p.priced else None, sign=False),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _subtotal_text(rows: list[PositionView], base: str, privacy: bool) -> Text:
    priced = [p for p in rows if p.priced]
    value = math.fsum(p.value_base or 0.0 for p in priced)
    book = math.fsum(p.book_base or 0.0 for p in priced)
    gain = value - book
    noun = "position" if len(priced) == 1 else "positions"
    line = Text(f"Subtotal of {len(priced)} priced {noun}  ", style="muted")
    line.append(f"value {fmt.money(value, base, privacy=privacy)} {base}")
    line.append(f"  ·  book {fmt.money(book, base, privacy=privacy)}")
    line.append("  ·  unrealized ")
    line.append_text(render.trend(fmt.money(gain, base, sign=True, privacy=privacy), gain))
    line.append_text(render.trend(f" ({fmt.pct(gain / book * 100 if book else None)})", gain))
    if len(priced) < len(rows):
        line.append(f"  ·  {len(rows) - len(priced)} unpriced left out", style="warn")
    return line


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
@click.option("--csv", "as_csv", is_flag=True, help="Print the raw, unmasked metrics as metric,value CSV rows.")
@click.option("--index-csv", is_flag=True, help="Print the time-weighted index as date,level CSV rows.")
@pass_app
def perf(app: App, as_json: bool, metric: str | None, as_csv: bool, index_csv: bool) -> None:
    """Returns: money-weighted, time-weighted, drawdown and volatility."""
    if as_json and metric:
        raise click.UsageError("Choose either --json or --metric.")
    if sum([as_json, metric is not None, as_csv, index_csv]) > 1:
        raise click.UsageError("Choose one of --json, --metric, --csv or --index-csv.")
    tr = app.tracker
    quiet = as_json or metric or as_csv or index_csv
    with contextlib.nullcontext() if quiet else app.busy("Calculating performance…"):
        view = tr.valuation()
        result = tr.performance(view)
    if as_csv:
        rows = [
            {"metric": attr, "value": "" if value is None else value}
            for attr in PERF_METRICS.values()
            for value in [result.since or None if attr == "since" else getattr(result, attr)]
        ]
        _echo_rows(["metric", "value", "base_currency"], rows, view.base)
        return
    if index_csv:
        _echo_rows(["date", "level"], [{"date": day, "level": level} for day, level in result.index], view.base)
        return
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
@click.option("--json", "as_json", is_flag=True, help="Print raw, unmasked base-currency figures as JSON.")
@click.option("--csv", "as_csv", is_flag=True, help="Print raw, unmasked monthly (or --by) totals as CSV to stdout.")
@click.option("--months", type=click.IntRange(1, 120), help="Monthly history window ending this month (default 12).")
@click.option("--year", type=click.IntRange(1900, 9999), help="January to December of this year, and its sources.")
@click.option("-a", "--account", default=None, help="Only this active account (name, id or type).")
@click.option("--symbol", help="Only this symbol, ignoring case.")
@click.option(
    "--kind",
    "kinds",
    multiple=True,
    type=click.Choice(INCOME_KINDS, case_sensitive=False),
    help="Only this kind of income; repeat for several.",
)
@click.option(
    "--by",
    type=click.Choice(INCOME_GROUPS, case_sensitive=False),
    help="Totals per month, symbol, account or kind over the window, instead of the report.",
)
@click.option("--top", type=click.IntRange(min=1), help="Keep the N largest sources, groups or forecast rows.")
@click.option("--forecast-only", is_flag=True, help="Only the forward 12-month estimate.")
@click.option(
    "--forecast-sort",
    type=click.Choice(FORECAST_SORTS),
    help="Order forecast rows by estimated annual income, yield or yield on cost (largest first), or symbol.",
)
@click.option(
    "--min-yield",
    type=click.FloatRange(min=0),
    callback=_finite_weight,
    metavar="PCT",
    help="Only forecast rows yielding at least PCT% at today's price.",
)
@click.option("--stats", "show_stats", is_flag=True, help="Add the monthly average, best month and months paid.")
@pass_app
def income(
    app: App,
    no_forecast: bool,
    as_json: bool,
    as_csv: bool,
    months: int | None,
    year: int | None,
    account: str | None,
    symbol: str | None,
    kinds: tuple[str, ...],
    by: str | None,
    top: int | None,
    forecast_only: bool,
    forecast_sort: str | None,
    min_yield: float | None,
    show_stats: bool,
) -> None:
    """Dividends and interest: monthly history, sources and forward estimate.

    Any option other than --no-forecast selects from active accounts only and
    lists payouts with no FX rate instead of counting them as zero."""
    selection = IncomeSelection(months, year, account, symbol, tuple(k.lower() for k in kinds), by and by.lower(), top)
    selection.forecast_sort, selection.min_yield, selection.stats = forecast_sort, min_yield, show_stats
    selection.active = selection.active or forecast_sort is not None or min_yield is not None or show_stats
    if not (as_json or as_csv or forecast_only or selection.active):
        from ..analytics import income_by_month, income_by_symbol

        tr = app.tracker
        with app.busy("Crunching income…"):
            view = tr.valuation()
            state = tr.store.ledger()
            months_ = income_by_month(state, view.fx.convert)
            sources = income_by_symbol(state, view.fx.convert, date.today().year)
            forecast = None if no_forecast else tr.income_forecast(view)
        app.title("Income")
        app.console.print(render.income_group(months_, sources, forecast, view, privacy=app.privacy))
        return
    _selected_income(app, selection, no_forecast, as_json, as_csv, forecast_only)


class IncomeSelection:
    """What `income` options choose; the plain report runs only when none are given."""

    def __init__(
        self,
        months: int | None,
        year: int | None,
        account: str | None,
        symbol: str | None,
        kinds: tuple[str, ...],
        by: str | None,
        top: int | None,
    ) -> None:
        self.months, self.year, self.account, self.kinds, self.by, self.top = months, year, account, kinds, by, top
        self.symbol = symbol.strip().upper() if symbol is not None else None
        self.active = any(x is not None for x in (months, year, account, symbol, by, top)) or bool(kinds)
        self.forecast_sort: str | None = None
        self.min_yield: float | None = None
        self.stats = False

    @property
    def window(self) -> int:
        return 12 if self.months is None else self.months

    def matches(self, e: IncomeEvent) -> bool:
        return (self.symbol is None or e.symbol.upper() == self.symbol) and (
            not self.kinds or e.kind.value.lower() in self.kinds
        )


def _selected_income(
    app: App, sel: IncomeSelection, no_forecast: bool, as_json: bool, as_csv: bool, forecast_only: bool
) -> None:
    from ..analytics import income_by_month, income_by_symbol
    from ..ledger import LedgerState

    if as_json and as_csv:
        raise click.UsageError("Choose either --json or --csv.")
    if sel.months is not None and sel.year is not None:
        raise click.UsageError("Choose either --months or --year.")
    if sel.symbol == "":
        raise click.UsageError("--symbol cannot be blank.")
    if forecast_only and (no_forecast or sel.by or sel.months is not None or sel.year is not None or sel.kinds):
        raise click.UsageError("--forecast-only combines only with -a/--account, --symbol, --top, --json and --csv.")
    if sel.stats and (as_csv or sel.by or forecast_only):
        raise click.UsageError("--stats can't be combined with --csv, --by or --forecast-only.")
    acct_id = None
    if sel.account is not None:
        acct = app.account(sel.account)
        if acct.archived:
            fail(f"No active account '{sel.account}'.")  # archived accounts are reported exactly like unknown ones
        acct_id = acct.saved_id
    tr = app.tracker
    # The forecast fetches distribution history; the offline views (--by, CSV) never do.
    wants_forecast = forecast_only or (
        not no_forecast and sel.by is None and not as_csv and (not sel.kinds or {"dividend", "drip"} & set(sel.kinds))
    )
    if (sel.forecast_sort is not None or sel.min_yield is not None) and not wants_forecast:
        raise click.UsageError(
            "--forecast-sort and --min-yield need the forward estimate: drop --no-forecast, --by or "
            "--csv (or add --forecast-only), and keep a dividend --kind."
        )
    with contextlib.nullcontext() if as_json or as_csv else app.busy("Crunching income…"):
        view = tr.valuation(account_id=acct_id)
        forecast = tr.income_forecast(view) if wants_forecast else None
        accounts = {k: a for k, a in tr.store.account_map().items() if not a.archived}
        events = [
            e
            for e in tr.store.ledger().income
            if e.account_id in accounts and (acct_id is None or e.account_id == acct_id) and sel.matches(e)
        ]
    if forecast is not None and sel.symbol is not None:
        forecast = [r for r in forecast if r.symbol.upper() == sel.symbol]
    if forecast is not None and sel.min_yield is not None:
        floor = sel.min_yield
        forecast = [r for r in forecast if r.yield_pct is not None and r.yield_pct >= floor]
    if forecast is not None and sel.forecast_sort is not None:
        forecast = _sort_forecast(forecast, sel.forecast_sort)
    forecast_total = sum(r.annual_base or 0 for r in forecast) if forecast is not None else None
    if forecast is not None and sel.top is not None:
        forecast = forecast[: sel.top]
    if forecast_only:
        _forecast_only(app, view, forecast or [], forecast_total or 0.0, as_json, as_csv)
        return
    convert = view.fx.convert
    state = LedgerState(income=[e for e in events if convert(e.amount, e.currency) is not None])
    end = date(sel.year, 12, 31) if sel.year is not None else None
    months = income_by_month(state, convert, sel.window, end)
    window = {m for m, _ in months}
    sources_year = sel.year if sel.year is not None else date.today().year
    sources = income_by_symbol(state, convert, sources_year)
    # Payouts with no FX rate are listed rather than counted as zero, when they fall in what is shown.
    missing = [
        _unconverted_row(e, accounts)
        for e in events
        if convert(e.amount, e.currency) is None
        and (e.date[:7] in window or (sel.by is None and e.date[:4] == f"{sources_year:04d}"))
    ]
    if sel.by is not None:
        in_window = [e for e in state.income if e.date[:7] in window]
        groups = _income_groups(in_window, sel.by, accounts, convert)
        total = math.fsum(g["amount"] for g in groups)
        payouts = sum(g["count"] for g in groups)
        if sel.top is not None:
            keep = {id(g) for g in sorted(groups, key=lambda g: -g["amount"])[: sel.top]}
            groups = [g for g in groups if id(g) in keep]
        if as_csv:
            _echo_rows(["group", "label", "count", "amount", "base_currency"], groups, view.base)
            _warn_unconverted(app, view.base, missing, stderr=True)
        elif as_json:
            payload = {
                "base_currency": view.base,
                "by": sel.by,
                "window_months": None if sel.year is not None else sel.window,
                "year": sel.year,
                "groups": groups,
                "total": total,
                "payouts": payouts,
                "unconverted": missing,
            }
            click.echo(json.dumps(payload, ensure_ascii=False))
        else:
            _print_income_groups(app, sel, view.base, groups, total, payouts)
            _warn_unconverted(app, view.base, missing)
        return
    sources_total = math.fsum(amount for _, amount in sources)
    if sel.top is not None:
        sources = sources[: sel.top]
    if as_csv:
        _echo_rows(["month", "amount", "base_currency"], [{"month": m, "amount": a} for m, a in months], view.base)
        _warn_unconverted(app, view.base, missing, stderr=True)
        return
    if as_json:
        payload = {
            "base_currency": view.base,
            "window_months": None if sel.year is not None else sel.window,
            "year": sel.year,
            "months": [{"month": m, "amount": a} for m, a in months],
            "window_total": math.fsum(a for _, a in months),
            "sources_year": sources_year,
            "sources": [{"source": s, "amount": a} for s, a in sources],
            "sources_total": sources_total,
            "forecast": None if forecast is None else [_forecast_row(r, view.base) for r in forecast],
            "forecast_total": forecast_total,
            "unconverted": missing,
        }
        if sel.stats:
            payload["stats"] = _income_stats(months)
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    _print_income_report(app, sel, view, months, sources, sources_year, sources_total, forecast, forecast_total)
    _warn_unconverted(app, view.base, missing)


def _sort_forecast(rows: list[IncomeForecast], by: str) -> list[IncomeForecast]:
    """Largest first for amounts and yields, with rows missing the figure last; symbols alphabetically."""
    if by == "symbol":
        return sorted(rows, key=lambda r: r.symbol)
    attr = {"annual": "annual_base", "yield": "yield_pct", "yield-on-cost": "yield_on_cost_pct"}[by]
    present = [r for r in rows if getattr(r, attr) is not None]
    missing = sorted((r for r in rows if getattr(r, attr) is None), key=lambda r: r.symbol)
    return sorted(present, key=lambda r: (-getattr(r, attr), r.symbol)) + missing


def _income_stats(months: list[tuple[str, float]]) -> dict[str, Any]:
    """`income --stats`: the window's monthly average, its best month and how many months paid anything."""
    paid = [(m, a) for m, a in months if a > 0]
    best = max(paid, key=lambda item: item[1]) if paid else None
    return {
        "months": len(months),
        "paying_months": len(paid),
        "monthly_average": math.fsum(a for _, a in months) / len(months) if months else 0.0,
        "best_month": best[0] if best else None,
        "best_month_amount": best[1] if best else None,
    }


def _income_stats_text(stats: dict[str, Any], base: str, privacy: bool) -> Text:
    line = Text(f"Monthly average {fmt.money(stats['monthly_average'], base, privacy=privacy)}", style="muted")
    if stats["best_month"] is not None:
        amount = fmt.money(stats["best_month_amount"], base, privacy=privacy)
        line.append(f" · best month {stats['best_month']} ({amount})")
    line.append(f" · {stats['paying_months']} of {stats['months']} months paid")
    return line


def _unconverted_row(e: IncomeEvent, accounts: dict) -> dict[str, Any]:
    return {
        "date": e.date,
        "account": accounts[e.account_id].name,
        "symbol": e.symbol,
        "kind": e.kind.value.lower(),
        "amount": e.amount,
        "currency": e.currency,
    }


def _forecast_row(r: IncomeForecast, base: str) -> dict[str, Any]:
    return {
        "symbol": r.symbol,
        "name": r.name,
        "quantity": r.quantity,
        "per_share_ttm": r.per_share_ttm,
        "currency": r.currency,
        "annual": r.annual,
        "base_currency": base,
        "annual_base": r.annual_base,
        "yield_pct": r.yield_pct,
        "yield_on_cost_pct": r.yield_on_cost_pct,
    }


def _income_groups(
    events: list[IncomeEvent], by: str, accounts: dict, convert: Callable[[float, str], float | None]
) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    labels: dict[str, str] = {}
    for e in events:
        if by == "month":
            key = label = e.date[:7]
        elif by == "symbol":
            key = label = e.symbol or "Interest"  # the label the plain report's sources use
        elif by == "account":
            key, label = str(e.account_id), accounts[e.account_id].name
        else:
            key = e.kind.value.lower()
            label = INCOME_KIND_LABELS[key]
        grouped.setdefault(key, []).append(convert(e.amount, e.currency) or 0.0)
        labels[key] = label
    rows = [
        {"group": key, "label": labels[key], "count": len(amounts), "amount": math.fsum(amounts)}
        for key, amounts in grouped.items()
    ]
    if by == "month":
        return sorted(rows, key=lambda r: r["group"])
    return sorted(rows, key=lambda r: (-r["amount"], r["label"].casefold(), r["group"]))


def _echo_rows(fields: list[str], rows: list[dict[str, Any]], base: str) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows({**row, "base_currency": base} for row in rows)
    click.echo(stream.getvalue(), nl=False)


def _window_text(sel: IncomeSelection) -> str:
    return str(sel.year) if sel.year is not None else f"last {sel.window} months"


def _print_income_groups(
    app: App, sel: IncomeSelection, base: str, groups: list[dict[str, Any]], total: float, payouts: int
) -> None:
    app.title("Income")
    if not groups:
        app.console.print(Text(f"No income matches these filters in the {_window_text(sel)}.", style="muted"))
        return
    table = render.table(
        sel.by.title() if sel.by else "", ("Payouts", "right"), (f"Amount ({base})", "right"), title=f"By {sel.by}"
    )
    for g in groups:
        table.add_row(
            Text(g["label"], style="bright"),
            Text(str(g["count"]), style="muted"),
            Text(fmt.money(g["amount"], base, privacy=app.privacy), style="up"),
        )
    app.console.print(table)
    noun = "payout" if payouts == 1 else "payouts"
    app.console.print(
        Text(
            f"{fmt.money(total, base, privacy=app.privacy)} {base} from {payouts} {noun} in the {_window_text(sel)}, "
            "converted at today's rates.",
            style="muted",
        )
    )


def _print_income_report(
    app: App,
    sel: IncomeSelection,
    view: PortfolioView,
    months: list[tuple[str, float]],
    sources: list[tuple[str, float]],
    sources_year: int,
    sources_total: float,
    forecast: list[IncomeForecast] | None,
    forecast_total: float | None,
) -> None:
    from .. import charts

    privacy, base = app.privacy, view.base
    values = [v for _, v in months]
    head = Text()
    head.append(f"{_window_text(sel).upper()}  ", style="muted")
    head.append(fmt.money(math.fsum(values), base, privacy=privacy), style="up bold")
    if sel.year is None:
        head.append("    YTD  ", style="muted")
        head.append(fmt.money(sources_total, base, privacy=privacy), style="up")
    if forecast_total is not None and forecast:
        head.append("    NEXT 12M EST.  ", style="muted")
        head.append(fmt.money(forecast_total, base, privacy=privacy), style="accent")
    app.title("Income")
    app.console.print(head)
    if sel.stats:
        app.console.print(_income_stats_text(_income_stats(months), base, privacy))
    app.console.print(Text(""))
    if any(values):
        # As many of the most recent months as fit the terminal, four columns each down to two.
        width = max(app.console.width - 2, 24)
        col = max(2, min(4, width // len(values)))
        shown = months[-(width // col) :]
        labels = [calendar.month_abbr[int(m[5:7])] for m, _ in shown]
        app.console.print(charts.column_chart([v for _, v in shown], labels, 8, "up", col_width=col))
    else:
        app.console.print(Text(f"No matching dividends or interest in the {_window_text(sel)}.", style="muted"))
    if sources:
        column = "This year" if sources_year == date.today().year else str(sources_year)
        table = render.table("Source", (column, "right"), title="By source")
        for source, amount in sources[: sel.top or 12]:
            table.add_row(Text(source, style="bright"), Text(fmt.money(amount, base, privacy=privacy), style="up"))
        app.console.print(Text(""))
        app.console.print(table)
    if forecast:
        app.console.print(Text(""))
        app.console.print(_forecast_table(forecast, base, privacy))


def _forecast_table(forecast: list[IncomeForecast], base: str, privacy: bool) -> Any:
    table = render.table(
        "Symbol",
        ("Qty", "right"),
        ("TTM / share", "right"),
        ("Est. annual", "right"),
        ("Yield", "right"),
        ("Yield on cost", "right"),
        title="Forward income (trailing 12m distributions)",
    )
    for r in forecast:
        table.add_row(
            Text(r.symbol, style="bright"),
            Text(fmt.MASK if privacy else fmt.qty(r.quantity)),
            Text(f"{r.per_share_ttm:,.4f} {r.currency}", style="muted"),
            Text(fmt.money(r.annual_base, base, privacy=privacy), style="up"),
            Text(fmt.pct(r.yield_pct, sign=False)),
            Text(fmt.pct(r.yield_on_cost_pct, sign=False), style="accent"),
        )
    return table


def _forecast_only(
    app: App, view: PortfolioView, forecast: list[IncomeForecast], total: float, as_json: bool, as_csv: bool
) -> None:
    if as_csv:
        _echo_rows(FORECAST_FIELDS, [_forecast_row(r, view.base) for r in forecast], view.base)
        return
    if as_json:
        rows = [_forecast_row(r, view.base) for r in forecast]
        click.echo(json.dumps({"base_currency": view.base, "forecast": rows, "total": total}, ensure_ascii=False))
        return
    app.title("Income")
    if not forecast:
        app.console.print(Text("No trailing distributions for these holdings.", style="muted"))
        return
    head = Text("NEXT 12M EST.  ", style="muted")
    head.append(fmt.money(total, view.base, privacy=app.privacy), style="accent")
    app.console.print(head)
    app.console.print(Text(""))
    app.console.print(_forecast_table(forecast, view.base, app.privacy))


def _warn_unconverted(app: App, base: str, missing: list[dict[str, Any]], *, stderr: bool = False) -> None:
    """Name payouts left out for want of an FX rate; on stderr when stdout is CSV for a script."""
    if missing:
        currencies = ", ".join(sorted({m["currency"] for m in missing}))
        n = len(missing)
        noun, verb = ("payout", "has") if n == 1 else ("payouts", "have")
        message = f"{n} {noun} in {currencies} {verb} no FX rate to {base} and {'is' if n == 1 else 'are'} left out."
        if stderr:
            click.echo(f"! {message}", err=True)
        else:
            app.warn(message)
