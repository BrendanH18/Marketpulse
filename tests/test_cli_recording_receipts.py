"""Recording previews, receipts and shortcuts (#130, items 1–10) on a fictional ledger."""

import json
from dataclasses import replace

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Transaction, TxnType


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "200")

    def run(*args, input=None):
        return CliRunner().invoke(main, list(args), input=input, catch_exceptions=False)

    return run


@pytest.fixture
def maple(store):
    """Maple Cash tracks cash and holds 10 XEQT.TO bought at $40; Maple TFSA doesn't track cash."""
    cash = store.add_account(Account(name="Maple Cash", type=AccountType.NONREG, track_cash=True))
    store.add_account(Account(name="Maple TFSA", type=AccountType.TFSA))
    store.add_transaction(Transaction(cash.saved_id, TxnType.DEPOSIT, "2025-01-02", amount=1000, currency="CAD"))
    store.add_transaction(
        Transaction(cash.saved_id, TxnType.BUY, "2025-01-06", "XEQT.TO", quantity=10, price=40, currency="CAD")
    )
    return cash


def receipt(result) -> dict:
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


# 1. --dry-run


ALL_COMMANDS = [
    ["buy", "XEQT.TO", "2", "41", "-a", "Maple Cash", "-d", "2025-01-08"],
    ["sell", "XEQT.TO", "2", "42", "-a", "Maple Cash", "-d", "2025-01-08"],
    ["drip", "XEQT.TO", "0.1", "41", "-a", "Maple Cash", "-d", "2025-01-08", "-c", "CAD"],
    ["dividend", "XEQT.TO", "3", "-a", "Maple Cash", "-d", "2025-01-08"],
    ["interest", "1.5", "-a", "Maple Cash", "-d", "2025-01-08"],
    ["deposit", "100", "-a", "Maple Cash", "-d", "2025-01-08"],
    ["withdraw", "100", "-a", "Maple Cash", "-d", "2025-01-08"],
    ["fee", "5", "-a", "Maple Cash", "-d", "2025-01-08"],
    ["split", "XEQT.TO", "2", "-a", "Maple Cash", "-d", "2025-01-08"],
    ["roc", "XEQT.TO", "2", "-a", "Maple Cash", "-d", "2025-01-08"],
    ["transfer", "XEQT.TO", "2", "--from", "Maple Cash", "--to", "Maple TFSA", "-p", "41", "-d", "2025-01-08"],
]


@pytest.mark.parametrize("args", ALL_COMMANDS, ids=lambda a: a[0])
def test_dry_run_previews_every_command_without_saving(cli, store, maple, args):
    before = store.transactions()
    result = cli(*args, "--dry-run")
    assert result.exit_code == 0, result.output
    assert result.output.startswith("○ Dry run, not saved: ")
    assert store.transactions() == before
    # The preview says exactly what the real command then prints.
    real = cli(*args)
    assert result.output.splitlines()[0].removeprefix("○ Dry run, not saved: ") == real.output.splitlines()[0][2:]


def test_dry_run_never_creates_the_first_account(cli, store):
    for flag in ("--dry-run", "--confirm"):
        result = cli("deposit", "100", flag, input="n\n")
        assert result.exit_code == 1 and "a preview doesn't create one" in result.output
        assert store.accounts() == [] and store.transactions() == []


def test_dry_run_uses_a_configured_default_account(cli, store, tracker):
    old = store.add_account(Account(name="Old Cedar", type=AccountType.NONREG))
    old.archived = True
    store.update_account(old)
    tracker.config.default_account = "Old Cedar"
    result = cli("deposit", "50", "--dry-run")
    assert result.exit_code == 0 and "Dry run, not saved: Deposit 50.00" in result.output
    assert store.transactions() == []


def test_dry_run_refuses_what_the_save_would_refuse(cli, store, maple):
    result = cli("sell", "XEQT.TO", "11", "45", "-a", "Maple Cash", "-d", "2025-01-08", "--dry-run")
    assert result.exit_code == 1
    assert "Cannot sell 11 XEQT.TO — only 10 held in this account." in result.output
    future = cli("deposit", "5", "-a", "Maple Cash", "-d", "2999-01-01", "--dry-run")
    assert future.exit_code != 0
    assert len(store.transactions()) == 2


def test_dry_run_shows_the_position_after_the_entry(cli, maple):
    result = cli("buy", "XEQT.TO", "10", "50", "-a", "Maple Cash", "-d", "2025-01-08", "--dry-run")
    assert "now 20 @ avg 45.00" in result.output


def test_new_options_refuse_a_request_id(cli, maple):
    result = cli(
        "deposit", "5", "-a", "Maple Cash", "--dry-run", "--request-id", "11111111-2222-3333-4444-555555555555"
    )
    assert result.exit_code == 2
    assert "--request-id can't be combined with --dry-run." in result.output


# 2. --json receipts


def test_json_receipt_names_every_saved_field(cli, store, maple):
    data = receipt(cli("buy", "XEQT.TO", "5", "42", "-a", "Maple Cash", "-d", "2025-01-08", "-f", "4.95", "--json"))
    saved = store.transactions()[-1]
    assert data["id"] == saved.id
    assert (data["recorded"], data["dry_run"], data["duplicate"]) == (True, False, False)
    assert {k: data[k] for k in ("type", "date", "account", "symbol", "quantity", "price", "fees", "currency")} == {
        "type": "BUY",
        "date": "2025-01-08",
        "account": "Maple Cash",
        "symbol": "XEQT.TO",
        "quantity": 5.0,
        "price": 42.0,
        "fees": 4.95,
        "currency": "CAD",
    }
    assert data["message"].startswith("Bought 5 XEQT.TO @ 42.00 CAD in Maple Cash")


def test_json_dry_run_has_no_id_and_saves_nothing(cli, store, maple):
    data = receipt(cli("deposit", "50", "-a", "Maple Cash", "-d", "2025-01-08", "--json", "--dry-run"))
    assert (data["id"], data["recorded"], data["dry_run"], data["amount"]) == (None, False, True, 50.0)
    assert len(store.transactions()) == 2


def test_json_keeps_warnings_off_stdout(cli, maple):
    result = cli("transfer", "XEQT.TO", "1", "--from", "Maple Cash", "--to", "Maple TFSA", "-d", "2025-01-08", "--json")
    data = receipt(result)
    assert data["target_account"] == "Maple TFSA"
    assert "no --price given" in result.stderr


# 3. The position and cash after the entry


def test_json_after_block_reports_position_gain_and_cash(cli, maple):
    after = receipt(cli("sell", "XEQT.TO", "4", "45", "-a", "Maple Cash", "-d", "2025-01-08", "--json"))["after"]
    assert after["position"] == {"quantity": 6.0, "book": 240.0, "avg_cost": 40.0, "currency": "CAD"}
    assert after["realized_gain"] == pytest.approx(20.0)
    assert after["cash"] == {"CAD": pytest.approx(780.0)}


def test_json_after_block_for_a_transfer_and_an_untracked_account(cli, maple):
    after = receipt(
        cli("transfer", "XEQT.TO", "10", "--from", "Maple Cash", "--to", "Maple TFSA", "-p", "40", "--json")
    )["after"]
    assert after["position"] is None
    assert after["target_position"]["quantity"] == 10.0
    tfsa = receipt(cli("deposit", "20", "-a", "Maple TFSA", "-d", "2025-01-08", "--json"))["after"]
    assert tfsa == {"position": None, "realized_gain": None, "cash": None}


# 4. --quiet


def test_quiet_prints_only_the_new_id(cli, store, maple):
    result = cli("dividend", "XEQT.TO", "2.5", "-a", "Maple Cash", "-d", "2025-01-31", "--quiet")
    assert result.exit_code == 0
    assert result.stdout == f"{store.transactions()[-1].id}\n"


def test_quiet_dry_run_prints_nothing_and_json_quiet_clash(cli, maple):
    assert cli("deposit", "5", "-a", "Maple Cash", "--quiet", "--dry-run").stdout == ""
    clash = cli("deposit", "5", "-a", "Maple Cash", "--quiet", "--json")
    assert clash.exit_code == 2 and "--json can't be combined with --quiet." in clash.output


# 5. --balance


def test_balance_shows_cash_after_the_entry(cli, maple):
    result = cli("withdraw", "250", "-a", "Maple Cash", "-d", "2025-01-08", "--balance")
    assert result.output.splitlines()[0] == "✓ Withdrawal 250.00 CAD → Maple Cash on 2025-01-08"
    assert result.output.splitlines()[1] == "  cash in Maple Cash: 350.00 CAD"


def test_balance_and_negative_cash_are_masked_in_privacy_mode(cli, tracker, maple):
    tracker.config.privacy = True
    result = cli("withdraw", "700", "-a", "Maple Cash", "-d", "2025-01-08", "--balance", "--check")
    assert "-100.00" not in result.output
    assert "  cash in Maple Cash: •••• CAD" in result.output.splitlines()
    assert "! cash in Maple Cash is now •••• CAD" in result.output


def test_balance_for_a_transfer_names_both_accounts(cli, maple):
    result = cli(
        "transfer", "XEQT.TO", "1", "--from", "Maple Cash", "--to", "Maple TFSA", "-p", "40", "-d", "2025-01-08",
        "--balance",
    )  # fmt: skip
    assert "cash in Maple Cash: " in result.output
    assert "Maple TFSA doesn't track cash" in result.output


# 6. --confirm


def test_confirm_saves_only_after_yes(cli, store, maple):
    declined = cli("fee", "9.99", "-a", "Maple Cash", "-d", "2025-01-08", "--confirm", input="n\n")
    assert declined.exit_code == 1
    assert "○ Dry run, not saved: Fee 9.99 CAD → Maple Cash on 2025-01-08" in declined.output
    assert "Not recorded." in declined.output
    assert len(store.transactions()) == 2
    accepted = cli("fee", "9.99", "-a", "Maple Cash", "-d", "2025-01-08", "--confirm", input="y\n")
    assert accepted.exit_code == 0
    assert "✓ Fee 9.99 CAD → Maple Cash on 2025-01-08" in accepted.output
    assert store.transactions()[-1].type is TxnType.FEE


def test_confirm_refuses_non_interactive_modes(cli, maple):
    result = cli("fee", "1", "-a", "Maple Cash", "--confirm", "--json")
    assert result.exit_code == 2 and "--confirm can't be combined with --json." in result.output


# 7. --once


def test_once_skips_an_identical_entry(cli, store, maple):
    args = ["dividend", "XEQT.TO", "2.5", "-a", "Maple Cash", "-d", "2025-01-31", "-m", "Q4", "--once"]
    first = cli(*args)
    assert first.output.startswith("✓ Dividend 2.50 CAD")
    again = cli(*args)
    saved = store.transactions()[-1]
    assert again.output == f"✓ Already recorded (#{saved.id}); nothing saved.\n"
    assert len(store.transactions()) == 3
    assert cli(*args, "--quiet").stdout == f"{saved.id}\n"
    data = receipt(cli(*args, "--json"))
    assert (data["id"], data["duplicate"], data["recorded"]) == (saved.id, True, False)
    # A different note is a different entry.
    cli("dividend", "XEQT.TO", "2.5", "-a", "Maple Cash", "-d", "2025-01-31", "-m", "Q1", "--once")
    assert len(store.transactions()) == 4


def test_once_checks_again_under_the_write_lock(cli, store, maple, monkeypatch):
    """Another run saves the same entry just after the first check: it is still saved once."""
    from marketpulse.cli import recording

    real = recording._same
    calls = []

    def racing(app, txn):
        calls.append(1)
        if len(calls) == 1:
            store.add_transaction(replace(txn, id=None))  # the other run wins the race
            return None
        return real(app, txn)

    monkeypatch.setattr(recording, "_same", racing)
    result = cli("dividend", "XEQT.TO", "2.5", "-a", "Maple Cash", "-d", "2025-01-31", "--once")
    assert result.output == f"✓ Already recorded (#{store.transactions()[-1].id}); nothing saved.\n"
    assert len(store.transactions()) == 3


# 8. --total


def test_total_sets_price_from_the_gross_value(cli, store, maple):
    result = cli("buy", "XEQT.TO", "8", "--total", "1000", "-c", "CAD", "-a", "Maple Cash", "-d", "2025-01-08")
    assert result.output.startswith("✓ Bought 8 XEQT.TO @ 125.00 CAD")
    assert store.transactions()[-1].price == 125.0
    cli("drip", "XEQT.TO", "0.25", "--total", "10", "-c", "CAD", "-a", "Maple Cash", "-d", "2025-01-31")
    assert store.transactions()[-1].price == 40.0
    sold = cli("sell", "XEQT.TO", "3", "--total", "150", "-c", "CAD", "-a", "Maple Cash", "-d", "2025-02-03")
    assert "@ 50.00 CAD" in sold.output


def test_total_is_validated(cli, maple):
    both = cli("buy", "XEQT.TO", "8", "40", "--total", "1000", "-a", "Maple Cash", "-d", "2025-01-08")
    assert both.exit_code == 2 and "Give PRICE or --total, not both." in both.output
    zero = cli("buy", "XEQT.TO", "8", "--total", "0", "-a", "Maple Cash")
    assert zero.exit_code == 2 and "must be a positive amount" in zero.output
    drip = cli("drip", "XEQT.TO", "1", "2", "--total", "5", "-a", "Maple Cash")
    assert drip.exit_code == 2 and "Give PRICE or --total, not both." in drip.output
    no_qty = cli("sell", "XEQT.TO", "0", "--total", "5", "-a", "Maple Cash", "-d", "2025-01-08")
    assert no_qty.exit_code == 1 and "Quantity must be positive." in no_qty.output


# 9. sell all


def test_sell_all_sells_the_whole_position(cli, store, maple):
    result = cli("sell", "XEQT.TO", "all", "45", "-a", "Maple Cash", "-d", "2025-01-08")
    assert result.output == "✓ Sold 10 XEQT.TO @ 45.00 CAD in Maple Cash — realized +50.00 CAD · position closed\n"
    assert store.transactions()[-1].quantity == 10.0
    none = cli("sell", "XEQT.TO", "ALL", "45", "-a", "Maple Cash", "-d", "2025-01-09")
    assert none.exit_code == 1 and "Maple Cash holds no XEQT.TO on 2025-01-09." in none.output


def test_sell_all_counts_units_held_on_the_entry_date(cli, store, maple):
    cli("buy", "XEQT.TO", "5", "40", "-a", "Maple Cash", "-d", "2025-03-03")
    result = cli("sell", "XEQT.TO", "all", "45", "-a", "Maple Cash", "-d", "2025-02-03", "--dry-run")
    assert "Sold 10 XEQT.TO" in result.output


# 10. transfer all


def test_transfer_all_moves_the_whole_position(cli, store, maple):
    result = cli(
        "transfer", "XEQT.TO", "all", "--from", "Maple Cash", "--to", "Maple TFSA", "-p", "41", "-d", "2025-01-08"
    )
    assert result.output == "✓ Transferred 10 XEQT.TO Maple Cash → Maple TFSA\n"
    assert store.transactions()[-1].quantity == 10.0
    empty = cli("transfer", "XEQT.TO", "all", "--from", "Maple TFSA", "--to", "Maple Cash", "-d", "2025-01-07")
    assert empty.exit_code == 1 and "Maple TFSA holds no XEQT.TO on 2025-01-07." in empty.output
