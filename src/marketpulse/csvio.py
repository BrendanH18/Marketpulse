"""CSV import/export of the transaction ledger.

The importer reads a file through a broker profile (`brokers.py`): a named one for
exports it recognizes (Questrade, Wealthsimple), or the generic one, which maps common
column names onto MarketPulse transactions. Anything it can't interpret is skipped
with the line, the field and a reason rather than guessed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, TextIO

from . import brokers
from .analytics import disposition_note
from .brokers import RowError, map_headers, parse_number
from .models import Account, AccountType, Transaction, TxnType, guess_currency, parse_date

if TYPE_CHECKING:
    from .analytics import TaxYear
    from .db import Store

EXPORT_COLUMNS = [
    "date",
    "account",
    "type",
    "symbol",
    "quantity",
    "price",
    "amount",
    "fees",
    "currency",
    "note",
    "ratio",
    "target_account",
]

_TYPE_KEYWORDS = [
    (("reinvest", "drip"), TxnType.DRIP),
    (("return of capital", "roc"), TxnType.ROC),
    (("dividend", "distribution", "div"), TxnType.DIVIDEND),
    (("interest", "int"), TxnType.INTEREST),
    (("deposit", "contribution", "cont", "eft in", "transfer in cash"), TxnType.DEPOSIT),
    (("withdraw", "wd", "eft out"), TxnType.WITHDRAWAL),
    (("split",), TxnType.SPLIT),
    (("fee", "commission charge"), TxnType.FEE),
    (("valuation", "mark"), TxnType.VALUATION),
    (("transfer",), TxnType.TRANSFER),
    (("buy", "bought", "purchase"), TxnType.BUY),
    (("sell", "sold", "sale"), TxnType.SELL),
]


@dataclass
class RowIssue:
    """A skipped line: which field was at fault (empty if no single one), its value, and why."""

    line: int
    field: str
    value: str
    reason: str


@dataclass
class DuplicateRow:
    """A line matching a transaction already in the ledger, so it was left out."""

    line: int
    summary: str


@dataclass
class ImportResult:
    added: int = 0
    duplicates: int = 0
    skipped: list[tuple[int, str]] = field(default_factory=list)  # (line, reason); `issues` has the detail
    accounts_created: list[str] = field(default_factory=list)
    backup: Path | None = None  # pre-import snapshot of the database (None on a dry run)
    fingerprint: str = ""  # the import's inputs; pass to `expect_fingerprint` to commit exactly a preview
    profile: str = brokers.GENERIC.name  # the broker profile that read the file
    profile_label: str = brokers.GENERIC.label
    issues: list[RowIssue] = field(default_factory=list)  # one per skipped line, in the same order
    duplicate_rows: list[DuplicateRow] = field(default_factory=list)


# Which field a `Transaction.validate()` message is about.
_VALIDATION_FIELDS = [
    ("symbol", "symbol"),
    ("quantity", "quantity"),
    ("price", "price"),
    ("amount", "amount"),
    ("fees", "fees"),
    ("split ratio", "ratio"),
    ("transfer", "target_account"),
    ("date", "date"),
]


def _validation_field(message: str) -> str:
    lowered = message.lower()
    return next((f for word, f in _VALIDATION_FIELDS if word in lowered), "")


def parse_type(raw: str) -> TxnType | None:
    s = raw.strip().lower()
    if not s:
        return None
    try:
        return TxnType(s.upper())
    except ValueError:
        pass
    words = set(re.split(r"[^a-z]+", s))
    for keywords, txn_type in _TYPE_KEYWORDS:
        for kw in keywords:
            # short codes must match a whole word; longer ones may prefix one ("reinvest" → "reinvestment")
            if (" " in kw and kw in s) or kw in words or (len(kw) >= 4 and any(w.startswith(kw) for w in words)):
                return txn_type
    return None


def export_transactions(store: Store, out: TextIO) -> int:
    accounts = store.account_map()
    writer = csv.writer(out)
    writer.writerow(EXPORT_COLUMNS)
    n = 0
    for t in store.transactions():
        target = accounts.get(t.target_account_id) if t.target_account_id else None
        writer.writerow(
            [
                t.date,
                accounts[t.account_id].name if t.account_id in accounts else t.account_id,
                t.type.value,
                t.symbol,
                f"{t.quantity:g}" if t.quantity else "",
                f"{t.price:g}" if t.price else "",
                f"{t.amount:g}" if t.amount else "",
                f"{t.fees:g}" if t.fees else "",
                t.currency,
                t.note,
                f"{t.ratio:g}" if t.ratio else "",
                target.name if target else "",
            ]
        )
        n += 1
    return n


DISPOSITION_KINDS = {
    "sale": "Sale",
    "roc": "Return of capital above ACB",
    "deemed": "Transfer in kind to a registered account",
}


def _plain(value: float) -> str:
    """A number as written, never in exponent form a spreadsheet would misread: 1234567, 0.00000000125."""
    text = format(Decimal(str(value)), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def export_capital_gains(
    years: Sequence[TaxYear], accounts: dict[int, Account], base: str, out: TextIO, *, year: int | None = None
) -> int:
    """Write every disposition (one year's, or all) as CSV for an accountant. Amounts are in
    `base`, as `marketpulse tax` reports them. A row missing an FX rate keeps its date, units
    and note but no amounts, because they aren't known."""
    writer = csv.writer(out)
    writer.writerow(
        [
            "Tax year",
            "Date",
            "Account",
            "Account type",
            "Symbol",
            "Quantity",
            "Trading currency",
            f"FX rate to {base}",
            f"Proceeds ({base})",
            f"ACB ({base})",
            f"Gain or loss ({base})",
            f"Denied loss ({base})",
            f"Reported gain or loss ({base})",
            "Type",
            "Note",
        ]
    )
    n = 0
    for y in sorted(years, key=lambda y: y.year):
        if year is not None and y.year != year:
            continue
        for r in y.rows:
            acct = accounts.get(r.account_id)
            amounts = (
                [f"{v:.2f}" for v in (r.proceeds, r.acb, r.gain, r.denied, r.allowed_gain)] if r.complete else [""] * 5
            )
            writer.writerow(
                [
                    y.year,
                    r.date,
                    acct.name if acct else r.account_id,
                    acct.type.value if acct else "",
                    r.symbol,
                    _plain(r.quantity) if r.quantity else "",
                    r.currency,
                    f"{r.fx:.6f}" if r.fx is not None else "",
                    *amounts,
                    DISPOSITION_KINDS.get(r.kind, r.kind),
                    disposition_note(r),
                ]
            )
            n += 1
    return n


def import_transactions(
    store: Store,
    source: Path | str | TextIO,
    *,
    default_account: Account | None = None,
    create_accounts: bool = True,
    dry_run: bool = False,
    expect_fingerprint: str | None = None,
    profile: str = "auto",
) -> ImportResult:
    """Import (or preview) CSV rows. A commit given `expect_fingerprint` from its preview
    refuses to write anything if the file or the ledger changed in between. `profile` names
    a broker profile from `brokers.PROFILES`; "auto" picks one from the header row."""
    text = Path(source).read_text(encoding="utf-8-sig") if isinstance(source, Path | str) else source.read()
    if not dry_run:
        # One transaction from the check to the last write: no other process can change the
        # ledger in between, and a failure leaves no half-import (or new accounts) behind.
        with store.transaction():
            default_account = _reread(store, default_account)
            fingerprint = import_fingerprint(store, text, default_account, create_accounts, profile)
            if expect_fingerprint is not None and expect_fingerprint != fingerprint:
                raise ValueError("The ledger or the file changed since the preview. Preview the import again.")
            result = _import(
                store,
                text,
                default_account=default_account,
                create_accounts=create_accounts,
                profile=profile,
                backup=True,
            )
        result.fingerprint = fingerprint
        return result
    # A preview runs the real import against a throwaway copy of the ledger, so its
    # counts, new accounts and skipped lines are exactly what the import will produce.
    from .db import Store

    with TemporaryDirectory(prefix="marketpulse-preview-") as tmp:
        scratch = Store(store.backup(dest=Path(tmp) / "preview.db"))
        try:
            # Use the exact copy the preview runs on, not the live ledger (or the caller's
            # account object) as it was a moment earlier.
            default_account = _reread(scratch, default_account)
            fingerprint = import_fingerprint(scratch, text, default_account, create_accounts, profile)
            result = _import(
                scratch,
                text,
                default_account=default_account,
                create_accounts=create_accounts,
                profile=profile,
                backup=False,
            )
        finally:
            scratch.close()
    result.fingerprint = fingerprint
    return result


def _reread(store: Store, account: Account | None) -> Account | None:
    """The default account as `store` has it now; it may have changed (e.g. been archived)."""
    if account is None:
        return None
    current = store.get_account(account.saved_id)
    if current is None:
        raise ValueError("The selected account no longer exists.")
    return current


def import_fingerprint(
    store: Store, text: str, default_account: Account | None, create_accounts: bool, profile: str = "auto"
) -> str:
    """Everything an import's outcome depends on: the file, the options, the ledger, and the
    day (dates in the future are rejected, so a preview from yesterday may no longer hold)."""
    inputs = {
        "today": date.today().isoformat(),
        "csv": text,
        "profile": profile,
        "default_account": default_account.id if default_account else None,
        "create_accounts": create_accounts,
        "accounts": [asdict(a) for a in store.accounts(include_archived=True)],
        "transactions": [asdict(t) for t in store.transactions()],
    }
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()


def read_headers(text: str) -> list[str]:
    return next(csv.reader(io.StringIO(text)), [])


def _row_reader(profile: brokers.BrokerProfile, headers: list[str]) -> Callable[[dict], dict[str, str]]:
    """A function from one CSV row to the importer's canonical fields."""
    convert = profile.convert
    if convert is None:
        cols = map_headers(headers)
        missing = [f for f in ("date", "type") if f not in cols]
        if missing:
            raise ValueError(f"CSV is missing required column(s): {', '.join(missing)}. Found: {', '.join(headers)}")
        return lambda row: {name: (row.get(col) or "").strip() for name, col in cols.items()}
    # Short rows leave None values and long ones a None key; profiles see normalized headers.
    return lambda row: convert({brokers.norm(k): v or "" for k, v in row.items() if isinstance(k, str)})


def _summary(txn: Transaction, account: str) -> str:
    """One line describing a transaction, for duplicate reports."""
    if txn.type.uses_quantity:
        what = f"{txn.quantity:g} {txn.symbol} @ {txn.price:g}"
    elif txn.type.uses_amount:
        what = f"{txn.symbol} {txn.amount:,.2f}".strip()
    else:
        what = txn.symbol
    return f"{txn.date} {txn.type.value} {what} {txn.currency} · {account}"


def _import(
    store: Store, text: str, *, default_account: Account | None, create_accounts: bool, profile: str, backup: bool
) -> ImportResult:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")
    broker = brokers.resolve(profile, list(reader.fieldnames))
    fields_of = _row_reader(broker, list(reader.fieldnames))

    result = ImportResult(profile=broker.name, profile_label=broker.label)
    if backup:
        # An import can add hundreds of rows (and new accounts) in one go, and
        # a mis-mapped CSV is easy to do. Snapshot the ledger first so the
        # whole import can be reverted by restoring this one file. Taken before
        # the loop because resolve_account() may already write.
        result.backup = store.backup(reason="import")

    def key(t: Transaction) -> tuple:
        return (t.account_id, t.date, t.type, t.symbol, round(t.quantity, 6), round(t.price, 6), round(t.amount, 2))

    # A multiset: each file row consumes one matching stored row, so re-importing the
    # same export is a no-op while genuine repeated fills (two identical partial
    # executions on one day) are all kept.
    existing = Counter(key(t) for t in store.transactions())
    pending: list[Transaction] = []
    created: list[Account] = []

    def resolve_account(name: str) -> Account | None:
        if not name:
            return default_account
        acct = store.get_account(name)
        if acct is None and create_accounts:
            guessed = next((t for t in AccountType if t.value.lower() in name.lower()), AccountType.NONREG)
            acct = store.add_account(
                Account(name=name, type=guessed, currency=default_account.currency if default_account else "CAD")
            )
            created.append(acct)
        return acct

    def magnitude(fields: dict[str, str], name: str) -> float:
        # Brokers sign quantities and amounts by direction; the type already says which way.
        return abs(parse_number(fields.get(name), name) or 0.0)

    def build(fields: dict[str, str]) -> tuple[Transaction, Account]:
        def get(name: str) -> str:
            return (fields.get(name) or "").strip()

        txn_type = parse_type(get("type"))
        if txn_type is None:
            raise RowError(f"unrecognized type '{get('type')}'", "type", get("type"))
        raw_date = get("date")
        try:
            when = parse_date(raw_date[:10] if re.match(r"\d{4}", raw_date) else raw_date)
        except ValueError as e:
            raise RowError(str(e), "date", raw_date) from None
        acct = resolve_account(get("account"))
        if acct is None or acct.id is None:
            raise RowError(
                f"unknown account '{get('account')}'" if get("account") else "no account", "account", get("account")
            )
        # Archived accounts are closed to new entries; their rows would vanish from view.
        if acct.archived:
            raise RowError(f"account '{acct.name}' is archived", "account", get("account"))
        symbol = get("symbol").upper()
        qty, price, cash, fees = (magnitude(fields, f) for f in ("quantity", "price", "amount", "fees"))
        ratio = parse_number(get("ratio"), "ratio") or 0.0
        if txn_type in (TxnType.BUY, TxnType.SELL) and not price and qty and cash:
            price = cash / qty
        if txn_type.uses_amount and not cash and qty and price:
            cash = qty * price
        # Only transfers have a destination; other rows never create one.
        target_name = get("target_account") if txn_type is TxnType.TRANSFER else ""
        target = resolve_account(target_name) if target_name else None
        if target is not None and target.archived:
            raise RowError(f"account '{target.name}' is archived", "target_account", target_name)
        txn = Transaction(
            account_id=acct.id,
            type=txn_type,
            date=when,
            symbol=symbol,
            quantity=qty,
            price=price,
            amount=cash,
            fees=fees,
            currency=get("currency").upper() or (guess_currency(symbol, acct.currency) if symbol else acct.currency),
            note=get("note"),
            ratio=ratio,
            target_account_id=target.id if target else None,
        )
        try:
            txn.validate()
            if txn_type.uses_amount and txn.amount <= 0:
                raise RowError(f"{txn_type.value} row has no amount", "amount", get("amount"))
        except RowError:
            raise
        except ValueError as e:
            name = _validation_field(str(e))
            raise RowError(str(e), name, get(name) if name else "") from None
        return txn, acct

    for line_no, row in enumerate(reader, start=2):
        try:
            txn, acct = build(fields_of(row))
        except RowError as e:
            result.skipped.append((line_no, e.reason))
            result.issues.append(RowIssue(line_no, e.field, e.value, e.reason))
            continue
        k = key(txn)
        if existing[k] > 0:
            existing[k] -= 1
            result.duplicates += 1
            result.duplicate_rows.append(DuplicateRow(line_no, _summary(txn, acct.name)))
            continue
        pending.append(txn)

    # An account created only for rows that were then skipped would be left empty.
    used = {t.account_id for t in pending} | {t.target_account_id for t in pending}
    for acct in created:
        if acct.id in used:
            result.accounts_created.append(acct.name)
        else:
            store.delete_account(acct.saved_id)
    if pending:
        store.add_transactions(pending)
    result.added = len(pending)
    return result
