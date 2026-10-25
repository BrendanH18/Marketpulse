"""Broker CSV profiles: how one brokerage's export maps onto MarketPulse's import fields.

The importer works on canonical fields (`date`, `type`, `symbol`, `quantity`, `price`,
`amount`, `fees`, `currency`, `account`, `note`, `ratio`, `target_account`). A profile
turns one row of a broker's export into those fields, or rejects the row with a reason.
A profile that can't tell which listing a row is about sets `symbol_choices` (listings
separated by spaces); the importer uses the one the account holds, or skips the row.

- `generic` maps common column names (see `_ALIASES`) and guesses transaction types
  from keywords. It's the fallback for any file no other profile recognizes.
- Named profiles are identified by their header row and translate the broker's own
  transaction codes through a table. A row whose code isn't in the table is skipped,
  never guessed.

To add a broker: write a `_convert_<broker>` function driven by a code table, add a
`BrokerProfile` to `PROFILES`, and add a fictional export under `tests/fixtures/brokers/`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .models import TxnType

Fields = dict[str, str]

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


class RowError(ValueError):
    """A row the importer can't use; `field` is the canonical field at fault, if any."""

    def __init__(self, reason: str, field: str = "", value: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.field = field
        self.value = value


def norm(header: str) -> str:
    return re.sub(r"\s+", " ", header.strip().lower().replace("_", " "))


def map_headers(headers: list[str]) -> dict[str, str]:
    """Map MarketPulse field names onto the CSV's actual column headers."""
    normalized = {norm(h): h for h in headers}
    mapping = {}
    for field_name, aliases in _ALIASES.items():
        for alias in aliases:
            if norm(alias) in normalized:
                mapping[field_name] = normalized[norm(alias)]
                break
    return mapping


@dataclass(frozen=True)
class BrokerProfile:
    name: str  # what `--profile` takes
    label: str  # what people see
    # Normalized headers that must all be present for auto-detection; empty for generic.
    headers: frozenset[str]
    # (row keyed by normalized header) -> canonical fields; raises RowError to skip the row.
    convert: Callable[[Mapping[str, str]], Fields] | None
    has_accounts: bool  # whether rows name their own account
    limits: str = ""  # shown in docs and `--help`

    def columns_missing(self, headers: list[str]) -> list[str]:
        present = {norm(h) for h in headers}
        return sorted(self.headers - present)


def _cell(row: Mapping[str, str], header: str) -> str:
    return (row.get(header) or "").strip()


def parse_number(raw: str | None, field: str = "") -> float | None:
    """A number from a CSV cell, sign kept; None when blank. Anything else unreadable is a RowError."""
    if raw is None:
        return None
    s = raw.strip().replace(",", "").replace("$", "").replace("€", "").replace("£", "")
    if not s or s in {"-", "—"}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    try:
        v = float(s.strip("()"))
    except ValueError:
        raise RowError("expected a number like 1234.56", field, raw) from None
    return -v if neg else v


# Cash direction a broker's signed amount must have for each type: money in (+1) or out (-1).
# A row with the opposite sign is a reversal, a correction or withholding tax; importing it
# as the type would count it the wrong way, so it is skipped for the user to record by hand.
_CASH_DIRECTION = {
    TxnType.BUY: -1,
    TxnType.SELL: 1,
    TxnType.DIVIDEND: 1,
    TxnType.INTEREST: 1,
    TxnType.DEPOSIT: 1,
    TxnType.WITHDRAWAL: -1,
    TxnType.FEE: -1,
}


def _check_direction(txn_type: TxnType, amount: float | None, raw: str) -> None:
    want = _CASH_DIRECTION.get(txn_type)
    if want is None or not amount or (amount > 0) == (want > 0):
        return
    sign = "negative" if amount < 0 else "positive"
    raise RowError(f"{sign} amount on a {txn_type.value} (a reversal or correction?); record it by hand", "amount", raw)


# ── Questrade ────────────────────────────────────────────────────────────────
# Account activity exported from Reports › Account activity (saved as CSV). Rows carry
# an "Activity Type" category and an "Action" code; the category is the stable one.

_TRADE = "trade"
# Each category maps to a type, to _TRADE, or to the reason its rows are skipped.
_QUESTRADE_ACTIVITY: dict[str, TxnType | str] = {
    "trades": _TRADE,  # Buy / Sell from the Action column
    "dividends": TxnType.DIVIDEND,
    # The dividend arrives as its own cash row; the reinvestment is a purchase with it.
    # (A DRIP would count the income a second time and never spend the cash.)
    "dividend reinvestment": TxnType.BUY,
    "interest": TxnType.INTEREST,
    "deposits": TxnType.DEPOSIT,
    "withdrawals": TxnType.WITHDRAWAL,
    "fees and rebates": TxnType.FEE,
    "transfers": "transfers between institutions aren't imported; record them as a deposit or buys",
    "fx conversion": "currency conversions aren't imported; MarketPulse tracks each currency's cash separately",
    "corporate actions": "corporate actions aren't imported; record splits or mergers by hand",
    "other": "Questrade lists this as 'Other'; record it by hand if it matters",
}

_QUESTRADE_TRADES = {"buy": TxnType.BUY, "sell": TxnType.SELL}


def _questrade_account(row: Mapping[str, str]) -> str:
    kind = _cell(row, "account type") or "account"
    number = re.sub(r"\D", "", _cell(row, "account #"))
    # The full number: two accounts whose numbers end alike must not be merged into one.
    return f"Questrade {kind} {number}" if number else f"Questrade {kind}"


def _convert_questrade(row: Mapping[str, str]) -> Fields:
    activity = _cell(row, "activity type")
    mapped = _QUESTRADE_ACTIVITY.get(activity.lower())
    if mapped is None:
        raise RowError(f"Questrade activity type '{activity}' isn't supported", "type", activity)
    action = _cell(row, "action")
    # TxnType is a str too, so test for it before treating a string as a skip reason.
    if isinstance(mapped, TxnType):
        txn_type = mapped
    elif mapped == _TRADE:
        if action.lower() not in _QUESTRADE_TRADES:
            raise RowError(f"Questrade trade action '{action}' isn't a buy or sell", "type", action)
        txn_type = _QUESTRADE_TRADES[action.lower()]
    else:
        raise RowError(mapped, "type", activity)
    raw_amount = _cell(row, "net amount")
    _check_direction(txn_type, parse_number(raw_amount, "amount"), raw_amount)
    return {
        "date": _cell(row, "transaction date"),
        "type": txn_type.value,
        "symbol": _cell(row, "symbol"),
        "quantity": _cell(row, "quantity"),
        "price": _cell(row, "price"),
        "amount": raw_amount,
        "fees": _cell(row, "commission"),
        "currency": _cell(row, "currency"),
        "account": _questrade_account(row),
        "note": _cell(row, "description"),
    }


# ── Wealthsimple ─────────────────────────────────────────────────────────────
# Monthly account statements exported as CSV: one account per file, a transaction code,
# and the security, share count and FX rate written into the description.

# Each code maps to a type or to the reason its rows are skipped.
_WEALTHSIMPLE_CODES: dict[str, TxnType | str] = {
    "BUY": TxnType.BUY,
    "SELL": TxnType.SELL,
    "DIV": TxnType.DIVIDEND,
    "CONT": TxnType.DEPOSIT,
    "DEP": TxnType.DEPOSIT,
    "WD": TxnType.WITHDRAWAL,
    "INT": TxnType.INTEREST,
    "FPLINT": TxnType.INTEREST,  # stock-lending interest
    "FEE": TxnType.FEE,
    "NRT": "non-resident withholding tax isn't imported; record it as a fee by hand",
    "TRFIN": "transfers between institutions aren't imported; record them as a deposit or buys",
    "TRFOUT": "transfers between institutions aren't imported; record them as a withdrawal or sells",
    "TRFINTF": "transfers between institutions aren't imported; record them as a deposit or buys",
    "LOAN": "securities lending doesn't change your holdings",
    "RECALL": "securities lending doesn't change your holdings",
    "STKDIS": "stock distributions aren't imported; record a split or buy by hand",
    "STKREORG": "corporate actions aren't imported; record splits or mergers by hand",
}

_CANADIAN_SUFFIXES = (".TO", ".V", ".NE", ".CN")
_WS_SYMBOL = re.compile(r"^\s*([A-Z0-9][A-Z0-9.\-]*)\s+-\s+")
_WS_SHARES = re.compile(r"\b(?:bought|sold|purchased|reinvested)\s+([\d,]*\.?\d+)\s+shares?\b", re.IGNORECASE)


def _wealthsimple_symbols(description: str, currency: str) -> list[str]:
    """The listings a statement's bare ticker may stand for, most likely first."""
    m = _WS_SYMBOL.match(description)
    if not m:
        return []
    symbol = m.group(1)
    # A CAD amount without an FX conversion suggests a Canadian listing, which Yahoo quotes
    # with an exchange suffix; assume the TSX (".TO"). Yahoo writes share classes and trust
    # units with a dash (RCI.B → RCI-B.TO, REI.UN → REI-UN.TO).
    if currency.upper() == "CAD" and "fx rate" not in description.lower() and not symbol.endswith(_CANADIAN_SUFFIXES):
        return [symbol.replace(".", "-") + ".TO", symbol]
    return [symbol]


def _convert_wealthsimple(row: Mapping[str, str]) -> Fields:
    code = _cell(row, "transaction")
    mapped = _WEALTHSIMPLE_CODES.get(code.upper())
    if mapped is None:
        raise RowError(f"Wealthsimple transaction code '{code}' isn't supported", "type", code)
    if not isinstance(mapped, TxnType):
        raise RowError(mapped, "type", code)
    description = _cell(row, "description")
    currency = _cell(row, "currency")
    raw_amount = _cell(row, "amount")
    _check_direction(mapped, parse_number(raw_amount, "amount"), raw_amount)
    fields: Fields = {
        "date": _cell(row, "date"),
        "type": mapped.value,
        "amount": raw_amount,
        "currency": currency,
        "note": description,
    }
    if mapped.needs_symbol:
        symbols = _wealthsimple_symbols(description, currency)
        if not symbols:
            raise RowError("couldn't read the symbol from the description", "symbol", description)
        fields["symbol"] = symbols[0]
        if not mapped.uses_quantity and len(symbols) > 1:
            # A trade's FX rate shows a converted US purchase; a dividend paid in CAD doesn't
            # say, so it goes to whichever listing the account holds.
            fields["symbol_choices"] = " ".join(symbols)
    if mapped.uses_quantity:
        m = _WS_SHARES.search(description)
        if not m:
            raise RowError("couldn't read the share count from the description", "quantity", description)
        fields["quantity"] = m.group(1)
    return fields


GENERIC = BrokerProfile(
    name="generic",
    label="Generic CSV",
    headers=frozenset(),
    convert=None,
    has_accounts=False,  # decided per file by whether an account column is present
    limits="Common column names and transaction words; anything ambiguous is skipped.",
)

PROFILES = [
    BrokerProfile(
        name="questrade",
        label="Questrade",
        headers=frozenset({"transaction date", "action", "symbol", "net amount", "activity type", "account #"}),
        convert=_convert_questrade,
        has_accounts=True,
        limits=(
            "Account activity export. Transfers, currency conversions and corporate actions are skipped. "
            "New accounts are named 'Questrade <account type> <account number>'."
        ),
    ),
    BrokerProfile(
        name="wealthsimple",
        label="Wealthsimple",
        headers=frozenset({"date", "transaction", "description", "amount", "balance", "currency"}),
        convert=_convert_wealthsimple,
        has_accounts=False,
        limits=(
            "Monthly statement CSV, one account per file. Bare CAD tickers are assumed to trade on the "
            "TSX ('.TO'); fix NEO or CSE listings afterwards. Withholding tax and transfers are skipped."
        ),
    ),
    GENERIC,
]

PROFILE_NAMES = ["auto", *(p.name for p in PROFILES)]


def detect(headers: list[str]) -> BrokerProfile:
    """The named profile whose headers the file has, else generic."""
    return next((p for p in PROFILES if p.headers and not p.columns_missing(headers)), GENERIC)


def resolve(name: str, headers: list[str]) -> BrokerProfile:
    """The profile to use for `name` ("auto" detects one). A named profile must match the file."""
    if name == "auto":
        return detect(headers)
    profile = next((p for p in PROFILES if p.name == name), None)
    if profile is None:
        raise ValueError(f"Unknown broker profile '{name}'. Choose one of: {', '.join(PROFILE_NAMES)}.")
    if missing := profile.columns_missing(headers):
        raise ValueError(f"This file doesn't look like a {profile.label} export: no {', '.join(missing)} column(s).")
    return profile


def names_accounts(profile: BrokerProfile, headers: list[str]) -> bool:
    """Whether the file's rows say which account they belong to."""
    if profile.convert is None:
        return "account" in map_headers(headers)
    return profile.has_accounts
