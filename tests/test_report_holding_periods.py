"""Holding periods: each episode an active account held a symbol, from fictional ledger entries."""

import json
from collections import defaultdict

import pytest
from click.testing import CliRunner

from marketpulse.cli import main, report_ledger
from marketpulse.cli.base import App
from marketpulse.cli.report_holding_periods import PRESETS, SOURCES, load_source
from marketpulse.db import Store
from marketpulse.models import Account, Transaction, TxnType

SOURCE = "holding-periods"
BUY, SELL, DRIP, SPLIT, TRANSFER = TxnType.BUY, TxnType.SELL, TxnType.DRIP, TxnType.SPLIT, TxnType.TRANSFER

# (account_id, account, symbol, episode, status, opened, closed, days_held, increases, decreases, peak, quantity)
CASH, MARGIN = "Fictional Cash", "Fictional Margin"
EXPECTED = [
    # A DRIP raises the quantity and counts as an increase.
    (1, CASH, "DRIPCO", 1, "closed", "2023-01-05", "2024-12-31", 726, 2, 1, 2.5, 0.0),
    # Reopened after closing: a second episode, numbered by opening.
    (1, CASH, "FRUIT", 1, "closed", "2023-01-10", "2023-06-01", 142, 1, 2, 10.0, 0.0),
    (1, CASH, "FRUIT", 2, "open", "2024-01-02", None, None, 2, 0, 5.0, 5.0),
    # Transferred to another active account: closed here, opened there on the transfer date.
    (1, CASH, "MOVE", 1, "closed", "2023-01-01", "2023-08-01", 212, 1, 1, 8.0, 0.0),
    # A 2-for-1 split doubles the quantity and the peak but counts as neither an increase nor a decrease.
    (1, CASH, "SPLITCO", 1, "open", "2023-02-01", None, None, 1, 1, 10.0, 7.0),
    # Moved in from an archived account: the episode opens on the transfer, as holdings does.
    (2, MARGIN, "BACK", 1, "open", "2023-11-01", None, None, 1, 0, 5.0, 5.0),
    # Bought and sold on one day.
    (2, MARGIN, "FLIP", 1, "closed", "2024-03-01", "2024-03-01", 0, 1, 1, 1.0, 0.0),
    (2, MARGIN, "FRUIT", 1, "open", "2024-05-01", None, None, 1, 0, 1.0, 1.0),
    # Transferred out to an archived account: the transfer closes the active account's episode.
    (2, MARGIN, "GONE", 1, "closed", "2023-09-01", "2023-10-01", 30, 1, 1, 4.0, 0.0),
    (2, MARGIN, "MOVE", 1, "open", "2023-08-01", None, None, 1, 0, 8.0, 8.0),
]


@pytest.fixture
def app(tracker, monkeypatch, fake):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    store = tracker.store
    cash = store.add_account(Account(CASH)).saved_id
    margin = store.add_account(Account(MARGIN)).saved_id
    archived = store.add_account(Account("Fictional Archived", archived=True)).saved_id
    store.add_transactions(
        [
            Transaction(cash, BUY, "2023-01-10", "FRUIT", 10, 5),
            Transaction(cash, SELL, "2023-03-01", "FRUIT", 4, 6),
            Transaction(cash, SELL, "2023-06-01", "FRUIT", 6, 6),
            Transaction(cash, BUY, "2024-01-02", "FRUIT", 3, 5),
            Transaction(cash, BUY, "2024-02-01", "FRUIT", 2, 5),
            Transaction(cash, BUY, "2023-02-01", "SPLITCO", 5, 10),
            Transaction(cash, SPLIT, "2023-05-01", "SPLITCO", ratio=2),
            Transaction(cash, SELL, "2023-07-01", "SPLITCO", 3, 6),
            Transaction(cash, BUY, "2023-01-05", "DRIPCO", 2, 20),
            Transaction(cash, DRIP, "2023-04-01", "DRIPCO", 0.5, 20),
            Transaction(cash, SELL, "2024-12-31", "DRIPCO", 2.5, 21),
            Transaction(cash, BUY, "2023-01-01", "MOVE", 8, 3),
            Transaction(cash, TRANSFER, "2023-08-01", "MOVE", 8, target_account_id=margin),
            Transaction(margin, BUY, "2023-09-01", "GONE", 4, 7),
            Transaction(margin, TRANSFER, "2023-10-01", "GONE", 4, target_account_id=archived),
            Transaction(archived, BUY, "2022-01-01", "BACK", 5, 9),
            Transaction(archived, TRANSFER, "2023-11-01", "BACK", 5, target_account_id=margin),
            Transaction(archived, BUY, "2023-01-01", "HIDDEN", 1, 1),
            # Entered sell first: same-day order still buys before it sells.
            Transaction(margin, SELL, "2024-03-01", "FLIP", 1, 1),
            Transaction(margin, BUY, "2024-03-01", "FLIP", 1, 1),
            Transaction(margin, BUY, "2024-05-01", "FRUIT", 1, 5),
        ]
    )
    assert (cash, margin, archived) == (1, 2, 3)
    yield App()
    assert not fake.calls


def _run(*args: str):
    result = CliRunner().invoke(main, list(args))
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_episodes_follow_buys_sells_splits_drips_and_transfers(app):
    store = app.store
    changes = store._conn.total_changes
    rows = load_source(SOURCE, app)
    assert all(tuple(row) == SOURCES[SOURCE] for row in rows)
    assert [tuple(row.values()) for row in rows] == EXPECTED
    # The archived account's own positions, held or moved out, never appear.
    assert {row["account_id"] for row in rows} == {1, 2}
    assert "HIDDEN" not in {row["symbol"] for row in rows}
    assert store._conn.total_changes == changes


def test_open_episodes_match_the_holdings_dataset(app):
    rows = load_source(SOURCE, app)
    state = app.store.ledger()
    accounts = {account.saved_id for account in app.store.accounts()}
    held = {(h.account_id, h.symbol): h for h in state.open_holdings() if h.account_id in accounts}
    open_rows = {(row["account_id"], row["symbol"]): row for row in rows if row["status"] == "open"}
    # One open episode per held position, with the ledger's quantity and first date, and none for the rest.
    assert open_rows.keys() == held.keys()
    for key, row in open_rows.items():
        assert (row["quantity"], row["opened"]) == (held[key].quantity, held[key].first_date)
        assert row["peak_quantity"] >= row["quantity"]
    assert all(row["quantity"] == 0.0 for row in rows if row["status"] == "closed")

    pooled: dict[str, float] = defaultdict(float)
    for (_, symbol), row in sorted(open_rows.items()):  # account order, as holdings sums
        pooled[symbol] += row["quantity"]
    holdings = report_ledger.load_source("holdings", app)
    assert {row["symbol"]: row["quantity"] for row in holdings} == pooled


def test_float_noise_closes_an_episode_with_the_ledgers_tolerance(tracker, fake):
    app = App()
    app._tracker = tracker
    store = tracker.store
    account = store.add_account(Account(CASH)).saved_id
    store.add_transactions(
        [
            Transaction(account, BUY, "2024-01-01", "NOISE", 0.1, 1),
            Transaction(account, BUY, "2024-01-02", "NOISE", 0.2, 1),
            Transaction(account, SELL, "2024-01-03", "NOISE", 0.3, 1),
        ]
    )
    [row] = load_source(SOURCE, app)
    assert (row["status"], row["closed"], row["days_held"], row["quantity"]) == ("closed", "2024-01-03", 2, 0.0)
    assert report_ledger.load_source("holdings", app) == []
    assert not fake.calls


PRESET_EPISODES = {
    "open": [row[2:4] for row in EXPECTED if row[4] == "open"],
    "closed": [row[2:4] for row in EXPECTED if row[4] == "closed"],
    # Open episodes have no days held, so a numeric filter leaves them out.
    "under-a-year": [("FRUIT", 1), ("MOVE", 1), ("FLIP", 1), ("GONE", 1)],
}


@pytest.mark.parametrize("preset", PRESETS[SOURCE])
def test_presets_filter_report_and_summarize(app, preset):
    changes = app.store._conn.total_changes
    rows = _run("report", SOURCE, "--preset", preset)
    assert [(row["symbol"], row["episode"]) for row in rows] == PRESET_EPISODES[preset]
    summary = _run("summarize", SOURCE, "--preset", preset, "--metric", "rows=count")
    assert summary == [{"rows": len(PRESET_EPISODES[preset])}]
    assert app.store._conn.total_changes == changes


def test_no_rows_without_positions(tracker, fake):
    app = App()
    app._tracker = tracker
    tracker.store.add_account(Account("Fictional Empty"))
    assert load_source(SOURCE, app) == []
    with pytest.raises(KeyError):
        load_source("holding-period", app)
    assert not fake.calls


def test_episodes_read_accounts_and_transactions_from_one_snapshot(tracker, fake, monkeypatch):
    app = App()
    app._tracker = tracker
    store = tracker.store
    cash = store.add_account(Account(CASH)).saved_id
    accounts = store.accounts
    other = Store(store.path)

    def read_then_buy(**kwargs):
        active = accounts(**kwargs)
        if not kwargs:  # the first read of active accounts; `account_map` follows with archived ones
            other.add_transactions([Transaction(cash, BUY, "2024-01-02", "FRUIT", 1, 5)])
        return active

    monkeypatch.setattr(store, "accounts", read_then_buy)
    try:
        assert load_source(SOURCE, app) == []
        assert len(store.transactions()) == 1
    finally:
        other.close()
