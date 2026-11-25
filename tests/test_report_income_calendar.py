"""Income payments can be audited by calendar year without replaying or repricing the ledger."""

import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.cli.base import App
from marketpulse.cli.report_income_calendar import SOURCES, load_source
from marketpulse.models import Account, Transaction, TxnType

SOURCE = "income-calendar"


@pytest.fixture
def income_app(tracker, monkeypatch, fake):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    monkeypatch.setattr(tracker.store, "ledger", lambda: pytest.fail("the income calendar should not replay"))
    yield App()
    assert not fake.calls


def _set_date(store, txn_id: int, day: str) -> None:
    # The store normalizes dates on write, so damaged history has to be planted directly.
    store._conn.execute("UPDATE transactions SET date = ? WHERE id = ?", (day, txn_id))
    store._conn.commit()


def _seed(store) -> tuple[int, int]:
    cad = store.add_account(Account("Fictional TFSA")).saved_id
    usd = store.add_account(Account("Fictional USD Cash", currency="USD", track_cash=True)).saved_id
    archived = store.add_account(Account("Fictional Archived", archived=True)).saved_id
    store.add_transactions(
        [
            Transaction(cad, TxnType.DIVIDEND, "2024-03-15", "FRUIT.TO", amount=0.1),
            Transaction(cad, TxnType.DIVIDEND, "2024-01-15", "FRUIT.TO", amount=0.2),
            Transaction(cad, TxnType.DRIP, "2024-03-15", "FRUIT.TO", 3, 0.1, fees=1),
            Transaction(cad, TxnType.DIVIDEND, "2024-06-15", "FRUIT.TO", amount=1, currency="USD"),
            Transaction(cad, TxnType.DIVIDEND, "2023-12-15", "FRUIT.TO", amount=5),
            Transaction(cad, TxnType.BUY, "2024-01-02", "FRUIT.TO", 10, 20),
            Transaction(cad, TxnType.DEPOSIT, "2024-01-01", amount=200),
            Transaction(usd, TxnType.INTEREST, "2024-02-29", amount=1.25),
            Transaction(usd, TxnType.INTEREST, "2024-02-01", amount=0.75),
            Transaction(usd, TxnType.DIVIDEND, "2024-07-01", "BERRY", amount=4),
            Transaction(archived, TxnType.DIVIDEND, "2024-01-15", "HIDDEN.TO", amount=9),
            Transaction(archived, TxnType.DRIP, "2024-01-15", "HIDDEN.TO", 1, 9),
        ]
    )
    return cad, usd


def test_income_calendar_groups_payments_by_year_account_symbol_and_currency(income_app):
    store = income_app.store
    cad, usd = _seed(store)
    changes = store._conn.total_changes

    rows = load_source(SOURCE, income_app)

    assert all(tuple(row) == SOURCES[SOURCE] for row in rows)
    assert [tuple(row.values()) for row in rows] == [
        (2023, cad, "Fictional TFSA", "FRUIT.TO", "CAD", 1, 1, 0, 5.0, [12], 1, "2023-12-15", "2023-12-15"),
        # The DRIP counts its reinvested value, quantity x price, without fees, as the ledger does.
        (2024, cad, "Fictional TFSA", "FRUIT.TO", "CAD", 3, 2, 1, 0.6, [1, 3], 2, "2024-01-15", "2024-03-15"),
        (2024, cad, "Fictional TFSA", "FRUIT.TO", "USD", 1, 1, 0, 1.0, [6], 1, "2024-06-15", "2024-06-15"),
        (2024, usd, "Fictional USD Cash", "", "USD", 2, 2, 0, 2.0, [2], 1, "2024-02-01", "2024-02-29"),
        (2024, usd, "Fictional USD Cash", "BERRY", "USD", 1, 1, 0, 4.0, [7], 1, "2024-07-01", "2024-07-01"),
    ]
    assert store._conn.total_changes == changes


def test_income_calendar_matches_the_ledgers_income_events(tracker, fake):
    app = App()
    app._tracker = tracker
    _seed(tracker.store)
    active = {account.saved_id for account in tracker.store.accounts()}
    totals: dict[tuple, float] = {}
    for event in tracker.store.ledger().income:
        if event.account_id in active:
            key = (int(event.date[:4]), event.account_id, event.symbol, event.currency)
            totals[key] = totals.get(key, 0.0) + event.amount

    rows = load_source(SOURCE, app)

    amounts = {(row["year"], row["account_id"], row["symbol"], row["currency"]): row["amount"] for row in rows}
    assert amounts == pytest.approx(totals)
    assert not fake.calls


def test_income_calendar_skips_dates_that_are_not_canonical(income_app):
    store = income_app.store
    account = store.add_account(Account("Fictional TFSA")).saved_id
    days = ["2024-01-15", "2024-02-30", "20240315", "2024-04-15x", "unknown", "0000-01-01", "2024-05-15"]
    store.add_transactions([Transaction(account, TxnType.DIVIDEND, "2024-01-01", "FRUIT.TO", amount=1) for _ in days])
    for txn, day in zip(store.transactions(), days, strict=True):
        _set_date(store, txn.saved_id, day)

    rows = load_source(SOURCE, income_app)

    assert [(row["year"], row["payments"], row["months"], row["first_date"], row["last_date"]) for row in rows] == [
        (2024, 2, [1, 5], "2024-01-15", "2024-05-15")
    ]


def test_income_calendar_is_empty_without_income(income_app):
    store = income_app.store
    account = store.add_account(Account("Fictional TFSA")).saved_id
    store.add_transactions([Transaction(account, TxnType.BUY, "2024-01-02", "FRUIT.TO", 1, 20)])

    assert load_source(SOURCE, income_app) == []


@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        ("monthly", [("FRUIT.TO", 13, 1, 12)]),
        ("reinvested", [("FRUIT.TO", 13, 1, 12), ("SEED.TO", 2, 2, 2)]),
        ("single-payment", [("", 1, 0, 1)]),
    ],
)
def test_income_calendar_presets_through_report_and_summarize(tracker, fake, monkeypatch, preset, expected):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    store = tracker.store
    account = store.add_account(Account("Fictional TFSA")).saved_id
    archived = store.add_account(Account("Fictional Archived", archived=True)).saved_id
    store.add_transactions(
        [
            *(Transaction(account, TxnType.DIVIDEND, f"2024-{m:02d}-15", "FRUIT.TO", amount=1) for m in range(1, 13)),
            Transaction(account, TxnType.DRIP, "2024-06-15", "FRUIT.TO", 1, 2),
            Transaction(account, TxnType.DRIP, "2024-01-15", "SEED.TO", 1, 2),
            Transaction(account, TxnType.DRIP, "2024-02-15", "SEED.TO", 1, 2),
            Transaction(account, TxnType.INTEREST, "2024-05-01", amount=3),
            Transaction(archived, TxnType.DRIP, "2024-06-15", "HIDDEN.TO", 1, 2),
        ]
    )
    changes = store._conn.total_changes
    runner = CliRunner()
    fields = "symbol,payments,drip_payments,distinct_months"

    report = runner.invoke(main, ["report", SOURCE, "--preset", preset, "--fields", fields])
    metrics = ["--metric", "rows=count", "--metric", "payments=number-sum:payments"]
    summary = runner.invoke(main, ["summarize", SOURCE, "--preset", preset, *metrics])

    assert report.exit_code == 0, report.output
    assert [tuple(row.values()) for row in json.loads(report.output)] == expected
    assert summary.exit_code == 0, summary.output
    assert json.loads(summary.output) == [{"rows": len(expected), "payments": str(sum(row[1] for row in expected))}]
    assert store._conn.total_changes == changes
    assert not fake.calls
