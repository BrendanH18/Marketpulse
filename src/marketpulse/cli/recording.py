"""Recording transactions: trades, cash events, splits, return of capital and transfers."""

from __future__ import annotations

from datetime import date

import click

from .. import fmt
from ..market import MarketError
from ..models import EPSILON, Transaction, TxnType, parse_date
from ..requests import record_once
from .base import App, date_callback, fail, pass_app, retryable, txn_options
from .root import main


def record(app: App, txn: Transaction) -> Transaction:
    try:
        if app.request_id is not None:
            return record_once(
                app.store,
                app.request_id,
                app.request_fingerprint,
                lambda: app.tracker.add_transaction(txn, restore_id=app.restore_id),
            )
        return app.tracker.add_transaction(txn, restore_id=app.restore_id)
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
    txn = record(
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
    record(app, txn)
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
@click.option("-c", "--currency", default="", help="Currency of PRICE (default: the listing's).")
@txn_options
@pass_app
def drip(app: App, symbol, quantity, price, currency, account, when, note) -> None:
    """Record a reinvested dividend (new shares at PRICE)."""
    acct = app.account(account)
    ccy = currency.upper() or app.tracker.resolve_currency(symbol, acct)[0]
    record(
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
    record(
        app,
        Transaction(
            account_id=acct.saved_id, type=TxnType.SPLIT, date=parse_date(when), symbol=symbol, ratio=ratio, note=note
        ),
    )
    app.ok(f"Split {symbol.upper()} ×{ratio:g} in {acct.name}")


def _warn_roc_gain(app: App, txn: Transaction, sym: str, *, account_book_exceeded: bool) -> None:
    """Say whether a return of capital creates a capital gain, from the tax engine.

    Tax pools the cost base across every taxable account, so this account's book
    value alone can't tell. Only base-currency rates are known offline, so the
    figure is exact only when every taxable entry for the symbol is in the base
    currency (a missing rate can reach the cost base indirectly, e.g. through a
    superficial loss). Otherwise point to `marketpulse tax` instead of guessing,
    and only when this account's cost base ran out, to stay quiet.
    """
    from .. import tax
    from ..ledger import transaction_currency

    base = app.tracker.base
    txns = app.store.transactions()
    accounts = app.store.account_map()
    exact = all(
        transaction_currency(t, accounts).upper() == base
        for t in txns
        if t.symbol == sym
        and (
            tax.is_taxable(accounts.get(t.account_id))
            or (t.target_account_id is not None and tax.is_taxable(accounts.get(t.target_account_id)))
        )
    )
    if exact:
        report = tax.compute(txns, accounts, tax.fx_lookup({}, base))
        d = next((d for d in report.dispositions if d.txn_id == txn.id and d.kind == "roc"), None)
        if d is None:
            return
        if d.complete:  # e.g. an unpriced transfer in leaves the cost base unknown
            app.warn(
                f"the pooled cost base of {sym} reached zero, so {fmt.money(d.gain)} {base} counts as a capital gain"
            )
            return
    if account_book_exceeded:
        app.warn(f"the cost base of {sym} here reached zero; `marketpulse tax` works out any capital gain")


@main.command()
@click.argument("symbol")
@click.argument("amount", type=float)
@click.option("-c", "--currency", default="", help="Currency of AMOUNT (default: the listing's).")
@txn_options
@pass_app
def roc(app: App, symbol, amount, currency, account, when, note) -> None:
    """Record a return of capital: AMOUNT paid out that lowers the cost base.

    \b
    Funds and ETFs report it in box 42 of the T3 slip. Once the cost base
    reaches zero, the rest counts as a capital gain.
    """
    acct = app.account(account)
    sym = symbol.upper()
    day = when or date.today().isoformat()
    txn = record(
        app,
        Transaction(
            account_id=acct.saved_id,
            type=TxnType.ROC,
            date=day,
            symbol=sym,
            amount=amount,
            currency=currency.upper(),
            note=note,
        ),
    )
    state = app.store.ledger()
    msg = f"Return of capital {fmt.money(amount)} {txn.currency} on {sym} in {acct.name} on {day}"
    h = state.holdings.get((acct.saved_id, sym))
    if h and h.quantity > EPSILON:
        msg += f" · cost base now {fmt.money(h.book)} {h.currency}"
    app.ok(msg)
    if not acct.type.registered:
        _warn_roc_gain(app, txn, sym, account_book_exceeded=any(r.txn_id == txn.id for r in state.realized))
    if h is None or h.quantity <= EPSILON:
        app.warn(f"{acct.name} holds no {sym} now; a return of capital only lowers the cost of shares held on its date")


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
@click.option("-c", "--currency", default="", help="Currency of --price (default: the listing's).")
@click.option("-d", "--date", "when", default=None, callback=date_callback)
@click.option("-m", "--note", default="")
@retryable
@pass_app
def transfer(app: App, symbol, quantity, source, target, price, currency, when, note) -> None:
    """Move shares between accounts (e.g. in-kind to a TFSA).

    \b
    Holdings move at cost. For tax, a move from a taxable account into a
    registered one is a deemed sale at market value (a loss is denied), and
    a move out of a registered account resets the cost to market value, so
    give --price for those.
    """
    src, dst = app.account(source), app.account(target)
    day = parse_date(when)
    currency = currency.upper()
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
    record(
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
