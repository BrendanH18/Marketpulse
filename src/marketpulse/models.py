"""Core data models for MarketPulse.

Everything the app knows about your money is an append-only ledger of
Transactions grouped into Accounts. Holdings, cash, cost base, income and
realized gains are all *derived* by replaying that ledger (see ledger.py),
so there is exactly one source of truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from enum import StrEnum

# Tolerance for float share arithmetic (fractional shares accumulate error)
EPSILON = 1e-9


# ── Enumerations ──────────────────────────────────────────────────────────────


class AccountType(StrEnum):
    TFSA = "TFSA"
    RRSP = "RRSP"
    FHSA = "FHSA"
    RESP = "RESP"
    LIRA = "LIRA"
    RRIF = "RRIF"
    NONREG = "NONREG"
    MARGIN = "MARGIN"
    CRYPTO = "CRYPTO"
    CASH = "CASH"
    OTHER = "OTHER"

    @property
    def registered(self) -> bool:
        """Tax-sheltered in Canada: no capital gains reporting inside."""
        return self in _REGISTERED

    @property
    def label(self) -> str:
        return _ACCOUNT_LABELS[self]


_REGISTERED = {
    AccountType.TFSA,
    AccountType.RRSP,
    AccountType.FHSA,
    AccountType.RESP,
    AccountType.LIRA,
    AccountType.RRIF,
}
_ACCOUNT_LABELS = {
    AccountType.TFSA: "TFSA",
    AccountType.RRSP: "RRSP",
    AccountType.FHSA: "FHSA",
    AccountType.RESP: "RESP",
    AccountType.LIRA: "LIRA",
    AccountType.RRIF: "RRIF",
    AccountType.NONREG: "Non-registered",
    AccountType.MARGIN: "Margin",
    AccountType.CRYPTO: "Crypto",
    AccountType.CASH: "Cash",
    AccountType.OTHER: "Other",
}


class TxnType(StrEnum):
    BUY = "BUY"  # quantity @ price, fees add to cost base
    SELL = "SELL"  # quantity @ price, fees reduce proceeds
    DIVIDEND = "DIVIDEND"  # cash income: amount
    DRIP = "DRIP"  # dividend reinvested: quantity @ price, counted as income
    INTEREST = "INTEREST"  # cash income: amount
    DEPOSIT = "DEPOSIT"  # external cash in: amount (a contribution)
    WITHDRAWAL = "WITHDRAWAL"  # external cash out: amount
    FEE = "FEE"  # account-level fee: amount
    SPLIT = "SPLIT"  # quantity multiplied by ratio, cost base unchanged
    ROC = "ROC"  # return of capital: amount reduces cost base
    TRANSFER = "TRANSFER"  # move quantity (at cost) to target_account
    VALUATION = "VALUATION"  # mark a manual asset at price (no quantity change)

    @property
    def needs_symbol(self) -> bool:
        return self not in {TxnType.DEPOSIT, TxnType.WITHDRAWAL, TxnType.FEE, TxnType.INTEREST}

    @property
    def uses_quantity(self) -> bool:
        return self in {TxnType.BUY, TxnType.SELL, TxnType.DRIP, TxnType.TRANSFER}

    @property
    def uses_amount(self) -> bool:
        return self in {
            TxnType.DIVIDEND,
            TxnType.INTEREST,
            TxnType.DEPOSIT,
            TxnType.WITHDRAWAL,
            TxnType.FEE,
            TxnType.ROC,
        }


class AssetKind(StrEnum):
    MARKET = "market"  # priced live from the market data provider
    FIXED_INCOME = "fixed_income"  # GIC / bond: priced by accrual
    MANUAL = "manual"  # real estate, private, collectibles: priced by valuations
    CASH = "cash"  # cash equivalent held as a symbol (e.g. HISA), price 1


class AssetClass(StrEnum):
    EQUITY = "equity"
    ETF = "etf"
    FUND = "fund"
    CRYPTO = "crypto"
    FIXED_INCOME = "fixed_income"
    CASH = "cash"
    REAL_ESTATE = "real_estate"
    COMMODITY = "commodity"
    ALTERNATIVE = "alternative"
    OTHER = "other"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title().replace("Etf", "ETF")


# Yahoo instrumentType -> AssetClass
_INSTRUMENT_CLASSES = {
    "EQUITY": AssetClass.EQUITY,
    "ETF": AssetClass.ETF,
    "MUTUALFUND": AssetClass.FUND,
    "CRYPTOCURRENCY": AssetClass.CRYPTO,
    "CURRENCY": AssetClass.CASH,
    "FUTURE": AssetClass.COMMODITY,
    "INDEX": AssetClass.OTHER,
    "MONEYMARKET": AssetClass.CASH,
}


def asset_class_for_instrument(instrument_type: str | None) -> AssetClass:
    return _INSTRUMENT_CLASSES.get((instrument_type or "").upper(), AssetClass.OTHER)


# ── Helpers ───────────────────────────────────────────────────────────────────


def today() -> str:
    return date.today().isoformat()


def parse_date(raw: str | date | None) -> str:
    """Normalize user input to ISO YYYY-MM-DD. Raises ValueError on garbage.

    Accepts YYYY-MM-DD, YYYY/MM/DD, full ISO timestamps, unambiguous
    MM/DD/YYYY or DD/MM/YYYY, and relative forms 'today', 'yesterday', '-3d'.
    """
    if raw is None or raw == "":
        return today()
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    s = raw.strip().lower()
    if s == "today":
        return today()
    if s == "yesterday":
        return date.fromordinal(date.today().toordinal() - 1).isoformat()
    if m := re.fullmatch(r"-(\d+)d", s):
        return date.fromordinal(date.today().toordinal() - int(m.group(1))).isoformat()
    s = s.replace("/", "-")
    try:
        if m := re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})(?:[ t].*)?", s):
            # Broker exports: MM-DD-YYYY (US) or DD-MM-YYYY (elsewhere); only accept it when unambiguous.
            a, b, year = int(m[1]), int(m[2]), int(m[3])
            if a > 12 >= b:
                day, month = a, b
            elif b > 12 >= a or a == b:
                month, day = a, b
            else:
                raise ValueError(f"Ambiguous date '{raw}' — use YYYY-MM-DD.")
            return date(year, month, day).isoformat()
        return datetime.fromisoformat(s).date().isoformat()
    except ValueError as e:
        if "Ambiguous" in str(e):
            raise
        raise ValueError(f"Invalid date '{raw}' — use YYYY-MM-DD.") from None


def parse_symbols(raw: str) -> list[str]:
    """Split user input into upper-cased, de-duplicated symbols."""
    seen: set[str] = set()
    out = []
    for token in raw.replace(",", " ").split():
        sym = token.upper()
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


_SUFFIX_CURRENCIES = {
    ".TO": "CAD",
    ".V": "CAD",
    ".NE": "CAD",
    ".CN": "CAD",
    ".L": "GBP",
    ".PA": "EUR",
    ".DE": "EUR",
    ".AS": "EUR",
    ".MI": "EUR",
    ".SW": "CHF",
    ".T": "JPY",
    ".HK": "HKD",
    ".AX": "AUD",
}


def guess_currency(symbol: str, default: str = "USD") -> str:
    """Best-effort trading currency from a Yahoo symbol, used when no quote is available."""
    s = symbol.upper()
    for suffix, ccy in _SUFFIX_CURRENCIES.items():
        if s.endswith(suffix):
            return ccy
    if m := re.fullmatch(r"[A-Z0-9]+-([A-Z]{3})", s):
        return m.group(1)
    if s.endswith("=X") and len(s) == 8:
        return s[3:6]
    return default


# ── Entities ──────────────────────────────────────────────────────────────────


@dataclass
class Account:
    name: str
    type: AccountType = AccountType.NONREG
    currency: str = "CAD"
    institution: str = ""
    track_cash: bool = False
    id: int | None = None
    archived: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def saved_id(self) -> int:
        """The database id of an account that has been stored.

        `id` is None until Store.add_account() assigns one. Code that needs a
        real id (to reference the account from a transaction, or delete it)
        uses this instead, so an unsaved account fails loudly here rather
        than slipping None into a query that then silently matches nothing.
        """
        if self.id is None:
            raise ValueError(f"Account '{self.name}' hasn't been saved yet.")
        return self.id


@dataclass
class Transaction:
    account_id: int
    type: TxnType
    date: str = field(default_factory=today)
    symbol: str = ""
    quantity: float = 0.0
    price: float = 0.0
    amount: float = 0.0
    fees: float = 0.0
    currency: str = ""
    note: str = ""
    ratio: float = 0.0  # SPLIT: new shares per old share
    target_account_id: int | None = None  # TRANSFER destination
    id: int | None = None

    def __post_init__(self) -> None:
        self.type = TxnType(self.type)
        self.symbol = self.symbol.upper()
        self.currency = self.currency.upper()

    @property
    def saved_id(self) -> int:
        """The database id of a stored transaction (see Account.saved_id)."""
        if self.id is None:
            raise ValueError("Transaction hasn't been saved yet.")
        return self.id

    @property
    def gross_value(self) -> float:
        """Headline value of the transaction for ledgers and exports."""
        if self.type.uses_quantity:
            return self.quantity * self.price
        return self.amount

    def validate(self) -> None:
        t = self.type
        if t.needs_symbol and not self.symbol:
            raise ValueError(f"{t} needs a symbol.")
        if t.uses_quantity and self.quantity <= 0:
            raise ValueError("Quantity must be positive.")
        if t in {TxnType.BUY, TxnType.SELL, TxnType.DRIP, TxnType.VALUATION} and self.price < 0:
            raise ValueError("Price cannot be negative.")
        if t.uses_amount and self.amount < 0:
            raise ValueError("Amount cannot be negative.")
        if self.fees < 0:
            raise ValueError("Fees cannot be negative.")
        if t is TxnType.SPLIT and self.ratio <= 0:
            raise ValueError("Split ratio must be positive (e.g. 2 for a 2-for-1).")
        if t is TxnType.TRANSFER and (self.target_account_id is None or self.target_account_id == self.account_id):
            raise ValueError("Transfer needs a different target account.")
        if parse_date(self.date) > today():
            raise ValueError("Date cannot be in the future.")


@dataclass
class Asset:
    """Metadata for a symbol. Optional for market symbols; required for
    fixed income and manual assets, which the market can't price."""

    symbol: str
    kind: AssetKind = AssetKind.MARKET
    name: str = ""
    asset_class: AssetClass | None = None
    currency: str = ""
    # Fixed income
    rate: float = 0.0  # annual rate, percent
    compounding: str = "annual"  # annual | semiannual | quarterly | monthly | simple
    start_date: str = ""
    maturity_date: str = ""

    def __post_init__(self) -> None:
        self.symbol = self.symbol.upper()
        self.kind = AssetKind(self.kind)
        if self.asset_class is not None:
            self.asset_class = AssetClass(self.asset_class)

    def accrual_factor(self, on: str | None = None) -> float:
        """Growth of 1 unit of principal from start_date to `on` (capped at maturity)."""
        if self.kind is not AssetKind.FIXED_INCOME or not self.start_date:
            return 1.0
        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(on or today())
        if self.maturity_date:
            end = min(end, date.fromisoformat(self.maturity_date))
        years = max((end - start).days, 0) / 365.0
        r = self.rate / 100.0
        periods = {"annual": 1, "semiannual": 2, "quarterly": 4, "monthly": 12}.get(self.compounding)
        if periods is None:  # simple interest
            return 1.0 + r * years
        return (1.0 + r / periods) ** (periods * years)


@dataclass
class Quote:
    symbol: str
    price: float
    prev_close: float
    name: str = ""
    currency: str = "USD"
    exchange: str = ""
    instrument_type: str = ""
    day_high: float | None = None
    day_low: float | None = None
    volume: int | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    market_time: float | None = None  # epoch seconds of last trade
    market_state: str = ""  # PRE | REGULAR | POST | CLOSED | "" (unknown)
    intraday: list[float] = field(default_factory=list)
    fetched_at: float = 0.0
    stale: bool = False  # served from the offline cache

    @property
    def change(self) -> float:
        return self.price - self.prev_close

    @property
    def change_pct(self) -> float:
        return (self.change / self.prev_close * 100) if self.prev_close else 0.0

    @property
    def asset_class(self) -> AssetClass:
        return asset_class_for_instrument(self.instrument_type)


@dataclass
class Bar:
    time: float  # epoch seconds
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    offset: int = 0  # exchange UTC offset in seconds (Yahoo meta.gmtoffset)

    @property
    def date(self) -> str:
        """Calendar date at the exchange, not on this machine."""
        return datetime.fromtimestamp(self.time + self.offset, tz=UTC).date().isoformat()

    def local(self) -> datetime:
        """Bar time as a tz-aware datetime in the exchange's zone."""
        return datetime.fromtimestamp(self.time, tz=timezone(timedelta(seconds=self.offset)))


@dataclass
class FxRates:
    """Spot FX rates: rates[ccy] = base units per 1 unit of ccy."""

    base: str
    rates: dict[str, float] = field(default_factory=dict)
    stale: bool = False  # any rate came from the offline cache

    def rate(self, currency: str) -> float | None:
        if not currency or currency.upper() == self.base:
            return 1.0
        return self.rates.get(currency.upper())

    def convert(self, amount: float, currency: str) -> float | None:
        r = self.rate(currency)
        return None if r is None else amount * r


@dataclass
class Alert:
    symbol: str
    condition: str  # above | below | up_pct | down_pct
    threshold: float
    note: str = ""
    active: bool = True
    triggered_at: str = ""  # set while the condition holds; cleared when it re-arms
    id: int | None = None

    def __post_init__(self) -> None:
        self.symbol = self.symbol.upper()
        if self.condition not in ALERT_CONDITIONS:
            raise ValueError(f"Alert condition must be one of: {', '.join(ALERT_CONDITIONS)}")

    @property
    def saved_id(self) -> int:
        """The database id of a stored alert (see Account.saved_id)."""
        if self.id is None:
            raise ValueError("Alert hasn't been saved yet.")
        return self.id

    def describe(self) -> str:
        return {
            "above": f"{self.symbol} ≥ {self.threshold:,.2f}",
            "below": f"{self.symbol} ≤ {self.threshold:,.2f}",
            "up_pct": f"{self.symbol} up {self.threshold:g}% today",
            "down_pct": f"{self.symbol} down {self.threshold:g}% today",
        }[self.condition]

    def is_met(self, quote: Quote) -> bool:
        return {
            "above": quote.price >= self.threshold,
            "below": quote.price <= self.threshold,
            "up_pct": quote.change_pct >= self.threshold,
            "down_pct": quote.change_pct <= -self.threshold,
        }[self.condition]


ALERT_CONDITIONS = ("above", "below", "up_pct", "down_pct")
