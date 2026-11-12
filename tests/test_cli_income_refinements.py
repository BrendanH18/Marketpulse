"""Income report selection remains offline and never changes ledger arithmetic."""

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
    maple = store.add_account(Account(name="Fictional Maple", type=AccountType.NONREG))
    gull = store.add_account(Account(name="Fictional Gull", type=AccountType.TFSA, currency="USD"))
    hidden = store.add_account(Account(name="Archived Fiction", type=AccountType.RRSP, archived=True))
    for acct, symbol, currency in [(maple, "MAPL", "CAD"), (gull, "GULL", "USD"), (hidden, "HIDDEN", "CAD")]:
        for kind, day, quantity, price, amount in [
            (TxnType.BUY, "2023-01-01", 10, 10, 0),
            (TxnType.SELL, "2023-06-01", 4, 15, 0),
            (TxnType.SELL, "2024-02-01", 2, 5, 0),
            (TxnType.DIVIDEND, "2023-06-10", 0, 0, 12),
            (TxnType.INTEREST, "2024-02-10", 0, 0, 3),
        ]:
            store.add_transaction(
                Transaction(
                    acct.saved_id,
                    kind,
                    day,
                    "" if kind == TxnType.INTEREST else symbol,
                    quantity,
                    price,
                    amount,
                    currency=currency,
                )
            )
    fake.offline = True
    runner = CliRunner()

    def invoke(*args):
        calls = len(fake.calls)
        before = store.snapshots()
        result = runner.invoke(main, list(args), catch_exceptions=False)
        assert len(fake.calls) == calls
        assert store.snapshots() == before
        if result.exit_code == 0:
            assert "HIDDEN" not in result.output and "Archived Fiction" not in result.output
        return result

    return invoke


def data(cli, command, *options):
    result = cli(command, *options, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_sale_exclusions_and_native_proceeds_bounds(cli):
    rows = data(cli, "realized", "--exclude-symbol", " mapl ", "--min-proceeds", "60", "--max-proceeds", "60")
    assert [(row["symbol"], row["proceeds"]) for row in rows["rows"]] == [("GULL", 60)]
    assert rows["totals"] == {"USD": {"count": 1, "proceeds": 60, "cost": 40, "gain": 20}}
    assert data(cli, "realized", "--exclude-symbol", "MAPL", "--exclude-symbol", "GULL")["rows"] == []
    result = cli("realized", "--min-proceeds", "60", "--csv")
    assert len(list(csv.DictReader(io.StringIO(result.output)))) == 2


def test_quantity_bounds_are_inclusive_and_apply_before_count(cli):
    assert cli("realized", "--min-quantity", "4", "--max-quantity", "4", "--count").output.strip() == "2"
    assert [r["quantity"] for r in data(cli, "realized", "--max-quantity", "2")["rows"]] == [2, 2]
    assert data(cli, "realized", "--min-quantity", "5")["rows"] == []


@pytest.mark.parametrize("command", ["realized", "payouts"])
def test_account_exclusions_resolve_name_type_and_id(cli, command):
    assert {r["account_id"] for r in data(cli, command, "--exclude-account", "fictional maple")["rows"]} == {2}
    assert {r["account_id"] for r in data(cli, command, "--exclude-account", "TFSA")["rows"]} == {1}
    assert data(cli, command, "--exclude-account", "1", "--exclude-account", "2")["rows"] == []
    assert cli(command, "--exclude-account", "3").exit_code == 1
    assert cli(command, "--exclude-account", "missing").exit_code == 1


@pytest.mark.parametrize("command", ["realized", "payouts"])
def test_calendar_filters_intersect_existing_year_and_date_bounds(cli, command):
    assert len(data(cli, command, "--month", "6")["rows"]) == 2
    assert len(data(cli, command, "--quarter", "1")["rows"]) == 2
    assert data(cli, command, "--month", "6", "--quarter", "1")["rows"] == []
    assert data(cli, command, "--year", "2024", "--quarter", "2")["rows"] == []
    assert data(cli, command, "--quarter", "2", "--since", "2024-01-01")["rows"] == []


def test_page_info_counts_filtered_sales_and_preserves_full_totals(cli):
    page = data(cli, "realized", "--quarter", "2", "--limit", "1", "--page-info")
    assert {key: page[key] for key in ["total", "offset", "limit", "returned", "next_offset"]} == {
        "total": 2,
        "offset": 0,
        "limit": 1,
        "returned": 1,
        "next_offset": 1,
    }
    assert set(page["totals"]) == {"CAD", "USD"}
    beyond = data(cli, "realized", "--offset", "9", "--page-info")
    assert beyond["returned"] == 0 and beyond["next_offset"] is None and beyond["total"] == 4
    assert "total" not in data(cli, "realized")


def test_payout_symbol_presence_filters_rows_groups_and_totals(cli):
    assert [row["kind"] for row in data(cli, "payouts", "--no-symbol")["rows"]] == ["interest", "interest"]
    grouped = data(cli, "payouts", "--has-symbol", "--quarter", "2", "--by", "year")
    assert [(g["group"], g["count"], g["amount"]) for g in grouped["groups"]] == [
        ("2023", 1, 12),
        ("2023", 1, 12),
    ]
    assert cli("payouts", "--no-symbol", "--month", "2", "--count").output.strip() == "2"


def test_filtered_human_output_preserves_privacy_and_exports_stay_raw(cli):
    assert cli("config", "set", "privacy", "true").exit_code == 0
    result = cli("realized", "--min-quantity", "4")
    assert "••••" in result.output and "60.00" not in result.output
    result = cli("payouts", "--no-symbol")
    assert "••••" in result.output and "3.00" not in result.output
    assert data(cli, "realized", "--min-quantity", "4")["rows"][0]["proceeds"] == 60


@pytest.mark.parametrize(
    "args",
    [
        ("realized", "--exclude-symbol", " "),
        ("realized", "--min-proceeds", "nan"),
        ("realized", "--max-proceeds", "inf"),
        ("realized", "--min-proceeds", "2", "--max-proceeds", "1"),
        ("realized", "--min-quantity", "-1"),
        ("realized", "--max-quantity", "inf"),
        ("realized", "--min-quantity", "4", "--max-quantity", "2"),
        ("realized", "--page-info"),
        ("realized", "--month", "0"),
        ("realized", "--quarter", "5"),
        ("payouts", "--month", "13"),
        ("payouts", "--quarter", "0"),
    ],
)
def test_bad_options_fail_before_reading_reports(cli, args):
    assert cli(*args).exit_code == 2


@pytest.mark.parametrize("command", ["realized", "payouts"])
@pytest.mark.parametrize("reference", ["", "   "])
def test_blank_exclusion_never_creates_default_account(store, tracker, fake, monkeypatch, command, reference):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    result = CliRunner().invoke(main, [command, "--exclude-account", reference, "--json"], catch_exceptions=False)
    assert result.exit_code == 2
    assert "--exclude-account cannot be blank" in result.output
    assert store.accounts(include_archived=True) == []
    assert store.snapshots() == []
    assert fake.calls == []
