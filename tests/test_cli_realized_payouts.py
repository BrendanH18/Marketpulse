"""Offline realized-gain and payout logs (#111, items 11-20) on fictional ledgers in two currencies."""

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
    maple = store.add_account(Account(name="Maple Fictional", type=AccountType.NONREG, currency="CAD"))
    harbor = store.add_account(Account(name="Harbor Fictional", type=AccountType.MARGIN, currency="USD"))
    hidden = store.add_account(Account(name="Hidden archive", type=AccountType.TFSA, archived=True))

    def add(acct, kind, day, symbol="", quantity=0.0, price=0.0, amount=0.0, currency="CAD"):
        store.add_transaction(Transaction(acct.saved_id, kind, day, symbol, quantity, price, amount, currency=currency))

    add(maple, TxnType.BUY, "2023-03-01", "MAPL", 10, 10)
    add(maple, TxnType.SELL, "2023-06-01", "MAPL", 4, 15)  # proceeds 60, ACB 40, gain +20
    add(maple, TxnType.DIVIDEND, "2023-09-15", "MAPL", amount=12.5)
    add(maple, TxnType.INTEREST, "2024-01-31", amount=3)
    add(maple, TxnType.SELL, "2024-02-01", "MAPL", 2, 5)  # proceeds 10, ACB 20, loss -10
    add(harbor, TxnType.BUY, "2023-04-01", "GULL", 5, 100, currency="USD")
    add(harbor, TxnType.SELL, "2024-03-01", "GULL", 2, 120, currency="USD")  # 240 - 200 = +40 USD
    add(harbor, TxnType.DRIP, "2024-03-15", "GULL", 0.5, 110, currency="USD")  # 55 USD of income
    add(harbor, TxnType.DIVIDEND, "2024-06-30", "GULL", amount=7, currency="USD")
    add(hidden, TxnType.BUY, "2023-01-02", "SECRETX", 1, 10)
    add(hidden, TxnType.SELL, "2024-01-02", "SECRETX", 1, 987654)
    add(hidden, TxnType.DIVIDEND, "2024-01-03", "SECRETX", amount=31337)
    add(hidden, TxnType.INTEREST, "2024-01-04", amount=4242)

    fake.offline = True
    calls = len(fake.calls)
    runner = CliRunner()

    def invoke(*args):
        result = runner.invoke(main, list(args), catch_exceptions=False)
        assert len(fake.calls) == calls  # never a quote, FX or history lookup
        assert "SECRETX" not in result.output and "Hidden archive" not in result.output
        assert "987" not in result.output and "31337" not in result.output and "4242" not in result.output
        return result

    return invoke


def data(cli, *args):
    result = cli(*args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def gains(cli, *args):
    return [(r["date"], r["symbol"], r["gain"]) for r in data(cli, "realized", *args)["rows"]]


def payouts(cli, *args):
    return [(r["date"], r["kind"], r["amount"]) for r in data(cli, "payouts", *args)["rows"]]


def test_realized_table_lists_oldest_first_with_native_totals(cli):
    result = cli("realized")
    assert result.exit_code == 0, result.output
    out = result.output
    assert out.index("2023-06-01") < out.index("2024-02-01") < out.index("2024-03-01")
    for text in ("Maple Fictional", "Harbor Fictional", "MAPL", "GULL", "+$20.00", "-$10.00", "+$40.00", "$60.00"):
        assert text in out
    assert "Totals by currency" in out and "$70.00" in out and "$240.00" in out
    assert "Not the tax report" in out


def test_realized_json_rows_carry_ids_and_totals_never_mix_currencies(cli):
    payload = data(cli, "realized")
    assert [(r["symbol"], r["currency"], r["txn_id"]) for r in payload["rows"]] == [
        ("MAPL", "CAD", 2),
        ("MAPL", "CAD", 5),
        ("GULL", "USD", 7),
    ]
    first = payload["rows"][0]
    assert first == {
        "date": "2023-06-01",
        "account_id": 1,
        "account": "Maple Fictional",
        "symbol": "MAPL",
        "quantity": 4,
        "proceeds": 60,
        "cost": 40,
        "gain": 20,
        "currency": "CAD",
        "txn_id": 2,
    }
    assert payload["totals"] == {
        "CAD": {"count": 2, "proceeds": 70, "cost": 60, "gain": 10},
        "USD": {"count": 1, "proceeds": 240, "cost": 200, "gain": 40},
    }


def test_realized_date_filters(cli):
    assert gains(cli, "--year", "2023") == [("2023-06-01", "MAPL", 20)]
    assert gains(cli, "--since", "2024-02-01") == [("2024-02-01", "MAPL", -10), ("2024-03-01", "GULL", 40)]
    assert gains(cli, "--until", "2024-02-01") == [("2023-06-01", "MAPL", 20), ("2024-02-01", "MAPL", -10)]
    assert gains(cli, "--year", "2024", "--until", "2024-02-15") == [("2024-02-01", "MAPL", -10)]
    assert data(cli, "realized", "--year", "2030") == {"rows": [], "totals": {}}
    assert "No matching realized gains." in cli("realized", "--year", "2030").output


def test_realized_account_and_exact_symbol_filters(cli):
    assert gains(cli, "-a", "harbor fictional") == [("2024-03-01", "GULL", 40)]
    assert gains(cli, "--account", "1") == [("2023-06-01", "MAPL", 20), ("2024-02-01", "MAPL", -10)]
    assert gains(cli, "--symbol", " mapl ") == [("2023-06-01", "MAPL", 20), ("2024-02-01", "MAPL", -10)]
    assert gains(cli, "--symbol", "MAP") == []  # exact match, not a substring
    assert gains(cli, "-a", "Maple Fictional", "--symbol", "GULL") == []
    assert gains(cli, "--symbol", "SECRETX") == []
    archived = cli("realized", "-a", "3")  # the archived account, by id
    assert archived.exit_code == 1 and "No active account" in archived.output
    assert cli("realized", "-a", "Nowhere").exit_code == 1


def test_realized_csv_has_rows_on_stdout(cli):
    result = cli("realized", "--csv", "--symbol", "MAPL")
    assert result.exit_code == 0
    rows = list(csv.DictReader(io.StringIO(result.output)))
    assert [(r["date"], r["proceeds"], r["cost"], r["gain"], r["txn_id"]) for r in rows] == [
        ("2023-06-01", "60.0", "40.0", "20.0", "2"),
        ("2024-02-01", "10.0", "20.0", "-10.0", "5"),
    ]
    assert list(rows[0]) == [
        "date",
        "account_id",
        "account",
        "symbol",
        "quantity",
        "proceeds",
        "cost",
        "gain",
        "currency",
        "txn_id",
    ]
    assert cli("realized", "--csv", "--year", "2030").output.splitlines() == [
        "date,account_id,account,symbol,quantity,proceeds,cost,gain,currency,txn_id"
    ]


def test_realized_gains_or_losses_only(cli):
    assert gains(cli, "--gains-only") == [("2023-06-01", "MAPL", 20), ("2024-03-01", "GULL", 40)]
    assert gains(cli, "--losses-only") == [("2024-02-01", "MAPL", -10)]
    assert data(cli, "realized", "--losses-only")["totals"] == {
        "CAD": {"count": 1, "proceeds": 10, "cost": 20, "gain": -10}
    }


def test_payouts_list_all_income_kinds_with_native_totals(cli):
    assert payouts(cli) == [
        ("2023-09-15", "dividend", 12.5),
        ("2024-01-31", "interest", 3),
        ("2024-03-15", "drip", 55),
        ("2024-06-30", "dividend", 7),
    ]
    payload = data(cli, "payouts")
    assert payload["rows"][1] == {
        "date": "2024-01-31",
        "account_id": 1,
        "account": "Maple Fictional",
        "symbol": "",
        "kind": "interest",
        "amount": 3,
        "currency": "CAD",
    }
    assert payload["totals"] == {"CAD": {"count": 2, "amount": 15.5}, "USD": {"count": 2, "amount": 62}}
    out = cli("payouts").output
    assert out.index("2023-09-15") < out.index("2024-06-30")
    for text in ("Dividend", "Interest", "DRIP", "—", "$12.50", "$55.00", "$15.50", "$62.00"):
        assert text in out


def test_payout_filters(cli):
    assert payouts(cli, "--year", "2024", "--until", "2024-03-31") == [
        ("2024-01-31", "interest", 3),
        ("2024-03-15", "drip", 55),
    ]
    assert payouts(cli, "--since", "2024-06-01") == [("2024-06-30", "dividend", 7)]
    assert [r[0] for r in payouts(cli, "-a", "Maple Fictional")] == ["2023-09-15", "2024-01-31"]
    assert payouts(cli, "--symbol", "gull", "--kind", "DRIP") == [("2024-03-15", "drip", 55)]
    assert payouts(cli, "--kind", "interest", "--kind", "drip") == [
        ("2024-01-31", "interest", 3),
        ("2024-03-15", "drip", 55),
    ]
    assert payouts(cli, "--symbol", "GUL") == []
    assert "No matching payouts." in cli("payouts", "--kind", "interest", "--year", "2023").output
    archived = cli("payouts", "-a", "3")  # the archived account, by id
    assert archived.exit_code == 1 and "No active account" in archived.output


def test_payouts_grouped_by_month_year_symbol_and_account(cli):
    assert data(cli, "payouts", "--by", "year")["groups"] == [
        {"group": "2023", "currency": "CAD", "count": 1, "amount": 12.5},
        {"group": "2024", "currency": "CAD", "count": 1, "amount": 3},
        {"group": "2024", "currency": "USD", "count": 2, "amount": 62},
    ]
    assert [g["group"] for g in data(cli, "payouts", "--by", "month")["groups"]] == [
        "2023-09",
        "2024-01",
        "2024-03",
        "2024-06",
    ]
    by_symbol = data(cli, "payouts", "--by", "symbol")
    assert by_symbol["by"] == "symbol"
    assert [(g["group"], g["amount"]) for g in by_symbol["groups"]] == [("", 3), ("GULL", 62), ("MAPL", 12.5)]
    assert by_symbol["totals"] == {"CAD": {"count": 2, "amount": 15.5}, "USD": {"count": 2, "amount": 62}}
    assert data(cli, "payouts", "--by", "account", "--kind", "dividend")["groups"] == [
        {"group": "1", "currency": "CAD", "count": 1, "amount": 12.5, "account": "Maple Fictional"},
        {"group": "2", "currency": "USD", "count": 1, "amount": 7, "account": "Harbor Fictional"},
    ]
    out = cli("payouts", "--by", "account").output
    assert "Payouts by account" in out and "Harbor Fictional" in out and "$62.00" in out
    assert "No matching payouts." in cli("payouts", "--by", "year", "--year", "2030").output


def test_payouts_csv_for_rows_and_groups(cli):
    rows = list(csv.DictReader(io.StringIO(cli("payouts", "--csv", "--kind", "dividend").output)))
    assert [(r["date"], r["symbol"], r["kind"], r["amount"], r["currency"]) for r in rows] == [
        ("2023-09-15", "MAPL", "dividend", "12.5", "CAD"),
        ("2024-06-30", "GULL", "dividend", "7.0", "USD"),
    ]
    grouped = cli("payouts", "--by", "account", "--csv")
    assert list(csv.DictReader(io.StringIO(grouped.output))) == [
        {"group": "1", "currency": "CAD", "count": "2", "amount": "15.5", "account": "Maple Fictional"},
        {"group": "2", "currency": "USD", "count": "2", "amount": "62.0", "account": "Harbor Fictional"},
    ]
    assert cli("payouts", "--by", "month", "--csv", "--year", "2030").output.splitlines() == [
        "group,currency,count,amount"
    ]


def test_privacy_masks_human_output_but_not_exports(cli):
    assert cli("config", "set", "privacy", "true").exit_code == 0
    realized = cli("realized").output
    assert "••••" in realized and "MAPL" in realized
    assert "60.00" not in realized and "20.00" not in realized and "70.00" not in realized
    paid = cli("payouts").output
    assert "••••" in paid and "12.50" not in paid and "15.50" not in paid
    grouped = cli("payouts", "--by", "year").output
    assert "••••" in grouped and "62.00" not in grouped
    assert data(cli, "realized")["totals"]["CAD"]["gain"] == 10  # exports stay raw, as other exports do
    assert data(cli, "payouts")["totals"]["USD"]["amount"] == 62


@pytest.mark.parametrize(
    "args",
    [
        ["realized", "--json", "--csv"],
        ["realized", "--gains-only", "--losses-only"],
        ["realized", "--since", "2024-05-01", "--until", "2024-01-01"],
        ["realized", "--since", "not-a-date"],
        ["realized", "--until", "2024-13-40"],
        ["realized", "--year", "0"],
        ["payouts", "--json", "--csv"],
        ["payouts", "--by", "week"],
        ["payouts", "--kind", "rent"],
        ["payouts", "--since", "2024-05-01", "--until", "2024-01-01"],
        ["payouts", "--since", "yesterdayish"],
    ],
)
def test_usage_errors(cli, args):
    result = cli(*args)
    assert result.exit_code == 2, result.output
