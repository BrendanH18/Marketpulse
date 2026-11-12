"""Non-market assets: GICs, bonds and manually valued holdings."""

from __future__ import annotations

import csv
import io
import json
import math
from collections import Counter
from dataclasses import fields

import click
from rich.text import Text

from .. import fmt, render
from ..models import Asset, AssetClass, AssetKind, Transaction, TxnType, parse_date
from ..requests import record_once
from .base import App, date_callback, fail, pass_app, retryable
from .recording import record
from .root import main

ASSET_FIELDS = tuple(field.name for field in fields(Asset))


def _asset_csv(rows: list[dict], field_names: tuple[str, ...]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=field_names)
    writer.writeheader()
    writer.writerows(rows)
    click.echo(stream.getvalue(), nl=False)


def _asset_summary(app: App, items: list[Asset], group: str, as_json: bool, as_csv: bool) -> None:
    def key(a: Asset) -> str:
        if group == "class":
            return a.asset_class.value if a.asset_class is not None else "(unclassified)"
        if group == "compounding":
            return a.compounding if a.kind is AssetKind.FIXED_INCOME else "(not applicable)"
        return a.kind.value if group == "kind" else a.currency.strip() or "(unspecified)"

    rows = [{"group": value, "count": count} for value, count in sorted(Counter(key(a) for a in items).items())]
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
    elif as_csv:
        _asset_csv(rows, ("group", "count"))
    else:
        table = render.table(group.title(), ("Assets", "right"), title="Matching asset metadata")
        for row in rows:
            table.add_row(Text(str(row["group"])), Text(str(row["count"])))
        app.console.print(table)


@main.group()
def asset() -> None:
    """GICs, bonds, real estate and other assets the market can't price."""


def _create_asset(app: App, asset: Asset, txn: Transaction, *, new_symbol: bool) -> None:
    def create() -> Transaction:
        # Includes archived accounts and symbols with no asset metadata. The write lock
        # keeps another CLI process from claiming the symbol between the check and save.
        if new_symbol and (asset.symbol in app.store.assets() or app.store.transactions(symbol=asset.symbol)):
            raise ValueError(f"{asset.symbol} is already in your ledger. Choose another symbol.")
        app.store.upsert_asset(asset)
        return app.tracker.add_transaction(txn, restore_id=app.restore_id)

    try:
        if app.request_id is not None:
            record_once(app.store, app.request_id, app.request_fingerprint, create)
        else:
            with app.store.atomic():
                create()
    except ValueError as error:
        fail(str(error))


@asset.command("list")
@click.option("--csv", "as_csv", is_flag=True, help="Print raw asset metadata as CSV, offline.")
@click.option("--count", "count_only", is_flag=True, help="Count all matches before pagination.")
@click.option("--page-info", is_flag=True, help="With --json, include pagination metadata.")
@click.option("--symbol", help="Match one configured symbol exactly, ignoring case.")
@click.option("--unclassified", is_flag=True, help="Only assets without an explicit asset class.")
@click.option("--json", "as_json", is_flag=True, help="Print unmasked asset metadata as JSON.")
@click.option("--kind", type=click.Choice([k.value for k in AssetKind], case_sensitive=False))
@click.option("--class", "asset_class", type=click.Choice([c.value for c in AssetClass], case_sensitive=False))
@click.option("--currency", help="Match the asset's configured currency, ignoring case.")
@click.option("--search", help="Find asset symbols or names containing this text, ignoring case.")
@click.option("--exclude-symbol", "excluded_symbols", multiple=True, help="Exclude exact symbols; repeat for several.")
@click.option("--min-rate", type=float, help="Minimum fixed-income annual rate in percent, inclusive.")
@click.option("--max-rate", type=float, help="Maximum fixed-income annual rate in percent, inclusive.")
@click.option("--starts-since", callback=date_callback, help="Fixed-income start date on or after this date.")
@click.option("--starts-until", callback=date_callback, help="Fixed-income start date on or before this date.")
@click.option("--matures-since", callback=date_callback, help="Fixed-income maturity on or after this date.")
@click.option("--matures-until", callback=date_callback, help="Fixed-income maturity on or before this date.")
@click.option(
    "--compounding",
    type=click.Choice(["annual", "semiannual", "quarterly", "monthly", "simple"], case_sensitive=False),
    help="Match a fixed-income compounding schedule.",
)
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(
        ["symbol", "name", "kind", "currency", "rate", "maturity-date", "start-date", "class", "compounding"]
    ),
)
@click.option("--descending", is_flag=True, help="Reverse the selected order (default: stored order).")
@click.option("--limit", type=click.IntRange(min=1), help="Show at most this many matching assets.")
@click.option("--offset", type=click.IntRange(min=0), default=0, help="Skip this many matching assets.")
@click.option("--symbols", multiple=True, help="Include exact symbols, ignoring case; repeat for several.")
@click.option("--exclude-currency", "excluded_currencies", multiple=True, help="Exclude configured currencies; repeat.")
@click.option(
    "--exclude-kind",
    "excluded_kinds",
    multiple=True,
    type=click.Choice([k.value for k in AssetKind], case_sensitive=False),
    help="Exclude configured asset kinds; repeat.",
)
@click.option(
    "--exclude-class",
    "excluded_classes",
    multiple=True,
    type=click.Choice([c.value for c in AssetClass], case_sensitive=False),
    help="Exclude explicit asset classes; repeat.",
)
@click.option("--name", help="Match text only in the configured name, ignoring case.")
@click.option("--symbol-prefix", help="Match a symbol prefix, ignoring case.")
@click.option("--symbol-suffix", help="Match a symbol suffix, ignoring case.")
@click.option("--has-name/--no-name", default=None, help="Match metadata with or without a nonblank name.")
@click.option(
    "--has-currency/--no-currency", default=None, help="Match metadata with or without a configured currency."
)
@click.option("--classified", is_flag=True, help="Only assets with an explicit asset class.")
@click.option(
    "--has-start-date/--no-start-date", default=None, help="Match metadata with or without a saved start date."
)
@click.option(
    "--has-maturity-date/--no-maturity-date",
    default=None,
    help="Match metadata with or without a saved maturity date.",
)
@click.option(
    "--summary", type=click.Choice(["kind", "currency", "class", "compounding"]), help="Count matches by metadata."
)
@click.option("--symbols-only", is_flag=True, help="Print matching symbols one per line for scripts.")
@click.option(
    "--fields",
    "selected_fields",
    multiple=True,
    type=click.Choice(ASSET_FIELDS),
    help="Select JSON/CSV fields; repeat.",
)
@pass_app
def asset_list(
    app: App,
    as_json: bool,
    as_csv: bool,
    count_only: bool,
    page_info: bool,
    symbol: str | None,
    unclassified: bool,
    kind: str | None,
    asset_class: str | None,
    currency: str | None,
    search: str | None,
    sort_by: str | None,
    descending: bool,
    limit: int | None,
    offset: int,
    excluded_symbols: tuple[str, ...],
    min_rate: float | None,
    max_rate: float | None,
    starts_since: str | None,
    starts_until: str | None,
    matures_since: str | None,
    matures_until: str | None,
    compounding: str | None,
    symbols: tuple[str, ...],
    excluded_currencies: tuple[str, ...],
    excluded_kinds: tuple[str, ...],
    excluded_classes: tuple[str, ...],
    name: str | None,
    symbol_prefix: str | None,
    symbol_suffix: str | None,
    has_name: bool | None,
    has_currency: bool | None,
    classified: bool,
    has_start_date: bool | None,
    has_maturity_date: bool | None,
    summary: str | None,
    symbols_only: bool,
    selected_fields: tuple[str, ...],
) -> None:
    """List configured asset metadata without fetching prices."""
    if sum((as_json, as_csv, count_only, symbols_only)) > 1:
        raise click.UsageError("Choose one of --json, --csv, --count, or --symbols-only.")
    if page_info and not as_json:
        raise click.UsageError("--page-info requires --json.")
    if classified and unclassified:
        raise click.UsageError("Choose one of --classified or --unclassified.")
    if summary and (
        count_only
        or symbols_only
        or page_info
        or limit is not None
        or offset
        or sort_by
        or descending
        or selected_fields
    ):
        raise click.UsageError(
            "--summary cannot combine with counting, symbol output, projection, ordering or pagination."
        )
    if selected_fields and not (as_json or as_csv):
        raise click.UsageError("--fields requires --json or --csv.")
    included_symbols = {value.strip().upper() for value in symbols}
    omitted_currencies = {value.strip().upper() for value in excluded_currencies}
    for option, values in (("--symbols", included_symbols), ("--exclude-currency", omitted_currencies)):
        if "" in values:
            raise click.UsageError(f"{option} cannot be blank.")
    for option, text_value in (
        ("--name", name),
        ("--symbol-prefix", symbol_prefix),
        ("--symbol-suffix", symbol_suffix),
    ):
        if text_value is not None and not text_value.strip():
            raise click.UsageError(f"{option} cannot be blank.")
    excluded = {value.strip().upper() for value in excluded_symbols}
    if "" in excluded:
        raise click.UsageError("--exclude-symbol cannot be blank.")
    for option, value in (("--min-rate", min_rate), ("--max-rate", max_rate)):
        if value is not None and not math.isfinite(value):
            raise click.BadParameter("must be finite", param_hint=option)
    if min_rate is not None and max_rate is not None and min_rate > max_rate:
        raise click.UsageError("--min-rate must be at or below --max-rate.")
    for lower, upper, label in ((starts_since, starts_until, "starts"), (matures_since, matures_until, "matures")):
        if lower and upper and lower > upper:
            raise click.UsageError(f"--{label}-since must be on or before --{label}-until.")
    items = [a for a in app.store.assets().values() if a.symbol not in excluded]
    fixed_filters = any(
        value is not None
        for value in (min_rate, max_rate, starts_since, starts_until, matures_since, matures_until, compounding)
    )
    if fixed_filters:
        items = [
            a
            for a in items
            if a.kind is AssetKind.FIXED_INCOME
            and (min_rate is None or math.isfinite(a.rate) and a.rate >= min_rate)
            and (max_rate is None or math.isfinite(a.rate) and a.rate <= max_rate)
            and (not starts_since or bool(a.start_date) and a.start_date >= starts_since)
            and (not starts_until or bool(a.start_date) and a.start_date <= starts_until)
            and (not matures_since or bool(a.maturity_date) and a.maturity_date >= matures_since)
            and (not matures_until or bool(a.maturity_date) and a.maturity_date <= matures_until)
            and (compounding is None or a.compounding == compounding)
        ]
    filtered = any(value is not None for value in (kind, asset_class, currency, search, limit)) or offset > 0
    filtered = filtered or symbol is not None or unclassified or bool(excluded) or fixed_filters
    filtered = filtered or bool(symbols or excluded_currencies or excluded_kinds or excluded_classes or classified)
    filtered = filtered or any(
        value is not None
        for value in (name, symbol_prefix, symbol_suffix, has_name, has_currency, has_start_date, has_maturity_date)
    )
    items = [
        a
        for a in items
        if (not included_symbols or a.symbol in included_symbols)
        and a.currency.strip().upper() not in omitted_currencies
        and a.kind.value not in excluded_kinds
        and (a.asset_class is None or a.asset_class.value not in excluded_classes)
        and (name is None or name.strip().casefold() in a.name.casefold())
        and (symbol_prefix is None or a.symbol.casefold().startswith(symbol_prefix.strip().casefold()))
        and (symbol_suffix is None or a.symbol.casefold().endswith(symbol_suffix.strip().casefold()))
        and (has_name is None or bool(a.name.strip()) == has_name)
        and (has_currency is None or bool(a.currency.strip()) == has_currency)
        and (not classified or a.asset_class is not None)
        and (has_start_date is None or bool(a.start_date.strip()) == has_start_date)
        and (has_maturity_date is None or bool(a.maturity_date.strip()) == has_maturity_date)
    ]
    if symbol is not None:
        items = [a for a in items if a.symbol == symbol.strip().upper()]
    if unclassified:
        items = [a for a in items if a.asset_class is None]
    if kind is not None:
        items = [a for a in items if a.kind.value == kind]
    if asset_class is not None:
        items = [a for a in items if a.asset_class is not None and a.asset_class.value == asset_class]
    if currency is not None:
        items = [a for a in items if a.currency == currency.strip().upper()]
    if search is not None:
        items = [a for a in items if search.casefold() in a.symbol.casefold() or search.casefold() in a.name.casefold()]
    if summary:
        _asset_summary(app, items, summary, as_json, as_csv)
        return
    if sort_by in ("rate", "maturity-date", "start-date", "compounding", "class"):
        field_name = {"class": "asset_class"}.get(sort_by, sort_by.replace("-", "_"))
        known = [
            a
            for a in items
            if (a.asset_class is not None if sort_by == "class" else a.kind is AssetKind.FIXED_INCOME)
            and (math.isfinite(a.rate) if sort_by == "rate" else bool(getattr(a, field_name)))
        ]
        unknown = [a for a in items if a not in known]
        known.sort(key=lambda a: (getattr(a, field_name), a.symbol), reverse=descending)
        unknown.sort(key=lambda a: a.symbol, reverse=descending)
        items = known + unknown
    else:
        if sort_by is not None:
            items.sort(key=lambda a: (str(getattr(a, sort_by)).casefold(), a.symbol))
        if descending:
            items.reverse()
    total = len(items)
    if count_only:
        click.echo(total)
        return
    items = items[offset:] if limit is None else items[offset : offset + limit]
    if symbols_only:
        for item in items:
            click.echo(item.symbol)
        return
    field_names = tuple(dict.fromkeys(selected_fields)) or ASSET_FIELDS
    if as_csv:
        _asset_csv([{field: getattr(a, field) for field in field_names} for a in items], field_names)
        return
    if as_json:
        rows = [{field: getattr(a, field) for field in field_names} for a in items]
        payload = (
            {
                "total": total,
                "offset": offset,
                "limit": limit,
                "returned": len(rows),
                "next_offset": offset + len(rows) if offset + len(rows) < total else None,
                "items": rows,
            }
            if page_info
            else rows
        )
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if not items:
        message = "No assets match these filters." if filtered else "No custom assets. Market symbols need no setup."
        app.console.print(Text(message, style="muted"))
        return
    t = render.table("Symbol", "Kind", "Name", "Class", "Ccy", ("Rate", "right"), "Term")
    for a in items:
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


@asset.command("show")
@click.argument("symbol")
@click.option("--json", "as_json", is_flag=True, help="Print unmasked asset metadata as JSON.")
@click.option("--csv", "as_csv", is_flag=True, help="Print raw metadata as a one-row CSV.")
@click.option(
    "--fields",
    "selected_fields",
    multiple=True,
    type=click.Choice(ASSET_FIELDS),
    help="Select displayed fields; repeat.",
)
@click.option("--value", "value_field", type=click.Choice(ASSET_FIELDS), help="Print one raw field value for scripts.")
@click.option("--exists", is_flag=True, help="Print nothing; exit 0 if configured, 1 otherwise.")
@pass_app
def asset_show(
    app: App,
    symbol: str,
    as_json: bool,
    as_csv: bool,
    selected_fields: tuple[str, ...],
    value_field: str | None,
    exists: bool,
) -> None:
    """Inspect a configured asset without fetching prices or creating metadata."""
    if sum((as_json, as_csv, value_field is not None, exists)) > 1:
        raise click.UsageError("Choose one of --json, --csv, --value or --exists.")
    if selected_fields and (value_field is not None or exists):
        raise click.UsageError("--fields cannot combine with --value or --exists.")
    definition = app.store.assets().get(symbol.strip().upper())
    if exists:
        raise click.exceptions.Exit(0 if definition is not None else 1)
    if definition is None:
        fail(f"No configured asset '{symbol}'.")
    field_names = tuple(dict.fromkeys(selected_fields)) or ASSET_FIELDS
    payload = {field: getattr(definition, field) for field in field_names}
    if value_field is not None:
        value = getattr(definition, value_field)
        click.echo("" if value is None else str(value))
        return
    if as_csv:
        _asset_csv([payload], field_names)
        return
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    table = render.table("Field", "Value", title="Asset metadata")
    for field, value in payload.items():
        shown = fmt.MASK if app.privacy and field == "rate" else "—" if value is None else str(value)
        table.add_row(Text(field), Text(shown))
    app.console.print(table)


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
@click.option(
    "--new-symbol", is_flag=True, help="Refuse symbols used anywhere in the ledger, including archived accounts."
)
@retryable
@pass_app
def asset_fixed(
    app: App, symbol, principal, rate, start, maturity, compounding, name, currency, account, new_symbol
) -> None:
    """Add a GIC / term deposit / bond held to maturity, valued by accrual."""
    acct = app.account(account)
    start_d, maturity_d = parse_date(start), parse_date(maturity)
    ccy = (currency or acct.currency).upper()
    _create_asset(
        app,
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
        ),
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
        new_symbol=new_symbol,
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
@click.option(
    "--new-symbol", is_flag=True, help="Refuse symbols used anywhere in the ledger, including archived accounts."
)
@retryable
@pass_app
def asset_manual(app: App, symbol, value, name, asset_class, currency, account, when, new_symbol) -> None:
    """Add a manually valued asset (property, private shares, collectibles, pension…)."""
    acct = app.account(account)
    ccy = (currency or acct.currency).upper()
    _create_asset(
        app,
        Asset(
            symbol=symbol,
            kind=AssetKind.MANUAL,
            name=name or symbol.upper(),
            asset_class=AssetClass(asset_class),
            currency=ccy,
        ),
        Transaction(
            account_id=acct.saved_id,
            type=TxnType.BUY,
            date=parse_date(when),
            symbol=symbol,
            quantity=1,
            price=value,
            currency=ccy,
        ),
        new_symbol=new_symbol,
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
