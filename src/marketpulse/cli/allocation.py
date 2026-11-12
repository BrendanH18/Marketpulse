"""Allocation breakdown, asset-class targets and rebalancing drift."""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import click
from click.core import ParameterSource
from rich.text import Text

from .. import fmt, render
from ..models import AssetClass
from .base import App, fail, pass_app
from .root import main

if TYPE_CHECKING:
    from ..analytics import RebalanceRow
    from ..valuation import Breakdown

BREAKDOWN_FIELDS = ["key", "label", "value", "weight"]
REBALANCE_FIELDS = ["bucket", "label", "value", "weight", "target", "drift", "delta"]
TARGET_FIELDS = ["bucket", "label", "target"]
SORTS = ["value", "weight", "name"]


def _percent(ctx: click.Context, param: click.Parameter, value: float | None) -> float | None:
    if value is not None and (not math.isfinite(value) or not 0 <= value <= 100):
        raise click.BadParameter("Must be a percentage from 0 to 100.")
    return value


def _class_key(text: str) -> str:
    return text.strip().lower().replace(" ", "_")


def _class_label(key: str) -> str:
    try:
        return AssetClass(key).label
    except ValueError:
        return key.replace("_", " ").title()


def _emit_csv(fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    click.echo(stream.getvalue(), nl=False)


def _target_rows(targets: dict[str, float]) -> list[dict[str, Any]]:
    return [{"bucket": key, "label": _class_label(key), "target": value} for key, value in targets.items()]


def _planned_targets(
    store_targets: dict[str, float], targets: tuple[str, ...], removals: tuple[str, ...], clear_targets: bool
) -> dict[str, float]:
    """Validate every --target and --remove-target before anything is saved, so a rejected
    entry never changes the saved targets."""
    parsed = {} if clear_targets else dict(store_targets)
    valid = {c.value for c in AssetClass}
    for item in targets:
        key, _, value = item.partition("=")
        key = _class_key(key)
        if key not in valid:
            fail(f"Unknown asset class '{key}'. Choose from: {', '.join(sorted(valid))}")
        try:
            weight = float(value)
        except ValueError:
            fail(f"Target for {key} must be a number.")
        if not (math.isfinite(weight) and 0 <= weight <= 100):
            fail(f"Target for {key} must be between 0 and 100.")
        parsed[key] = weight
    for item in removals:
        key = _class_key(item)
        if key not in valid:
            fail(f"Unknown asset class '{key}'. Choose from: {', '.join(sorted(valid))}")
        if key not in parsed:
            fail(f"No target saved for {key}.")
        del parsed[key]
    return parsed


def _sorted_breakdown(rows: Sequence[Breakdown], sort_by: str | None, descending: bool) -> list[Breakdown]:
    out = list(rows)
    if sort_by == "value":
        out.sort(key=lambda b: (b.value, b.label.casefold()))
    elif sort_by == "weight":
        out.sort(key=lambda b: (b.weight, b.label.casefold()))
    elif sort_by == "name":
        out.sort(key=lambda b: b.label.casefold())
    return out[::-1] if descending else out


def _sorted_rebalance(rows: Sequence[RebalanceRow], sort_by: str | None, descending: bool) -> list[RebalanceRow]:
    out = list(rows)
    if sort_by == "value":
        out.sort(key=lambda r: (r.value, r.label.casefold()))
    elif sort_by == "weight":
        out.sort(key=lambda r: (r.weight, r.label.casefold()))
    elif sort_by == "name":
        out.sort(key=lambda r: r.label.casefold())
    return out[::-1] if descending else out


def _rebalance_dict(r: RebalanceRow) -> dict[str, Any]:
    return {
        "bucket": r.bucket,
        "label": r.label,
        "value": r.value,
        "weight": r.weight,
        "target": r.target,
        "drift": r.drift,
        "delta": r.delta,
    }


def _show_targets(app: App, as_json: bool) -> None:
    """Saved targets straight from the database: no quotes, no valuation, no snapshot."""
    saved = app.store.targets()
    total = sum(saved.values())
    if as_json:
        payload = {"targets": _target_rows(saved), "total": total, "unallocated": max(0.0, 100.0 - total)}
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if not saved:
        app.console.print(Text("No targets set. Add some with `marketpulse allocation --target CLASS=PCT`.", "muted"))
        return
    app.title("Allocation targets")
    table = render.table("Class", ("Target", "right"))
    for row in _target_rows(saved):
        table.add_row(Text(str(row["label"]), style="bright"), Text(fmt.pct(row["target"], sign=False)))
    app.console.print(table)
    app.console.print(
        Text(
            f"{fmt.pct(total, sign=False)} targeted · {fmt.pct(max(0.0, 100.0 - total), sign=False)} unallocated",
            style="muted",
        )
    )


@main.command()
@click.option("--by", type=click.Choice(["class", "account", "currency"]), default="class", show_default=True)
@click.option(
    "--target", "targets", multiple=True, metavar="CLASS=PCT", help="Set an asset-class target, e.g. --target etf=80."
)
@click.option("--clear-targets", is_flag=True, help="Remove all targets (with --target: replace them).")
@click.option("-q", "--quiet", is_flag=True, help="Only save targets; don't price holdings or show the allocation.")
@click.option(
    "--remove-target", "removals", multiple=True, metavar="CLASS", help="Remove one class's target; repeat for several."
)
@click.option("--dry-run", is_flag=True, help="Validate target changes and show what would be saved; write nothing.")
@click.option("--show-targets", is_flag=True, help="List saved targets without pricing holdings.")
@click.option("--json", "as_json", is_flag=True, help="Print the raw, unmasked allocation as JSON.")
@click.option("--csv", "as_csv", is_flag=True, help="Print raw, unmasked rows as CSV to stdout.")
@click.option("--count", "count_only", is_flag=True, help="Print only the number of rows that would be shown.")
@click.option("--sort", "sort_by", type=click.Choice(SORTS, case_sensitive=False), help="Order rows by this field.")
@click.option("--descending", is_flag=True, help="Reverse the row order.")
@click.option("--min-weight", type=float, callback=_percent, metavar="PCT", help="Hide breakdown rows below PCT%.")
@click.option("--drift-only", is_flag=True, help="Show only the rebalancing rows against your targets.")
@click.option(
    "--threshold", type=float, callback=_percent, metavar="PCT", help="Only rebalancing rows drifting more than PCT."
)
@click.option("--exit-code", is_flag=True, help="Exit 1 when any class drifts more than --threshold.")
@pass_app
def allocation(
    app: App,
    by: str,
    targets: tuple[str, ...],
    clear_targets: bool,
    quiet: bool,
    removals: tuple[str, ...],
    dry_run: bool,
    show_targets: bool,
    as_json: bool,
    as_csv: bool,
    count_only: bool,
    sort_by: str | None,
    descending: bool,
    min_weight: float | None,
    drift_only: bool,
    threshold: float | None,
    exit_code: bool,
) -> None:
    """Allocation breakdown and rebalancing against asset-class targets."""
    from ..analytics import rebalance

    ctx = click.get_current_context()
    changing = bool(targets or removals or clear_targets)
    outputs = as_json or as_csv or count_only
    view_options = bool(
        sort_by or descending or min_weight is not None or drift_only or threshold is not None or exit_code
    )
    by_given = ctx.get_parameter_source("by") is not ParameterSource.DEFAULT
    if (as_json and as_csv) or (count_only and (as_json or as_csv)):
        raise click.UsageError("Choose one output format; --count cannot be combined with --json or --csv.")
    if show_targets and (changing or quiet or dry_run or as_csv or count_only or view_options or by_given):
        raise click.UsageError("--show-targets only combines with --json.")
    if removals and clear_targets:
        raise click.UsageError("--remove-target cannot be combined with --clear-targets.")
    if dry_run and not changing:
        raise click.UsageError("--dry-run needs --target, --remove-target or --clear-targets.")
    if changing and outputs:
        raise click.UsageError("--json, --csv and --count can't be combined with target changes; save them first.")
    if dry_run and (view_options or by_given):
        raise click.UsageError("--dry-run only previews target changes; it doesn't show the allocation.")
    if {_class_key(t.partition("=")[0]) for t in targets} & {_class_key(r) for r in removals}:
        raise click.UsageError("Don't --target and --remove-target the same class.")
    if quiet and (outputs or view_options):
        raise click.UsageError("--quiet saves targets only; it can't be combined with output or view options.")
    if (drift_only or threshold is not None or exit_code) and by != "class":
        raise click.UsageError("Targets are by asset class; drift options need --by class.")
    if exit_code and threshold is None:
        raise click.UsageError("--exit-code needs --threshold PCT.")
    if min_weight is not None and drift_only:
        raise click.UsageError("--min-weight filters the breakdown; use --threshold with --drift-only.")

    store = app.store
    if show_targets:
        _show_targets(app, as_json)
        return
    if dry_run:
        planned = _planned_targets(store.targets(), targets, removals, clear_targets)
        total = sum(planned.values())
        if total > 100.0001:
            fail(f"Targets add up to {total:g}% — keep them at or under 100%.")
        if not planned:
            app.ok("Would clear all targets. Nothing saved (dry run).")
            return
        app.ok(f"Would save targets ({total:g}% allocated). Nothing saved (dry run).")
        for row in _target_rows(planned):
            app.console.print(Text(f"  {row['label']}: {row['target']:g}%", style="muted"))
        return
    if clear_targets and not targets:
        store.set_targets({})
        app.ok("Targets cleared.")
    if targets or removals:
        # Checked in full before anything is saved, so a rejected entry never clears the old targets.
        parsed = _planned_targets(store.targets(), targets, removals, clear_targets)
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
    current_targets = store.targets()
    rows = _sorted_breakdown(
        [b for b in breakdown if min_weight is None or b.weight >= min_weight], sort_by, descending
    )
    drift: list[RebalanceRow] = []
    if by == "class" and current_targets:
        drift = _sorted_rebalance(
            [
                r
                for r in rebalance(view.by_class, current_targets, view.net_worth)
                if threshold is None or abs(r.drift) > threshold
            ],
            sort_by,
            descending,
        )
    failing = exit_code and bool(drift)

    if count_only:
        click.echo(len(drift) if drift_only else len(rows))
    elif as_csv:
        if drift_only:
            _emit_csv(REBALANCE_FIELDS, [_rebalance_dict(r) for r in drift])
        else:
            _emit_csv(BREAKDOWN_FIELDS, [{f: getattr(b, f) for f in BREAKDOWN_FIELDS} for b in rows])
    elif as_json:
        rebalance_rows = [_rebalance_dict(r) for r in drift]
        payload: Any = (
            rebalance_rows
            if drift_only
            else {
                "by": by,
                "base": view.base,
                "total": view.net_worth,
                "rows": [{f: getattr(b, f) for f in BREAKDOWN_FIELDS} for b in rows],
                "rebalance": rebalance_rows,
            }
        )
        click.echo(json.dumps(payload, ensure_ascii=False))
    else:
        if not drift_only:
            app.title(f"Allocation by {by}")
            if breakdown and not rows:
                app.console.print(Text(f"No {by} weighs {min_weight:g}% or more.", style="muted"))
            else:
                app.console.print(
                    render.allocation(
                        rows,
                        app.palette,
                        width=min(app.console.width - 4, 80),
                        privacy=app.privacy,
                        base=view.base,
                        # Groups hidden by --min-weight keep their share of the bar, so it stays to scale.
                        hidden=sum(b.value for b in breakdown) - sum(b.value for b in rows),
                    )
                )
        if drift:
            if not drift_only:
                app.console.print()
            app.console.print(render.rebalance_table(drift, view.base, privacy=app.privacy))
        elif drift_only or threshold is not None:
            if not drift_only:
                app.console.print()
            if not current_targets:
                message = "No targets set. Add some with `marketpulse allocation --target CLASS=PCT`."
            else:
                message = f"No class drifts more than {threshold or 0:g}%."
            app.console.print(Text(message, style="muted"))
    if failing:
        raise click.exceptions.Exit(1)
