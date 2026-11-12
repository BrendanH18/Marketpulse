"""Recording checks and shortcuts (#130, items 11–20) on a fictional ledger."""

import json
from datetime import date

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Transaction, TxnType


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "200")
    return lambda *args: CliRunner().invoke(main, list(args), catch_exceptions=False)


@pytest.fixture
def maple(store):
    """Maple Cash tracks cash ($600 left after 10 XEQT.TO at $40); Birch TFSA holds 20 VFV.TO."""
    cash = store.add_account(Account(name="Maple Cash", type=AccountType.NONREG, track_cash=True))
    tfsa = store.add_account(Account(name="Birch TFSA", type=AccountType.TFSA))
    store.add_transaction(Transaction(cash.saved_id, TxnType.DEPOSIT, "2025-01-02", amount=1000, currency="CAD"))
    store.add_transaction(
        Transaction(cash.saved_id, TxnType.BUY, "2025-01-06", "XEQT.TO", quantity=10, price=40, currency="CAD")
    )
    store.add_transaction(
        Transaction(tfsa.saved_id, TxnType.BUY, "2025-01-06", "VFV.TO", quantity=20, price=100, currency="CAD")
    )
    return cash


def codes(result) -> list[str]:
    assert result.exit_code == 0, result.output
    return [w["code"] for w in json.loads(result.stdout)["warnings"]]


# 11. --check


def test_check_shows_warnings_after_a_real_save(cli, store, maple):
    plain = cli("buy", "XEQT.TO", "1", "40", "-a", "Maple Cash", "-d", "2025-01-11")
    assert plain.output == "✓ Bought 1 XEQT.TO @ 40.00 CAD in Maple Cash · now 11 @ avg 40.00\n"
    checked = cli("buy", "XEQT.TO", "1", "40", "-a", "Maple Cash", "-d", "2025-01-12", "--check")
    assert checked.output.splitlines() == [
        "✓ Bought 1 XEQT.TO @ 40.00 CAD in Maple Cash · now 12 @ avg 40.00",
        "! 2025-01-12 is a Sunday, when markets are closed",
    ]
    assert len(store.transactions()) == 5


def test_check_with_quiet_sends_warnings_to_stderr(cli, store, maple):
    result = cli("buy", "XEQT.TO", "1", "40", "-a", "Maple Cash", "-d", "2025-01-12", "--check", "--quiet")
    assert result.stdout == f"{store.transactions()[-1].id}\n"
    assert "Sunday" in result.stderr


# 12. --strict


def test_strict_refuses_an_entry_with_warnings(cli, store, maple):
    result = cli("sell", "XEQT.TO", "1", "40", "-a", "Maple Cash", "-d", "2025-01-11", "--strict")
    assert result.exit_code == 1
    assert result.output == "Error: Not recorded (--strict): 2025-01-11 is a Saturday, when markets are closed.\n"
    assert len(store.transactions()) == 3
    ok = cli("sell", "XEQT.TO", "1", "40", "-a", "Maple Cash", "-d", "2025-01-10", "--strict")
    assert ok.exit_code == 0 and ok.output.startswith("✓ Sold 1 XEQT.TO")
    assert len(store.transactions()) == 4


def test_strict_dry_run_validates_without_saving(cli, store, maple):
    assert cli("deposit", "5", "-a", "Maple Cash", "-d", "2025-01-08", "--dry-run", "--strict").exit_code == 0
    assert (
        cli("buy", "XEQT.TO", "1", "40", "-a", "Maple Cash", "-d", "2025-01-11", "--dry-run", "--strict").exit_code == 1
    )
    assert len(store.transactions()) == 3


# 13. Archived account


def test_warns_when_recording_into_an_archived_account(cli, store, maple):
    old = store.add_account(Account(name="Old Cedar", type=AccountType.MARGIN))
    old.archived = True
    store.update_account(old)
    result = cli("deposit", "50", "-a", "Old Cedar", "-d", "2025-01-08", "--dry-run")
    assert "! Old Cedar is archived, so this entry stays out of sight" in result.output
    assert codes(cli("deposit", "50", "-a", "Old Cedar", "-d", "2025-01-08", "--json")) == ["archived_account"]
    moved = cli("transfer", "VFV.TO", "1", "--from", "Birch TFSA", "--to", "Old Cedar", "-p", "100", "--check")
    assert "Old Cedar is archived" in moved.output


# 14. Same-day duplicates


def test_warns_about_a_matching_entry_on_the_same_day(cli, store, maple):
    result = cli("buy", "XEQT.TO", "10", "41", "-a", "Maple Cash", "-d", "2025-01-06", "--check")
    assert result.output.splitlines()[1] == "! a matching BUY on 2025-01-06 is already recorded (#2)"
    other_day = cli("dividend", "XEQT.TO", "2", "-a", "Maple Cash", "-d", "2025-01-07", "--json")
    assert codes(other_day) == []
    repeat = cli("dividend", "XEQT.TO", "2", "-a", "Maple Cash", "-d", "2025-01-07", "-m", "again", "--json")
    assert codes(repeat) == ["possible_duplicate"]


# 15. Weekend trade dates


def test_warns_about_a_weekend_trade_date_but_not_cash_events(cli, maple):
    assert codes(cli("buy", "XEQT.TO", "1", "40", "-a", "Maple Cash", "-d", "2025-01-11", "--json")) == ["weekend"]
    assert codes(cli("deposit", "5", "-a", "Maple Cash", "-d", "2025-01-11", "--json")) == []


# 16. Negative cash


def test_warns_when_cash_goes_negative(cli, maple):
    result = cli("withdraw", "700", "-a", "Maple Cash", "-d", "2025-01-08", "--check")
    assert "! cash in Maple Cash is now -100.00 CAD" in result.output
    assert codes(cli("withdraw", "1", "-a", "Birch TFSA", "-d", "2025-01-08", "--json")) == []


def test_negative_cash_counts_a_buy(cli, maple):
    result = cli("buy", "XEQT.TO", "20", "40", "-a", "Maple Cash", "-d", "2025-01-08", "--json")
    assert codes(result) == ["negative_cash"]


# 17. Price far from the last known quote


def test_warns_when_a_price_is_far_from_the_cached_quote(cli, tracker, maple):
    tracker.market.quote("XEQT.TO")  # the fake listing: $40 CAD, now in the offline cache
    today = date.today().isoformat()
    typo = cli("buy", "XEQT.TO", "1", "400", "-a", "Maple Cash", "-d", today, "--json")
    assert "price_far_from_quote" in codes(typo)
    warning = next(w for w in json.loads(typo.stdout)["warnings"] if w["code"] == "price_far_from_quote")
    assert warning["message"] == "price 400.00 CAD is far from the last known quote 40.00 CAD"
    near = cli("buy", "XEQT.TO", "1", "45", "-a", "Maple Cash", "-d", today, "--json")
    assert "price_far_from_quote" not in codes(near)
    old = cli("buy", "XEQT.TO", "1", "400", "-a", "Maple Cash", "-d", "2025-01-08", "--json")
    assert "price_far_from_quote" not in codes(old)


# 18. withdraw all


def test_withdraw_all_empties_the_cash_balance(cli, store, maple):
    result = cli("withdraw", "all", "-a", "Maple Cash", "-d", "2025-01-08", "--balance")
    assert result.output.splitlines() == [
        "✓ Withdrawal 600.00 CAD → Maple Cash on 2025-01-08",
        "  cash in Maple Cash: 0.00 CAD",
    ]
    assert store.transactions()[-1].amount == 600.0
    again = cli("withdraw", "all", "-a", "Maple Cash", "-d", "2025-01-09")
    assert again.exit_code == 1 and "No CAD cash in Maple Cash on 2025-01-09." in again.output
    untracked = cli("withdraw", "all", "-a", "Birch TFSA")
    assert untracked.exit_code == 1 and "Birch TFSA doesn't track cash" in untracked.output


# 19. --per-unit


def test_per_unit_dividend_and_roc_multiply_by_units_held(cli, store, maple):
    result = cli("dividend", "VFV.TO", "0.125", "--per-unit", "-a", "Birch TFSA", "-d", "2025-03-31")
    assert result.output == "✓ Dividend 2.50 CAD from VFV.TO → Birch TFSA on 2025-03-31 (0.1250 × 20 units)\n"
    assert store.transactions()[-1].amount == 2.5
    roc = cli("roc", "VFV.TO", "0.05", "--per-unit", "-a", "Birch TFSA", "-d", "2025-03-31", "--json")
    assert json.loads(roc.stdout)["amount"] == 1.0
    before = cli("dividend", "VFV.TO", "0.1", "--per-unit", "-a", "Birch TFSA", "-d", "2025-01-05")
    assert before.exit_code == 1 and "Birch TFSA holds no VFV.TO on 2025-01-05." in before.output


# 20. Split ratios written new:old


@pytest.mark.parametrize(
    ("text", "ratio"), [("3:1", 3.0), ("1:10", 0.1), ("2-for-1", 2.0), ("1 for 4", 0.25), ("3/2", 1.5), ("4", 4.0)]
)
def test_split_accepts_new_to_old_ratios(cli, store, maple, text, ratio):
    result = cli("split", "XEQT.TO", text, "-a", "Maple Cash", "-d", "2025-02-03")
    assert result.exit_code == 0, result.output
    assert result.output == f"✓ Split XEQT.TO ×{ratio:g} in Maple Cash\n"
    assert store.transactions()[-1].ratio == pytest.approx(ratio)


def test_split_ratio_rejects_zero_shares(cli, maple):
    result = cli("split", "XEQT.TO", "0:1", "-a", "Maple Cash")
    assert result.exit_code == 2
    assert "'0:1' needs two positive share counts, e.g. 3:1." in result.output
