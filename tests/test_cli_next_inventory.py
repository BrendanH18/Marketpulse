"""The next inventory improvements use fictional data and never fetch prices."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Asset, AssetClass, AssetKind, Transaction, TxnType


@pytest.fixture
def inventory_next(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "200")

    def unexpected(*args, **kwargs):
        raise AssertionError("Offline inventory must not price accounts")

    monkeypatch.setattr(tracker, "valuation", unexpected)
    alpha = store.add_account(Account("Fictional Alpha", AccountType.TFSA, institution="Maple", track_cash=True))
    beta = store.add_account(Account("Fictional Beta", AccountType.MARGIN, institution="Spruce", track_cash=True))
    gamma = store.add_account(Account("Fictional Gamma", AccountType.RRSP))
    closed = store.add_account(Account("Fictional Closed"))
    idle = store.add_account(Account("Idle Fictional"))
    incoming = store.add_account(Account("Fictional Incoming"))
    hidden = store.add_account(Account("Fictional Hidden", archived=True, track_cash=True))
    for owner, kind, symbol, quantity, price, amount, currency, target in [
        (alpha, TxnType.DEPOSIT, "", 0, 0, 1000, "CAD", None),
        (alpha, TxnType.BUY, "AAA", 2, 10, 0, "CAD", None),
        (alpha, TxnType.BUY, "BBB", 3, 20, 0, "CAD", None),
        (beta, TxnType.BUY, "CCC", 1, 30, 0, "USD", None),
        (beta, TxnType.DEPOSIT, "", 0, 0, 0.1, "CAD", None),
        (beta, TxnType.DEPOSIT, "", 0, 0, 0.2, "CAD", None),
        (beta, TxnType.WITHDRAWAL, "", 0, 0, 0.3, "CAD", None),
        (gamma, TxnType.BUY, "AAA", 1, 15, 0, "CAD", None),
        (closed, TxnType.BUY, "OLD", 1, 10, 0, "CAD", None),
        (closed, TxnType.SELL, "OLD", 1, 10, 0, "CAD", None),
        (alpha, TxnType.TRANSFER, "AAA", 1, 0, 0, "CAD", incoming.saved_id),
        (incoming, TxnType.SELL, "AAA", 1, 10, 0, "CAD", None),
        (hidden, TxnType.BUY, "SECRET", 100, 100, 0, "CAD", None),
    ]:
        store.add_transaction(
            Transaction(
                owner.saved_id,
                kind,
                "2024-01-02",
                symbol,
                quantity,
                price,
                amount,
                currency=currency,
                target_account_id=target,
            )
        )
    store.upsert_asset(Asset("AAA", asset_class=AssetClass.ETF))
    store.upsert_asset(Asset("BBB", kind=AssetKind.FIXED_INCOME, asset_class=AssetClass.FIXED_INCOME))
    before = store.transactions()
    fake.offline = True

    def invoke(*args):
        result = CliRunner().invoke(main, list(args), catch_exceptions=False)
        assert not fake.calls
        assert store.transactions() == before
        assert store.snapshots() == []
        return result

    return invoke, [alpha, beta, gamma, closed, idle, incoming, hidden]


def read(inventory_next, *args):
    invoke, _ = inventory_next
    result = invoke(*args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


@pytest.mark.parametrize(
    "flags,symbols",
    [
        (("--exclude-currency", " cad "), ["CCC"]),
        (("--exclude-account", "tfsa", "--exclude-account", "Fictional Gamma"), ["CCC"]),
        (("--min-average-cost", "20"), ["BBB", "CCC"]),
        (("--max-average-cost", "15"), ["AAA", "AAA"]),
        (("--registered",), ["AAA", "BBB", "AAA"]),
        (("--nonregistered",), ["CCC"]),
        (("--cash-tracked",), ["AAA", "BBB", "CCC"]),
        (("--cash-untracked",), ["AAA"]),
        (("--has-metadata",), ["AAA", "BBB", "AAA"]),
        (("--no-metadata",), ["CCC"]),
        (("--asset-kind", "fixed_INCOME"), ["BBB"]),
        (("--asset-kind", "market"), ["AAA", "CCC", "AAA"]),
        (("--asset-class", "etf"), ["AAA", "AAA"]),
        (("--symbol-prefix", " a "), ["AAA", "AAA"]),
    ],
)
def test_position_filters(inventory_next, flags, symbols):
    assert [row["symbol"] for row in read(inventory_next, "positions", *flags)] == symbols
    invoke, _ = inventory_next
    assert invoke("positions", *flags, "--count").output == f"{len(symbols)}\n"
    assert invoke("positions", *flags).exit_code == 0


@pytest.mark.parametrize(
    "group,expected",
    [
        (
            "account",
            [
                {"group": "Fictional Alpha", "count": 2},
                {"group": "Fictional Beta", "count": 1},
                {"group": "Fictional Gamma", "count": 1},
            ],
        ),
        ("currency", [{"group": "CAD", "count": 3}, {"group": "USD", "count": 1}]),
        ("symbol", [{"group": "AAA", "count": 2}, {"group": "BBB", "count": 1}, {"group": "CCC", "count": 1}]),
    ],
)
def test_position_summaries_all_formats_and_before_pagination(inventory_next, group, expected):
    invoke, _ = inventory_next
    args = ("positions", "--summary", group, "--limit", "1", "--offset", "100")
    assert read(inventory_next, *args) == expected
    exported = list(csv.DictReader(io.StringIO(invoke(*args, "--csv").output)))
    assert exported == [{"group": row["group"], "count": str(row["count"])} for row in expected]
    assert invoke(*args).exit_code == 0
    assert read(inventory_next, *args, "--symbol", "absent") == []


def test_position_filters_before_pages_and_no_archived_references(inventory_next):
    invoke, _ = inventory_next
    payload = read(inventory_next, "positions", "--min-average-cost", "15", "--limit", "1", "--page-info")
    assert payload["total"] == 3 and payload["rows"][0]["symbol"] == "BBB"
    assert read(inventory_next, "positions", "--exclude-currency", "cad", "--exclude-currency", "usd") == []
    for name in ("missing", "Fictional Hidden", ""):
        result = invoke("positions", "--exclude-account", name)
        assert result.exit_code == 1 and "No active account" in result.output


def test_cash_zero_and_registration(inventory_next):
    assert read(inventory_next, "cash", "--zero") == [
        {"account_id": inventory_next[1][1].saved_id, "account": "Fictional Beta", "currency": "CAD", "balance": 0.0}
    ]
    assert [row["balance"] for row in read(inventory_next, "cash", "--registered")] == [920]
    assert [row["balance"] for row in read(inventory_next, "cash", "--nonregistered")] == [0, -30]
    invoke, _ = inventory_next
    assert invoke("cash", "--zero", "--count").output == "1\n"
    assert invoke("cash", "--zero").exit_code == 0


@pytest.mark.parametrize(
    "group,expected",
    [
        ("account", [{"group": "Fictional Alpha", "count": 1}, {"group": "Fictional Beta", "count": 2}]),
        ("currency", [{"group": "CAD", "count": 2}, {"group": "USD", "count": 1}]),
        ("account-type", [{"group": "MARGIN", "count": 2}, {"group": "TFSA", "count": 1}]),
        ("institution", [{"group": "Maple", "count": 1}, {"group": "Spruce", "count": 2}]),
    ],
)
def test_cash_summaries(inventory_next, group, expected):
    invoke, _ = inventory_next
    args = ("cash", "--summary", group, "--limit", "1", "--offset", "100")
    assert read(inventory_next, *args) == expected
    exported = list(csv.DictReader(io.StringIO(invoke(*args, "--csv").output)))
    assert exported == [{"group": row["group"], "count": str(row["count"])} for row in expected]
    assert invoke(*args).exit_code == 0
    assert read(inventory_next, *args, "--search", "absent") == []


def test_cash_negative_summary_preserves_exit_status(inventory_next):
    invoke, _ = inventory_next
    result = invoke("cash", "--summary", "currency", "--negative", "--json")
    assert result.exit_code == 1
    assert json.loads(result.output) == [{"group": "USD", "count": 1}]
    assert invoke("cash", "--summary", "currency", "--negative", "--currency", "CAD").exit_code == 0


@pytest.mark.parametrize(
    "flags,indexes",
    [
        (("--has-positions",), [0, 1, 2]),
        (("--no-positions",), [3, 4, 5]),
        (("--has-transactions",), [0, 1, 2, 3, 5]),
        (("--no-transactions",), [4]),
        (("--min-transactions", "2"), [0, 1, 3, 5]),
        (("--max-transactions", "1"), [2, 4]),
        (("--name-prefix", "fictional"), [0, 1, 2, 3, 5]),
        (("--name-suffix", "ALPHA"), [0]),
    ],
)
def test_accounts_ledger_and_name_filters(inventory_next, flags, indexes):
    invoke, accounts = inventory_next
    args = ("accounts", "list", *flags)
    assert [row["id"] for row in read(inventory_next, *args)] == [accounts[index].id for index in indexes]
    assert invoke(*args).exit_code == 0  # human output also must stay offline
    assert invoke(*args, "--count").output == f"{len(indexes)}\n"


def test_accounts_counts_include_incoming_transfer_and_compose(inventory_next):
    args = (
        "accounts",
        "list",
        "--min-transactions",
        "2",
        "--max-transactions",
        "2",
        "--no-positions",
        "--name-suffix",
        "Incoming",
    )
    rows = read(inventory_next, *args)
    assert [row["name"] for row in rows] == ["Fictional Incoming"]
    page = read(inventory_next, "accounts", "list", "--has-transactions", "--limit", "1", "--page-info")
    assert page["total"] == 5
    summary = read(inventory_next, "accounts", "list", "--no-positions", "--summary", "type")
    assert summary == [{"group": "NONREG", "count": 3}]


def test_position_privacy_preserved_with_new_filters(inventory_next):
    invoke, _ = inventory_next
    assert invoke("config", "set", "privacy", "true").exit_code == 0
    result = invoke("positions", "--min-average-cost", "15")
    assert "••••" in result.output and "20.00" not in result.output
    assert read(inventory_next, "positions", "--min-average-cost", "15")[0]["average_cost"] == 20


@pytest.mark.parametrize(
    "args",
    [
        ("positions", "--min-average-cost", "2", "--max-average-cost", "1"),
        ("positions", "--min-average-cost", "nan"),
        ("positions", "--max-average-cost", "inf"),
        ("positions", "--summary", "symbol", "--count"),
        ("positions", "--summary", "currency", "--page-info", "--json"),
        ("cash", "--summary", "currency", "--count"),
        ("cash", "--summary", "currency", "--page-info", "--json"),
        ("cash", "--zero", "--positive"),
        ("cash", "--zero", "--negative"),
        ("cash", "--zero", "--nonzero"),
        ("accounts", "list", "--min-transactions", "2", "--max-transactions", "1"),
        ("accounts", "list", "--min-transactions", "-1"),
        ("accounts", "list", "--max-transactions", "-1"),
    ],
)
def test_invalid_options_do_not_open_tracker(monkeypatch, args):
    def unexpected(*args, **kwargs):
        raise AssertionError("Invalid arguments opened tracker")

    monkeypatch.setattr("marketpulse.services.Tracker.open", unexpected)
    assert CliRunner().invoke(main, args, catch_exceptions=False).exit_code == 2
