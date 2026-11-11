"""Offline `positions` and `cash` reports from the ledger replay, on fictional rows."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Transaction, TxnType


@pytest.fixture
def cli(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "160")
    tfsa = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA, track_cash=True))
    margin = store.add_account(Account(name="Fictional Margin", type=AccountType.MARGIN, track_cash=True))
    rrsp = store.add_account(Account(name="Fictional RRSP", type=AccountType.RRSP))
    hidden = store.add_account(Account(name="Archived secret", track_cash=True, archived=True))
    rows = [
        (tfsa, TxnType.DEPOSIT, "2024-01-02", "", 0, 0, 1000, 0, "CAD"),
        (tfsa, TxnType.BUY, "2024-01-03", "AAA", 10, 20, 0, 1, "CAD"),
        (tfsa, TxnType.BUY, "2023-06-01", "BBB.TO", 5, 10, 0, 0, "CAD"),
        (margin, TxnType.DEPOSIT, "2024-01-05", "", 0, 0, 100, 0, "USD"),
        (margin, TxnType.BUY, "2024-02-01", "ZZZ", 3, 50, 0, 0, "USD"),
        # 0.1 + 0.2 - 0.3 leaves float residue that must read as zero, not overdrawn.
        (margin, TxnType.DEPOSIT, "2024-02-02", "", 0, 0, 0.1, 0, "CAD"),
        (margin, TxnType.DEPOSIT, "2024-02-02", "", 0, 0, 0.2, 0, "CAD"),
        (margin, TxnType.WITHDRAWAL, "2024-02-02", "", 0, 0, 0.3, 0, "CAD"),
        (rrsp, TxnType.BUY, "2024-03-01", "AAA", 2, 30, 0, 0, "USD"),
        (rrsp, TxnType.BUY, "2024-03-01", "CCC", 1, 5, 0, 0, "USD"),
        (rrsp, TxnType.SELL, "2024-03-02", "CCC", 1, 6, 0, 0, "USD"),
        (hidden, TxnType.DEPOSIT, "2024-01-01", "", 0, 0, 100, 0, "CAD"),
        (hidden, TxnType.BUY, "2024-01-02", "SECRET", 7, 100, 0, 0, "CAD"),
    ]
    for acct, kind, day, symbol, quantity, price, amount, fees, ccy in rows:
        store.add_transaction(
            Transaction(acct.saved_id, kind, day, symbol, quantity, price, amount, fees, currency=ccy)
        )
    fake.offline = True
    calls = len(fake.calls)
    runner = CliRunner()

    def invoke(*args):
        result = runner.invoke(main, list(args), catch_exceptions=False)
        assert len(fake.calls) == calls  # never touches the market
        return result

    return invoke


def records(cli, *args):
    result = cli(*args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def pairs(cli, *args):
    return [(r["account"], r["symbol"]) for r in records(cli, "positions", *args)]


# 1. Human table of open positions


def test_positions_table_lists_open_positions_at_cost_offline(cli):
    result = cli("positions")
    assert result.exit_code == 0, result.output
    out = result.output
    for text in ("Open positions (at cost)", "Fictional TFSA", "BBB.TO", "ZZZ", "201.00", "20.10", "2023-06-01"):
        assert text in out
    assert "prices are not fetched" in out
    assert "CCC" not in out  # closed
    assert "SECRET" not in out and "Archived secret" not in out


def test_positions_filtered_to_nothing_says_so(cli):
    assert "No positions match these filters." in cli("positions", "--symbol", "nothing").output
    assert "No positions match" in cli("positions", "-a", "Fictional RRSP", "--currency", "JPY").output


def test_positions_without_any_holdings(tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    fake.offline = True
    result = CliRunner().invoke(main, ["positions"])
    assert result.exit_code == 0 and "No open positions yet." in result.output
    assert fake.calls == []


# 2. JSON


def test_positions_json_has_raw_fields(cli):
    rows = records(cli, "positions")
    assert [(r["account"], r["symbol"]) for r in rows] == [
        ("Fictional Margin", "ZZZ"),
        ("Fictional RRSP", "AAA"),
        ("Fictional TFSA", "AAA"),
        ("Fictional TFSA", "BBB.TO"),
    ]
    tfsa_aaa = rows[2]
    assert tfsa_aaa == {
        "account_id": 1,
        "account": "Fictional TFSA",
        "symbol": "AAA",
        "quantity": 10,
        "book": 201,
        "average_cost": pytest.approx(20.1),
        "currency": "CAD",
        "first_date": "2024-01-03",
    }


# 3. CSV


def test_positions_csv_matches_json(cli):
    result = cli("positions", "--csv")
    assert result.exit_code == 0
    rows = list(csv.DictReader(io.StringIO(result.output)))
    assert list(rows[0]) == [
        "account_id",
        "account",
        "symbol",
        "quantity",
        "book",
        "average_cost",
        "currency",
        "first_date",
    ]
    assert [(r["account"], r["symbol"]) for r in rows] == pairs(cli)
    assert rows[1]["book"] == "60.0" and rows[1]["currency"] == "USD"


# 4. Account filter


def test_positions_account_filter_and_archived_refs(cli):
    assert pairs(cli, "-a", "fictional tfsa") == [("Fictional TFSA", "AAA"), ("Fictional TFSA", "BBB.TO")]
    assert pairs(cli, "--account", "RRSP") == [("Fictional RRSP", "AAA")]
    assert pairs(cli, "-a", "2") == [("Fictional Margin", "ZZZ")]
    for ref in ("Archived secret", "4", "Nobody"):
        result = cli("positions", "-a", ref, "--json")
        assert result.exit_code == 1
        assert f"No active account '{ref}'" in result.output
        assert "SECRET" not in result.output


# 5. Symbol filter


def test_positions_symbol_substring_ignores_case(cli):
    assert pairs(cli, "--symbol", "aa") == [("Fictional RRSP", "AAA"), ("Fictional TFSA", "AAA")]
    assert pairs(cli, "--symbol", ".to") == [("Fictional TFSA", "BBB.TO")]
    assert pairs(cli, "--symbol", "secret") == []


# 6. Currency filter


def test_positions_currency_filter_ignores_case(cli):
    assert pairs(cli, "--currency", "usd") == [("Fictional Margin", "ZZZ"), ("Fictional RRSP", "AAA")]
    assert pairs(cli, "--currency", " CAD ", "-a", "TFSA") == [("Fictional TFSA", "AAA"), ("Fictional TFSA", "BBB.TO")]


# 7. Sorting


def test_positions_sort_and_descending(cli):
    assert [s for _, s in pairs(cli, "--sort", "symbol")] == ["AAA", "AAA", "BBB.TO", "ZZZ"]
    assert [s for _, s in pairs(cli, "--sort", "quantity")] == ["AAA", "ZZZ", "BBB.TO", "AAA"]
    assert [s for _, s in pairs(cli, "--sort", "book", "--descending")] == ["AAA", "ZZZ", "AAA", "BBB.TO"]
    assert [s for _, s in pairs(cli, "--sort", "FIRST-DATE")] == ["BBB.TO", "AAA", "ZZZ", "AAA"]
    assert pairs(cli, "--descending")[0] == ("Fictional TFSA", "BBB.TO")
    assert cli("positions", "--sort", "price").exit_code == 2


# 8. Count


def test_positions_count_and_output_conflicts(cli):
    assert cli("positions", "--count").output == "4\n"
    assert cli("positions", "--count", "--currency", "usd", "--symbol", "z").output == "1\n"
    assert cli("positions", "--count", "-a", "TFSA").output == "2\n"
    for args in (("--count", "--json"), ("--count", "--csv"), ("--json", "--csv")):
        result = cli("positions", *args)
        assert result.exit_code == 2 and "Choose one output format" in result.output


# 9. Cash balances


def test_cash_lists_tracked_balances_from_ledger(cli):
    rows = records(cli, "cash")
    assert rows == [
        {"account_id": 2, "account": "Fictional Margin", "currency": "CAD", "balance": 0.0},
        {"account_id": 2, "account": "Fictional Margin", "currency": "USD", "balance": -50.0},
        {"account_id": 1, "account": "Fictional TFSA", "currency": "CAD", "balance": 749.0},
    ]
    out = cli("cash").output
    assert "Fictional TFSA" in out and "749.00" in out and "-50.00" in out
    assert "Archived secret" not in out and "RRSP" not in out
    assert records(cli, "cash", "-a", "TFSA") == [rows[2]]
    assert records(cli, "cash", "--currency", "usd") == [rows[1]]
    csv_rows = list(csv.DictReader(io.StringIO(cli("cash", "--csv").output)))
    assert [(r["account"], r["currency"], r["balance"]) for r in csv_rows] == [
        ("Fictional Margin", "CAD", "0.0"),
        ("Fictional Margin", "USD", "-50.0"),
        ("Fictional TFSA", "CAD", "749.0"),
    ]


def test_cash_messages_and_rejections(cli):
    assert "doesn't track cash" in cli("cash", "-a", "RRSP").output
    assert records(cli, "cash", "-a", "RRSP") == []
    assert "No cash balances match" in cli("cash", "--currency", "JPY").output
    hidden = cli("cash", "-a", "Archived secret")
    assert hidden.exit_code == 1 and "No active account" in hidden.output
    assert cli("cash", "--json", "--csv").exit_code == 2


# 10. Overdrawn balances and exit status


def test_cash_negative_filters_and_sets_exit_status(cli):
    result = cli("cash", "--negative", "--json")
    assert result.exit_code == 1
    assert json.loads(result.output) == [
        {"account_id": 2, "account": "Fictional Margin", "currency": "USD", "balance": -50.0}
    ]
    human = cli("cash", "--negative")
    assert human.exit_code == 1 and "-50.00" in human.output and "749" not in human.output
    assert cli("cash", "--negative", "--csv").exit_code == 1
    # The archived account is overdrawn in CAD, and Margin's CAD residue is zero: neither counts.
    clean = cli("cash", "--negative", "--currency", "CAD")
    assert clean.exit_code == 0 and "No overdrawn cash balances." in clean.output
    assert cli("cash", "--negative", "-a", "TFSA", "--json").output.strip() == "[]"
    assert cli("cash", "--negative", "-a", "TFSA").exit_code == 0


# Privacy


def test_privacy_masks_human_output_but_not_machine_output(cli):
    assert cli("config", "set", "privacy", "true").exit_code == 0
    positions = cli("positions").output
    assert "••••" in positions and "AAA" in positions
    for amount in ("201.00", "20.10", "60.00", "150.00"):
        assert amount not in positions
    cash = cli("cash").output
    assert "••••" in cash and "749" not in cash and "-50" not in cash
    assert records(cli, "positions", "-a", "TFSA")[0]["book"] == 201
    assert "749.0" in cli("cash", "--csv").output
    assert "201.0" in cli("positions", "--csv").output
