"""Recording transactions: trades, cash events, splits, return of capital and transfers.

Every command saves one ledger entry. The options added under #130 (previews, receipts,
checks and input shortcuts) are opt-in: without them a command prints and saves exactly
what it always has.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field, fields, replace
from datetime import date
from functools import wraps
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.text import Text
from rich.theme import Theme as RichTheme

from .. import fmt
from ..config import data_dir
from ..ledger import LedgerState, replay
from ..market import MarketError
from ..models import EPSILON, Account, Transaction, TxnType, parse_date
from ..requests import record_once
from ..themes import rich_styles
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


# ── Opt-in recording options (#130) ───────────────────────────────────────────

ALL = "all"


class _FloatOrAll(click.ParamType):
    """A number, or the word `all` (the whole position or cash balance)."""

    name = "float"

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> Any:
        if isinstance(value, str) and value.strip().lower() == ALL:
            return ALL
        return click.FLOAT.convert(value, param, ctx)


class _Ratio(click.ParamType):
    """A split ratio: a number (4, 0.1) or new:old shares (`3:1`, `1:10`, `2-for-1`, `3/2`)."""

    name = "float"
    _FORM = re.compile(r"\s*(\d+(?:\.\d+)?)\s*(?::|/|-?\s*for\s*-?)\s*(\d+(?:\.\d+)?)\s*", re.IGNORECASE)

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> Any:
        if isinstance(value, str) and (m := self._FORM.fullmatch(value)):
            new, old = float(m[1]), float(m[2])
            if new <= 0 or old <= 0:
                self.fail(f"{value!r} needs two positive share counts, e.g. 3:1.", param, ctx)
            return new / old
        return click.FLOAT.convert(value, param, ctx)


MAX = "max"
_PERCENT = re.compile(r"\s*(\d+(?:\.\d+)?)\s*%\s*")


class _Units(click.ParamType):
    """A number of units, `all`, a share of the units held (`50%`) or, for a buy, `max`.

    Words and percentages stay strings (`"all"`, `"max"`, `"50%"`) so a `--request-id`
    fingerprint can still be written as JSON; numbers convert exactly as before.
    """

    name = "float"

    def __init__(self, *, allow_max: bool = False, allow_all: bool = True) -> None:
        self.allow_max = allow_max
        self.allow_all = allow_all

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> Any:
        if isinstance(value, str):
            word = value.strip().lower()
            if self.allow_all and word == ALL:
                return ALL
            if self.allow_max and word == MAX:
                return MAX
            if not self.allow_max and (m := _PERCENT.fullmatch(value)):
                pct = float(m[1])
                if not 0 < pct <= 100:
                    self.fail(f"{value!r} must be a percentage above 0 and at most 100.", param, ctx)
                return f"{pct!r}%"
        return click.FLOAT.convert(value, param, ctx)


FLOAT_OR_ALL = _FloatOrAll()
RATIO = _Ratio()
BUY_UNITS = _Units(allow_max=True, allow_all=False)
HELD_UNITS = _Units()


@dataclass
class Extras:
    """The opt-in options of one recording command (all off means the classic behaviour)."""

    dry_run: bool = False
    json: bool = False
    quiet: bool = False
    balance: bool = False
    confirm: bool = False
    once: bool = False
    check: bool = False
    strict: bool = False
    total: float | None = None
    per_unit: bool = False
    receipt_file: str | None = None
    fee_pct: float | None = None
    net: float | None = None
    max_value: float | None = None
    keep: float | None = None
    withholding: float | None = None
    require_holding: bool = False
    leave: float | None = None
    reverse: bool = False

    @property
    def plain(self) -> bool:
        return not any(getattr(self, f.name) not in (False, None) for f in fields(self))

    @property
    def probes(self) -> bool:
        """Whether the entry is tried in a rolled-back transaction before (or instead of) saving."""
        return self.dry_run or self.strict or self.confirm


_META_KEY = "marketpulse.recording"

_FLAGS: list[tuple[str, str, str]] = [
    ("dry_run", "--dry-run", "Check the entry and show what it would do, without saving it."),
    ("json", "--json", "Print a JSON receipt of the saved entry and the position or cash after it."),
    ("quiet", "--quiet", "Print only the new entry's id."),
    ("balance", "--balance", "Show the account's cash balance after the entry."),
    ("confirm", "--confirm", "Show a preview and ask before saving."),
    ("once", "--once", "Skip the entry if an identical one is already recorded."),
    ("check", "--check", "Show warnings about the entry (they are always shown with --dry-run)."),
    ("strict", "--strict", "Refuse the entry when any warning applies (exit code 1)."),
]


def _percent_option(name: str, help: str):
    return click.option(name, type=float, default=None, metavar="PCT", help=help)


def _amount_option(name: str, help: str):
    return click.option(name, type=float, default=None, metavar="AMOUNT", help=help)


# Further opt-in options, chosen per command by name (items 1–11 of the 100 CLI/TUI batch).
_OPTIONAL: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "fee_pct": (
        "--fee-pct",
        _percent_option("--fee-pct", "Commission as a percentage of quantity × price, rounded to the cent."),
    ),
    "net": (
        "--net",
        _amount_option(
            "--net",
            "Net amount from the trade confirmation (a buy's cost or a sell's proceeds); "
            "the fees are the difference from quantity × price.",
        ),
    ),
    "max_value": (
        "--max-value",
        _amount_option("--max-value", "Refuse the trade when quantity × price is above AMOUNT (exit code 1)."),
    ),
    "keep": (
        "--keep",
        click.option(
            "--keep",
            type=float,
            default=None,
            metavar="UNITS",
            help="With QUANTITY `all`, keep this many units and sell the rest.",
        ),
    ),
    "withholding": (
        "--withholding",
        _percent_option(
            "--withholding", "AMOUNT is gross: record what's left after PCT foreign withholding tax (e.g. 15)."
        ),
    ),
    "require_holding": (
        "--require-holding",
        click.option(
            "--require-holding",
            is_flag=True,
            help="Refuse the entry unless the account holds SYMBOL at the end of the date.",
        ),
    ),
    "leave": (
        "--leave",
        _amount_option("--leave", "With AMOUNT `all`, leave this much cash in the account."),
    ),
    "reverse": (
        "--reverse",
        click.option(
            "--reverse",
            is_flag=True,
            help="RATIO is a consolidation: old shares per new share (`10` records ×0.1).",
        ),
    ),
}


def recording_extras(*, total: bool = False, per_unit: bool = False, extra: tuple[str, ...] = ()):
    """Add the opt-in options to a recording command.

    They are taken out of the arguments before `retryable` fingerprints the command, so a
    plain command's `--request-id` fingerprint is unchanged, and they're refused together.
    """

    def decorate(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            values = {name: kwargs.pop(name) for name, _, _ in _FLAGS}
            if total:
                values["total"] = kwargs.pop("total")
            if per_unit:
                values["per_unit"] = kwargs.pop("per_unit")
            values["receipt_file"] = kwargs.pop("receipt_file")
            for name in extra:
                values[name] = kwargs.pop(name)
            extras = Extras(**values)
            ctx = click.get_current_context()
            _check_combinations(extras, request_id=kwargs.get("request_id"))
            ctx.meta[_META_KEY] = extras
            if extras.json or extras.quiet:
                # Keep stdout to the receipt or id: warnings and spinners go to stderr.
                app = ctx.ensure_object(App)
                app.console = Console(theme=RichTheme(rich_styles(app.palette)), highlight=False, stderr=True)
            return f(*args, **kwargs)

        for name in reversed(extra):
            wrapper = _OPTIONAL[name][1](wrapper)
        wrapper = click.option(
            "--receipt-file",
            default=None,
            metavar="PATH",
            help="Also write the JSON receipt (saved, dry run or duplicate) to PATH.",
        )(wrapper)
        if per_unit:
            wrapper = click.option(
                "--per-unit",
                is_flag=True,
                help="AMOUNT is per unit: multiply it by the units held at the end of the date.",
            )(wrapper)
        if total:
            wrapper = click.option(
                "--total",
                type=float,
                default=None,
                help="Gross trade value (quantity × price, before fees); sets PRICE to TOTAL / QUANTITY.",
            )(wrapper)
        for name, flag, text in reversed(_FLAGS):
            wrapper = click.option(flag, name, is_flag=True, help=text)(wrapper)
        return wrapper

    return decorate


def _check_combinations(extras: Extras, *, request_id: object) -> None:
    def clash(a: str, b: str) -> None:
        raise click.UsageError(f"{a} can't be combined with {b}.")

    if extras.json and extras.quiet:
        clash("--json", "--quiet")
    if extras.confirm:
        for flag, on in (("--dry-run", extras.dry_run), ("--json", extras.json), ("--quiet", extras.quiet)):
            if on:
                clash("--confirm", flag)
    if extras.total is not None and not (extras.total > 0 and math.isfinite(extras.total)):
        raise click.BadParameter("must be a positive amount.", param_hint="'--total'")
    for name in ("net", "max_value"):
        value = getattr(extras, name)
        if value is not None and not (value > 0 and math.isfinite(value)):
            raise click.BadParameter("must be a positive amount.", param_hint=f"'{_OPTIONAL[name][0]}'")
    for name in ("keep", "leave"):
        value = getattr(extras, name)
        if value is not None and not (value >= 0 and math.isfinite(value)):
            raise click.BadParameter("must be zero or more.", param_hint=f"'{_OPTIONAL[name][0]}'")
    for name in ("fee_pct", "withholding"):
        value = getattr(extras, name)
        if value is not None and not (0 <= value < 100):
            raise click.BadParameter("must be a percentage from 0 to below 100.", param_hint=f"'{_OPTIONAL[name][0]}'")
    if extras.receipt_file is not None:
        target = Path(extras.receipt_file).expanduser()
        if not extras.receipt_file.strip() or target.is_dir() or not target.parent.is_dir():
            raise click.BadParameter("must be a file in an existing folder.", param_hint="'--receipt-file'")
        if _is_ledger_file(target):
            raise click.BadParameter("must not be the ledger database.", param_hint="'--receipt-file'")
    if request_id is not None and not extras.plain:
        given = [flag for name, flag, _ in _FLAGS if getattr(extras, name)]
        given += ["--total"] * (extras.total is not None) + ["--per-unit"] * extras.per_unit
        given += ["--receipt-file"] * (extras.receipt_file is not None)
        given += [flag for name, (flag, _) in _OPTIONAL.items() if getattr(extras, name) not in (False, None)]
        clash("--request-id", given[0])


def _is_ledger_file(target: Path) -> bool:
    """True when TARGET is the SQLite ledger or one of its sidecar files (also through links)."""
    ledger = data_dir(create=False) / "marketpulse.db"
    # SQLite keeps its sidecars beside the real file, so check both the configured path and a symlink's target.
    for base in {ledger, ledger.resolve()}:
        for suffix in ("", "-wal", "-shm", "-journal"):
            candidate = Path(f"{base}{suffix}")
            if target.resolve() == candidate.resolve():
                return True
            if target.exists() and candidate.exists() and os.path.samefile(target, candidate):
                return True
    return False


def _extras() -> Extras:
    ctx = click.get_current_context(silent=True)
    found = ctx.meta.get(_META_KEY) if ctx is not None else None
    return found if isinstance(found, Extras) else Extras()


def _account(app: App, ref: str | None) -> Account:
    """`app.account`, except that a preview (--dry-run, --confirm) never creates the first account."""
    store, default = app.store, app.config.default_account
    creates = not ref and not (default and store.get_account(default)) and not store.accounts()
    ex = _extras()
    if creates and (ex.dry_run or ex.confirm):
        fail("No accounts yet, and a preview doesn't create one. Add one with `marketpulse accounts add`.")
    return app.account(ref)


def _state_on(app: App, day: str) -> LedgerState:
    """The ledger at the end of `day` (every entry dated on or before it)."""
    return replay(app.store.transactions(), app.store.account_map(), until=day)


def _units_held(app: App, acct: Account, sym: str, day: str) -> float:
    h = _state_on(app, day).holdings.get((acct.saved_id, sym))
    if h is None or h.quantity <= EPSILON:
        fail(f"{acct.name} holds no {sym} on {day}.")
    return h.quantity


def _normalize(app: App, txn: Transaction) -> None:
    """Fill in what `Tracker.add_transaction` would: the currency and the ISO date."""
    try:
        txn.currency = app.tracker.transaction_currency(txn)
        txn.date = parse_date(txn.date)
    except ValueError as e:
        fail(str(e))


# Describes a saved (or tried) entry: its confirmation line and any follow-up warnings.
Describe = Callable[[Transaction], tuple[str, list[str]]]


@dataclass
class Caution:
    code: str
    message: str


@dataclass
class Outcome:
    txn: Transaction
    message: str
    notes: list[str]
    after: dict[str, Any]
    warnings: list[Caution]
    cash: list[tuple[Account, dict[str, float] | None]] = field(default_factory=list)


class _Rollback(Exception):
    """Raised inside a dry run's transaction so nothing it wrote is kept."""


def _position(state: LedgerState, account_id: int, symbol: str) -> dict[str, Any] | None:
    h = state.holdings.get((account_id, symbol))
    if h is None or h.quantity <= EPSILON:
        return None
    return {"quantity": h.quantity, "book": h.book, "avg_cost": h.avg_cost, "currency": h.currency}


def _cash(state: LedgerState, acct: Account) -> dict[str, float] | None:
    if not acct.track_cash:
        return None
    return {ccy: bal for (_, ccy), bal in sorted(state.cash_balances(acct.saved_id).items())}


def _warnings(app: App, txn: Transaction, accounts: list[Account], state: LedgerState) -> list[Caution]:
    """Checks that don't block an entry but often mean a typo (items 13–17)."""
    out: list[Caution] = []
    for acct in accounts:
        if acct.archived:
            out.append(Caution("archived_account", f"{acct.name} is archived, so this entry stays out of sight"))
    similar = [
        t.saved_id
        for t in app.store.transactions()
        if t.id != txn.id
        and (t.account_id, t.type, t.date, t.symbol, t.target_account_id)
        == (txn.account_id, txn.type, txn.date, txn.symbol, txn.target_account_id)
        and math.isclose(t.quantity, txn.quantity)
        and math.isclose(t.amount, txn.amount)
        and math.isclose(t.ratio, txn.ratio)
    ]
    if similar:
        ids = ", ".join(f"#{i}" for i in similar)
        out.append(
            Caution("possible_duplicate", f"a matching {txn.type.value} on {txn.date} is already recorded ({ids})")
        )
    day = date.fromisoformat(txn.date)
    if txn.type in (TxnType.BUY, TxnType.SELL) and day.weekday() >= 5:
        out.append(Caution("weekend", f"{txn.date} is a {day.strftime('%A')}, when markets are closed"))
    primary = accounts[0]
    if primary.track_cash and txn.cash_direction < 0:
        balance = state.cash.get((primary.saved_id, txn.currency), 0.0)
        if balance < -0.005:
            out.append(
                Caution(
                    "negative_cash",
                    f"cash in {primary.name} is now {fmt.money(balance, privacy=app.privacy)} {txn.currency}",
                )
            )
    recent = (date.today() - day).days <= 7
    if txn.type in (TxnType.BUY, TxnType.SELL, TxnType.DRIP) and txn.price > 0 and recent:
        q = app.store.cached_quotes([txn.symbol]).get(txn.symbol)
        if q is not None and q.price > 0 and q.currency.upper() == txn.currency and abs(txn.price / q.price - 1) > 0.5:
            out.append(
                Caution(
                    "price_far_from_quote",
                    f"price {fmt.price(txn.price)} {txn.currency} is far from the last known quote "
                    f"{fmt.price(q.price)} {txn.currency}",
                )
            )
    return out


def _outcome(app: App, txn: Transaction, accounts: list[Account], describe: Describe) -> Outcome:
    message, notes = describe(txn)
    state = app.store.ledger()
    realized = [r.gain for r in state.realized if r.txn_id is not None and r.txn_id == txn.id]
    after: dict[str, Any] = {
        "position": _position(state, txn.account_id, txn.symbol) if txn.symbol else None,
        "realized_gain": sum(realized) if realized else None,
        "cash": _cash(state, accounts[0]),
    }
    if txn.target_account_id is not None:
        after["target_position"] = _position(state, txn.target_account_id, txn.symbol)
    cash = [(a, _cash(state, a)) for a in accounts]
    return Outcome(txn, message, notes, after, _warnings(app, txn, accounts, state), cash)


def _probe(app: App, txn: Transaction, accounts: list[Account], describe: Describe) -> Outcome:
    """Run the real save, checks and description in a transaction that is then rolled back."""
    trial = replace(txn)
    _normalize(app, trial)  # may fetch a quote, so outside the write lock
    found: Outcome | None = None
    try:
        with app.store.transaction():
            try:
                saved = app.tracker.add_transaction(trial, restore_id=app.restore_id)
            except ValueError as e:
                fail(str(e))
            found = _outcome(app, saved, accounts, describe)
            raise _Rollback
    except _Rollback:
        pass
    assert found is not None
    found.txn = replace(found.txn, id=None)
    return found


def _receipt(app: App, out: Outcome, *, dry_run: bool, duplicate: bool = False) -> dict[str, Any]:
    t = out.txn
    accounts = app.store.account_map()

    def name(account_id: int | None) -> str | None:
        acct = accounts.get(account_id) if account_id is not None else None
        return acct.name if acct else None

    return {
        "recorded": not dry_run and not duplicate,
        "dry_run": dry_run,
        "duplicate": duplicate,
        "id": t.id,
        "type": t.type.value,
        "date": t.date,
        "account_id": t.account_id,
        "account": name(t.account_id),
        "symbol": t.symbol,
        "quantity": t.quantity,
        "price": t.price,
        "amount": t.amount,
        "fees": t.fees,
        "currency": t.currency,
        "ratio": t.ratio,
        "target_account_id": t.target_account_id,
        "target_account": name(t.target_account_id),
        "note": t.note,
        "message": out.message,
        "notes": out.notes,
        "warnings": [{"code": w.code, "message": w.message} for w in out.warnings],
        "after": out.after,
    }


def _show(app: App, out: Outcome, ex: Extras, *, dry_run: bool) -> None:
    if dry_run:
        app.console.print(Text("○ ", style="accent") + Text("Dry run, not saved: ", style="muted") + Text(out.message))
    else:
        app.ok(out.message)
    for note in out.notes:
        app.warn(note)
    if dry_run or ex.check:
        for w in out.warnings:
            app.warn(w.message)
    if ex.balance:
        for acct, balances in out.cash:
            if balances is None:
                app.console.print(Text(f"  {acct.name} doesn't track cash", style="muted"))
                continue
            shown = balances or {acct.currency: 0.0}
            for ccy, bal in shown.items():
                shown_bal = fmt.money(bal, privacy=app.privacy)
                app.console.print(Text(f"  cash in {acct.name}: {shown_bal} {ccy}", style="info"))


def _write_receipt(app: App, ex: Extras, receipt: dict[str, Any]) -> bool:
    """--receipt-file: keep a JSON copy of the receipt beside the usual output; False when the write failed."""
    if ex.receipt_file is None:
        return True
    try:
        Path(ex.receipt_file).expanduser().write_text(json.dumps(receipt, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as e:
        app.warn(f"couldn't write the receipt to {ex.receipt_file}: {e.strerror or e}")
        return False
    return True


def _exit_if_unwritten(written: bool) -> None:
    """A requested receipt that couldn't be written fails the command (after the usual output)."""
    if not written:
        click.get_current_context().exit(1)


def _report(app: App, out: Outcome, ex: Extras, *, dry_run: bool) -> None:
    written = _write_receipt(app, ex, _receipt(app, out, dry_run=dry_run))
    if ex.json:
        click.echo(json.dumps(_receipt(app, out, dry_run=dry_run), ensure_ascii=False))
    elif ex.quiet:
        if not dry_run:
            click.echo(str(out.txn.id))
        for note in out.notes:
            app.warn(note)
        if dry_run or ex.check:
            for w in out.warnings:
                app.warn(w.message)
    else:
        _show(app, out, ex, dry_run=dry_run)
    _exit_if_unwritten(written)


def _finish(app: App, txn: Transaction, accounts: list[Account], describe: Describe) -> None:
    """Save `txn` and report it, honouring the opt-in options; plain commands behave as always."""
    ex = _extras()
    if ex.plain:
        saved = record(app, txn)
        message, notes = describe(saved)
        app.ok(message)
        for note in notes:
            app.warn(note)
        return
    if ex.once:
        _normalize(app, txn)
        same = _same(app, txn)
        if same is not None:
            _report_duplicate(app, same, accounts, describe, ex)
            return
    if ex.probes:
        preview = _probe(app, txn, accounts, describe)
        if ex.strict and preview.warnings:
            fail("Not recorded (--strict): " + "; ".join(w.message for w in preview.warnings) + ".")
        if ex.dry_run:
            _report(app, preview, ex, dry_run=True)
            return
        if ex.confirm:
            _show(app, preview, replace(ex, balance=False), dry_run=True)
            if not click.confirm("Record it?", default=False):
                fail("Not recorded.")
    if not ex.once:
        saved = record(app, txn)
    else:
        # Checked again with the save under one write lock, so overlapping runs save it once.
        with app.store.atomic():
            same = _same(app, txn)
            if same is None:
                saved = record(app, txn)
        if same is not None:
            _report_duplicate(app, same, accounts, describe, ex)
            return
    _report(app, _outcome(app, saved, accounts, describe), ex, dry_run=False)


def _same(app: App, txn: Transaction) -> Transaction | None:
    """A saved entry identical to `txn` (apart from its id), for --once."""
    return next((t for t in app.store.transactions() if replace(t, id=None) == replace(txn, id=None)), None)


def _report_duplicate(app: App, same: Transaction, accounts: list[Account], describe: Describe, ex: Extras) -> None:
    if ex.json or ex.receipt_file is not None:
        existing = _outcome(app, same, accounts, describe)
        existing.message = f"Already recorded (#{same.id})."
        receipt = _receipt(app, existing, dry_run=False, duplicate=True)
        written = _write_receipt(app, ex, receipt)
    else:
        written = True
    if ex.json:
        click.echo(json.dumps(receipt, ensure_ascii=False))
    elif ex.quiet:
        click.echo(str(same.id))
    else:
        app.ok(f"Already recorded (#{same.id}); nothing saved.")
    _exit_if_unwritten(written)


# ── Commands ──────────────────────────────────────────────────────────────────


def _max_units(app: App, acct: Account, ccy: str, day: str, price: float, fees: float, fee_pct: float | None) -> float:
    """Buy QUANTITY `max`: the most whole units the account's cash covers, fees included."""
    if not acct.track_cash:
        fail(f"{acct.name} doesn't track cash, so QUANTITY `max` has no balance to spend.")
    if price <= 0:
        fail("QUANTITY `max` needs a positive PRICE.")
    cash = _state_on(app, day).cash.get((acct.saved_id, ccy), 0.0)

    def cost(units: int) -> float:
        paid = round(units * price * fee_pct / 100, 2) if fee_pct is not None else fees
        return units * price + paid

    def fits(units: int) -> bool:
        return cost(units) <= cash + 1e-9

    # Cost never falls as units grow, so binary-search the largest whole count the cash covers.
    low, high = 0, max(math.floor(cash / price), 0) + 1
    while low < high:
        mid = (low + high + 1) // 2
        if fits(mid):
            low = mid
        else:
            high = mid - 1
    units = low
    if units > 0 and fits(units + 1):  # beyond float precision: units no longer add up exactly
        fail(f"Couldn't work out how many units {fmt.money(cash)} {ccy} buys at {fmt.price(price)}; give QUANTITY.")
    if units < 1:
        fail(f"{fmt.money(cash)} {ccy} cash in {acct.name} on {day} doesn't cover one unit at {fmt.price(price)}.")
    return float(units)


def _trade(
    app: App,
    kind: TxnType,
    symbol: str,
    quantity: float | str,
    price: float | None,
    account: str | None,
    fees: float,
    when: str | None,
    currency: str,
    note: str,
) -> None:
    ex = _extras()
    if ex.keep is not None and quantity != ALL:
        raise click.UsageError("--keep needs QUANTITY `all`.")
    if ex.net is not None and (fees or ex.fee_pct is not None):
        raise click.UsageError("--net works out the fees; omit -f/--fees and --fee-pct.")
    if ex.fee_pct is not None and fees:
        raise click.UsageError("Give -f/--fees or --fee-pct, not both.")
    if quantity == MAX and (ex.total is not None or ex.net is not None):
        raise click.UsageError("QUANTITY `max` can't be combined with --total or --net.")
    acct = _account(app, account)
    sym = symbol.upper()
    ccy = currency.upper()
    day = when or date.today().isoformat()
    total = ex.total
    if quantity == ALL:
        quantity = _units_held(app, acct, sym, day)
        if ex.keep is not None:
            quantity -= ex.keep
            if quantity <= EPSILON:
                fail(
                    f"{acct.name} holds only {fmt.qty(quantity + ex.keep)} {sym} on {day}, so nothing is left to sell."
                )
    elif isinstance(quantity, str) and quantity.endswith("%"):
        quantity = _units_held(app, acct, sym, day) * float(quantity[:-1]) / 100
    if total is not None:
        assert isinstance(quantity, float)
        if price is not None:
            raise click.UsageError("Give PRICE or --total, not both.")
        if quantity <= 0:
            fail("Quantity must be positive.")
        price = total / quantity
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
    if quantity == MAX:
        quantity = _max_units(app, acct, ccy, day, price, fees, ex.fee_pct)
    assert isinstance(quantity, float)
    fee_detail = ""
    if ex.fee_pct is not None:
        fees = round(quantity * price * ex.fee_pct / 100, 2)
        fee_detail = f" (fees {fmt.money(fees)} {ccy})"
    if ex.net is not None:
        gross = quantity * price
        fees = ex.net - gross if kind is TxnType.BUY else gross - ex.net
        if abs(fees) < 1e-9:
            fees = 0.0
        if fees < 0:
            side = "below" if kind is TxnType.BUY else "above"
            fail(
                f"--net {fmt.money(ex.net)} is {side} quantity × price ({fmt.money(gross)}), "
                "so the fees can't be worked out."
            )
        fee_detail = f" (fees {fmt.money(fees)} {ccy})"
    if ex.max_value is not None and quantity * price > ex.max_value + 1e-9:
        fail(
            f"Not recorded: {fmt.qty(quantity)} × {fmt.price(price)} is {fmt.money(quantity * price)} {ccy}, "
            f"above --max-value {fmt.money(ex.max_value)}."
        )
    traded = quantity

    def describe(txn: Transaction) -> tuple[str, list[str]]:
        state = app.store.ledger()
        h = state.holdings.get((acct.saved_id, sym))
        verb = "Bought" if kind is TxnType.BUY else "Sold"
        msg = f"{verb} {fmt.qty(traded)} {sym} @ {fmt.price(txn.price)} {ccy} in {acct.name}{fee_detail}"
        if kind is TxnType.SELL:
            gain = next((r.gain for r in reversed(state.realized) if r.txn_id == txn.id), None)
            if gain is not None:
                msg += f" — realized {fmt.money(gain, sign=True)} {ccy}"
        if h and h.quantity > EPSILON:
            msg += f" · now {fmt.qty(h.quantity)} @ avg {fmt.price(h.avg_cost)}"
        elif kind is TxnType.SELL:
            msg += " · position closed"
        return msg, []

    txn = Transaction(
        account_id=acct.saved_id,
        type=kind,
        date=day,
        symbol=sym,
        quantity=quantity,
        price=price,
        fees=fees,
        currency=ccy,
        note=note,
    )
    _finish(app, txn, [acct], describe)


@main.command()
@click.argument("symbol")
@click.argument("quantity", type=BUY_UNITS)
@click.argument("price", type=float, required=False)
@click.option("-f", "--fees", type=float, default=0.0, help="Commission; added to cost base.")
@click.option("-c", "--currency", default="", help="Trade currency (default: the listing's).")
@recording_extras(total=True, extra=("fee_pct", "net", "max_value"))
@txn_options
@pass_app
def buy(app: App, symbol, quantity, price, fees, currency, account, when, note) -> None:
    """Record a buy. PRICE defaults to the live price.

    QUANTITY can be `max`: the most whole units the account's cash covers at PRICE,
    fees included (accounts that track cash only).
    """
    _trade(app, TxnType.BUY, symbol, quantity, price, account, fees, when, currency, note)


@main.command()
@click.argument("symbol")
@click.argument("quantity", type=HELD_UNITS)
@click.argument("price", type=float, required=False)
@click.option("-f", "--fees", type=float, default=0.0, help="Commission; deducted from proceeds.")
@click.option("-c", "--currency", default="", help="Trade currency (default: the listing's).")
@recording_extras(total=True, extra=("fee_pct", "net", "max_value", "keep"))
@txn_options
@pass_app
def sell(app: App, symbol, quantity, price, fees, currency, account, when, note) -> None:
    """Record a sell (average-cost ACB). PRICE defaults to the live price.

    QUANTITY can be `all`: every unit held in the account at the end of the date,
    or a percentage of them such as `50%`.
    """
    _trade(app, TxnType.SELL, symbol, quantity, price, account, fees, when, currency, note)


def _cash_event(
    app: App,
    kind: TxnType,
    amount: float | str,
    symbol: str,
    account: str | None,
    when: str | None,
    currency: str,
    note: str,
) -> None:
    ex = _extras()
    if ex.leave is not None and amount != ALL:
        raise click.UsageError("--leave needs AMOUNT `all`.")
    acct = _account(app, account)
    day = when or date.today().isoformat()
    sym = symbol.upper()
    detail = ""
    if ex.require_holding:
        _units_held(app, acct, sym, day)
    if amount == ALL:  # withdraw all
        if not acct.track_cash:
            fail(f"{acct.name} doesn't track cash, so there's no balance to withdraw.")
        ccy = currency.upper() or acct.currency
        balance = _state_on(app, day).cash.get((acct.saved_id, ccy), 0.0)
        if balance <= 0.005:
            fail(f"No {ccy} cash in {acct.name} on {day}.")
        amount = round(balance, 2)
        if ex.leave is not None:
            # Round down to the cent so the account keeps at least --leave.
            amount = math.floor((balance - ex.leave) * 100 + 1e-6) / 100
            if amount <= 0.005:
                fail(
                    f"{acct.name} has {fmt.money(balance)} {ccy} on {day}, not more than --leave {fmt.money(ex.leave)}."
                )
            detail = f" (leaving {fmt.money(ex.leave)} {ccy})"
    elif ex.per_unit:
        assert isinstance(amount, float)
        units = _units_held(app, acct, sym, day)
        detail = f" ({fmt.price(amount)} × {fmt.qty(units)} units)"
        amount = round(amount * units, 2)
    assert isinstance(amount, float)
    if ex.withholding is not None:
        gross = amount
        withheld = round(gross * ex.withholding / 100, 2)
        amount = round(gross - withheld, 2)
        if amount <= 0:
            fail("Nothing is left after --withholding.")
        detail += f" (gross {fmt.money(gross)} less {ex.withholding:g}% withheld: {fmt.money(withheld)})"
    txn = Transaction(
        account_id=acct.saved_id,
        type=kind,
        date=day,
        symbol=sym,
        amount=amount,
        currency=currency.upper(),
        note=note,
    )
    paid = amount

    def describe(saved: Transaction) -> tuple[str, list[str]]:
        target = f" from {saved.symbol}" if saved.symbol else ""
        return f"{kind.value.title()} {fmt.money(paid)} {saved.currency}{target} → {acct.name} on {day}{detail}", []

    _finish(app, txn, [acct], describe)


@main.command()
@click.argument("symbol")
@click.argument("amount", type=float)
@click.option("-c", "--currency", default="")
@recording_extras(per_unit=True, extra=("withholding", "require_holding"))
@txn_options
@pass_app
def dividend(app: App, symbol, amount, currency, account, when, note) -> None:
    """Record a cash dividend or distribution."""
    _cash_event(app, TxnType.DIVIDEND, amount, symbol, account, when, currency, note)


@main.command()
@click.argument("symbol")
@click.argument("quantity", type=float)
@click.argument("price", type=float, required=False, metavar="PRICE")
@click.option("-c", "--currency", default="", help="Currency of PRICE (default: the listing's).")
@recording_extras(total=True)
@txn_options
@pass_app
def drip(app: App, symbol, quantity, price, currency, account, when, note) -> None:
    """Record a reinvested dividend (new shares at PRICE)."""
    total = _extras().total
    if price is None and total is None:
        ctx = click.get_current_context()
        param = next(p for p in ctx.command.params if p.name == "price")
        raise click.MissingParameter(ctx=ctx, param=param)
    if total is not None:
        if price is not None:
            raise click.UsageError("Give PRICE or --total, not both.")
        if quantity <= 0:
            fail("Quantity must be positive.")
        price = total / quantity
    acct = _account(app, account)
    ccy = currency.upper() or app.tracker.resolve_currency(symbol, acct)[0]
    txn = Transaction(
        account_id=acct.saved_id,
        type=TxnType.DRIP,
        date=parse_date(when),
        symbol=symbol,
        quantity=quantity,
        price=price,
        currency=ccy,
        note=note,
    )
    message = f"DRIP {fmt.qty(quantity)} {symbol.upper()} @ {fmt.price(price)} {ccy} in {acct.name}"
    _finish(app, txn, [acct], lambda _: (message, []))


@main.command()
@click.argument("amount", type=float)
@click.option("-c", "--currency", default="")
@recording_extras()
@txn_options
@pass_app
def deposit(app: App, amount, currency, account, when, note) -> None:
    """Record money added to an account (counts as a contribution)."""
    _cash_event(app, TxnType.DEPOSIT, amount, "", account, when, currency, note)


@main.command()
@click.argument("amount", type=FLOAT_OR_ALL)
@click.option("-c", "--currency", default="")
@recording_extras(extra=("leave",))
@txn_options
@pass_app
def withdraw(app: App, amount, currency, account, when, note) -> None:
    """Record money taken out of an account.

    AMOUNT can be `all`: the account's whole cash balance at the end of the date
    (accounts that track cash only).
    """
    _cash_event(app, TxnType.WITHDRAWAL, amount, "", account, when, currency, note)


@main.command()
@click.argument("amount", type=float)
@click.option("-s", "--symbol", default="", help="Security paying the interest (optional).")
@click.option("-c", "--currency", default="")
@recording_extras()
@txn_options
@pass_app
def interest(app: App, amount, symbol, currency, account, when, note) -> None:
    """Record interest income."""
    _cash_event(app, TxnType.INTEREST, amount, symbol, account, when, currency, note)


@main.command()
@click.argument("amount", type=float)
@click.option("-c", "--currency", default="")
@recording_extras()
@txn_options
@pass_app
def fee(app: App, amount, currency, account, when, note) -> None:
    """Record an account-level fee."""
    _cash_event(app, TxnType.FEE, amount, "", account, when, currency, note)


@main.command()
@click.argument("symbol")
@click.argument("ratio", type=RATIO)
@recording_extras(extra=("reverse",))
@txn_options
@pass_app
def split(app: App, symbol, ratio, account, when, note) -> None:
    """Record a stock split (RATIO new shares per old share, e.g. 4 or 0.1).

    RATIO can also be written new:old, e.g. `3:1`, `1:10` or `2-for-1`.
    """
    acct = _account(app, account)
    if _extras().reverse:
        if ratio <= 0:
            fail("RATIO must be positive.")
        if ratio < 1:
            raise click.UsageError(
                f"RATIO {ratio:g} is already a consolidation; drop --reverse, "
                "or give the old shares per new one (e.g. 10)."
            )
        ratio = 1 / ratio
    txn = Transaction(
        account_id=acct.saved_id, type=TxnType.SPLIT, date=parse_date(when), symbol=symbol, ratio=ratio, note=note
    )
    message = f"Split {symbol.upper()} ×{ratio:g} in {acct.name}"
    _finish(app, txn, [acct], lambda _: (message, []))


def _roc_gain_note(app: App, txn: Transaction, sym: str, *, account_book_exceeded: bool) -> str | None:
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
            return None
        if d.complete:  # e.g. an unpriced transfer in leaves the cost base unknown
            return f"the pooled cost base of {sym} reached zero, so {fmt.money(d.gain)} {base} counts as a capital gain"
    if account_book_exceeded:
        return f"the cost base of {sym} here reached zero; `marketpulse tax` works out any capital gain"
    return None


@main.command()
@click.argument("symbol")
@click.argument("amount", type=float)
@click.option("-c", "--currency", default="", help="Currency of AMOUNT (default: the listing's).")
@recording_extras(per_unit=True)
@txn_options
@pass_app
def roc(app: App, symbol, amount, currency, account, when, note) -> None:
    """Record a return of capital: AMOUNT paid out that lowers the cost base.

    \b
    Funds and ETFs report it in box 42 of the T3 slip. Once the cost base
    reaches zero, the rest counts as a capital gain.
    """
    acct = _account(app, account)
    sym = symbol.upper()
    day = when or date.today().isoformat()
    detail = ""
    if _extras().per_unit:
        units = _units_held(app, acct, sym, day)
        detail = f" ({fmt.price(amount)} × {fmt.qty(units)} units)"
        amount = round(amount * units, 2)
    paid = amount

    def describe(saved: Transaction) -> tuple[str, list[str]]:
        state = app.store.ledger()
        msg = f"Return of capital {fmt.money(paid)} {saved.currency} on {sym} in {acct.name} on {day}{detail}"
        notes: list[str] = []
        h = state.holdings.get((acct.saved_id, sym))
        if h and h.quantity > EPSILON:
            msg += f" · cost base now {fmt.money(h.book)} {h.currency}"
        if not acct.type.registered:
            exceeded = any(r.txn_id == saved.id for r in state.realized)
            if gain_note := _roc_gain_note(app, saved, sym, account_book_exceeded=exceeded):
                notes.append(gain_note)
        if h is None or h.quantity <= EPSILON:
            notes.append(
                f"{acct.name} holds no {sym} now; a return of capital only lowers the cost of shares held on its date"
            )
        return msg, notes

    txn = Transaction(
        account_id=acct.saved_id,
        type=TxnType.ROC,
        date=day,
        symbol=sym,
        amount=amount,
        currency=currency.upper(),
        note=note,
    )
    _finish(app, txn, [acct], describe)


@main.command()
@click.argument("symbol")
@click.argument("amount", type=float)
@click.option("-c", "--currency", default="", help="Currency of AMOUNT (must match the holding).")
@recording_extras()
@txn_options
@pass_app
def acb_increase(app: App, symbol, amount, currency, account, when, note) -> None:
    """Increase a holding's cost base by AMOUNT without adding shares or cash."""
    acct = _account(app, account)
    txn = Transaction(
        account_id=acct.saved_id,
        type=TxnType.ACB_INCREASE,
        date=when or date.today().isoformat(),
        symbol=symbol,
        amount=amount,
        currency=currency,
        note=note,
    )

    def describe(saved: Transaction) -> tuple[str, list[str]]:
        return (
            f"ACB increase of {fmt.money(saved.amount)} {saved.currency} "
            f"for {saved.symbol} in {acct.name} on {saved.date}",
            [],
        )

    _finish(app, txn, [acct], describe)


@main.command()
@click.argument("symbol")
@click.argument("quantity", type=HELD_UNITS)
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
@recording_extras()
@retryable
@pass_app
def transfer(app: App, symbol, quantity, source, target, price, currency, when, note) -> None:
    """Move shares between accounts (e.g. in-kind to a TFSA).

    \b
    Holdings move at cost. For tax, a move from a taxable account into a
    registered one is a deemed sale at market value (a loss is denied), and
    a move out of a registered account resets the cost to market value, so
    give --price for those. QUANTITY can be `all`: every unit held in the
    source account at the end of the date, or a percentage of them (`50%`).
    """
    src, dst = _account(app, source), _account(app, target)
    day = parse_date(when)
    currency = currency.upper()
    if quantity == ALL:
        quantity = _units_held(app, src, symbol.upper(), day)
    elif isinstance(quantity, str):  # a percentage, e.g. "50%"
        quantity = _units_held(app, src, symbol.upper(), day) * float(quantity.rstrip("%")) / 100
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
    txn = Transaction(
        account_id=src.saved_id,
        type=TxnType.TRANSFER,
        date=day,
        symbol=symbol,
        quantity=quantity,
        price=price or 0.0,
        currency=currency,
        target_account_id=dst.id,
        note=note,
    )
    message = f"Transferred {fmt.qty(quantity)} {symbol.upper()} {src.name} → {dst.name}"
    _finish(app, txn, [src, dst], lambda _: (message, []))
