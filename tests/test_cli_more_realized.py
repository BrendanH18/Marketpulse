"""The 25 additions to realized/payout inspection use only fictional local data."""

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
    maple = store.add_account(Account(name="Fictional Maple", institution="Fictional Bank"))
    gull = store.add_account(
        Account(
            name="Fictional Gull",
            type=AccountType.TFSA,
            currency="USD",
            institution="Fictional Credit",
            track_cash=True,
        )
    )
    hidden = store.add_account(Account(name="Hidden Fiction", archived=True))

    def add(acct, kind, day, symbol="", qty=0, price=0, amount=0, currency="CAD"):
        return store.add_transaction(
            Transaction(acct.saved_id, kind, day, symbol, qty, price, amount, currency=currency)
        )

    add(maple, TxnType.BUY, "2024-01-01", "MAPL", 10, 10)
    add(maple, TxnType.SELL, "2024-02-01", "MAPL", 2, 20)  # 2: +20, cost 20
    add(maple, TxnType.SELL, "2024-04-01", "MAPL", 2, 5)  # 3: -10, cost 20
    add(maple, TxnType.SELL, "2024-04-02", "MAPL", 1, 10)  # 4: zero, cost 10
    add(maple, TxnType.SELL, "2024-04-03", "MAPL", 1, 10.004)  # 5: zero rounded to cent
    add(gull, TxnType.BUY, "2024-01-02", "GULL", 10, 100, currency="USD")
    add(gull, TxnType.SELL, "2024-06-03", "GULL", 2, 130, currency="USD")  # 7: +60, cost 200
    add(maple, TxnType.DIVIDEND, "2024-02-02", "MAPL", amount=12)
    add(maple, TxnType.INTEREST, "2024-04-01", amount=3)
    add(maple, TxnType.DIVIDEND, "2024-04-02", "MAPL", amount=8)
    add(gull, TxnType.DIVIDEND, "2024-01-16", "GULL", amount=20, currency="USD")
    add(gull, TxnType.DRIP, "2024-04-03", "GULL", 1, 100, currency="USD")
    add(hidden, TxnType.BUY, "2024-01-01", "HIDDEN", 10, 10)
    add(hidden, TxnType.SELL, "2024-02-01", "HIDDEN", 1, 100)
    add(hidden, TxnType.DIVIDEND, "2024-02-02", "HIDDEN", amount=900)
    fake.offline = True
    runner = CliRunner()

    def invoke(*args):
        transactions = store.transactions()
        snapshots = store.snapshots()
        accounts = store.accounts(include_archived=True)
        calls = len(fake.calls)
        result = runner.invoke(main, list(args), catch_exceptions=False)
        assert len(fake.calls) == calls
        assert store.transactions() == transactions
        assert store.snapshots() == snapshots
        assert store.accounts(include_archived=True) == accounts
        assert "HIDDEN" not in result.output and "Hidden Fiction" not in result.output
        return result

    return invoke


def data(cli, command, *args):
    result = cli(command, *args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


@pytest.mark.parametrize("command", ["realized", "payouts"])
def test_shared_symbol_and_account_filters(cli, command):
    assert {r["symbol"] for r in data(cli, command, "--symbols", " mapl ")["rows"]} == {"MAPL"}
    both = data(cli, command, "--symbols", "MAPL", "--symbols", "gull")["rows"]
    assert {r["symbol"] for r in both} == {"MAPL", "GULL"}
    assert {r["account"] for r in data(cli, command, "--account-type", "TFSA")["rows"]} == {"Fictional Gull"}
    assert {r["account"] for r in data(cli, command, "--institution", " fictional bank ")["rows"]} == {
        "Fictional Maple"
    }
    assert {r["account"] for r in data(cli, command, "--registered")["rows"]} == {"Fictional Gull"}
    assert {r["account"] for r in data(cli, command, "--nonregistered")["rows"]} == {"Fictional Maple"}
    assert {r["account"] for r in data(cli, command, "--cash-tracked")["rows"]} == {"Fictional Gull"}
    assert {r["account"] for r in data(cli, command, "--cash-untracked")["rows"]} == {"Fictional Maple"}
    assert {r["symbol"] for r in data(cli, command, "--symbol-prefix", " gu ")["rows"]} == {"GULL"}
    assert data(cli, command, "--registered", "--institution", "Fictional Bank")["rows"] == []
    assert data(cli, command, "--symbols", "GULL", "--symbol", "MAPL")["rows"] == []


@pytest.mark.parametrize("command", ["realized", "payouts"])
def test_shared_currency_and_date_sets_intersect(cli, command):
    assert {r["currency"] for r in data(cli, command, "--exclude-currency", " usd ")["rows"]} == {"CAD"}
    assert data(cli, command, "--exclude-currency", "usd", "--exclude-currency", "cad")["rows"] == []
    selected = data(cli, command, "--on", "2024-04-01", "--on", "2024-04-02", "--exclude-date", "2024-04-02")
    assert [r["date"] for r in selected["rows"]] == ["2024-04-01"]
    assert data(cli, command, "--on", "2024-04-01", "--until", "2024-03-31")["rows"] == []
    # Monday 1 April, Tuesday 2 April, Wednesday 3 April.
    selected = data(cli, command, "--month", "4", "--weekday", "MON", "--weekday", "tue")
    assert [r["date"] for r in selected["rows"]] == ["2024-04-01", "2024-04-02"]
    selected = data(cli, command, "--month", "4", "--exclude-date", "2024-04-01", "--exclude-date", "2024-04-02")
    assert [r["date"] for r in selected["rows"]] == ["2024-04-03"]


def test_sale_cost_and_transaction_id_bounds_apply_before_counts_and_totals(cli):
    assert cli("realized", "--min-cost", "20", "--max-cost", "20", "--count").output.strip() == "2"
    selected = data(cli, "realized", "--min-cost", "200", "--max-cost", "200")
    assert [r["txn_id"] for r in selected["rows"]] == [7]
    assert selected["totals"] == {"USD": {"count": 1, "proceeds": 260, "cost": 200, "gain": 60}}
    assert [r["txn_id"] for r in data(cli, "realized", "--min-txn-id", "3", "--max-txn-id", "4")["rows"]] == [3, 4]
    assert data(cli, "realized", "--min-txn-id", "8")["rows"] == []
    assert cli("realized", "--max-txn-id", "1", "--count").output.strip() == "0"


def test_breakeven_matches_existing_gain_and_loss_cent_rounding(cli):
    selected = data(cli, "realized", "--breakeven-only")
    assert [r["txn_id"] for r in selected["rows"]] == [4, 5]
    assert selected["rows"][1]["gain"] == pytest.approx(0.004)
    assert cli("realized", "--breakeven-only", "--max-txn-id", "4", "--count").output.strip() == "1"


@pytest.mark.parametrize(
    ("by", "expected"),
    [
        ("year", [{"group": "2024", "count": 5}]),
        (
            "month",
            [{"group": "2024-02", "count": 1}, {"group": "2024-04", "count": 3}, {"group": "2024-06", "count": 1}],
        ),
        ("account", [{"group": "Fictional Gull", "count": 1}, {"group": "Fictional Maple", "count": 4}]),
        ("symbol", [{"group": "GULL", "count": 1}, {"group": "MAPL", "count": 4}]),
    ],
)
def test_sales_count_summaries_support_all_formats_and_selection(cli, by, expected):
    assert data(cli, "realized", "--summary", by) == expected
    result = cli("realized", "--summary", by, "--csv")
    assert list(csv.DictReader(io.StringIO(result.output))) == [
        {"group": item["group"], "count": str(item["count"])} for item in expected
    ]
    result = cli("realized", "--summary", by)
    assert result.exit_code == 0 and "Matching realized sales" in " ".join(result.output.split())
    assert data(cli, "realized", "--summary", by, "--year", "2023") == []
    assert cli("realized", "--summary", by, "--year", "2023", "--csv").output.strip() == "group,count"
    selected = data(cli, "realized", "--summary", by, "--registered")
    assert len(selected) == 1 and selected[0]["count"] == 1


def test_payout_sorting_pagination_and_totals(cli):
    rows = data(cli, "payouts", "--sort", "amount", "--descending", "--offset", "1", "--limit", "2", "--page-info")
    assert [r["amount"] for r in rows["rows"]] == [20, 12]
    assert rows["total"] == 5 and rows["next_offset"] == 3
    assert rows["totals"] == {"CAD": {"count": 3, "amount": 23}, "USD": {"count": 2, "amount": 120}}
    assert [r["date"] for r in data(cli, "payouts", "--descending")["rows"]] == [
        "2024-04-03",
        "2024-04-02",
        "2024-04-01",
        "2024-02-02",
        "2024-01-16",
    ]
    for field in ("date", "account", "symbol", "kind", "currency"):
        sorted_rows = data(cli, "payouts", "--sort", field)["rows"]
        values = [row[field].casefold() for row in sorted_rows]
        assert values == sorted(values)
    rows = list(csv.DictReader(io.StringIO(cli("payouts", "--sort", "amount", "--limit", "1", "--csv").output)))
    assert len(rows) == 1 and rows[0]["amount"] == "3.0"


def test_payout_kind_exclusions_intersect_inclusions(cli):
    assert [r["kind"] for r in data(cli, "payouts", "--exclude-kind", "DIVIDEND")["rows"]] == ["interest", "drip"]
    selected = data(cli, "payouts", "--exclude-kind", "dividend", "--exclude-kind", "interest")
    assert [r["kind"] for r in selected["rows"]] == ["drip"]
    assert data(cli, "payouts", "--kind", "interest", "--exclude-kind", "interest")["rows"] == []


@pytest.mark.parametrize(
    ("by", "expected"),
    [
        ("quarter", [("2024-Q1", "CAD", 12), ("2024-Q1", "USD", 20), ("2024-Q2", "CAD", 11), ("2024-Q2", "USD", 100)]),
        ("kind", [("dividend", "CAD", 20), ("dividend", "USD", 20), ("drip", "USD", 100), ("interest", "CAD", 3)]),
        ("currency", [("CAD", "CAD", 23), ("USD", "USD", 120)]),
    ],
)
def test_new_payout_groups_remain_separated_by_native_currency(cli, by, expected):
    payload = data(cli, "payouts", "--by", by)
    assert [(r["group"], r["currency"], r["amount"]) for r in payload["groups"]] == expected
    assert cli("payouts", "--by", by, "--count").output.strip() == str(len(expected))
    page = data(cli, "payouts", "--by", by, "--limit", "1", "--offset", "1", "--page-info")
    assert page["total"] == len(expected) and page["groups"] == payload["groups"][1:2]
    assert page["totals"] == payload["totals"]
    csv_rows = list(csv.DictReader(io.StringIO(cli("payouts", "--by", by, "--csv").output)))
    assert len(csv_rows) == len(expected)
    assert cli("payouts", "--by", by).exit_code == 0


def test_privacy_masks_new_payout_views_but_script_exports_stay_raw(cli):
    assert cli("config", "set", "privacy", "true").exit_code == 0
    output = cli("payouts", "--by", "kind").output
    assert "••••" in output and "120.00" not in output and "100.00" not in output
    output = cli("payouts", "--sort", "amount", "--descending").output
    assert "••••" in output and "100.00" not in output
    output = cli("realized", "--breakeven-only").output
    assert "••••" in output and "10.00" not in output
    assert data(cli, "payouts", "--by", "currency")["groups"][1]["amount"] == 120


@pytest.mark.parametrize("command", ["realized", "payouts"])
@pytest.mark.parametrize(
    "args",
    [
        ("--symbols", " "),
        ("--institution", " "),
        ("--symbol-prefix", ""),
        ("--exclude-currency", " "),
        ("--on", "2024-02-30"),
        ("--exclude-date", "oops"),
        ("--weekday", "someday"),
        ("--account-type", "unknown"),
    ],
)
def test_shared_bad_filters_are_usage_errors(cli, command, args):
    assert cli(command, *args).exit_code == 2


@pytest.mark.parametrize(
    "args",
    [
        ("realized", "--min-cost", "nan"),
        ("realized", "--max-cost", "inf"),
        ("realized", "--min-cost", "2", "--max-cost", "1"),
        ("realized", "--min-txn-id", "2", "--max-txn-id", "1"),
        ("realized", "--min-txn-id", "0"),
        ("realized", "--max-txn-id", "-1"),
        ("realized", "--breakeven-only", "--gains-only"),
        ("realized", "--breakeven-only", "--losses-only"),
        ("payouts", "--sort", "amount", "--newest-first"),
        ("payouts", "--descending", "--newest-first"),
        ("payouts", "--sort", "kind", "--count"),
        ("payouts", "--descending", "--count"),
        ("payouts", "--sort", "amount", "--by", "kind"),
        ("payouts", "--descending", "--by", "quarter"),
        ("payouts", "--exclude-kind", "rent"),
    ],
)
def test_specific_bad_combinations_are_usage_errors(cli, args):
    assert cli(*args).exit_code == 2


@pytest.mark.parametrize(
    "args",
    [
        ("--count",),
        ("--newest-first",),
        ("--sort", "date"),
        ("--descending",),
        ("--limit", "1"),
        ("--offset", "0"),
        ("--page-info", "--json"),
    ],
)
def test_summary_rejects_options_that_suggest_paged_or_ordered_counts(cli, args):
    assert cli("realized", "--summary", "year", *args).exit_code == 2
