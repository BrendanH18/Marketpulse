"""Report browsing is offline, hides archives, and keeps totals over the full match."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Transaction, TxnType


@pytest.fixture
def browse(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    account = store.add_account(Account(name="Fictional", type=AccountType.NONREG))
    hidden = store.add_account(Account(name="Archived fictional", type=AccountType.NONREG, archived=True))
    for owner in (account, hidden):
        for ccy, sym in (("CAD", "MAPL"), ("USD", "GULL")):
            store.add_transaction(Transaction(owner.saved_id, TxnType.BUY, "2024-01-01", sym, 10, 10, currency=ccy))
            for day, price in (("2024-02-01", 15), ("2024-03-01", 20)):
                store.add_transaction(Transaction(owner.saved_id, TxnType.SELL, day, sym, 1, price, currency=ccy))
                store.add_transaction(
                    Transaction(owner.saved_id, TxnType.DIVIDEND, day, sym, amount=price, currency=ccy)
                )
    fake.offline = True
    runner = CliRunner()

    def invoke(*args):
        result = runner.invoke(main, list(args), catch_exceptions=False)
        assert not fake.calls
        assert "Archived fictional" not in result.output
        return result

    return invoke


def payload(browse, *args):
    result = browse(*args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


@pytest.mark.parametrize("command", ["realized", "payouts"])
def test_currency_count_and_combined_filters(browse, command):
    assert browse(command, "--count").output == "4\n"
    assert browse(command, "--currency", " cad ", "--count").output == "2\n"
    assert browse(command, "--currency", "USD", "--symbol", "MAPL", "--count").output == "0\n"
    data = payload(browse, command, "--currency", "usd", "--since", "2024-03-01")
    assert len(data["rows"]) == 1
    assert data["rows"][0]["symbol"] == "GULL"
    assert set(data["totals"]) == {"USD"}
    assert browse(command, "--account", "2", "--count").exit_code == 1


@pytest.mark.parametrize("command", ["realized", "payouts"])
def test_order_page_and_totals(browse, command):
    full = payload(browse, command)
    newest = payload(browse, command, "--newest-first")
    assert [row["date"] for row in newest["rows"]] == ["2024-03-01"] * 2 + ["2024-02-01"] * 2
    # Same-day order stays stable when dates are reversed.
    assert [row["symbol"] for row in newest["rows"][:2]] == [row["symbol"] for row in full["rows"][2:]]
    page = payload(browse, command, "--newest-first", "--offset", "1", "--limit", "2")
    assert page["rows"] == newest["rows"][1:3]
    assert page["totals"] == full["totals"]
    assert payload(browse, command, "--offset", "100")["rows"] == []
    result = browse(command, "--newest-first", "--offset", "1", "--limit", "2", "--csv")
    assert result.exit_code == 0
    assert [r["date"] for r in csv.DictReader(io.StringIO(result.output))] == ["2024-03-01", "2024-02-01"]


def test_group_count_order_and_paging(browse):
    assert browse("payouts", "--by", "month", "--count").output == "4\n"
    assert browse("payouts", "--by", "symbol", "--count").output == "2\n"
    full = payload(browse, "payouts", "--by", "month")
    page = payload(browse, "payouts", "--by", "month", "--newest-first", "--offset", "1", "--limit", "1")
    assert page["groups"] == list(reversed(full["groups"]))[1:2]
    assert page["totals"] == full["totals"]
    csv_out = browse("payouts", "--by", "month", "--currency", "usd", "--limit", "1", "--csv")
    rows = list(csv.DictReader(io.StringIO(csv_out.output)))
    assert len(rows) == 1 and rows[0]["currency"] == "USD" and rows[0]["group"] == "2024-02"


@pytest.mark.parametrize("command", ["realized", "payouts"])
@pytest.mark.parametrize(
    "options",
    [
        ["--currency", " "],
        ["--limit", "0"],
        ["--offset", "-1"],
        ["--count", "--offset", "0"],
        ["--count", "--limit", "1"],
        ["--count", "--newest-first"],
        ["--count", "--json"],
        ["--count", "--csv"],
    ],
)
def test_invalid_combinations(browse, command, options):
    result = browse(command, *options)
    assert result.exit_code == 2, result.output


def test_paged_human_reports_respect_privacy(browse):
    assert browse("config", "set", "privacy", "true").exit_code == 0
    for args in (("realized",), ("payouts",), ("payouts", "--by", "month")):
        result = browse(*args, "--limit", "1")
        assert result.exit_code == 0
        assert "••••" in result.output and "15.00" not in result.output and "35.00" not in result.output
