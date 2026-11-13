"""Fictional saved data proves the offline ledger rollup report sources."""

from __future__ import annotations

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse import db
from marketpulse.cli import main, report_portfolio
from marketpulse.cli.base import App
from marketpulse.cli.report_ledger import SOURCES, load_source
from marketpulse.db import Snapshot
from marketpulse.models import Account, AccountType, Alert, Asset, AssetKind, Quote, Transaction, TxnType

ARCHIVED = "Archived Fictional"


@pytest.fixture
def app(tracker, monkeypatch):
    """A CLI context on the isolated store, for direct calls and for commands run through Click."""
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    return App()


@pytest.fixture
def ledger_app(app):
    store = app.store
    cash = store.add_account(Account("Fictional Cash", AccountType.TFSA, track_cash=True)).saved_id  # 1
    archived = store.add_account(Account(ARCHIVED, currency="GBP", track_cash=True, archived=True)).saved_id  # 2
    invested = store.add_account(Account("Fictional Invested", currency="USD")).saved_id  # 3
    store.add_account(Account("Fictional Empty", AccountType.RRSP))  # 4
    # Saved in this order, so a transaction's id is its position below (1 to 19).
    for txn in (
        Transaction(cash, TxnType.DEPOSIT, "2024-01-02", amount=5000),
        Transaction(cash, TxnType.BUY, "2024-01-03", "FIC.TO", 10, 20, fees=5),
        Transaction(cash, TxnType.BUY, "2024-01-04", "GONE.TO", 5, 10),
        Transaction(cash, TxnType.TRANSFER, "2024-01-15", "GONE.TO", 5, target_account_id=invested),
        Transaction(cash, TxnType.FEE, "2024-01-20", amount=12),
        Transaction(cash, TxnType.WITHDRAWAL, "2024-02-01", amount=300),
        # The archived account has the earliest and the latest records, its own currency and its own symbol.
        Transaction(archived, TxnType.DEPOSIT, "2023-12-01", amount=900),
        Transaction(archived, TxnType.BUY, "2023-12-15", "FIC.TO", 7, 20, fees=3),
        Transaction(archived, TxnType.BUY, "2024-01-05", "HIDDEN.L", 2, 30, fees=4),
        Transaction(archived, TxnType.SELL, "2024-01-08", "HIDDEN.L", 9, 31, fees=2),
        Transaction(archived, TxnType.FEE, "2024-01-09", amount=7),
        Transaction(archived, TxnType.WITHDRAWAL, "2024-03-01", amount=50),
        Transaction(invested, TxnType.DEPOSIT, "2024-02-01", amount=1000),
        Transaction(invested, TxnType.BUY, "2024-01-02", "FIC.TO", 4, 21, fees=1.25),
        Transaction(invested, TxnType.SELL, "2024-01-18", "GONE.TO", 5, 12, fees=1.5),
        Transaction(invested, TxnType.BUY, "2024-01-20", "FICUS", 3, 100, fees=2.5),
        Transaction(invested, TxnType.BUY, "2024-01-22", "OVER.TO", 2, 8),
        Transaction(invested, TxnType.SELL, "2024-01-25", "OVER.TO", 5, 9, fees=0.5),
        Transaction(invested, TxnType.DIVIDEND, "2024-02-05", "GONE.TO", amount=6, fees=9),
    ):
        store.add_transaction(txn)
    store.upsert_asset(Asset("FIC.TO", name="Fictional Fund", currency="CAD"))
    store.upsert_asset(Asset("FICGIC", AssetKind.FIXED_INCOME, "Fictional GIC", currency="CAD", rate=4))
    store.add_watch(["FICUS", "WATCH.TO"])
    store.add_alert(Alert("FICUS", "above", 150, note="fictional alert"))
    store.add_alert(Alert("FICUS", "below", 80))
    store.add_alert(Alert("ALERT.TO", "up_pct", 5, active=False))
    store.cache_quotes(
        [
            Quote("FIC.TO", 21, 20.5, currency="CAD", fetched_at=1700000000),
            Quote("FICUS", 110, 108, currency="USD", fetched_at=1700000000),
            Quote("FICEUR.PA", 9, 9, currency="EUR", fetched_at=1700000000),
        ]
    )
    store.set_room("TFSA", 2024, 7000)
    store.set_room("RRSP", 2023, 12500.5)
    store.upsert_snapshot(Snapshot("2024-02-05", 5000, 4800, 4700, "CAD", {}))
    store.backup()
    return app


# Worked out by hand from the fixture above, never by calling the adapter. Each tuple is one row in
# its source's field order; numbers are written with the JSON type the row carries.
EXPECTED: dict[str, list[tuple]] = {
    # symbol, currency, accounts, quantity, book, first_date
    "holdings": [
        ("FIC.TO", "CAD", 2, 14.0, 290.25, "2024-01-02"),  # 10 @ 20 + 5 and 4 @ 21 + 1.25; not the archived 7
        ("FICUS", "USD", 1, 3.0, 302.5, "2024-01-20"),  # 3 @ 100 + 2.5
    ],
    # account_id, account, symbol, currency, first_date, last_date, transactions
    "closed-positions": [
        (1, "Fictional Cash", "GONE.TO", "CAD", "2024-01-04", "2024-01-15", 2),  # bought, moved out
        (3, "Fictional Invested", "GONE.TO", "CAD", "2024-01-15", "2024-02-05", 3),  # moved in, sold, paid
        (3, "Fictional Invested", "OVER.TO", "CAD", "2024-01-22", "2024-01-25", 2),  # bought, oversold
    ],
    # date, account_id, account, amount, currency
    "cash-flows": [
        ("2024-01-02", 1, "Fictional Cash", 5000.0, "CAD"),
        ("2024-02-01", 3, "Fictional Invested", 1000.0, "USD"),  # replayed before that day's withdrawal
        ("2024-02-01", 1, "Fictional Cash", -300.0, "CAD"),
    ],
    # transaction_id, date, account_id, account, type, symbol, fee, currency
    "fees": [
        (14, "2024-01-02", 3, "Fictional Invested", "BUY", "FIC.TO", 1.25, "CAD"),
        (2, "2024-01-03", 1, "Fictional Cash", "BUY", "FIC.TO", 5.0, "CAD"),
        (15, "2024-01-18", 3, "Fictional Invested", "SELL", "GONE.TO", 1.5, "CAD"),
        (16, "2024-01-20", 3, "Fictional Invested", "BUY", "FICUS", 2.5, "USD"),  # buys replay before fees
        (5, "2024-01-20", 1, "Fictional Cash", "FEE", "", 12.0, "CAD"),
        (18, "2024-01-25", 3, "Fictional Invested", "SELL", "OVER.TO", 0.5, "CAD"),
    ],
    # transaction_id, date, account_id, account, code, message, details
    "ledger-issues": [
        (
            18,
            "2024-01-25",
            3,
            "Fictional Invested",
            "sell_exceeds_held",
            "Sell of 5.0000 OVER.TO exceeds 2.0000 held",
            {"symbol": "OVER.TO", "quantity": 5.0, "held": 2.0},
        ),
    ],
    # symbol, transactions, first_date, last_date, held, watched, alerts, asset_kind, cached_quote
    "symbols": [
        ("ALERT.TO", 0, None, None, False, False, 1, None, False),
        ("FIC.TO", 2, "2024-01-02", "2024-01-03", True, False, 0, "market", True),  # not the 2023 purchase
        ("FICEUR.PA", 0, None, None, False, False, 0, None, True),
        ("FICGIC", 0, None, None, False, False, 0, "fixed_income", False),
        ("FICUS", 1, "2024-01-20", "2024-01-20", True, True, 2, None, True),
        ("GONE.TO", 4, "2024-01-04", "2024-02-05", False, False, 0, None, False),
        ("OVER.TO", 2, "2024-01-22", "2024-01-25", False, False, 0, None, False),
        ("WATCH.TO", 0, None, None, False, True, 0, None, False),
    ],
    # currency, base, accounts, transactions, positions, cash_balances, cached_quotes
    "currencies": [
        ("CAD", True, 2, 11, 2, 1, 1),
        ("EUR", False, 0, 0, 0, 0, 1),
        ("USD", False, 1, 2, 1, 0, 1),  # the deposit and the FICUS purchase
    ],
    # account_id, account, type, currency, transactions, first_date, last_date, open_positions, symbols
    "account-activity": [
        (1, "Fictional Cash", "TFSA", "CAD", 6, "2024-01-02", "2024-02-01", 1, 2),
        (3, "Fictional Invested", "NONREG", "USD", 8, "2024-01-02", "2024-02-05", 2, 4),  # with transfer #4 in
        (4, "Fictional Empty", "RRSP", "CAD", 0, None, None, 0, 0),
    ],
    # account_type, as_of_year, amount
    "rooms": [
        ("RRSP", 2023, 12500.5),
        ("TFSA", 2024, 7000.0),
    ],
}


def _json_native(value) -> bool:
    """Exactly a JSON type: an enum that merely serializes like a string does not count."""
    if type(value) is dict:
        return all(type(key) is str and _json_native(item) for key, item in value.items())
    if type(value) is list:
        return all(_json_native(item) for item in value)
    return type(value) in (str, int, float, bool, type(None))


@pytest.mark.parametrize("name", SOURCES)
def test_sources_return_the_hand_computed_rows(name, ledger_app):
    rows = load_source(name, ledger_app)
    expected = [dict(zip(SOURCES[name], values, strict=True)) for values in EXPECTED[name]]
    assert rows == expected
    # Python equates 1, 1.0 and True; the JSON text also holds rows to their types and column order.
    assert json.dumps(rows, allow_nan=False) == json.dumps(expected)
    assert all(tuple(row) == SOURCES[name] for row in rows)
    assert _json_native(rows)
    assert json.loads(json.dumps(rows)) == rows


@pytest.mark.parametrize("name", SOURCES)
def test_sources_read_saved_data_without_network_or_writes(name, ledger_app, fake):
    store = ledger_app.store
    changes = store._conn.total_changes
    snapshots, backups = store.snapshots(), store.backups()
    assert snapshots and backups
    assert load_source(name, ledger_app)
    assert fake.calls == []
    assert store._conn.total_changes == changes
    assert store.snapshots() == snapshots
    assert store.backups() == backups


@pytest.mark.parametrize("name", SOURCES)
def test_sources_never_reveal_the_archived_account(name, ledger_app):
    archived = ledger_app.store.get_account(ARCHIVED)
    assert archived is not None and archived.archived
    rows = load_source(name, ledger_app)
    text = json.dumps(rows)
    assert ARCHIVED not in text
    assert "HIDDEN" not in text and "GBP" not in text  # the symbol and the currency only it uses
    assert all(row.get("account_id") != archived.id for row in rows)


@pytest.mark.parametrize("name", SOURCES)
def test_ledger_is_replayed_once_and_not_at_all_for_rooms(name, ledger_app, monkeypatch):
    replays = []
    replay = db.replay
    monkeypatch.setattr(db, "replay", lambda *args, **kwargs: replays.append(args) or replay(*args, **kwargs))
    load_source(name, ledger_app)
    assert len(replays) == (0 if name == "rooms" else 1)


@pytest.mark.parametrize("name", SOURCES)
def test_empty_saved_data_lists_only_the_base_currency(name, app):
    base = {
        "currency": "CAD",
        "base": True,
        "accounts": 0,
        "transactions": 0,
        "positions": 0,
        "cash_balances": 0,
        "cached_quotes": 0,
    }
    assert load_source(name, app) == ([base] if name == "currencies" else [])


def test_unknown_source_is_rejected_before_opening_tracker(monkeypatch):
    monkeypatch.setattr(App, "store", property(lambda self: pytest.fail("must not open store")))
    with pytest.raises(KeyError, match="nope"):
        load_source("nope", App())


def test_base_currency_is_listed_even_when_unused_and_read_in_upper_case(ledger_app):
    ledger_app.config.base_currency = "jpy"  # a hand-edited setting; the engine reads it upper-cased
    rows = load_source("currencies", ledger_app)
    assert [(row["currency"], row["base"]) for row in rows] == [
        ("CAD", False),
        ("EUR", False),
        ("JPY", True),
        ("USD", False),
    ]
    assert [row[field] for row in rows if row["base"] for field in SOURCES["currencies"][2:]] == [0, 0, 0, 0, 0]


def test_sale_fee_is_in_the_currency_of_the_position_sold(app):
    store = app.store
    account = store.add_account(Account("Fictional Cash", track_cash=True)).saved_id
    for txn in (
        Transaction(account, TxnType.BUY, "2024-01-02", "FICUS", 4, 50, currency="USD"),
        # Neither sale says USD (the first would default to the account's CAD), yet both sell a USD position.
        Transaction(account, TxnType.SELL, "2024-01-03", "FICUS", 1, 55, fees=2),
        Transaction(account, TxnType.SELL, "2024-01-04", "FICUS", 1, 55, fees=3, currency="EUR"),
        # Nothing was ever held, so only the transaction itself names a currency.
        Transaction(account, TxnType.SELL, "2024-01-05", "NEVER.TO", 1, 5, fees=4, currency="EUR"),
        Transaction(account, TxnType.SELL, "2024-01-06", "NEVER.TO", 1, 5, fees=5),
        Transaction(account, TxnType.DRIP, "2024-01-07", "FICUS", 0.5, 50, fees=0.25, currency="USD"),
        # A purchase is charged in its own currency, here the account's, even into a USD position.
        Transaction(account, TxnType.BUY, "2024-01-08", "FICUS", 1, 50, fees=1),
        # Sold before anything was held: the USD position opened later had nothing to do with it.
        Transaction(account, TxnType.SELL, "2024-01-09", "FICLATE", 1, 5, fees=6),
        Transaction(account, TxnType.BUY, "2024-01-10", "FICLATE", 2, 5, currency="USD"),
    ):
        store.add_transaction(txn)
    assert [(row["type"], row["symbol"], row["fee"], row["currency"]) for row in load_source("fees", app)] == [
        ("SELL", "FICUS", 2, "USD"),
        ("SELL", "FICUS", 3, "USD"),
        ("SELL", "NEVER.TO", 4, "EUR"),
        ("SELL", "NEVER.TO", 5, "CAD"),
        ("DRIP", "FICUS", 0.25, "USD"),
        ("BUY", "FICUS", 1, "CAD"),
        ("SELL", "FICLATE", 6, "CAD"),
    ]
    # The engine agrees on each currency. It skips a sale of nothing, fee included, which the report still lists.
    assert dict(store.ledger().fees) == {"USD": 5.25, "CAD": 1}


def test_an_in_kind_transfer_counts_for_both_active_accounts(app):
    store = app.store
    rrsp = store.add_account(Account("Fictional RRSP", AccountType.RRSP)).saved_id
    rrif = store.add_account(Account("Fictional RRIF", AccountType.RRIF)).saved_id
    store.add_transaction(Transaction(rrsp, TxnType.BUY, "2024-01-02", "FIC.TO", 10, 20))
    store.add_transaction(Transaction(rrsp, TxnType.TRANSFER, "2025-12-31", "FIC.TO", 10, target_account_id=rrif))
    # As `activity -a` and `accounts list --has-transactions` count it: once in each account.
    assert [
        (
            row["account"],
            row["transactions"],
            row["first_date"],
            row["last_date"],
            row["open_positions"],
            row["symbols"],
        )
        for row in load_source("account-activity", app)
    ] == [
        ("Fictional RRSP", 2, "2024-01-02", "2025-12-31", 0, 1),
        ("Fictional RRIF", 1, "2025-12-31", "2025-12-31", 1, 1),
    ]
    assert len(store.transactions(account_id=rrif)) == 1


def test_holdings_pool_a_symbol_separately_in_each_currency(app):
    store = app.store
    for name, currency in (("Fictional One", "USD"), ("Fictional Two", "CAD"), ("Fictional Three", "USD")):
        account = store.add_account(Account(name)).saved_id
        store.add_transaction(Transaction(account, TxnType.BUY, "2024-01-02", "FICDUAL", 2, 10, currency=currency))
    assert load_source("holdings", app) == [
        {"symbol": "FICDUAL", "currency": "CAD", "accounts": 1, "quantity": 2, "book": 20, "first_date": "2024-01-02"},
        {"symbol": "FICDUAL", "currency": "USD", "accounts": 2, "quantity": 4, "book": 40, "first_date": "2024-01-02"},
    ]


def test_cash_balances_count_the_rows_of_the_cash_dataset(app):
    store = app.store
    tracked = store.add_account(Account("Fictional Cash", track_cash=True)).saved_id
    untracked = store.add_account(Account("Fictional Invested")).saved_id
    for txn in (
        Transaction(tracked, TxnType.DEPOSIT, "2024-01-02", amount=100),
        # Back to zero, which the `cash` dataset still lists.
        Transaction(tracked, TxnType.DEPOSIT, "2024-01-03", amount=40, currency="USD"),
        Transaction(tracked, TxnType.WITHDRAWAL, "2024-01-04", amount=40, currency="USD"),
        Transaction(untracked, TxnType.DEPOSIT, "2024-01-05", amount=70, currency="EUR"),
    ):
        store.add_transaction(txn)
    assert [(row["currency"], row["balance"]) for row in report_portfolio.load_source("cash", app)] == [
        ("CAD", 100),
        ("USD", 0),
    ]
    assert {row["currency"]: row["cash_balances"] for row in load_source("currencies", app)} == {
        "CAD": 1,
        "EUR": 0,
        "USD": 1,
    }


def test_transfers_with_an_archived_account_are_not_counted_but_received_positions_are_listed(app):
    store = app.store
    active = store.add_account(Account("Fictional Cash")).saved_id
    archived = store.add_account(Account(ARCHIVED, archived=True)).saved_id
    for txn in (
        Transaction(archived, TxnType.BUY, "2023-12-01", "DUST.TO", 5, 10),
        Transaction(archived, TxnType.BUY, "2023-12-01", "KEPT.TO", 6, 10),
        Transaction(archived, TxnType.BUY, "2023-12-01", "SOLD.TO", 3, 10),
        # Too little to open a position: one exists in the active account, at zero, with no visible transaction.
        Transaction(archived, TxnType.TRANSFER, "2024-01-05", "DUST.TO", 1e-10, target_account_id=active),
        Transaction(archived, TxnType.TRANSFER, "2024-01-05", "KEPT.TO", 6, target_account_id=active),
        Transaction(archived, TxnType.TRANSFER, "2024-01-05", "SOLD.TO", 3, target_account_id=active),
        Transaction(active, TxnType.SELL, "2024-01-10", "SOLD.TO", 3, 11),
        Transaction(active, TxnType.BUY, "2024-01-11", "SENT.TO", 2, 5),
        Transaction(active, TxnType.TRANSFER, "2024-01-12", "SENT.TO", 2, target_account_id=archived),
    ):
        store.add_transaction(txn)

    assert load_source("holdings", app) == [
        {"symbol": "KEPT.TO", "currency": "CAD", "accounts": 1, "quantity": 6, "book": 60, "first_date": "2024-01-05"}
    ]
    # The archived account's transfers in are not counted; the active account's own transfer out is.
    assert [
        (row["symbol"], row["first_date"], row["last_date"], row["transactions"])
        for row in load_source("closed-positions", app)
    ] == [
        ("DUST.TO", "2024-01-05", None, 0),
        ("SENT.TO", "2024-01-11", "2024-01-12", 2),
        ("SOLD.TO", "2024-01-05", "2024-01-10", 1),
    ]
    # A position received from the archived account is visible data, so its symbol is listed.
    assert [
        (row["symbol"], row["transactions"], row["first_date"], row["last_date"], row["held"])
        for row in load_source("symbols", app)
    ] == [
        ("DUST.TO", 0, None, None, False),
        ("KEPT.TO", 0, None, None, True),
        ("SENT.TO", 2, "2024-01-11", "2024-01-12", False),
        ("SOLD.TO", 1, "2024-01-10", "2024-01-10", False),
    ]
    assert load_source("account-activity", app) == [
        {
            "account_id": active,
            "account": "Fictional Cash",
            "type": "NONREG",
            "currency": "CAD",
            "transactions": 3,
            "first_date": "2024-01-10",
            "last_date": "2024-01-12",
            "open_positions": 1,
            "symbols": 2,
        }
    ]
    assert [(row["currency"], row["transactions"], row["positions"]) for row in load_source("currencies", app)] == [
        ("CAD", 3, 1)
    ]
    assert all(ARCHIVED not in json.dumps(load_source(name, app)) for name in SOURCES)


def test_numbers_json_cannot_carry_are_reported_as_null(app):
    store = app.store
    store.set_room("TFSA", 2024, float("inf"))  # what `accounts room TFSA 2024 inf` saves
    for name in ("Fictional One", "Fictional Two"):  # two positions whose pooled quantity overflows
        account = store.add_account(Account(name)).saved_id
        store.add_transaction(Transaction(account, TxnType.BUY, "2024-01-02", "FIC.TO", 1e308, 0))
    rooms, holdings = load_source("rooms", app), load_source("holdings", app)
    assert rooms == [{"account_type": "TFSA", "as_of_year": 2024, "amount": None}]
    assert holdings == [
        {"symbol": "FIC.TO", "currency": "CAD", "accounts": 2, "quantity": None, "book": 0, "first_date": "2024-01-02"}
    ]
    json.dumps([rooms, holdings], allow_nan=False)


def _invoke(*arguments: str) -> str:
    result = CliRunner().invoke(main, list(arguments))
    assert result.exit_code == 0, result.output
    return result.output


def test_report_command_filters_and_exports_pooled_holdings(ledger_app, fake):
    store = ledger_app.store
    changes = store._conn.total_changes
    output = _invoke("report", "holdings", "--where", "currency=CAD", "--format", "csv")
    assert list(csv.DictReader(io.StringIO(output))) == [
        {
            "symbol": "FIC.TO",
            "currency": "CAD",
            "accounts": "2",
            "quantity": "14.0",
            "book": "290.25",
            "first_date": "2024-01-02",
        }
    ]
    assert fake.calls == []
    assert store._conn.total_changes == changes


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            ["report", "symbols", "--where", "held=true", "--fields", "symbol,alerts"],
            [{"symbol": "FIC.TO", "alerts": 0}, {"symbol": "FICUS", "alerts": 2}],
        ),
        (
            ["report", "closed-positions", "--gt", "transactions=2", "--fields", "account,symbol,last_date"],
            [{"account": "Fictional Invested", "symbol": "GONE.TO", "last_date": "2024-02-05"}],
        ),
        (
            ["report", "account-activity", "--missing", "first_date", "--fields", "account,type"],
            [{"account": "Fictional Empty", "type": "RRSP"}],
        ),
        (
            ["summarize", "fees", "--group-by", "currency", "--metric", "total=number-sum:fee"],
            [{"currency": "CAD", "total": "20.25"}, {"currency": "USD", "total": "2.5"}],
        ),
        (
            ["summarize", "cash-flows", "--group-by", "account", "--metric", "net=number-sum:amount"],
            [{"account": "Fictional Cash", "net": "4700"}, {"account": "Fictional Invested", "net": "1000"}],
        ),
        (
            ["summarize", "ledger-issues", "--group-by", "code", "--metric", "issues=count"],
            [{"code": "sell_exceeds_held", "issues": 1}],
        ),
    ],
)
def test_report_and_summarize_commands_read_the_ledger_sources(ledger_app, fake, arguments, expected):
    store = ledger_app.store
    changes = store._conn.total_changes
    assert json.loads(_invoke(*arguments)) == expected
    assert fake.calls == []
    assert store._conn.total_changes == changes
