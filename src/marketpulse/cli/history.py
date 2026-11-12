"""The transaction ledger: list it, undo the latest entry, edit or delete one."""

from __future__ import annotations

import csv
import io
import json
import math
from collections import Counter
from dataclasses import asdict, fields, replace
from datetime import date

import click
from rich.text import Text

from .. import fmt, render
from ..ledger import replay, sort_key
from ..models import Account, AccountType, Transaction, TxnType
from .base import App, date_callback, fail, pass_app
from .root import main


def _finite_value(ctx: click.Context, param: click.Parameter, value: float | None) -> float | None:
    if value is not None and not math.isfinite(value):
        raise click.BadParameter("must be finite", ctx=ctx, param=param)
    return value


def _excluded_dates(ctx: click.Context, param: click.Parameter, values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(date_callback(ctx, param, value)) for value in values)


@main.command()
@click.option("-a", "--account", default=None)
@click.option("-s", "--symbol", default=None)
@click.option("-n", "--limit", type=click.IntRange(min=1), default=40, show_default=True)
@click.option("--all", "show_all", is_flag=True)
@click.option("--since", callback=date_callback, help="Include transactions on or after this date.")
@click.option("--until", callback=date_callback, help="Include transactions on or before this date.")
@click.option("--type", "types", multiple=True, type=click.Choice([t.value for t in TxnType], case_sensitive=False))
@click.option("--search", default="", help="Find text in the symbol, note, or account name (case-insensitive).")
@click.option("--currency", help="Include only transactions recorded in this currency.")
@click.option("--oldest-first", is_flag=True, help="Show oldest entries first.")
@click.option("--offset", type=click.IntRange(min=0), default=0, help="Skip this many matching entries.")
@click.option("--json", "as_json", is_flag=True, help="Print raw, unmasked transaction records as JSON.")
@click.option("--csv", "as_csv", is_flag=True, help="Print raw, unmasked transaction CSV to stdout.")
@click.option("--count", "count_only", is_flag=True, help="Count all matching entries before pagination.")
@click.option(
    "--summary",
    type=click.Choice(
        [
            "type",
            "account",
            "currency",
            "month",
            "symbol",
            "year",
            "day",
            "weekday",
            "institution",
            "quarter",
            "account-type",
        ]
    ),
    help="Count all matching entries by this field before pagination; supports --json or --csv.",
)
@click.option("--has-note/--no-note", default=None, help="Match entries with or without a nonblank note.")
@click.option("--min-id", type=click.IntRange(min=1), help="Include transaction IDs at or above this value.")
@click.option("--max-id", type=click.IntRange(min=1), help="Include transaction IDs at or below this value.")
@click.option(
    "--exclude-type",
    "excluded_types",
    multiple=True,
    type=click.Choice([t.value for t in TxnType], case_sensitive=False),
)
@click.option("--exclude-symbol", "excluded_symbols", multiple=True, help="Exclude a symbol; repeat for several.")
@click.option("--note", help="Find text only in transaction notes (case-insensitive).")
@click.option("--year", type=click.IntRange(min=1, max=9999), help="Include only this calendar year.")
@click.option("--on", "on_date", callback=date_callback, help="Include only this date.")
@click.option(
    "--summary-sort",
    type=click.Choice(["group", "count"]),
    default="group",
    help="Sort summaries by group or descending count.",
)
@click.option("--page-info", is_flag=True, help="With --json, wrap transactions with pagination metadata.")
@click.option("--symbols", multiple=True, help="Include any of these exact symbols; repeat for several.")
@click.option("--exclude-account", "excluded_accounts", multiple=True, help="Exclude either end of these accounts.")
@click.option("--account-type", type=click.Choice([a.value for a in AccountType], case_sensitive=False))
@click.option("--institution", help="Match the source account's institution exactly, ignoring case.")
@click.option("--has-symbol/--no-symbol", default=None, help="Match entries with or without a symbol.")
@click.option("--target-account", help="Match this transfer destination by ID, name or unique account type.")
@click.option("--quarter", type=click.IntRange(min=1, max=4), help="Include only this calendar quarter.")
@click.option("--weekday", type=click.Choice(["mon", "tue", "wed", "thu", "fri", "sat", "sun"], case_sensitive=False))
@click.option("--month", type=click.IntRange(min=1, max=12), help="Include only this calendar month in any year.")
@click.option(
    "--exclude-currency", "excluded_currencies", multiple=True, help="Exclude a currency; repeat for several."
)
@click.option(
    "--exclude-date",
    "excluded_dates",
    multiple=True,
    callback=_excluded_dates,
    help="Exclude a date; repeat for several.",
)
@click.option(
    "--min-amount",
    type=float,
    callback=_finite_value,
    help="Minimum recorded amount, inclusive (not trade consideration).",
)
@click.option(
    "--max-amount",
    type=float,
    callback=_finite_value,
    help="Maximum recorded amount, inclusive (not trade consideration).",
)
@click.option("--min-fees", type=float, callback=_finite_value, help="Minimum recorded fees, inclusive.")
@click.option("--max-fees", type=float, callback=_finite_value, help="Maximum recorded fees, inclusive.")
@click.option("--has-fees/--no-fees", default=None, help="Match entries with nonzero or zero recorded fees.")
@click.option("--min-quantity", type=float, callback=_finite_value, help="Inclusive minimum recorded quantity.")
@click.option("--max-quantity", type=float, callback=_finite_value, help="Inclusive maximum recorded quantity.")
@click.option("--min-price", type=float, callback=_finite_value, help="Inclusive minimum recorded unit price.")
@click.option("--max-price", type=float, callback=_finite_value, help="Inclusive maximum recorded unit price.")
@click.option("--exclude-note", help="Exclude notes containing this text, ignoring case.")
@click.option("--symbol-prefix", help="Match a symbol prefix, ignoring case.")
@click.option("--account-search", help="Find text only in source account names, ignoring case.")
@click.option("--id", "included_ids", multiple=True, type=click.IntRange(min=1), help="Include exact IDs; repeat.")
@click.option("--exclude-id", "excluded_ids", multiple=True, type=click.IntRange(min=1), help="Exclude IDs; repeat.")
@click.option("--has-target/--no-target", default=None, help="Match entries with or without a transfer destination.")
@click.option("--weekend/--no-weekend", default=None, help="Match Saturday/Sunday entries or Monday–Friday entries.")
@click.option("--has-price/--no-price", default=None, help="Match nonzero or zero recorded unit prices.")
@click.option("--has-quantity/--no-quantity", default=None, help="Match nonzero or zero recorded quantities.")
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(["date", "amount", "fees"]),
    default="date",
    help="Order by date, recorded amount or fees, descending unless --oldest-first is set. Ties use date then ID.",
)
@pass_app
def activity(
    app: App,
    account,
    symbol,
    limit,
    show_all,
    since,
    until,
    types,
    search,
    currency,
    oldest_first,
    offset,
    as_json,
    as_csv,
    count_only,
    summary,
    has_note,
    min_id,
    max_id,
    excluded_types,
    excluded_symbols,
    note,
    year,
    on_date,
    summary_sort,
    page_info,
    symbols,
    excluded_accounts,
    account_type,
    institution,
    has_symbol,
    target_account,
    quarter,
    weekday,
    month,
    excluded_currencies,
    excluded_dates,
    min_amount,
    max_amount,
    min_fees,
    max_fees,
    has_fees,
    min_quantity,
    max_quantity,
    min_price,
    max_price,
    exclude_note,
    symbol_prefix,
    account_search,
    included_ids,
    excluded_ids,
    has_target,
    weekend,
    has_price,
    has_quantity,
    sort_by,
) -> None:
    """The transaction ledger, newest first."""
    for lower, upper, label in (
        (min_amount, max_amount, "amount"),
        (min_fees, max_fees, "fees"),
        (min_quantity, max_quantity, "quantity"),
        (min_price, max_price, "price"),
    ):
        if lower is not None and upper is not None and lower > upper:
            raise click.UsageError(f"--min-{label} must be at or below --max-{label}.")
    if since and until and since > until:
        raise click.UsageError("--since must be on or before --until.")
    if min_id is not None and max_id is not None and min_id > max_id:
        raise click.UsageError("--min-id must be at or below --max-id.")
    if (as_json and as_csv) or (count_only and (as_json or as_csv or summary)):
        raise click.UsageError("Choose one output format; --count cannot be combined with --summary, --json or --csv.")
    if page_info and (not as_json or summary or count_only):
        raise click.UsageError("--page-info requires --json transaction output without --summary or --count.")
    if summary_sort != "group" and not summary:
        raise click.UsageError("--summary-sort requires --summary.")
    generation = app.store.restore_id
    accounts = app.store.account_map()
    acct = app.store.get_account(account) if account else None
    if account and (acct is None or acct.archived):
        fail(f"No active account '{account}'.")

    def active_account(ref: str) -> Account:
        found = app.store.get_account(ref)
        if found is None or found.archived:
            fail(f"No active account '{ref}'.")
        return found

    excluded_account_ids = {active_account(ref).saved_id for ref in excluded_accounts}
    target = active_account(target_account) if target_account is not None else None
    included_symbols = {value.strip().upper() for value in symbols}
    excluded_ccys = {value.strip().upper() for value in excluded_currencies}
    weekdays = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    needle = search.casefold()
    note_needle = note.casefold() if note is not None else None
    excluded = {value.strip().upper() for value in excluded_symbols}
    txns = [
        t
        for t in app.store.transactions(account_id=acct.id if acct else None, symbol=symbol)
        if _visible(t, accounts)
        and (min_quantity is None or t.quantity >= min_quantity)
        and (max_quantity is None or t.quantity <= max_quantity)
        and (min_price is None or t.price >= min_price)
        and (max_price is None or t.price <= max_price)
        and (exclude_note is None or exclude_note.casefold() not in t.note.casefold())
        and (symbol_prefix is None or t.symbol.startswith(symbol_prefix.strip().upper()))
        and (account_search is None or account_search.casefold() in accounts[t.account_id].name.casefold())
        and (not included_ids or t.saved_id in included_ids)
        and t.saved_id not in excluded_ids
        and (has_target is None or (t.target_account_id is not None) == has_target)
        and (weekend is None or (date.fromisoformat(t.date).weekday() >= 5) == weekend)
        and (has_price is None or (t.price != 0) == has_price)
        and (has_quantity is None or (t.quantity != 0) == has_quantity)
        and (not included_symbols or t.symbol in included_symbols)
        and t.account_id not in excluded_account_ids
        and t.target_account_id not in excluded_account_ids
        and (account_type is None or accounts[t.account_id].type.value == account_type)
        and (institution is None or accounts[t.account_id].institution.casefold() == institution.strip().casefold())
        and (has_symbol is None or bool(t.symbol.strip()) == has_symbol)
        and (target is None or (t.type == TxnType.TRANSFER and t.target_account_id == target.saved_id))
        and (quarter is None or (int(t.date[5:7]) - 1) // 3 + 1 == quarter)
        and (weekday is None or weekdays[date.fromisoformat(t.date).weekday()] == weekday)
        and (month is None or int(t.date[5:7]) == month)
        and t.currency.upper() not in excluded_ccys
        and t.date not in excluded_dates
        and (min_amount is None or t.amount >= min_amount)
        and (max_amount is None or t.amount <= max_amount)
        and (min_fees is None or t.fees >= min_fees)
        and (max_fees is None or t.fees <= max_fees)
        and (has_fees is None or (t.fees != 0) == has_fees)
        and (not since or t.date >= since)
        and (not until or t.date <= until)
        and (not types or t.type in types)
        and t.type not in excluded_types
        and t.symbol not in excluded
        and (note_needle is None or note_needle in t.note.casefold())
        and (year is None or t.date[:4] == f"{year:04d}")
        and (not on_date or t.date == on_date)
        and (not currency or t.currency == currency.strip().upper())
        and (has_note is None or bool(t.note.strip()) == has_note)
        and (min_id is None or t.saved_id >= min_id)
        and (max_id is None or t.saved_id <= max_id)
        and (
            not needle
            or needle
            in " ".join(
                [t.symbol, t.note, accounts[t.account_id].name]
                + ([accounts[t.target_account_id].name] if t.target_account_id is not None else [])
            ).casefold()
        )
    ]
    if count_only:
        click.echo(len(txns))
        return
    if summary:
        _activity_summary(app, txns, accounts, summary, as_json, as_csv, summary_sort)
        return
    total = len(txns)
    if sort_by == "date":
        txns.sort(key=lambda t: (t.date, t.id or 0), reverse=not oldest_first)
    else:
        txns.sort(key=lambda t: (getattr(t, sort_by), t.date, t.id or 0), reverse=not oldest_first)
    txns = txns[offset:] if show_all else txns[offset : offset + limit]
    if as_csv:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(
            stream, fieldnames=[f.name for f in fields(Transaction)] + ["account", "target_account", "revision"]
        )
        writer.writeheader()
        writer.writerows(_transaction_json(t, accounts, generation) for t in txns)
        click.echo(stream.getvalue(), nl=False)
        return
    if as_json:
        rows = [_transaction_json(t, accounts, generation) for t in txns]
        payload = (
            {
                "total": total,
                "offset": offset,
                "limit": None if show_all else limit,
                "returned": len(rows),
                "next_offset": offset + len(rows) if offset + len(rows) < total else None,
                "items": rows,
            }
            if page_info
            else rows
        )
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if not txns:
        app.console.print(
            Text("No matching transactions." if app.store.transactions() else "No transactions yet.", style="muted")
        )
        return
    table = render.table(*render.ACTIVITY_HEADERS)
    for t in txns:
        table.add_row(*render.activity_cells(t, accounts, privacy=app.privacy))
    app.console.print(table)
    shown = {t.id for t in txns}
    issues = app.store.ledger().issues
    for issue in issues:
        if issue.txn_id in shown:
            message = "Ledger issue (details hidden in privacy mode)." if app.privacy else issue.message
            app.warn(f"#{issue.txn_id} {issue.date}: {message}")


def _activity_summary(
    app: App,
    txns: list[Transaction],
    accounts: dict[int, Account],
    group: str,
    as_json: bool,
    as_csv: bool,
    sort: str,
) -> None:
    def key(t: Transaction) -> str:
        if group == "account":
            # Include the ID so identically named accounts remain distinct.
            return str(t.account_id)
        if group == "quarter":
            return f"{t.date[:4]}-Q{(int(t.date[5:7]) - 1) // 3 + 1}"
        if group == "account-type":
            return accounts[t.account_id].type.value
        if group == "weekday":
            return ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[date.fromisoformat(t.date).weekday()]
        if group == "institution":
            return accounts[t.account_id].institution
        if group == "month":
            return t.date[:7]
        if group == "year":
            return t.date[:4]
        if group == "day":
            return t.date
        return str(getattr(t, group))

    counts = Counter(key(t) for t in txns)
    rows = [{"group": value, "count": count} for value, count in sorted(counts.items())]
    if group == "account":
        for row in rows:
            row["account"] = accounts[int(str(row["group"]))].name
    if sort == "count":
        rows.sort(key=lambda row: (-int(str(row["count"])), str(row["group"])))
    if as_csv:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=["group", "count"] + (["account"] if group == "account" else []))
        writer.writeheader()
        writer.writerows(rows)
        click.echo(stream.getvalue(), nl=False)
        return
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
        return
    table = render.table(group.title(), ("Entries", "right"), title="Matching activity")
    for row in rows:
        empty_label = "(no institution)" if group == "institution" else "(no symbol)"
        label = str(row.get("account", row["group"])) or empty_label
        table.add_row(Text(label), Text(str(row["count"])))
    app.console.print(table)


def _visible(t: Transaction, accounts: dict[int, Account]) -> bool:
    """Browsing hides entries that would disclose an archived account at either end."""
    return (
        t.account_id in accounts
        and not accounts[t.account_id].archived
        and (
            t.target_account_id is None
            or (t.target_account_id in accounts and not accounts[t.target_account_id].archived)
        )
    )


def _transaction_json(t: Transaction, accounts: dict[int, Account], generation: str) -> dict:
    return {
        **asdict(t),
        "account": accounts[t.account_id].name,
        "target_account": accounts[t.target_account_id].name if t.target_account_id is not None else None,
        "revision": t.revision(generation),
    }


@main.command()
@click.option("-y", "--yes", is_flag=True)
@click.option(
    "-a", "--account", default=None, help="Undo the latest entry in this active account (either end of a transfer)."
)
@click.option("-s", "--symbol", default=None, help="Undo the latest entry for this exact symbol.")
@click.option("--dry-run", is_flag=True, help="Show the entry undo would delete and whether it can; change nothing.")
@click.option(
    "--json", "as_json", is_flag=True, help="Print the raw, unmasked entry and outcome; needs --yes or --dry-run."
)
@pass_app
def undo(app: App, yes: bool, account: str | None, symbol: str | None, dry_run: bool, as_json: bool) -> None:
    """Delete the most recently recorded transaction.

    With -a or -s, the most recently recorded matching entry in an active account."""
    if as_json and not (yes or dry_run):
        raise click.UsageError("--json needs --yes or --dry-run, since it can't ask for confirmation.")
    if symbol is not None and not symbol.strip():
        raise click.UsageError("--symbol cannot be blank.")
    restore_id = app.store.restore_id
    txns = app.store.transactions()
    if not txns:
        fail("Nothing to undo.")
    candidates = txns
    if account is not None or symbol is not None:
        accounts = app.store.account_map()
        acct = _active_account(app, account) if account is not None else None
        wanted = symbol.strip().upper() if symbol is not None else None
        candidates = [
            t
            for t in txns
            if _visible(t, accounts)
            and (acct is None or acct.id in (t.account_id, t.target_account_id))
            and (wanted is None or t.symbol == wanted)
        ]
        if not candidates:
            fail("No matching transaction to undo.")
    last = max(candidates, key=lambda t: t.id or 0)
    seen = last.revision(restore_id)  # the entry as shown; refused if it changes before the delete
    if not as_json:
        app.console.print(render.activity_table([last], app.store.account_map()))
    if dry_run:
        problem = _deletion_problem(app, [last.saved_id], seen)
        if as_json:
            _undo_json(app, last, restore_id, dry_run=True, error=problem)
        else:
            _finish_dry_run(app, problem, f"would delete transaction #{last.id}")
        return
    if yes or click.confirm("Delete this transaction?"):
        try:
            app.tracker.delete_transaction(last.saved_id, restore_id=restore_id, revision=seen)
        except ValueError as e:
            if as_json:
                _undo_json(app, last, restore_id, dry_run=False, error=str(e))
            fail(str(e))
        if as_json:
            _undo_json(app, last, restore_id, dry_run=False, error=None)
            return
        app.ok(f"Deleted transaction #{last.id}.")


def _undo_json(app: App, t: Transaction, generation: str, *, dry_run: bool, error: str | None) -> None:
    payload = {
        "dry_run": dry_run,
        "ok": error is None,
        "deleted": error is None and not dry_run,
        "error": error,
        "transaction": _transaction_json(t, app.store.account_map(), generation),
    }
    click.echo(json.dumps(payload, ensure_ascii=False))
    if error is not None:
        raise click.exceptions.Exit(1)


def _active_account(app: App, ref: str) -> Account:
    found = app.store.get_account(ref)
    if found is None or found.archived:
        fail(f"No active account '{ref}'.")
    return found


def _refusal(app: App, before: list[Transaction], after: list[Transaction], changed_id: int, verb: str) -> str | None:
    """Why the ledger would refuse turning `before` into `after`: the message a real save or
    delete gives, from the same replay check, or None if it would be accepted."""
    try:
        app.tracker._refuse_new_issues(before, after, changed_id, verb)
    except ValueError as e:
        return str(e)
    return None


def _deletion_problem(app: App, ids: list[int], revision: str | None = None) -> str | None:
    """Why deleting all of `ids` together would be refused, or None."""
    try:
        before = app.tracker._stored(ids[0], revision)
    except ValueError as e:
        return str(e)
    gone = set(ids)
    return _refusal(app, before, [t for t in before if t.id not in gone], ids[0], "deleted")


def _finish_dry_run(app: App, problem: str | None, would: str) -> None:
    if problem is None:
        app.ok(f"Dry run: {would}. Nothing was changed.")
        return
    app.warn(problem)
    raise click.exceptions.Exit(1)


@main.group()
def txn() -> None:
    """Inspect, check, edit or delete transactions (ids from `activity`)."""


@txn.command("show")
@click.argument("txn_ids", nargs=-1, required=True, type=click.IntRange(min=1), metavar="TXN_ID...")
@click.option("--json", "as_json", is_flag=True, help="Print raw, unmasked fields and the edit revision as JSON.")
@click.option(
    "--with-effect",
    is_flag=True,
    help="Also show each holding and cash balance the entry changes, before and after it (a ledger replay).",
)
@pass_app
def txn_show(app: App, txn_ids: tuple[int, ...], as_json: bool, with_effect: bool) -> None:
    """Inspect one or more transactions, including full notes and revisions.

    JSON is one object for one id and a list, in the order given, for several."""
    generation = app.store.restore_id
    accounts = app.store.account_map()
    txns = app.store.transactions()
    by_id = {t.id: t for t in txns if _visible(t, accounts)}
    ids = list(dict.fromkeys(txn_ids))
    missing = next((txn_id for txn_id in ids if txn_id not in by_id), None)
    if missing is not None:
        fail(f"No active transaction #{missing}.")
    payloads = []
    for txn_id in ids:
        payload = _transaction_json(by_id[txn_id], accounts, generation)
        if with_effect:
            payload["effect"] = _effect(by_id[txn_id], txns, accounts)
        payloads.append(payload)
    if as_json:
        click.echo(json.dumps(payloads if len(ids) > 1 else payloads[0], ensure_ascii=False))
        return
    for txn_id, payload in zip(ids, payloads, strict=True):
        effect = payload.pop("effect", None)
        table = render.table("Field", "Value", title=f"Transaction #{txn_id}")
        for field, value in payload.items():
            if app.privacy and field in ("quantity", "price", "amount", "fees", "ratio"):
                shown = fmt.MASK
            else:
                shown = "—" if value is None else str(value)
            table.add_row(Text(field), Text(shown))
        app.console.print(table)
        if effect is not None:
            _print_effect(app, txn_id, effect)


def _effect(t: Transaction, txns: list[Transaction], accounts: dict[int, Account]) -> list[dict]:
    """Holdings and tracked cash balances of the entry's account(s) that it changes, from replaying
    the ledger up to just before it and up to and including it (in replay order)."""
    key = sort_key(t)
    earlier = [x for x in txns if sort_key(x) < key]
    before, after = replay(earlier, accounts), replay([*earlier, t], accounts)
    touched = {t.account_id, t.target_account_id}

    def name(account_id: int) -> str:
        return accounts[account_id].name if account_id in accounts else str(account_id)

    rows: list[dict] = []
    for account_id, symbol in sorted(set(before.holdings) | set(after.holdings)):
        if account_id not in touched:
            continue
        old, new = before.holdings.get((account_id, symbol)), after.holdings.get((account_id, symbol))
        was = (old.quantity, old.book) if old else (0.0, 0.0)
        now = (new.quantity, new.book) if new else (0.0, 0.0)
        if all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(was, now, strict=True)):
            continue
        holding = new or old
        assert holding is not None  # the key came from one of the two states
        rows.append(
            {
                "kind": "holding",
                "account_id": account_id,
                "account": name(account_id),
                "symbol": symbol,
                "currency": holding.currency,
                "before": {"quantity": was[0], "book": was[1]},
                "after": {"quantity": now[0], "book": now[1]},
            }
        )
    for account_id, currency in sorted(set(before.cash) | set(after.cash)):
        if account_id not in touched or not (account_id in accounts and accounts[account_id].track_cash):
            continue
        was_cash, now_cash = before.cash.get((account_id, currency), 0.0), after.cash.get((account_id, currency), 0.0)
        if math.isclose(was_cash, now_cash, abs_tol=1e-9):
            continue
        rows.append(
            {
                "kind": "cash",
                "account_id": account_id,
                "account": name(account_id),
                "currency": currency,
                "before": {"balance": was_cash},
                "after": {"balance": now_cash},
            }
        )
    return rows


def _print_effect(app: App, txn_id: int, effect: list[dict]) -> None:
    if not effect:
        app.console.print(Text(f"#{txn_id} changes no holding or tracked cash balance.", style="muted"))
        return
    table = render.table("Account", "Item", ("Before", "right"), ("After", "right"), title=f"Effect of #{txn_id}")

    def amount(value: float, currency: str) -> str:
        return fmt.money(value, currency, privacy=app.privacy)

    for row in effect:
        account = Text(row["account"])
        if row["kind"] == "cash":
            ccy = row["currency"]
            balances = (amount(row["before"]["balance"], ccy), amount(row["after"]["balance"], ccy))
            table.add_row(account, Text(f"Cash ({ccy})"), *map(Text, balances))
            continue
        before, after = row["before"], row["after"]
        units = [fmt.MASK if app.privacy else fmt.qty(side["quantity"]) for side in (before, after)]
        table.add_row(account, Text(f"{row['symbol']} units"), *map(Text, units))
        books = [amount(side["book"], row["currency"]) for side in (before, after)]
        table.add_row(Text(""), Text(f"{row['symbol']} ACB ({row['currency']})"), *map(Text, books))
    app.console.print(table)


@txn.command("check")
@click.option("--json", "as_json", is_flag=True, help="Print raw diagnostics as JSON; exit 1 if issues exist.")
@click.option(
    "--code",
    "codes",
    multiple=True,
    help="Only issues with this code (e.g. sell_exceeds_held), ignoring case; repeat for several.",
)
@click.option(
    "-a", "--account", default=None, help="Only issues on entries in this active account (either end of a transfer)."
)
@pass_app
def txn_check(app: App, as_json: bool, codes: tuple[str, ...], account: str | None) -> None:
    """Check the full ledger offline. Exit 1 if any inconsistencies are found.

    The whole ledger is always replayed; --code and -a only choose which issues to report
    (and so whether the command exits 1)."""
    wanted = {code.strip().casefold() for code in codes}
    if "" in wanted:
        raise click.UsageError("--code cannot be blank.")
    accounts = app.store.account_map()
    acct = _active_account(app, account) if account is not None else None
    txns = {t.id: t for t in app.store.transactions()}
    visible = {i for i, t in txns.items() if _visible(t, accounts)}
    issues = [
        asdict(issue)
        if issue.txn_id in visible
        else {
            "txn_id": None,
            "date": "",
            "message": "Issue in a hidden account.",
            "code": "hidden_account_issue",
            "args": {},
        }
        for issue in app.store.ledger().issues
    ]
    filtered = bool(wanted) or acct is not None
    if wanted:
        issues = [issue for issue in issues if str(issue["code"]).casefold() in wanted]
    if acct is not None:
        issues = [
            issue
            for issue in issues
            if issue["txn_id"] is not None
            and acct.id in (txns[issue["txn_id"]].account_id, txns[issue["txn_id"]].target_account_id)
        ]
    if as_json:
        click.echo(json.dumps({"ok": not issues, "issues": issues}, ensure_ascii=False))
    elif not issues:
        app.ok("No matching ledger issues." if filtered else "Ledger is consistent.")
    else:
        app.warn(f"{len(issues)} ledger issue(s).")
        for issue in issues:
            message = "Ledger issue (details hidden in privacy mode)." if app.privacy else issue["message"]
            where = f"#{issue['txn_id']} {issue['date']}: " if issue["txn_id"] is not None else ""
            app.warn(f"{where}{message}")
    if issues:
        raise click.exceptions.Exit(1)


REVISION_HELP = "Refuse unless the entry is unchanged since it had this revision (from `desktop snapshot`)."


@txn.command("delete")
@click.argument("txn_ids", nargs=-1, required=True, type=int, metavar="TXN_ID...")
@click.option("-y", "--yes", is_flag=True)
@click.option("--revision", help=REVISION_HELP)
@click.option("--dry-run", is_flag=True, help="Show the entries and whether they can be deleted; change nothing.")
@pass_app
def txn_delete(app: App, txn_ids: tuple[int, ...], yes: bool, revision: str | None, dry_run: bool) -> None:
    """Delete transactions. Refused if a later entry depends on one (a sale of the shares it bought).

    Several ids are confirmed once and checked together first, so either all are deleted
    or none is; they are then deleted newest first."""
    ids = list(dict.fromkeys(txn_ids))
    if revision is not None and len(ids) > 1:
        raise click.UsageError("--revision needs a single transaction id.")
    restore_id = app.store.restore_id
    txns = app.store.transactions()
    by_id = {t.id: t for t in txns}
    missing = next((txn_id for txn_id in ids if txn_id not in by_id), None)
    if missing is not None:
        fail(f"No transaction #{missing}.")
    match = [by_id[txn_id] for txn_id in ids]
    if revision is None and len(ids) == 1:
        revision = match[0].revision(restore_id)  # the entry as shown; refused if it changes meanwhile
    app.console.print(render.activity_table(match, app.store.account_map()))
    if dry_run:
        _finish_dry_run(app, _deletion_problem(app, ids, revision), "would delete " + _id_list(ids))
        return
    if len(ids) == 1:
        txn_id = ids[0]
        if yes or click.confirm("Delete?"):
            try:
                app.tracker.delete_transaction(txn_id, restore_id=restore_id, revision=revision)
            except ValueError as e:
                fail(str(e))
            app.ok(f"Deleted #{txn_id}.")
        return
    if not (yes or click.confirm(f"Delete these {len(ids)} transactions?")):
        return
    seen = {t.saved_id: t.revision(restore_id) for t in match}
    # One transaction: the same combined check as the dry run, then every delete, so either all
    # go or none does (checking each delete on its own can refuse one after another went).
    with app.store.atomic():
        try:
            app.tracker._refuse_if_restored(restore_id, "deleted", "try again")
            for t in match:
                app.tracker._stored(t.saved_id, seen[t.saved_id])
        except ValueError as e:
            fail(f"{e} Nothing was deleted.")
        problem = _deletion_problem(app, ids)
        if problem is not None:
            fail(f"{problem} Nothing was deleted.")
        for t in sorted(match, key=sort_key, reverse=True):
            app.store.delete_transaction(t.saved_id)
    app.ok(f"Deleted {_id_list(ids)}.")


def _id_list(ids: list[int]) -> str:
    return ", ".join(f"#{txn_id}" for txn_id in sorted(ids))


@txn.command("edit")
@click.argument("txn_id", type=int)
@click.option("--date", "when", callback=date_callback)
@click.option("--account")
@click.option("--symbol")
@click.option("--quantity", type=float)
@click.option("--price", type=float)
@click.option("--amount", type=float)
@click.option("--fees", type=float)
@click.option("--currency", help="Blank to use the symbol's listing currency (or the account's for cash).")
@click.option("--note")
@click.option("--revision", help=REVISION_HELP)
@click.option("--dry-run", is_flag=True, help="Show the fields that would change and whether the edit is accepted.")
@pass_app
def txn_edit(
    app: App, txn_id: int, when, account, symbol, quantity, price, amount, fees, currency, note, revision, dry_run
) -> None:
    """Change a transaction's fields; its type stays the same.

    Changing the symbol without --currency works the currency out again. Refused if the
    result doesn't add up, e.g. a sale of more than was held then, or a later sale that
    would lose the shares it needs."""
    restore_id = app.store.restore_id
    match = [t for t in app.store.transactions() if t.id == txn_id]
    if not match:
        fail(f"No transaction #{txn_id}.")
    t = match[0]
    original = replace(t)
    if revision is None:
        # Every field of `t` is written back, so an edit made elsewhere since it was read (while a
        # quote is looked up, say) is refused rather than overwritten.
        revision = t.revision(restore_id)
    if symbol is not None and currency is None and symbol.strip().upper() != t.symbol:
        currency = ""  # the old symbol's currency may not be the new one's
    if when is not None:
        t.date = when
    if account is not None:
        t.account_id = app.account(account).saved_id
    for name, value in (
        ("symbol", symbol),
        ("quantity", quantity),
        ("price", price),
        ("amount", amount),
        ("fees", fees),
        ("currency", currency),
        ("note", note),
    ):
        if value is not None:
            setattr(t, name, value.strip().upper() if name in ("symbol", "currency") else value)
    if dry_run:
        _edit_dry_run(app, original, t, revision)
        return
    try:
        app.tracker.update_transaction(t, restore_id=restore_id, revision=revision)
    except ValueError as e:
        fail(str(e))
    app.console.print(render.activity_table([t], app.store.account_map()))
    app.ok(f"Updated #{txn_id}.")


EDIT_FIELDS = ("date", "account", "symbol", "quantity", "price", "amount", "fees", "currency", "note")


def _edit_dry_run(app: App, original: Transaction, edited: Transaction, revision: str) -> None:
    """Show the changed fields and run the checks `update_transaction` would, without saving."""
    accounts = app.store.account_map()
    if not edited.currency and edited.account_id in accounts:
        # Worked out exactly as the save would (an asset override, the listing, then a suffix guess).
        edited.currency, _ = app.tracker.resolve_currency(edited.symbol, accounts[edited.account_id])
    try:
        edited.validate()
        before = app.tracker._stored(edited.saved_id, revision)
    except ValueError as e:
        problem: str | None = str(e)
    else:
        after = [edited if t.id == edited.id else t for t in before]
        problem = _refusal(app, before, after, edited.saved_id, "saved")

    def value(t: Transaction, field: str) -> str:
        if field == "account":
            return accounts[t.account_id].name if t.account_id in accounts else str(t.account_id)
        if app.privacy and field in ("quantity", "price", "amount", "fees"):
            return fmt.MASK
        return str(getattr(t, field))

    def raw(t: Transaction, field: str) -> object:
        return t.account_id if field == "account" else getattr(t, field)

    changes = [(f, value(original, f), value(edited, f)) for f in EDIT_FIELDS if raw(original, f) != raw(edited, f)]
    if changes:
        table = render.table("Field", "Before", "After", title=f"Transaction #{edited.id} (dry run)")
        for field, old, new in changes:
            table.add_row(Text(field), Text(old or "—"), Text(new or "—"))
        app.console.print(table)
    else:
        app.console.print(Text("No changes.", style="muted"))
    _finish_dry_run(app, problem, f"would update #{edited.id}")
