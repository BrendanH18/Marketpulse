"""Non-market assets: GICs, bonds and manually valued holdings."""

from __future__ import annotations

import click
from rich.text import Text

from .. import fmt, render
from ..models import Asset, AssetClass, AssetKind, Transaction, TxnType, parse_date
from .base import App, date_callback, fail, pass_app, retryable
from .recording import record
from .root import main


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
@click.option("--start", default=None, callback=date_callback, help="Start date (default today).")
@click.option("--maturity", required=True, callback=date_callback, help="Maturity date.")
@click.option(
    "--compounding",
    type=click.Choice(["annual", "semiannual", "quarterly", "monthly", "simple"]),
    default="annual",
    show_default=True,
)
@click.option("--name", default="")
@click.option("-c", "--currency", default=None)
@click.option("-a", "--account", default=None)
@retryable
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
    record(
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
@click.option("-d", "--date", "when", default=None, callback=date_callback, help="Acquisition date.")
@retryable
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
    record(
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
@click.option("-d", "--date", "when", default=None, callback=date_callback)
@retryable
@pass_app
def asset_value(app: App, symbol, value, when) -> None:
    """Record a new valuation for a manual asset (per unit)."""
    sym = symbol.upper()
    holders = [h for h in app.store.ledger().open_holdings() if h.symbol == sym]
    if not holders:
        fail(f"No holding of {sym}.")
    record(
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
