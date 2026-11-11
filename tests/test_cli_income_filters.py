"""Offline report filters use fictional ledger rows and preserve full-match totals."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Transaction, TxnType


@pytest.fixture
def reports(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    owners = [
        store.add_account(Account(name="Fictional Élan", type=AccountType.NONREG)),
        store.add_account(Account(name="Fictional Beta", type=AccountType.NONREG)),
        store.add_account(Account(name="Hidden", type=AccountType.NONREG, archived=True)),
    ]
    for owner in owners:
        for sym, ccy, gain in (("ZETA", "CAD", -5), ("ALPHA", "USD", 20)):
            store.add_transaction(Transaction(owner.saved_id, TxnType.BUY, "2024-01-01", sym, 10, 10, currency=ccy))
            for month, delta in ((2, 0), (3, 1)):
                day = f"2024-0{month}-01"
                store.add_transaction(
                    Transaction(owner.saved_id, TxnType.SELL, day, sym, 1, 10 + gain + delta, currency=ccy)
                )
                store.add_transaction(
                    Transaction(owner.saved_id, TxnType.DIVIDEND, day, sym, amount=10 + delta, currency=ccy)
                )
    fake.offline = True
    runner = CliRunner()

    def invoke(*args):
        result = runner.invoke(main, list(args), catch_exceptions=False)
        assert fake.calls == []
        assert "Hidden" not in result.output
        return result

    return invoke


def data(reports, *args):
    result = reports(*args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_realized_search_ranges_totals_and_exports(reports):
    result = data(reports, "realized", "--search", "ÉLAN", "--min-gain", "-5", "--max-gain", "-4", "--limit", "1")
    assert len(result["rows"]) == 1
    assert result["totals"] == {"CAD": {"count": 2, "proceeds": 11, "cost": 20, "gain": -9}}
    assert reports("realized", "--search", "alpha", "--min-gain", "21", "--count").output == "2\n"
    out = reports("realized", "--search", "zeta", "--max-gain", "-5", "--csv")
    rows = list(csv.DictReader(io.StringIO(out.output)))
    assert len(rows) == 2 and all(row["gain"] == "-5.0" for row in rows)


@pytest.mark.parametrize("field", ["date", "account", "symbol", "quantity", "proceeds", "cost", "gain", "currency"])
def test_realized_order_and_pages(reports, field):
    full = data(reports, "realized", "--sort", field)

    def key(row):
        return row[field].casefold() if field == "account" else row[field]

    assert [key(row) for row in full["rows"]] == sorted(key(row) for row in full["rows"])
    reverse = data(reports, "realized", "--sort", field, "--descending")
    assert [key(row) for row in reverse["rows"]] == sorted((key(row) for row in full["rows"]), reverse=True)
    page = data(reports, "realized", "--sort", field, "--descending", "--offset", "1", "--limit", "2")
    assert page["rows"] == reverse["rows"][1:3]
    assert page["totals"] == full["totals"]


def test_payout_search_amount_exclusions_and_page_info(reports):
    args = ("payouts", "--search", "élan", "--min-amount", "10", "--max-amount", "11", "--exclude-symbol", " zeta ")
    full = data(reports, *args)
    page = data(reports, *args, "--page-info", "--limit", "1")
    assert page["total"] == 2 and page["returned"] == 1 and page["next_offset"] == 1
    assert page["rows"] == full["rows"][:1]
    assert page["totals"] == {"USD": {"count": 2, "amount": 21}}
    empty = data(reports, *args, "--page-info", "--offset", "99")
    assert empty["rows"] == [] and empty["next_offset"] is None and empty["total"] == 2
    assert reports(*args, "--count").output == "2\n"
    excluded = data(reports, "payouts", "--exclude-symbol", "alpha", "--exclude-symbol", "ZETA")
    assert excluded == {"rows": [], "totals": {}}


def test_group_page_metadata_counts_groups_after_row_filters(reports):
    args = ("payouts", "--min-amount", "11", "--by", "account", "--page-info")
    page = data(reports, *args, "--limit", "1")
    assert page["total"] == 4 and page["returned"] == 1 and page["next_offset"] == 1
    assert page["totals"] == {"CAD": {"count": 2, "amount": 22}, "USD": {"count": 2, "amount": 22}}
    assert data(reports, *args, "--offset", "3")["next_offset"] is None


@pytest.mark.parametrize(
    "args",
    [
        ("realized", "--min-gain", "nan"),
        ("realized", "--max-gain", "inf"),
        ("realized", "--min-gain", "2", "--max-gain", "1"),
        ("realized", "--sort", "gain", "--newest-first"),
        ("realized", "--descending", "--newest-first"),
        ("realized", "--sort", "date", "--count"),
        ("realized", "--descending", "--count"),
        ("payouts", "--min-amount", "-inf"),
        ("payouts", "--max-amount", "nan"),
        ("payouts", "--min-amount", "2", "--max-amount", "1"),
        ("payouts", "--exclude-symbol", " "),
        ("payouts", "--page-info"),
        ("payouts", "--page-info", "--csv"),
        ("payouts", "--page-info", "--count"),
    ],
)
def test_invalid_options(reports, args):
    assert reports(*args).exit_code == 2


def test_human_privacy_and_raw_export(reports):
    assert reports("config", "set", "privacy", "true").exit_code == 0
    for args in (("realized", "--sort", "gain"), ("payouts", "--min-amount", "11")):
        out = reports(*args)
        assert out.exit_code == 0
        assert "••••" in out.output and "11.00" not in out.output
    assert data(reports, "payouts", "--min-amount", "11")["rows"][0]["amount"] == 11
