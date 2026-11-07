"""Records helpers for the terminal app; Textual entry points stay on the app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import DataTable

from .. import fmt, render
from ..market import MarketError
from ..models import AssetKind, Transaction, TxnType, parse_date
from .screens import AccountForm, AssetForm, ConfirmScreen, PromptScreen, RoomForm, TransactionForm

if TYPE_CHECKING:
    from .app import MarketPulseApp


def action_new(app: MarketPulseApp) -> None:
    ws = app.workspace
    if ws == "tax":
        app.action_new_account()
    elif ws == "alerts":
        app.action_alert()
    else:
        app.action_trade("BUY")


def action_add(app: MarketPulseApp) -> None:
    ws = app.workspace
    if ws == "watchlist":
        app.action_watch_add(prompt=True)
    elif ws in ("tax", "alerts"):
        app.action_new()


def action_trade(app: MarketPulseApp, kind: str) -> None:
    form = TransactionForm(
        app.tracker,
        kind=TxnType(kind),
        symbol=app.context_symbol() if TxnType(kind).needs_symbol else "",
        account_id=app.context_account(),
        symbols=app.known_symbols(),
    )
    app.push_screen(form, app._txn_done)


def _txn_done(
    app: MarketPulseApp, txn: Transaction | None, restore_id: str | None = None, revision: str | None = None
) -> None:
    if txn is not None:
        app.save_txn(txn, restore_id, revision)


def save_txn(app: MarketPulseApp, txn: Transaction, restore_id: str | None = None, revision: str | None = None) -> None:
    tr = app.tracker
    try:
        if txn.id is not None:
            tr.update_transaction(txn, restore_id=restore_id, revision=revision)
            message = f"Updated transaction #{txn.id}"
        else:
            saved = tr.add_transaction(txn)
            acct = tr.store.get_account(saved.account_id)
            what = (
                f"{fmt.qty(saved.quantity)} {saved.symbol} @ {fmt.price(saved.price)}"
                if saved.quantity
                else f"{fmt.money(saved.gross_value)} {saved.symbol}".strip()
            )
            message = f"{saved.type.value.title()} {what} {saved.currency} → {acct.name if acct else ''}"
    except (ValueError, MarketError) as e:
        app.call_from_thread(app.notify, str(e), title="Not saved", severity="error")
        return
    app.call_from_thread(app.after_change, message)


def action_edit(app: MarketPulseApp) -> None:
    ws = app.workspace
    if ws == "activity":
        restore_id = app.tracker.store.restore_id
        key = app._selected_key(app.query_one("#activity-table", DataTable))
        txn = next((t for t in app.tracker.store.transactions() if str(t.id) == key), None)
        if txn:
            # Taken before the form opens: a change made elsewhere meanwhile refuses the save.
            seen = txn.revision(restore_id)
            app.push_screen(
                TransactionForm(app.tracker, txn=txn, symbols=app.known_symbols()),
                lambda edited: app._txn_done(edited, restore_id, seen),
            )
    elif ws == "tax":
        key = app._selected_key(app.query_one("#accounts-table", DataTable))
        acct = app.tracker.store.get_account(int(key)) if key else None
        if acct:
            app.push_screen(AccountForm(acct, app.tracker.base), app._account_done)


def action_delete(app: MarketPulseApp) -> None:
    ws, store = app.workspace, app.tracker.store
    if ws == "activity":
        restore_id = store.restore_id
        key = app._selected_key(app.query_one("#activity-table", DataTable))
        txn = next((t for t in store.transactions() if str(t.id) == key), None)
        if txn is None:
            return
        detail = " ".join(c.plain for c in render.activity_cells(txn, store.account_map())[1:8] if c.plain != "—")
        seen = txn.revision(restore_id)

        def done(yes: bool | None) -> None:
            if yes and app._delete_txn(txn.saved_id, restore_id, seen):
                app.after_change(f"Deleted transaction #{txn.id}")

        app.push_screen(ConfirmScreen(f"Delete transaction #{txn.id}?", detail), done)
    elif ws == "watchlist":
        sym = app.context_symbol()
        if not sym:
            return

        def unwatch(yes: bool | None) -> None:
            if yes:
                store.remove_watch([sym])
                app._watch_key = None
                app.watch_symbols = [s for s in app.watch_symbols if s != sym]
                app.render_watchlist()
                app.notify(f"Removed {sym} from watchlist")

        app.push_screen(ConfirmScreen(f"Remove {sym} from the watchlist?"), unwatch)
    elif ws == "alerts":
        key = app._selected_key(app.query_one("#alerts-table", DataTable))
        alert = next((a for a in store.alerts() if str(a.id) == key), None)
        if alert is None:
            return

        def remove(yes: bool | None) -> None:
            if yes:
                store.delete_alert(alert.saved_id)
                app.render_alerts()
                app.notify("Alert removed")

        app.push_screen(ConfirmScreen(f"Delete alert #{alert.id}?", alert.describe()), remove)
    elif ws == "tax":
        key = app._selected_key(app.query_one("#accounts-table", DataTable))
        acct = store.get_account(int(key)) if key else None
        if acct is None:
            return
        count = len([t for t in store.transactions() if t.account_id == acct.id])

        def confirmed(yes: bool | None) -> None:
            if yes:
                store.delete_account(acct.saved_id)
                app.after_change(f"Deleted {acct.name}")

        app.push_screen(
            ConfirmScreen(
                f"Delete {acct.name}?", f"This removes {count} transaction(s). Archiving (e → edit) keeps history."
            ),
            confirmed,
        )


def action_undo(app: MarketPulseApp) -> None:
    store = app.tracker.store
    restore_id = store.restore_id
    txns = store.transactions()
    if not txns:
        app.notify("Nothing to undo.")
        return
    last = max(txns, key=lambda t: t.id or 0)
    detail = " ".join(c.plain for c in render.activity_cells(last, store.account_map())[1:8] if c.plain != "—")

    def done(yes: bool | None) -> None:
        if yes and app._delete_txn(last.saved_id, restore_id, last.revision(restore_id)):
            app.after_change(f"Undid transaction #{last.id}")

    app.push_screen(ConfirmScreen("Undo the last transaction?", detail), done)


def _delete_txn(app: MarketPulseApp, txn_id: int, restore_id: str, revision: str) -> bool:
    try:
        app.tracker.delete_transaction(txn_id, restore_id=restore_id, revision=revision)
    except ValueError as e:
        app.notify(str(e), title="Not deleted", severity="error")
        return False
    return True


def action_new_account(app: MarketPulseApp) -> None:
    app.push_screen(AccountForm(None, app.tracker.base), app._account_done)


def _account_done(app: MarketPulseApp, account) -> None:
    if account is None:
        return
    store = app.tracker.store
    try:
        if account.id is None:
            store.add_account(account)
            message = f"Added account {account.name}"
        else:
            store.update_account(account)
            message = f"Updated {account.name}"
    except ValueError as e:
        app.notify(str(e), severity="error")
        return
    app.after_change(message)


def action_add_asset(app: MarketPulseApp) -> None:
    accounts = app.tracker.store.accounts() or [app.tracker.store.ensure_default_account(app.tracker.base)]

    def done(result) -> None:
        if result is None:
            return
        asset, txn = result
        existed = asset.symbol in app.tracker.store.assets()
        app.tracker.store.upsert_asset(asset)
        try:
            app.tracker.add_transaction(txn)
        except ValueError as e:
            if not existed:
                app.tracker.store.delete_asset(asset.symbol)  # don't leave an asset row with no holding
            app.notify(str(e), severity="error")
            return
        app.after_change(f"Added {asset.name}")

    app.push_screen(AssetForm(accounts), done)


def action_value_asset(app: MarketPulseApp) -> None:
    manual = [a.symbol for a in app.tracker.store.assets().values() if a.kind is AssetKind.MANUAL]
    if not manual:
        app.notify("No manual assets yet — ctrl+p → Add GIC or manual asset.")
        return

    def done(value: str | None) -> None:
        if not value:
            return
        parts = value.split()
        try:
            sym, amount = parts[0].upper(), float(parts[1].replace(",", ""))
            when = parse_date(parts[2] if len(parts) > 2 else None)
            if amount <= 0:
                raise ValueError
        except (IndexError, ValueError):
            app.notify("Use: SYMBOL VALUE [DATE] (value must be positive)", severity="error")
            return
        if sym not in manual:
            app.notify(f"{sym} is not a manual asset.", severity="error")
            return
        holders = [h for h in app.tracker.store.ledger().open_holdings() if h.symbol == sym]
        if not holders:
            app.notify(f"No holding of {sym}.", severity="error")
            return
        try:
            app.tracker.add_transaction(
                Transaction(
                    account_id=holders[0].account_id,
                    type=TxnType.VALUATION,
                    date=when,
                    symbol=sym,
                    price=amount,
                    currency=holders[0].currency,
                )
            )
        except ValueError as e:
            app.notify(str(e), severity="error")
            return
        app.after_change(f"{sym} valued at {fmt.money(amount)}")

    app.push_screen(
        PromptScreen(
            "Update manual asset value",
            "SYMBOL VALUE [DATE]",
            manual[0] + " ",
            hint=f"Manual assets: {', '.join(manual)}",
        ),
        done,
    )


def action_room(app: MarketPulseApp) -> None:
    def done(result) -> None:
        if result:
            app.tracker.store.set_room(*result)
            app.after_change(f"{result[0]} room saved")

    app.push_screen(RoomForm(), done)
