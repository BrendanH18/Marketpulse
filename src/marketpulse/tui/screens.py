"""Modal forms and pickers."""

from __future__ import annotations

from typing import TYPE_CHECKING, overload

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.timer import Timer
from textual.widgets import Button, Input, Label, OptionList, Select, Static, Switch
from textual.widgets.option_list import Option

from .. import fmt
from ..market import MarketError
from ..models import (
    ALERT_CONDITIONS,
    Account,
    AccountType,
    Alert,
    Asset,
    AssetClass,
    AssetKind,
    Transaction,
    TxnType,
    parse_date,
    today,
)

if TYPE_CHECKING:
    from ..services import Tracker


class FormError(ValueError):
    pass


@overload
def _num(screen: ModalScreen, selector: str, label: str, default: float = 0.0) -> float: ...
@overload
def _num(screen: ModalScreen, selector: str, label: str, default: None) -> float | None: ...
def _num(screen: ModalScreen, selector: str, label: str, default: float | None = 0.0) -> float | None:
    """Read a numeric input. Blank gives `default` (so callers passing a
    float default always get a float back); anything unparsable is a FormError."""
    raw = screen.query_one(selector, Input).value.strip().replace(",", "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise FormError(f"{label} must be a number.") from None


class BaseForm(ModalScreen):
    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("ctrl+s", "save", "Save")]

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    @on(Button.Pressed, "#cancel")
    def _cancel_pressed(self) -> None:
        self.action_cancel()

    @on(Button.Pressed, "#save")
    def _save_pressed(self) -> None:
        self.action_save()

    def show_error(self, message: str) -> None:
        self.query_one("#form-error", Static).update(Text(message, style="down"))

    def buttons(self, save_label: str = "Save") -> Horizontal:
        return Horizontal(
            Static("", id="form-error", classes="error"),
            Button(f"{save_label}  ^s", variant="primary", id="save"),
            Button("Cancel  esc", id="cancel"),
            classes="buttons",
        )


# ── Transactions ──────────────────────────────────────────────────────────────

_TYPE_LABELS = {
    TxnType.BUY: "Buy",
    TxnType.SELL: "Sell",
    TxnType.DIVIDEND: "Dividend",
    TxnType.DRIP: "DRIP (reinvested)",
    TxnType.INTEREST: "Interest",
    TxnType.DEPOSIT: "Deposit",
    TxnType.WITHDRAWAL: "Withdrawal",
    TxnType.FEE: "Fee",
    TxnType.SPLIT: "Split",
    TxnType.ROC: "Return of capital",
    TxnType.TRANSFER: "Transfer in-kind",
    TxnType.VALUATION: "Valuation (manual asset)",
}


class TransactionForm(BaseForm):
    """Create or edit any transaction; fields adapt to the type."""

    def __init__(
        self,
        tracker: Tracker,
        *,
        txn: Transaction | None = None,
        kind: TxnType = TxnType.BUY,
        symbol: str = "",
        account_id: int | None = None,
        symbols: list[str] | None = None,
    ):
        super().__init__()
        self.tracker = tracker
        self.txn = txn
        self.kind = txn.type if txn else kind
        self.symbol = txn.symbol if txn else symbol.upper()
        self.accounts = tracker.store.accounts() or [tracker.store.ensure_default_account(tracker.base)]
        ids = [a.saved_id for a in self.accounts]
        # Editing keeps the transaction's account; otherwise use the requested
        # account if it still exists, else the first one.
        self.account_id: int = (
            txn.account_id if txn else (account_id if account_id is not None and account_id in ids else ids[0])
        )
        self.symbols = symbols or []
        self.live_price: float | None = None
        self.live_currency = ""
        self._lookup_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        t = self.txn
        title = f"Edit transaction #{t.id}" if t else "New transaction"

        def val(v: float) -> str:
            return f"{v:g}" if v else ""

        account_options = [(f"{a.name}  ·  {a.type.label}", a.id) for a in self.accounts]
        with Vertical(classes="modal"):
            yield Label(title, classes="modal-title")
            with Horizontal(classes="field-row"):
                yield Select(
                    [(label, k) for k, label in _TYPE_LABELS.items()], value=self.kind, allow_blank=False, id="f-type"
                )
                yield Select(account_options, value=self.account_id, allow_blank=False, id="f-account")
            yield Select(
                account_options,
                value=t.target_account_id if t and t.target_account_id else Select.NULL,
                prompt="Destination account",
                id="f-target",
                classes="k-transfer",
            )
            yield Input(
                self.symbol,
                placeholder="Symbol  e.g. XEQT.TO",
                id="f-symbol",
                classes="k-symbol",
                suggester=SuggestFromList(self.symbols, case_sensitive=False) if self.symbols else None,
            )
            yield Static("", id="f-live", classes="hint k-symbol")
            with Horizontal(classes="field-row"):
                yield Input(val(t.quantity) if t else "", placeholder="Quantity", id="f-quantity", classes="k-qty")
                yield Input(
                    val(t.price) if t else "", placeholder="Price (blank = live)", id="f-price", classes="k-price"
                )
                yield Input(val(t.amount) if t else "", placeholder="Amount", id="f-amount", classes="k-amount")
                yield Input(
                    val(t.ratio) if t else "", placeholder="Ratio  e.g. 4 for 4-for-1", id="f-ratio", classes="k-ratio"
                )
            with Horizontal(classes="field-row"):
                yield Input(val(t.fees) if t else "", placeholder="Fees", id="f-fees", classes="k-fees")
                yield Input(t.currency if t else "", placeholder="Currency (auto)", id="f-currency", max_length=3)
                yield Input(t.date if t else today(), placeholder="Date  YYYY-MM-DD / yesterday / -3d", id="f-date")
            yield Input(t.note if t else "", placeholder="Note (optional)", id="f-note")
            yield self.buttons()

    def on_mount(self) -> None:
        self._apply_kind()
        if self.symbol:
            self._lookup()
            focus = "#f-quantity" if self.kind.uses_quantity else ("#f-amount" if self.kind.uses_amount else "#f-price")
            self.query_one(focus, Input).focus()
        else:
            self.query_one("#f-symbol", Input).focus()

    def _apply_kind(self) -> None:
        k = self.kind
        show = {
            "k-symbol": k.needs_symbol or k is TxnType.INTEREST,
            "k-qty": k.uses_quantity,
            # A transfer's price is the market value per unit, used by the tax
            # report when shares cross between taxable and registered accounts.
            "k-price": k in (TxnType.BUY, TxnType.SELL, TxnType.DRIP, TxnType.VALUATION, TxnType.TRANSFER),
            "k-amount": k.uses_amount,
            "k-ratio": k is TxnType.SPLIT,
            "k-fees": k in (TxnType.BUY, TxnType.SELL),
            "k-transfer": k is TxnType.TRANSFER,
        }
        for cls, visible in show.items():
            for w in self.query(f".{cls}"):
                w.display = visible
        price = self.query_one("#f-price", Input)
        if k in (TxnType.BUY, TxnType.SELL):
            price.placeholder = "Price (blank = live)"
        elif k is TxnType.TRANSFER:
            price.placeholder = "Market value / unit (for tax)"
        else:
            price.placeholder = "Price per unit"

    @on(Select.Changed, "#f-type")
    def _type_changed(self, event: Select.Changed) -> None:
        if isinstance(event.value, TxnType):
            self.kind = event.value
            self._apply_kind()

    @on(Select.Changed, "#f-account")
    def _account_changed(self, event: Select.Changed) -> None:
        if isinstance(event.value, int):
            self.account_id = event.value
            self._lookup()

    @on(Input.Changed, "#f-symbol")
    def _symbol_changed(self, event: Input.Changed) -> None:
        self.symbol = event.value.strip().upper()
        if self._lookup_timer is not None:
            self._lookup_timer.stop()
        self._lookup_timer = self.set_timer(0.45, self._lookup)

    @on(Input.Submitted)
    def _submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "f-note":
            self.action_save()
        else:
            self.focus_next()

    def _lookup(self) -> None:
        if self.symbol:
            self._fetch_live(self.symbol, self.account_id)

    @work(thread=True, exclusive=True, group="form-lookup")
    def _fetch_live(self, symbol: str, account_id: int) -> None:
        tr = self.tracker
        asset = tr.store.assets().get(symbol)
        hint = Text()
        price = None
        ccy = ""
        if asset and asset.kind is not AssetKind.MARKET:
            hint.append(f"{asset.name or symbol} · {asset.kind.value.replace('_', ' ')}", style="accent")
        else:
            try:
                q = tr.market.quote(symbol)
                price, ccy = q.price, q.currency
                hint.append(f"{q.name}  ", style="bright")
                hint.append(f"{fmt.price(q.price)} {q.currency} ", style="bright")
                hint.append(f"{fmt.arrow(q.change)} {fmt.pct(q.change_pct)}", style=fmt.trend_style(q.change))
            except MarketError as e:
                hint.append(str(e), style="warn")
        h = tr.store.ledger().holdings.get((account_id, symbol))
        if h and h.quantity > 0:
            hint.append(f"   held {fmt.qty(h.quantity)} @ {fmt.price(h.avg_cost)}", style="muted")
        self.app.call_from_thread(self._set_live, symbol, price, ccy, hint)

    def _set_live(self, symbol: str, price: float | None, currency: str, hint: Text) -> None:
        if symbol != self.symbol:
            return
        self.live_price, self.live_currency = price, currency
        self.query_one("#f-live", Static).update(hint)

    def action_save(self) -> None:
        try:
            k = self.kind
            symbol = (
                self.query_one("#f-symbol", Input).value.strip().upper()
                if k.needs_symbol or k is TxnType.INTEREST
                else ""
            )
            price = _num(self, "#f-price", "Price", None)
            day = parse_date(self.query_one("#f-date", Input).value)
            if k in (TxnType.BUY, TxnType.SELL) and price is None:
                if self.live_price is None or symbol != self.symbol:
                    raise FormError("Enter a price (no live quote available).")
                if day != today():
                    raise FormError("Back-dated trades need an explicit price.")
                price = self.live_price
            if k is TxnType.TRANSFER and price is None and day == today() and symbol == self.symbol:
                # Same convenience as a buy: today's transfer defaults to the live price.
                price = self.live_price
            target = self.query_one("#f-target", Select).value
            txn = Transaction(
                id=self.txn.id if self.txn else None,
                account_id=self.account_id,
                type=k,
                date=day,
                symbol=symbol,
                quantity=_num(self, "#f-quantity", "Quantity") if k.uses_quantity else 0.0,
                price=price or 0.0,
                amount=_num(self, "#f-amount", "Amount") if k.uses_amount else 0.0,
                fees=_num(self, "#f-fees", "Fees") if k in (TxnType.BUY, TxnType.SELL) else 0.0,
                ratio=_num(self, "#f-ratio", "Ratio") if k is TxnType.SPLIT else 0.0,
                currency=self.query_one("#f-currency", Input).value.strip().upper()
                or (self.live_currency if symbol == self.symbol else ""),
                note=self.query_one("#f-note", Input).value.strip(),
                target_account_id=target if isinstance(target, int) and k is TxnType.TRANSFER else None,
            )
            txn.validate()
        except (FormError, ValueError) as e:
            self.show_error(str(e))
            return
        self.dismiss(txn)


# ── Accounts, assets, alerts, room ────────────────────────────────────────────


class AccountForm(BaseForm):
    def __init__(self, account: Account | None = None, base_currency: str = "CAD"):
        super().__init__()
        self.account = account
        self.base_currency = base_currency

    def compose(self) -> ComposeResult:
        a = self.account
        with Vertical(classes="modal"):
            yield Label(f"Edit {a.name}" if a else "New account", classes="modal-title")
            yield Input(a.name if a else "", placeholder="Name  e.g. Wealthsimple TFSA", id="a-name")
            with Horizontal(classes="field-row"):
                yield Select(
                    [(t.label, t) for t in AccountType],
                    value=a.type if a else AccountType.TFSA,
                    allow_blank=False,
                    id="a-type",
                )
                yield Input(
                    a.currency if a else self.base_currency, placeholder="Currency", id="a-currency", max_length=3
                )
            yield Input(a.institution if a else "", placeholder="Institution (optional)", id="a-institution")
            with Horizontal(classes="field-row switch-row"):
                yield Switch(value=a.track_cash if a else False, id="a-cash")
                yield Label(
                    "Track cash balance — buys debit cash; sells, dividends and deposits credit it", classes="hint"
                )
            yield self.buttons()

    def on_mount(self) -> None:
        self.query_one("#a-name", Input).focus()

    def action_save(self) -> None:
        name = self.query_one("#a-name", Input).value.strip()
        ccy = self.query_one("#a-currency", Input).value.strip().upper()
        if not name:
            return self.show_error("Name is required.")
        if len(ccy) != 3:
            return self.show_error("Currency must be a 3-letter code.")
        a = self.account or Account(name=name)
        a.name = name
        a.type = self.query_one("#a-type", Select).value  # type: ignore[assignment]
        a.currency = ccy
        a.institution = self.query_one("#a-institution", Input).value.strip()
        a.track_cash = self.query_one("#a-cash", Switch).value
        self.dismiss(a)


class AssetForm(BaseForm):
    """Add a GIC/bond (accrual-priced) or a manually valued asset."""

    def __init__(self, accounts: list[Account], kind: AssetKind = AssetKind.FIXED_INCOME):
        super().__init__()
        self.accounts = accounts
        self.kind = kind

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label("Add an asset the market can't price", classes="modal-title")
            with Horizontal(classes="field-row"):
                yield Select(
                    [
                        ("GIC / term deposit / bond", AssetKind.FIXED_INCOME),
                        ("Manual (property, private, collectibles…)", AssetKind.MANUAL),
                    ],
                    value=self.kind,
                    allow_blank=False,
                    id="s-kind",
                )
                yield Select(
                    [(a.name, a.id) for a in self.accounts],
                    value=self.accounts[0].id,
                    allow_blank=False,
                    id="s-account",
                )
            with Horizontal(classes="field-row"):
                yield Input(placeholder="Short code  e.g. EQB-GIC-2027", id="s-symbol")
                yield Input(placeholder="Display name", id="s-name")
            with Horizontal(classes="field-row"):
                yield Input(placeholder="Principal / purchase value", id="s-value")
                yield Input(placeholder="Currency (account's)", id="s-currency", max_length=3)
                yield Input(today(), placeholder="Start / purchase date", id="s-start")
            with Horizontal(classes="field-row k-fixed"):
                yield Input(placeholder="Annual rate %", id="s-rate")
                yield Select(
                    [(c.title(), c) for c in ("annual", "semiannual", "quarterly", "monthly", "simple")],
                    value="annual",
                    allow_blank=False,
                    id="s-compounding",
                )
                yield Input(placeholder="Maturity date", id="s-maturity")
            yield Select(
                [(c.label, c) for c in AssetClass],
                value=AssetClass.REAL_ESTATE,
                allow_blank=False,
                id="s-class",
                classes="k-manual",
            )
            yield self.buttons("Add")

    def on_mount(self) -> None:
        self._apply()
        self.query_one("#s-symbol", Input).focus()

    def _apply(self) -> None:
        for w in self.query(".k-fixed"):
            w.display = self.kind is AssetKind.FIXED_INCOME
        for w in self.query(".k-manual"):
            w.display = self.kind is AssetKind.MANUAL

    @on(Select.Changed, "#s-kind")
    def _kind(self, event: Select.Changed) -> None:
        if isinstance(event.value, AssetKind):
            self.kind = event.value
            self._apply()

    def action_save(self) -> None:
        try:
            symbol = self.query_one("#s-symbol", Input).value.strip().upper()
            if not symbol:
                raise FormError("A short code is required.")
            value = _num(self, "#s-value", "Value", None)
            if not value or value <= 0:
                raise FormError("Enter the principal or purchase value.")
            account_id = self.query_one("#s-account", Select).value
            acct = next(a for a in self.accounts if a.id == account_id)
            ccy = self.query_one("#s-currency", Input).value.strip().upper() or acct.currency
            start = parse_date(self.query_one("#s-start", Input).value)
            name = self.query_one("#s-name", Input).value.strip() or symbol
            if self.kind is AssetKind.FIXED_INCOME:
                rate = _num(self, "#s-rate", "Rate", None)
                if rate is None:
                    raise FormError("Enter the annual rate.")
                maturity = parse_date(self.query_one("#s-maturity", Input).value or None)
                if maturity <= start:
                    raise FormError("Maturity must be after the start date.")
                asset = Asset(
                    symbol=symbol,
                    kind=AssetKind.FIXED_INCOME,
                    name=name,
                    asset_class=AssetClass.FIXED_INCOME,
                    currency=ccy,
                    rate=rate,
                    compounding=str(self.query_one("#s-compounding", Select).value),
                    start_date=start,
                    maturity_date=maturity,
                )
            else:
                # Select.BLANK (nothing chosen) isn't a str: leave the class unset.
                chosen = self.query_one("#s-class", Select).value
                asset = Asset(
                    symbol=symbol,
                    kind=AssetKind.MANUAL,
                    name=name,
                    asset_class=AssetClass(chosen) if isinstance(chosen, str) else None,
                    currency=ccy,
                )
            txn = Transaction(
                account_id=acct.saved_id,
                type=TxnType.BUY,
                date=start,
                symbol=symbol,
                quantity=1,
                price=value,
                currency=ccy,
            )
        except (FormError, ValueError, StopIteration) as e:
            self.show_error(str(e))
            return
        self.dismiss((asset, txn))


class AlertForm(BaseForm):
    def __init__(self, symbol: str = ""):
        super().__init__()
        self.symbol = symbol

    def compose(self) -> ComposeResult:
        labels = {
            "above": "Price at or above",
            "below": "Price at or below",
            "up_pct": "Up % today",
            "down_pct": "Down % today",
        }
        with Vertical(classes="modal"):
            yield Label("New price alert", classes="modal-title")
            with Horizontal(classes="field-row"):
                yield Input(self.symbol, placeholder="Symbol", id="l-symbol")
                yield Select(
                    [(labels[c], c) for c in ALERT_CONDITIONS], value="above", allow_blank=False, id="l-condition"
                )
                yield Input(placeholder="Threshold", id="l-threshold")
            yield Input(placeholder="Note (optional)", id="l-note")
            yield Label("Alerts notify once when triggered and re-arm when the condition clears.", classes="hint")
            yield self.buttons("Create")

    def on_mount(self) -> None:
        self.query_one("#l-threshold" if self.symbol else "#l-symbol", Input).focus()

    def action_save(self) -> None:
        try:
            threshold = _num(self, "#l-threshold", "Threshold", None)
            if threshold is None:
                raise FormError("Enter a threshold.")
            alert = Alert(
                symbol=self.query_one("#l-symbol", Input).value.strip(),
                condition=str(self.query_one("#l-condition", Select).value),
                threshold=threshold,
                note=self.query_one("#l-note", Input).value.strip(),
            )
            if not alert.symbol:
                raise FormError("Symbol is required.")
        except (FormError, ValueError) as e:
            self.show_error(str(e))
            return
        self.dismiss(alert)


class RoomForm(BaseForm):
    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label("Contribution room", classes="modal-title")
            yield Label(
                "Enter the room CRA shows for Jan 1 of a year (CRA My Account → RRSP & TFSA). "
                "TFSA and FHSA roll forward automatically.",
                classes="hint",
            )
            with Horizontal(classes="field-row"):
                yield Select(
                    [(t, t) for t in ("TFSA", "RRSP", "FHSA", "RESP")], value="TFSA", allow_blank=False, id="r-type"
                )
                yield Input(str(int(today()[:4])), placeholder="Year", id="r-year")
                yield Input(placeholder="Room as of Jan 1", id="r-amount")
            yield self.buttons()

    def action_save(self) -> None:
        try:
            year = int(self.query_one("#r-year", Input).value)
            amount = _num(self, "#r-amount", "Room", None)
            if amount is None:
                raise FormError("Enter the room amount.")
        except (FormError, ValueError) as e:
            self.show_error(str(e))
            return
        self.dismiss((str(self.query_one("#r-type", Select).value), year, amount))


class PromptScreen(BaseForm):
    def __init__(self, title: str, placeholder: str = "", value: str = "", hint: str = ""):
        super().__init__()
        self.title_text, self.placeholder, self.value, self.hint = title, placeholder, value, hint

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label(self.title_text, classes="modal-title")
            if self.hint:
                yield Label(self.hint, classes="hint")
            yield Input(self.value, placeholder=self.placeholder, id="p-input")
            yield self.buttons("OK")

    def on_mount(self) -> None:
        self.query_one("#p-input", Input).focus()

    @on(Input.Submitted)
    def _submit(self) -> None:
        self.action_save()

    def action_save(self) -> None:
        value = self.query_one("#p-input", Input).value.strip()
        self.dismiss(value or None)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("y,enter", "yes", "Yes"), Binding("n,escape", "no", "No")]

    def __init__(self, message: str, detail: str = ""):
        super().__init__()
        self.message, self.detail = message, detail

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal narrow"):
            yield Label(self.message, classes="modal-title")
            if self.detail:
                yield Label(self.detail, classes="hint")
            with Horizontal(classes="buttons"):
                yield Button("Yes  y", variant="error", id="yes")
                yield Button("No  n", id="no")

    @on(Button.Pressed, "#yes")
    def action_yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def action_no(self) -> None:
        self.dismiss(False)


# ── Symbol search ─────────────────────────────────────────────────────────────


class SearchScreen(ModalScreen[str | None]):
    """Fuzzy symbol search: local holdings/watchlist first, then Yahoo."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "cursor(1)", show=False),
        Binding("up", "cursor(-1)", show=False),
    ]

    def __init__(self, tracker: Tracker, known: list[str], title: str = "Search"):
        super().__init__()
        self.tracker = tracker
        self.known = known
        self.title_text = title
        self._timer: Timer | None = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label(self.title_text, classes="modal-title")
            yield Input(placeholder="Company, fund or symbol…", id="q")
            yield OptionList(id="results")
            yield Label("↑↓ choose · enter open · esc close", classes="hint")

    def on_mount(self) -> None:
        self._show_local("")
        self.query_one("#q", Input).focus()

    def _show_local(self, query: str) -> None:
        ol = self.query_one("#results", OptionList)
        ol.clear_options()
        q = query.upper()
        for sym in [s for s in self.known if q in s][:8]:
            ol.add_option(Option(Text.assemble((sym, "bold"), ("  in your portfolio", "dim")), id=sym))
        if ol.option_count:
            ol.highlighted = 0

    @on(Input.Changed, "#q")
    def _changed(self, event: Input.Changed) -> None:
        self._show_local(event.value)
        if self._timer is not None:
            self._timer.stop()
        if len(event.value.strip()) >= 2:
            self._timer = self.set_timer(0.35, lambda: self._search(event.value.strip()))

    @work(thread=True, exclusive=True, group="search")
    def _search(self, query: str) -> None:
        try:
            results = self.tracker.market.search(query, limit=10)
        except MarketError:
            return
        self.app.call_from_thread(self._show_remote, query, results)

    def _show_remote(self, query: str, results) -> None:
        if self.query_one("#q", Input).value.strip() != query:
            return
        ol = self.query_one("#results", OptionList)
        existing = {ol.get_option_at_index(i).id for i in range(ol.option_count)}
        for r in results:
            if r.symbol in existing:
                continue
            ol.add_option(
                Option(
                    Text.assemble(
                        (f"{r.symbol:<12}", "bold"), (f"{r.name[:44]:<46}", ""), (f"{r.exchange} · {r.type}", "dim")
                    ),
                    id=r.symbol,
                )
            )
        if ol.option_count and ol.highlighted is None:
            ol.highlighted = 0

    def action_cursor(self, delta: int) -> None:
        ol = self.query_one("#results", OptionList)
        if ol.option_count:
            ol.highlighted = ((ol.highlighted or 0) + delta) % ol.option_count

    @on(Input.Submitted, "#q")
    def _submit(self, event: Input.Submitted) -> None:
        ol = self.query_one("#results", OptionList)
        if ol.highlighted is not None and ol.option_count:
            self.dismiss(ol.get_option_at_index(ol.highlighted).id)
        elif event.value.strip():
            self.dismiss(event.value.strip().upper())

    @on(OptionList.OptionSelected)
    def _selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── Help ──────────────────────────────────────────────────────────────────────

HELP = [
    (
        "Navigation",
        [
            ("1-8", "switch workspace"),
            ("tab / shift+tab", "move focus"),
            ("ctrl+p", "command palette"),
            ("/", "search a symbol"),
            ("?", "this help"),
            ("q", "quit"),
        ],
    ),
    (
        "Portfolio",
        [
            ("n", "new transaction"),
            ("b / s", "buy / sell selected symbol"),
            ("D", "record dividend"),
            ("e", "edit selected"),
            ("x", "delete selected"),
            ("f", "cycle account filter"),
            ("u", "undo last transaction"),
        ],
    ),
    (
        "Markets",
        [
            ("enter", "open chart"),
            ("w", "add to watchlist"),
            ("A", "new alert"),
            ("[ ]", "chart period"),
            ("c / C", "compare / clear compare"),
            ("← →", "chart crosshair"),
        ],
    ),
    (
        "View",
        [
            ("r", "refresh now"),
            ("p", "privacy mode"),
            ("t", "next theme"),
            ("g", "cycle allocation grouping"),
            (", .", "net worth range"),
        ],
    ),
]


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,question_mark", "close", "Close")]

    def compose(self) -> ComposeResult:
        body = Text()
        for section, keys in HELP:
            body.append(f"{section}\n", style="title")
            for key, desc in keys:
                body.append(f"  {key:<18}", style="accent")
                body.append(f"{desc}\n")
            body.append("\n")
        body.append("Themes follow Omarchy — `marketpulse theme set <name>` or ctrl+p → theme.", style="muted")
        with Vertical(classes="modal"):
            yield Label("MarketPulse keys", classes="modal-title")
            yield VerticalScroll(Static(body))

    def action_close(self) -> None:
        self.dismiss(None)
