"""Identical property: symbols listing the same units, pooled into one ACB pool for tax."""

from __future__ import annotations

import json

import click
from rich.text import Text

from .. import render
from .base import App, fail, pass_app
from .taxes import tax


def _symbol(value: str, hint: str) -> str:
    sym = value.strip().upper()
    if not sym:
        raise click.BadParameter("cannot be blank.", param_hint=hint)
    return sym


@tax.command("link")
@click.argument("symbol")
@click.argument("pool")
@click.option("--dry-run", is_flag=True, help="Check the link without saving it.")
@click.option("--json", "as_json", is_flag=True, help="Print a JSON receipt; supports --dry-run.")
@pass_app
def tax_link(app: App, symbol: str, pool: str, dry_run: bool, as_json: bool) -> None:
    """Pool SYMBOL with POOL as identical property: one adjusted cost base for both.

    \b
    Use it for the same units listed twice, such as a fund's CAD and USD lines
    (DLR.TO and DLR-U.TO) or a share listed in Toronto and New York. Units of
    either count one for one, and buying either within 30 days of a loss on the
    other can make the loss superficial. T1135 shows the pool under POOL and
    uses POOL's foreign property setting. Don't link merely similar securities."""
    sym, target = _symbol(symbol, "SYMBOL"), _symbol(pool, "POOL")
    try:
        app.store.link_identical(sym, target, dry_run=dry_run)
    except ValueError as error:
        fail(str(error))
    if as_json:
        click.echo(json.dumps({"symbol": sym, "pool": target, "saved": not dry_run}, ensure_ascii=False))
    elif dry_run:
        app.ok(f"Would pool {sym} with {target} (not saved).")
    else:
        app.ok(f"{sym} now shares {target}'s cost base. `marketpulse tax` uses the combined pool.")


@tax.command("unlink")
@click.argument("symbol")
@click.option("--dry-run", is_flag=True, help="Preview without saving.")
@click.option("--json", "as_json", is_flag=True, help="Print a JSON receipt; supports --dry-run.")
@pass_app
def tax_unlink(app: App, symbol: str, dry_run: bool, as_json: bool) -> None:
    """Give SYMBOL its own cost base again, undoing `tax link`."""
    sym = _symbol(symbol, "SYMBOL")
    left = app.store.unlink_identical(sym, dry_run=dry_run)
    if left is None:
        fail(f"{sym} isn't linked to another symbol. `marketpulse tax links` lists the links.")
    if as_json:
        click.echo(json.dumps({"symbol": sym, "pool": left, "saved": not dry_run}, ensure_ascii=False))
        return
    app.ok(f"Would give {sym} its own cost base (not saved)." if dry_run else f"{sym} has its own cost base again.")


@tax.command("links")
@click.option("--json", "as_json", is_flag=True, help="Print the links as JSON.")
@pass_app
def tax_links(app: App, as_json: bool) -> None:
    """List symbols pooled with another symbol as identical property."""
    links = sorted(app.store.identical_property().items(), key=lambda item: (item[1], item[0]))
    if as_json:
        click.echo(json.dumps([{"symbol": s, "pool": p} for s, p in links], ensure_ascii=False))
        return
    if not links:
        app.console.print(
            Text("No linked symbols. `marketpulse tax link SYMBOL POOL` pools identical property.", style="muted")
        )
        return
    table = render.table("Symbol", "Shares the cost base of", title="Identical property")
    for sym, pool in links:
        table.add_row(Text(sym), Text(pool))
    app.console.print(table)
