"""Position/cash selection on fictional ledger rows, without prices or mutations."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Transaction, TxnType


@pytest.fixture
def select(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "180")
    alpha = store.add_account(
        Account(name="Fictional Alpha", type=AccountType.TFSA, institution="Maple", track_cash=True)
    )
    beta = store.add_account(
        Account(name="Fictional Beta", type=AccountType.MARGIN, institution="Spruce", track_cash=True)
    )
    hidden = store.add_account(
        Account(name="Fictional Hidden", type=AccountType.TFSA, institution="Maple", track_cash=True, archived=True)
    )
    for acct, kind, sym, quantity, price, amount, ccy in [
        (alpha, TxnType.DEPOSIT, "", 0, 0, 1000, "CAD"),
        (alpha, TxnType.BUY, "AAA", 2, 10, 0, "CAD"),
        (alpha, TxnType.BUY, "BBB", 3, 20, 0, "CAD"),
        (beta, TxnType.BUY, "CCC", 1, 30, 0, "USD"),
        (beta, TxnType.DEPOSIT, "", 0, 0, 0.1, "CAD"),
        (beta, TxnType.DEPOSIT, "", 0, 0, 0.2, "CAD"),
        (beta, TxnType.WITHDRAWAL, "", 0, 0, 0.3, "CAD"),
        (hidden, TxnType.BUY, "SECRET", 100, 100, 0, "CAD"),
    ]:
        store.add_transaction(
            Transaction(acct.saved_id, kind, "2024-01-02", sym, quantity, price, amount, currency=ccy)
        )
    fake.offline = True
    before = store.transactions()

    def invoke(*args):
        result = CliRunner().invoke(main, list(args), catch_exceptions=False)
        assert fake.calls == []
        assert store.transactions() == before
        return result

    return invoke


def rows(select, *args):
    result = select(*args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def symbols(select, *args):
    return [r["symbol"] for r in rows(select, "positions", *args)]


@pytest.mark.parametrize(
    "query,expected", [(" ALPHA ", ["AAA", "BBB"]), ("bBb", ["BBB"]), ("usd", ["CCC"]), ("hidden", [])]
)
def test_position_search_matches_name_symbol_and_currency(select, query, expected):
    assert symbols(select, "--search", query) == expected


def test_exact_symbol_inclusions_and_exclusions_compose(select):
    args = ("--symbols", " aaa ", "--symbols", "ccc", "--exclude-symbol", " CCC ")
    assert symbols(select, *args) == ["AAA"]
    assert select("positions", *args, "--count").output == "1\n"
    assert symbols(select, "--symbols", "AA") == []
    assert symbols(select, "--exclude-symbol", "AAA", "--exclude-symbol", "BBB") == ["CCC"]


def test_position_account_metadata_filters(select):
    assert symbols(select, "--account-type", "tfsa") == ["AAA", "BBB"]
    assert symbols(select, "--institution", " MAPLE ", "--account-type", "TFSA") == ["AAA", "BBB"]
    assert symbols(select, "--institution", "map") == []
    assert symbols(select, "--institution", "spruce", "--account-type", "TFSA") == []


def test_position_numeric_bounds_inclusive_before_pages_and_count(select):
    assert symbols(select, "--min-quantity", "2") == ["AAA", "BBB"]
    assert symbols(select, "--max-quantity", "2") == ["AAA", "CCC"]
    assert symbols(select, "--min-book", "30") == ["BBB", "CCC"]
    assert symbols(select, "--max-book", "30") == ["AAA", "CCC"]
    args = ("--min-quantity", "2", "--max-quantity", "2", "--min-book", "20", "--max-book", "20")
    assert symbols(select, *args) == ["AAA"]
    assert select("positions", *args, "--count").output == "1\n"
    page = rows(select, "positions", "--min-book", "30", "--limit", "1", "--page-info")
    assert page["total"] == 2 and page["rows"][0]["symbol"] == "BBB"


def test_average_cost_sort_supports_direction_and_exports(select):
    assert symbols(select, "--sort", "AVERAGE-COST") == ["AAA", "BBB", "CCC"]
    args = ("positions", "--sort", "average-cost", "--descending", "--limit", "1")
    assert rows(select, *args)[0]["symbol"] == "CCC"
    exported = list(csv.DictReader(io.StringIO(select(*args, "--csv").output)))
    assert exported[0]["symbol"] == "CCC"
    assert "CCC" in select(*args).output and "AAA" not in select(*args).output


def test_cash_pages_apply_after_filters_and_sort_across_formats(select):
    args = ("cash", "--sort", "balance", "--offset", "1", "--limit", "1")
    assert [r["balance"] for r in rows(select, *args)] == [0]
    assert list(csv.DictReader(io.StringIO(select(*args, "--csv").output)))[0]["balance"] == "0.0"
    assert "Fictional Beta" in select(*args).output and "Fictional Alpha" not in select(*args).output
    page = rows(select, *args, "--page-info")
    assert page == {"rows": rows(select, *args), "total": 3, "offset": 1, "limit": 1}
    assert rows(select, "cash", "--offset", "20", "--page-info") == {
        "rows": [],
        "total": 3,
        "offset": 20,
        "limit": None,
    }
    assert "No cash balances on this page" in select("cash", "--offset", "20").output


def test_cash_bounds_positive_and_float_residue(select):
    assert [r["balance"] for r in rows(select, "cash", "--min-balance", "0")] == [920, 0]
    assert [r["balance"] for r in rows(select, "cash", "--max-balance", "0")] == [0, -30]
    assert [r["balance"] for r in rows(select, "cash", "--min-balance", "0", "--max-balance", "0")] == [0]
    assert [r["balance"] for r in rows(select, "cash", "--positive")] == [920]
    assert select("cash", "--positive", "--count").output == "1\n"
    assert rows(select, "cash", "--positive", "--max-balance", "0") == []


def test_cash_currency_and_account_exclusions_are_repeatable(select):
    assert [r["currency"] for r in rows(select, "cash", "--exclude-currency", " cad ")] == ["USD"]
    assert rows(select, "cash", "--exclude-currency", "cad", "--exclude-currency", "USD") == []
    assert [r["balance"] for r in rows(select, "cash", "--exclude-account", "Fictional Alpha")] == [0, -30]
    assert rows(select, "cash", "--exclude-account", "TFSA", "--exclude-account", "2") == []
    for ref in ("Fictional Hidden", "missing", ""):
        result = select("cash", "--exclude-account", ref, "--json")
        assert result.exit_code != 0 and "No active account" in result.output


def test_cash_account_metadata_and_privacy(select):
    assert [r["balance"] for r in rows(select, "cash", "--account-type", "TFSA")] == [920]
    assert [r["balance"] for r in rows(select, "cash", "--institution", " SPRUCE ", "--account-type", "margin")] == [
        0,
        -30,
    ]
    assert rows(select, "cash", "--institution", "spr") == []
    assert select("config", "set", "privacy", "true").exit_code == 0
    for args in (
        ("positions", "--sort", "average-cost", "--min-book", "20"),
        ("cash", "--min-balance", "900", "--limit", "1"),
    ):
        human = select(*args).output
        assert "••••" in human and "920.00" not in human and "20.00" not in human
    assert rows(select, "cash", "--positive")[0]["balance"] == 920


def test_cash_negative_exit_depends_on_all_matches_not_page(select):
    for output in ((), ("--json",), ("--csv",), ("--json", "--page-info")):
        result = select("cash", "--negative", "--offset", "20", *output)
        assert result.exit_code == 1
        assert "No overdrawn" not in result.output
    assert select("cash", "--negative", "--min-balance", "0", "--offset", "20", "--json").exit_code == 0


@pytest.mark.parametrize(
    "command,args",
    [
        ("positions", ("--min-quantity", "3", "--max-quantity", "2")),
        ("positions", ("--min-book", "3", "--max-book", "2")),
        ("cash", ("--min-balance", "3", "--max-balance", "2")),
        ("cash", ("--positive", "--negative")),
        ("cash", ("--limit", "0")),
        ("cash", ("--offset", "-1")),
        ("cash", ("--count", "--offset", "0")),
        ("cash", ("--count", "--limit", "1")),
        ("cash", ("--count", "--page-info")),
        ("cash", ("--page-info",)),
        ("cash", ("--page-info", "--csv")),
        ("positions", ("--account-type", "unknown")),
        ("cash", ("--account-type", "unknown")),
    ]
    + [
        (command, (option, value))
        for command, options in [
            ("positions", ("--min-quantity", "--max-quantity", "--min-book", "--max-book")),
            ("cash", ("--min-balance", "--max-balance")),
        ]
        for option in options
        for value in ("nan", "inf", "-inf")
    ],
)
def test_invalid_selection_rejected_before_opening_database(monkeypatch, command, args):
    def unexpected(*args, **kwargs):
        raise AssertionError("Invalid options opened the tracker")

    monkeypatch.setattr("marketpulse.services.Tracker.open", unexpected)
    result = CliRunner().invoke(main, [command, *args], catch_exceptions=False)
    assert result.exit_code == 2, result.output
