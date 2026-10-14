"""CSV import/export of the transaction ledger.

The importer maps common broker column names (Wealthsimple, Questrade, IBKR
and generic exports use variations of these) onto MarketPulse transactions.
Anything it can't interpret is skipped with a reason rather than guessed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, TextIO

from .models import Account, AccountType, Transaction, TxnType, guess_currency, parse_date

if TYPE_CHECKING:
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

_ALIASES = {
    "date": ["date", "trade date", "transaction date", "settlement date", "process date", "activity date", "tradedate"],
    "type": ["type", "action", "transaction type", "activity type", "activity", "transaction", "buy/sell"],
    "symbol": ["symbol", "ticker", "security", "instrument", "stock symbol"],
    "quantity": ["quantity", "qty", "shares", "units", "no. of shares"],
    "price": ["price", "unit price", "price per share", "trade price", "t. price"],
    "amount": ["amount", "net amount", "value", "total", "net cash", "proceeds", "gross amount", "market value"],
    "fees": ["fees", "fee", "commission", "commissions", "comm/fee", "comm in usd"],
    "currency": ["currency", "ccy", "curr"],
    "account": ["account", "account name", "account type", "account #", "account number"],
    "note": ["note", "notes", "description", "memo", "details"],
    "ratio": ["ratio", "split ratio"],
    "target_account": ["target_account", "target account", "to account"],
}

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
class ImportResult:
    added: int = 0
    duplicates: int = 0
    skipped: list[tuple[int, str]] = field(default_factory=list)
    accounts_created: list[str] = field(default_factory=list)
    backup: Path | None = None  # pre-import snapshot of the database (None on a dry run)
    fingerprint: str = ""  # the import's inputs; pass to `expect_fingerprint` to commit exactly a preview


def _norm(header: str) -> str:
    return re.sub(r"\s+", " ", header.strip().lower().replace("_", " "))


def map_headers(headers: list[str]) -> dict[str, str]:
    """Map MarketPulse field names onto the CSV's actual column headers."""
    normalized = {_norm(h): h for h in headers}
    mapping = {}
    for field_name, aliases in _ALIASES.items():
        for alias in aliases:
            if _norm(alias) in normalized:
                mapping[field_name] = normalized[_norm(alias)]
                break
    return mapping


def _number(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = raw.strip().replace(",", "").replace("$", "").replace("€", "").replace("£", "")
    if not s or s in {"-", "—"}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


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


def import_transactions(
    store: Store,
    source: Path | str | TextIO,
    *,
    default_account: Account | None = None,
    create_accounts: bool = True,
    dry_run: bool = False,
    expect_fingerprint: str | None = None,
) -> ImportResult:
    """Import (or preview) CSV rows. A commit given `expect_fingerprint` from its preview
    refuses to write anything if the file or the ledger changed in between."""
    text = Path(source).read_text(encoding="utf-8-sig") if isinstance(source, Path | str) else source.read()
    fingerprint = import_fingerprint(store, text, default_account, create_accounts)
    if not dry_run:
        if expect_fingerprint is not None and expect_fingerprint != fingerprint:
            raise ValueError("The ledger or the file changed since the preview. Preview the import again.")
        result = _import(store, text, default_account=default_account, create_accounts=create_accounts, backup=True)
        result.fingerprint = fingerprint
        return result
    # A preview runs the real import against a throwaway copy of the ledger, so its
    # counts, new accounts and skipped lines are exactly what the import will produce.
    from .db import Store

    with TemporaryDirectory(prefix="marketpulse-preview-") as tmp:
        scratch = Store(store.backup(dest=Path(tmp) / "preview.db"))
        try:
            result = _import(
                scratch, text, default_account=default_account, create_accounts=create_accounts, backup=False
            )
        finally:
            scratch.close()
    result.fingerprint = fingerprint
    return result


def import_fingerprint(store: Store, text: str, default_account: Account | None, create_accounts: bool) -> str:
    """Everything an import's outcome depends on: the file, the options, and the ledger."""
    inputs = {
        "csv": text,
        "default_account": default_account.id if default_account else None,
        "create_accounts": create_accounts,
        "accounts": [asdict(a) for a in store.accounts(include_archived=True)],
        "transactions": [asdict(t) for t in store.transactions()],
    }
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()


def _import(
    store: Store, text: str, *, default_account: Account | None, create_accounts: bool, backup: bool
) -> ImportResult:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")
    cols = map_headers(list(reader.fieldnames))
    missing = [f for f in ("date", "type") if f not in cols]
    if missing:
        raise ValueError(
            f"CSV is missing required column(s): {', '.join(missing)}. Found: {', '.join(reader.fieldnames)}"
        )

    result = ImportResult()
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

    def get(row: dict, name: str) -> str:
        col = cols.get(name)
        return (row.get(col) or "").strip() if col else ""

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

    for line_no, row in enumerate(reader, start=2):
        txn_type = parse_type(get(row, "type"))
        if txn_type is None:
            result.skipped.append((line_no, f"unrecognized type '{get(row, 'type')}'"))
            continue
        try:
            when = parse_date(get(row, "date")[:10] if re.match(r"\d{4}", get(row, "date")) else get(row, "date"))
        except ValueError as e:
            result.skipped.append((line_no, str(e)))
            continue
        acct = resolve_account(get(row, "account"))
        if acct is None or acct.id is None:
            result.skipped.append(
                (line_no, f"unknown account '{get(row, 'account')}'" if get(row, "account") else "no account")
            )
            continue
        # Archived accounts are closed to new entries; their rows would vanish from view.
        if acct.archived:
            result.skipped.append((line_no, f"account '{acct.name}' is archived"))
            continue
        symbol = get(row, "symbol").upper()
        qty = abs(_number(get(row, "quantity")) or 0.0)
        price = abs(_number(get(row, "price")) or 0.0)
        amount = abs(_number(get(row, "amount")) or 0.0)
        fees = abs(_number(get(row, "fees")) or 0.0)
        if txn_type in (TxnType.BUY, TxnType.SELL) and not price and qty and amount:
            price = amount / qty
        if txn_type.uses_amount and not amount and qty and price:
            amount = qty * price
        # Only transfers have a destination; other rows never create one.
        target_name = get(row, "target_account") if txn_type is TxnType.TRANSFER else ""
        target = resolve_account(target_name) if target_name else None
        if target is not None and target.archived:
            result.skipped.append((line_no, f"account '{target.name}' is archived"))
            continue
        txn = Transaction(
            account_id=acct.id,
            type=txn_type,
            date=when,
            symbol=symbol,
            quantity=qty,
            price=price,
            amount=amount,
            fees=fees,
            currency=get(row, "currency").upper()
            or (guess_currency(symbol, acct.currency) if symbol else acct.currency),
            note=get(row, "note"),
            ratio=_number(get(row, "ratio")) or 0.0,
            target_account_id=target.id if target else None,
        )
        try:
            txn.validate()
            if txn_type.uses_amount and txn.amount <= 0:
                raise ValueError(f"{txn_type.value} row has no amount")
        except ValueError as e:
            result.skipped.append((line_no, str(e)))
            continue
        k = key(txn)
        if existing[k] > 0:
            existing[k] -= 1
            result.duplicates += 1
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
