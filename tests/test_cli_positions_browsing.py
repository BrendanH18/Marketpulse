"""Fictional-ledger checks for position pagination and cash balance browsing."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, Transaction, TxnType


@pytest.fixture
def browse(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "180")
    alpha = store.add_account(Account(name="Fictional Alpha", track_cash=True))
    beta = store.add_account(Account(name="Fictional Beta", track_cash=True))
    hidden = store.add_account(Account(name="Fictional Hidden", track_cash=True, archived=True))
    for account, kind, day, symbol, quantity, price, amount, currency in [
        (alpha, TxnType.DEPOSIT, "2024-01-01", "", 0, 0, 1000, "CAD"),
        (alpha, TxnType.BUY, "2024-01-02", "AAA", 2, 10, 0, "CAD"),
        (alpha, TxnType.BUY, "2024-02-02", "BBB", 3, 20, 0, "CAD"),
        (beta, TxnType.BUY, "2024-03-02", "CCC", 1, 30, 0, "USD"),
        (beta, TxnType.DEPOSIT, "2024-01-01", "", 0, 0, 0.1, "CAD"),
        (beta, TxnType.DEPOSIT, "2024-01-01", "", 0, 0, 0.2, "CAD"),
        (beta, TxnType.WITHDRAWAL, "2024-01-01", "", 0, 0, 0.3, "CAD"),
        (hidden, TxnType.BUY, "2024-01-02", "SECRET", 100, 100, 0, "CAD"),
    ]:
        store.add_transaction(
            Transaction(account.saved_id, kind, day, symbol, quantity, price, amount, currency=currency)
        )
    fake.offline = True

    def invoke(*args):
        result = CliRunner().invoke(main, list(args), catch_exceptions=False)
        assert fake.calls == []
        return result

    return invoke


def data(browse, *args):
    result = browse(*args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_positions_limit_offset_apply_after_sorting_to_every_format(browse):
    args = ("positions", "--sort", "symbol", "--descending", "--offset", "1", "--limit", "1")
    assert [r["symbol"] for r in data(browse, *args)] == ["BBB"]
    csv_result = browse(*args, "--csv")
    assert csv_result.exit_code == 0
    assert [r["symbol"] for r in csv.DictReader(io.StringIO(csv_result.output))] == ["BBB"]
    human = browse(*args)
    assert human.exit_code == 0
    assert "BBB" in human.output and "AAA" not in human.output and "CCC" not in human.output
    assert data(browse, "positions", "--offset", "1") == data(browse, "positions")[1:]


def test_position_page_metadata_counts_filtered_visible_rows_before_slice(browse):
    result = data(browse, "positions", "--currency", "cad", "--offset", "1", "--limit", "1", "--page-info")
    assert result == {"rows": [data(browse, "positions")[1]], "total": 2, "offset": 1, "limit": 1}
    empty = data(browse, "positions", "--offset", "20", "--page-info")
    assert empty == {"rows": [], "total": 3, "offset": 20, "limit": None}
    assert "SECRET" not in browse("positions", "--page-info", "--json").output


def test_held_date_bounds_are_inclusive_and_composable(browse):
    assert [r["symbol"] for r in data(browse, "positions", "--held-since", "2024-02-02")] == ["BBB", "CCC"]
    assert [r["symbol"] for r in data(browse, "positions", "--held-until", "2024-02-02")] == ["AAA", "BBB"]
    args = ("positions", "--held-since", "2024-02-02", "--held-until", "2024-02-02", "--currency", "cad")
    assert data(browse, *args)[0]["symbol"] == "BBB"
    assert browse(*args, "--count").output == "1\n"


@pytest.mark.parametrize(
    "args",
    [
        ("--limit", "0"),
        ("--offset", "-1"),
        ("--page-info",),
        ("--count", "--limit", "1"),
        ("--count", "--offset", "1"),
        ("--count", "--offset", "0"),
        ("--count", "--page-info"),
        ("--held-since", "invalid"),
        ("--held-until", "2024-02-30"),
        ("--held-since", "2024-03-01", "--held-until", "2024-02-01"),
    ],
)
def test_position_browsing_rejects_invalid_options(browse, args):
    assert browse("positions", *args).exit_code == 2


def test_cash_count_filters_and_negative_exit_status(browse):
    assert browse("cash", "--count").output == "3\n"
    assert browse("cash", "--nonzero", "--count").output == "2\n"
    assert browse("cash", "--search", "BETA", "--currency", "cad", "--count").output == "1\n"
    negative = browse("cash", "--negative", "--count")
    assert negative.exit_code == 1 and negative.output == "1\n"
    clean = browse("cash", "--negative", "--search", "alpha", "--count")
    assert clean.exit_code == 0 and clean.output == "0\n"
    for fmt in ("--json", "--csv"):
        assert browse("cash", "--count", fmt).exit_code == 2


def test_cash_sorting_and_direction_have_deterministic_ties(browse):
    assert [r["balance"] for r in data(browse, "cash", "--sort", "balance")] == [-30, 0, 920]
    assert [r["balance"] for r in data(browse, "cash", "--sort", "BALANCE", "--descending")] == [920, 0, -30]
    assert [r["currency"] for r in data(browse, "cash", "--sort", "currency")] == ["CAD", "CAD", "USD"]
    assert data(browse, "cash", "--descending") == list(reversed(data(browse, "cash")))
    assert browse("cash", "--sort", "unknown").exit_code == 2


def test_cash_search_nonzero_and_privacy_remain_offline(browse):
    assert [r["balance"] for r in data(browse, "cash", "--search", " beta ", "--nonzero")] == [-30]
    assert data(browse, "cash", "--search", "hidden") == []
    assert "No cash balances match" in browse("cash", "--search", "unknown").output
    assert browse("config", "set", "privacy", "true").exit_code == 0
    human = browse("cash", "--sort", "balance", "--descending", "--nonzero")
    assert "••••" in human.output and "920.00" not in human.output and "-30.00" not in human.output
    assert data(browse, "cash", "--search", "alpha")[0]["balance"] == 920
    page = browse("positions", "--held-until", "2024-02-02", "--limit", "1")
    assert "••••" in page.output and "20.00" not in page.output
