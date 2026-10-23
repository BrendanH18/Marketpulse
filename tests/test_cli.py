import json
import sqlite3
from dataclasses import replace
from uuid import uuid4

import click
import pytest
from click.testing import CliRunner

from marketpulse.cli import App, main
from marketpulse.config import Config, config_path
from marketpulse.models import Account


@pytest.fixture
def cli(tracker, monkeypatch, fake):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "160")
    fake.set_history("AAPL", {"2024-01-02": 150.0, "2024-01-03": 155.0, "2024-01-04": 152.0})
    runner = CliRunner()

    def invoke(*args: str):
        return runner.invoke(main, list(args), catch_exceptions=False)

    return invoke


def test_trading_flow(cli, store):
    assert "Added My TFSA" in cli("accounts", "add", "My TFSA", "-t", "TFSA").output
    out = cli("buy", "AAPL", "10", "150", "-a", "My TFSA", "--fees", "5").output
    assert "Bought 10 AAPL @ 150.00 USD in My TFSA" in out and "avg 150.50" in out
    live = cli("buy", "XEQT.TO", "5", "-a", "tfsa").output
    assert "@ 40.00 CAD" in live
    oversell = cli("sell", "AAPL", "20", "160", "-a", "My TFSA")
    assert oversell.exit_code == 1 and "only 10 held" in oversell.output
    sold = cli("sell", "AAPL", "4", "160", "-a", "My TFSA").output
    assert "realized +38.00 USD" in sold  # 4 × (160 − 150.50 avg incl. fees)
    assert "BUY" in cli("activity").output
    assert "Deleted transaction" in cli("undo", "-y").output
    assert len(store.transactions()) == 2


@pytest.mark.parametrize(
    "command",
    [
        ("buy", "AAPL", "1", "100"),
        ("sell", "AAPL", "1", "100"),
        ("deposit", "100"),
        ("withdraw", "100"),
        ("dividend", "AAPL", "100"),
        ("interest", "100"),
        ("fee", "100"),
    ],
)
def test_native_save_retries_after_confirmation_failure(cli, store, monkeypatch, command):
    cli("accounts", "add", "Fictional TFSA", "--type", "TFSA")
    if command[0] == "sell":
        cli("buy", "AAPL", "1", "90")
    before = len(store.transactions())
    request_id = str(uuid4())
    args = (command[0], "--request-id", request_id, *command[1:])

    def fail_confirmation(self, message):
        raise click.ClickException("Simulated post-commit confirmation failure")

    with monkeypatch.context() as patch:
        patch.setattr(App, "ok", fail_confirmation)
        failed = cli(*args)
    assert failed.exit_code == 1 and "confirmation failure" in failed.output
    assert len(store.transactions()) == before + 1
    status = json.loads(cli("desktop", "transaction-status", request_id).output)
    assert status == {"recorded": True, "transaction_id": store.transactions()[-1].id}
    # A SELL retry must bypass the now-empty position's oversell guard too.
    retry = cli(*args)
    assert retry.exit_code == 0 and "Transaction already recorded" in retry.output
    assert len(store.transactions()) == before + 1


def test_request_reuse_rejects_changed_intent_and_allows_intentional_duplicates(cli, store):
    request_id = str(uuid4())
    assert cli("deposit", "100", "--request-id", request_id).exit_code == 0
    changed = cli("deposit", "200", "--request-id", request_id)
    assert changed.exit_code == 1 and "different transaction" in changed.output
    assert cli("fee", "100", "--request-id", request_id).exit_code == 1
    assert len(store.transactions()) == 1
    assert cli("deposit", "100", "--request-id", str(uuid4())).exit_code == 0
    assert cli("deposit", "100").exit_code == 0  # ordinary terminal behavior stays unchanged
    assert len(store.transactions()) == 3


def test_request_status_is_offline_and_unsaved_requests_can_be_corrected(cli, store, fake):
    cli("accounts", "add", "Fictional TFSA")
    request_id = str(uuid4())
    failed = cli("buy", "AAPL", "0", "100", "--currency", "USD", "--request-id", request_id)
    assert failed.exit_code == 1
    fake.offline = True
    calls = len(fake.calls)
    assert json.loads(cli("desktop", "transaction-status", request_id).output) == {
        "recorded": False,
        "transaction_id": None,
    }
    assert len(fake.calls) == calls
    assert cli("buy", "AAPL", "1", "100", "--currency", "USD", "--request-id", request_id).exit_code == 0


def test_retry_does_not_resolve_changed_market_data_or_recreate_deleted_entry(cli, store, fake, monkeypatch):
    request_id = str(uuid4())
    args = ("buy", "AAPL", "1", "--request-id", request_id)
    assert cli(*args).exit_code == 0
    txn = store.transactions()[0]
    store.delete_transaction(txn.saved_id)
    store.delete_account(txn.account_id)
    fake.offline = True
    calls = len(fake.calls)
    # Receipt survives edits/deletions and bypasses account creation and quote lookup.
    assert cli(*args).exit_code == 0
    assert len(fake.calls) == calls and store.transactions() == [] and store.accounts() == []


def test_account_resolution_errors(cli, store):
    cli("accounts", "add", "A")
    cli("accounts", "add", "B")
    result = cli("buy", "AAPL", "1", "1")
    assert result.exit_code == 1 and "Several accounts" in result.output
    missing = cli("buy", "AAPL", "1", "1", "-a", "Nope")
    assert missing.exit_code == 1 and "No account 'Nope'" in missing.output


def test_first_trade_creates_default_account(cli, store):
    assert "Created account 'Main'" in cli("buy", "AAPL", "1", "100").output


def test_income_events_and_assets(cli, store):
    cli("accounts", "add", "Main")
    assert "Deposit" in cli("deposit", "1000").output
    assert "Dividend" in cli("dividend", "AAPL", "12.5").output
    assert "Added GIC1" in cli("asset", "fixed", "GIC1", "5000", "--rate", "4", "--maturity", "2030-01-01").output
    assert "Added HOUSE" in cli("asset", "manual", "HOUSE", "500000", "--class", "real_estate").output
    assert "valued at" in cli("asset", "value", "HOUSE", "550000").output
    assert "GIC1" in cli("asset", "list").output


def test_status_outputs(cli, store):
    cli("buy", "AAPL", "1", "100")
    payload = json.loads(cli("status", "--json").output)
    assert payload["net_worth"] == pytest.approx(270)
    waybar = json.loads(cli("status", "--waybar").output)
    assert waybar["class"] == "up" and "Net worth" in waybar["tooltip"]
    assert "▲" in cli("status", "--short").output
    assert "AAPL" in cli("holdings").output


def test_market_commands(cli):
    assert "Apple Inc." in cli("quote", "AAPL").output
    assert "XEQT.TO" in cli("quote", "AAPL", "XEQT.TO").output
    assert cli("chart", "AAPL", "-p", "1mo").exit_code == 0
    bad = cli("quote", "NOPE")
    assert bad.exit_code == 1


def test_config_theme_alerts_export(cli):
    assert cli("config", "set", "theme", "Kanagawa").exit_code == 0
    assert Config.load(config_path()).theme == "kanagawa"
    assert cli("config", "set", "refresh_seconds", "abc").exit_code == 1
    assert cli("config", "set", "refresh_seconds", "1").exit_code == 1
    assert cli("config", "set", "capital_gains_inclusion", "50").exit_code == 1
    assert cli("config", "set", "capital_gains_inclusion", "0.5").exit_code == 0
    assert cli("config", "set", "privacy", "yes").exit_code == 0
    assert cli("theme", "set", "osaka", "jade").exit_code == 0
    assert cli("theme").exit_code == 0
    assert "Alert #1: AAPL ≥ 100.00" in cli("alerts", "add", "AAPL", ">", "100").output
    assert "Fired" in cli("alerts", "check").output
    cli("buy", "AAPL", "1", "100")
    assert cli("export").output.startswith("date,account,type")


def test_backup_commands(cli, store, tmp_path):
    assert "No backups yet" in cli("backup", "list").output
    assert "Backed up to" in cli("backup").output  # bare `backup` backs up now
    cli("backup", "now", str(tmp_path / "copy.db"))
    assert (tmp_path / "copy.db").exists()
    listing = cli("backup", "list").output
    assert "manual" in listing and "copy.db" not in listing  # explicit paths live outside the backups dir


def test_backup_restore_command(cli, store, tmp_path):
    cli("accounts", "add", "My TFSA", "-t", "TFSA")
    taken = store.backup(dest=store.backup_dir / "marketpulse-20260101-090000-manual.db")
    cli("accounts", "add", "Taxable", "-t", "NONREG")
    assert cli("backup", "restore").exit_code != 0  # a backup or --latest is required
    # Declining the confirmation changes nothing.
    declined = CliRunner().invoke(main, ["backup", "restore", "--latest"], input="n\n")
    assert "taken 2026-01-01 09:00" in declined.output and len(store.accounts()) == 2
    # A file name from `backup list` is found in the backups directory.
    out = cli("backup", "restore", "-y", taken.name).output
    assert "Restored marketpulse-20260101-090000-manual.db: 1 accounts, 0 transactions" in out
    assert [a.name for a in store.accounts()] == ["My TFSA"]
    (safety,) = [p for p in store.backups() if store.backup_reason(p) == "pre-restore"]
    assert safety.name in out.replace("\n", "")
    # --latest skips the pre-restore copy the restore just made.
    cli("backup", "restore", "--latest", "-y")
    assert [a.name for a in store.accounts()] == ["My TFSA"]
    # Undo the restore by restoring its pre-restore backup.
    cli("backup", "restore", "-y", str(safety))
    assert sorted(a.name for a in store.accounts()) == ["My TFSA", "Taxable"]
    bad = tmp_path / "bad.db"
    bad.write_text("not a ledger")
    failed = cli("backup", "restore", "-y", str(bad))
    assert failed.exit_code == 1 and "database. Nothing was changed." in failed.output
    assert sorted(a.name for a in store.accounts()) == ["My TFSA", "Taxable"]


def test_backup_restore_prefers_the_backups_folder_for_a_bare_name(cli, store, tmp_path, monkeypatch):
    cli("accounts", "add", "My TFSA", "-t", "TFSA")
    taken = store.backup(dest=store.backup_dir / "marketpulse-20260101-090000-manual.db")
    cli("accounts", "add", "Taxable", "-t", "NONREG")
    # The current folder has an unrelated file with the same name: it must not be restored instead.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    store.backup(dest=elsewhere / taken.name)
    monkeypatch.chdir(elsewhere)
    cli("backup", "restore", "-y", taken.name)
    assert [a.name for a in store.accounts()] == ["My TFSA"]
    # "./name" means the local file, even though `Path` would drop the "./".
    cli("backup", "restore", "-y", f"./{taken.name}")
    assert sorted(a.name for a in store.accounts()) == ["My TFSA", "Taxable"]
    # A name the backups folder doesn't have is still found locally, and shown in full.
    store.backup(dest=elsewhere / "local.db")
    prompt = CliRunner().invoke(main, ["backup", "restore", "local.db"], input="n\n")
    assert str((elsewhere / "local.db").resolve()) in prompt.output


def test_a_trade_whose_quote_lookup_spans_a_restore_is_refused(cli, store, tracker, monkeypatch):
    cli("accounts", "add", "Current TFSA", "-t", "TFSA")
    other = store.backup(dest=store.backup_dir / "marketpulse-20260101-090000-manual.db")
    conn = sqlite3.connect(other)
    conn.execute("UPDATE accounts SET name = 'Other RRSP', type = 'RRSP'")  # same ID, another account
    conn.commit()
    conn.close()
    real_quote = tracker.market.quote

    def restore_mid_lookup(symbol):
        store.restore(other)  # in another terminal, while this command waits for the quote
        return real_quote(symbol)

    monkeypatch.setattr(tracker.market, "quote", restore_mid_lookup)
    out = cli("buy", "AAPL", "1", "100", "-a", "Current TFSA")
    assert out.exit_code == 1 and "restored from a backup while this was being saved" in out.output
    assert store.transactions() == [] and [a.name for a in store.accounts()] == ["Other RRSP"]


def test_backup_restore_latest_ignores_the_backup_taken_on_startup(cli, store, tracker, monkeypatch):
    cli("accounts", "add", "My TFSA", "-t", "TFSA")
    store.backup(dest=store.backup_dir / "marketpulse-20260101-090000-manual.db")
    cli("accounts", "add", "Taxable", "-t", "NONREG")

    def open_with_daily_backup(cls, config=None):
        store.backup(reason="daily")  # what opening the ledger does when the newest backup is a day old
        return tracker

    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(open_with_daily_backup))
    cli("backup", "restore", "--latest", "-y")
    assert [a.name for a in store.accounts()] == ["My TFSA"]


def test_backup_restore_latest_keeps_a_manual_backup_from_the_same_second(cli, store, tracker, monkeypatch):
    cli("accounts", "add", "My TFSA", "-t", "TFSA")

    def open_right_after_a_manual_backup(cls, config=None):
        store.backup(reason="manual")  # taken by the user a moment before
        store.add_account(Account(name="Later"))
        return tracker

    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(open_right_after_a_manual_backup))
    cli("backup", "restore", "--latest", "-y")
    assert [a.name for a in store.accounts()] == ["My TFSA"]


def test_tax_report_explains_superficial_losses_and_transfer_issues(cli, store):
    cli("accounts", "add", "Taxable", "-t", "NONREG")
    cli("accounts", "add", "My TFSA", "-t", "TFSA")
    cli("buy", "XEQT.TO", "10", "30", "-a", "Taxable", "-d", "2024-01-02")
    cli("sell", "XEQT.TO", "10", "25", "-a", "Taxable", "-d", "2024-03-01")  # −$50 loss
    cli("buy", "XEQT.TO", "10", "25", "-a", "My TFSA", "-d", "2024-03-05")  # …bought back in the TFSA
    cli("buy", "XEQT.TO", "5", "20", "-a", "Taxable", "-d", "2024-06-03")
    moved = cli("transfer", "XEQT.TO", "5", "--from", "Taxable", "--to", "My TFSA", "-d", "2024-07-02")
    assert "no --price given" in moved.output  # back-dated and unpriced: warned, not guessed
    out = cli("tax", "-y", "2024").output
    assert "superficial" in out and "50.00 of a 50.00 loss denied" in out
    assert "deemed sale at market value" in out
    assert "spouse or a corporation" in out


def test_accounts_edit_as_the_app_sends_it(cli, store):
    cli("accounts", "add", "Fictional TFSA", "-t", "TFSA", "-i", "Bank")
    cli("accounts", "add", "Fictional Cash", "-t", "CASH")
    acct = store.get_account("Fictional TFSA")
    ref = str(acct.saved_id)
    # Every field, user text in option values, the account id after `--`.
    out = cli(
        "accounts", "edit", "--name", "  -Renamed FHSA ", "--type", "FHSA", "--currency", "usd",
        "--institution", "", "--track-cash", "--", ref,
    )  # fmt: skip
    assert out.exit_code == 0 and "Updated -Renamed FHSA." in out.output
    edited = store.get_account(ref)
    assert (edited.name, edited.type.value, edited.currency, edited.institution, edited.track_cash) == (
        "-Renamed FHSA",
        "FHSA",
        "USD",
        "",
        True,
    )
    for name, error in [("fictional cash", "already exists"), ("   ", "name is required")]:
        result = cli("accounts", "edit", "--name", name, "--", ref)
        assert result.exit_code == 1 and error in result.output and "Traceback" not in result.output
    assert store.get_account(ref).name == "-Renamed FHSA"  # unchanged by the failed edits
    assert cli("accounts", "edit", "--archive", "--", ref).exit_code == 0
    assert store.get_account(ref).archived and [a.name for a in store.accounts()] == ["Fictional Cash"]
    assert cli("accounts", "edit", "--unarchive", "--", ref).exit_code == 0
    assert not store.get_account(ref).archived


def test_accounts_edit_refuses_an_account_changed_or_restored_since_it_was_loaded(cli, store):
    cli("accounts", "add", "Fictional TFSA", "-t", "TFSA")
    acct = store.get_account("Fictional TFSA")
    ref, seen = str(acct.saved_id), acct.revision(store.restore_id)  # what the app's sheet carries
    cli("accounts", "edit", "--institution", "Changed elsewhere", "--", ref)  # another window
    for args in (("--name", "Renamed"), ("--archive",)):
        stale = cli("accounts", "edit", *args, "--revision", seen, "--", ref)
        assert stale.exit_code == 1 and "has changed since it was loaded" in stale.output
    kept = store.get_account(ref)
    assert (kept.name, kept.institution, kept.archived) == ("Fictional TFSA", "Changed elsewhere", False)
    # A restore can put a different account under the same id, even with identical fields.
    current = kept.revision(store.restore_id)
    store.restore(store.backup())
    assert cli("accounts", "edit", "--archive", "--revision", current, "--", ref).exit_code == 1
    assert not store.get_account(ref).archived
    fresh = store.get_account(ref).revision(store.restore_id)
    assert cli("accounts", "edit", "--archive", "--revision", fresh, "--", ref).exit_code == 0
    assert store.get_account(ref).archived


def test_accounts_room_as_the_app_sends_it(cli, store):
    assert cli("accounts", "room", "--", "TFSA", "2026", "-250.5").exit_code == 0  # over-contributed
    assert store.rooms() == {"TFSA": (2026, -250.5)}
    assert cli("accounts", "room", "--", "TFSA", "2025", "7000").exit_code == 0  # replaces, never adds
    assert store.rooms() == {"TFSA": (2025, 7000.0)}


def test_fhsa_room_shows_capped_carry_forward(cli, store):
    cli("accounts", "add", "My FHSA", "-t", "FHSA")
    cli("accounts", "room", "FHSA", "2023", "8000")
    out = cli("tax").output
    assert "Capped" in out and "16,000.00" in out  # never more than $16k in a year


def test_bad_dates_are_usage_errors(cli):
    cli("accounts", "add", "Main")
    cli("buy", "AAPL", "1", "100")
    for args in (
        ("split", "AAPL", "2", "-d", "nope"),
        ("drip", "AAPL", "1", "100", "-d", "nope"),
        ("asset", "fixed", "GIC1", "5000", "--rate", "4", "--maturity", "nope"),
        ("asset", "manual", "HOUSE", "1", "-d", "nope"),
        ("buy", "AAPL", "1", "100", "-d", "2999-01-01"),
    ):
        result = cli(*args)
        assert result.exit_code in (1, 2) and "date" in result.output.lower(), args
        assert "Traceback" not in result.output
    assert cli("split", "AAPL", "2", "-d", "01/31/2024").exit_code == 0


def test_import_default_account(cli, store, tmp_path):
    no_account = tmp_path / "a.csv"
    no_account.write_text("date,type,symbol,quantity,price\n2024-01-01,BUY,XEQT.TO,1,30\n")
    with_account = tmp_path / "b.csv"
    with_account.write_text("date,type,symbol,quantity,price,account\n2024-01-01,BUY,XEQT.TO,1,30,B\n")
    cli("accounts", "add", "A")
    assert "Imported 1" in cli("import", str(no_account)).output  # one account: no -a needed
    cli("accounts", "add", "B")
    several = cli("import", str(no_account))
    assert several.exit_code == 1 and "Several accounts" in several.output
    assert "1 duplicate(s)" in cli("import", str(no_account), "-a", "A").output  # already in A from the first run
    assert "Imported 1" in cli("import", str(with_account)).output  # rows name their account
    assert {store.get_account(t.account_id).name for t in store.transactions()} == {"A", "B"}


def test_desktop_snapshot_and_one_shot_automation(cli, store):
    cli("buy", "AAPL", "1", "100")
    payload = json.loads(cli("desktop", "snapshot").output)
    assert payload["positions"][0]["symbol"] == "AAPL"
    assert payload["automation"]["backup"] is not None
    cycle = cli("automation", "run", "--once", "--json", "--quiet")
    assert cycle.exit_code == 0
    assert json.loads(cycle.output)["errors"] == []


def test_desktop_import_preview_is_read_only_and_structured(cli, store, tmp_path):
    path = tmp_path / "named.csv"
    path.write_text("date,account,type,symbol,quantity,price\n2024-01-01,New TFSA,BUY,XEQT.TO,2,30\n")
    result = cli("desktop", "import", str(path), "--dry-run")
    payload = json.loads(result.output)
    assert payload["added"] == 1 and payload["accounts_created"] == ["New TFSA"]
    assert payload["backup"] is None
    assert store.accounts() == []
    assert store.transactions() == []
    imported = json.loads(cli("desktop", "import", str(path)).output)
    assert imported["added"] == 1 and imported["backup"]


def test_desktop_preview_requires_default_account_without_creating_one(cli, store, tmp_path):
    path = tmp_path / "unnamed.csv"
    path.write_text("date,type,symbol,quantity,price\n2024-01-01,BUY,XEQT.TO,2,30\n")
    result = cli("desktop", "import", str(path), "--dry-run")
    assert result.exit_code == 1 and "Create an account first" in result.output
    assert store.accounts() == []
    cli("accounts", "add", "A")
    cli("accounts", "add", "B")
    result = cli("desktop", "import", str(path), "--dry-run")
    assert result.exit_code == 1 and "Select an account" in result.output
    assert len(store.accounts()) == 2


def test_desktop_snapshot_reports_alerts_fired_by_its_cycle(cli, store, notifications):
    cli("buy", "AAPL", "1", "100")
    cli("alerts", "add", "AAPL", "above", "1")
    payload = json.loads(cli("desktop", "snapshot").output)
    assert payload["automation"]["fired"] == ["AAPL ≥ 1.00"]
    assert payload["status"]["fired"] == payload["automation"]["fired"]
    assert len(notifications) == 1


def test_desktop_transaction_form_arguments_infer_listing_currency(cli, store):
    # The native form omits --currency when blank; a USD listing in a CAD account stays USD.
    cli("accounts", "add", "My TFSA", "-t", "TFSA", "-c", "CAD")
    acct = store.get_account("My TFSA")
    result = cli(
        "buy", "AAPL", "2", "150", "--fees", "0", "--account", str(acct.id), "--date", "2024-01-02", "--note", ""
    )
    assert result.exit_code == 0, result.output
    cli("deposit", "500", "--account", str(acct.id), "--date", "2024-01-02", "--note", "")
    assert [(t.type.value, t.currency) for t in store.transactions()] == [("BUY", "USD"), ("DEPOSIT", "CAD")]


def test_alert_invalid_threshold_is_a_friendly_error(cli):
    for value in ("nan", "inf", "-1", "0"):
        result = cli("alerts", "add", "--", "AAPL", "above", value)
        assert result.exit_code == 1
        assert "finite and positive" in result.output
        assert "Traceback" not in result.output


def test_desktop_import_commit_requires_an_unchanged_preview(cli, store, tmp_path):
    path = tmp_path / "named.csv"
    path.write_text("date,account,type,symbol,quantity,price\n2024-01-01,TFSA,BUY,XEQT.TO,2,30\n")
    preview = json.loads(cli("desktop", "import", "--dry-run", "--", str(path)).output)
    path.write_text("date,account,type,symbol,quantity,price\n2024-01-01,TFSA,BUY,XEQT.TO,20,30\n")
    stale = cli("desktop", "import", "--expect-fingerprint", preview["fingerprint"], "--", str(path))
    assert stale.exit_code == 1 and "changed since the preview" in stale.output
    assert store.transactions() == [] and store.accounts() == []


def test_txn_edit_and_delete_refuse_entries_that_no_longer_add_up(cli, store):
    cli("accounts", "add", "Fictional TFSA", "--type", "TFSA")
    cli("buy", "AAPL", "10", "100", "--date", "2024-01-02")
    cli("sell", "AAPL", "4", "110", "--date", "2024-02-01")
    buy, sale = store.transactions()

    oversell = cli("txn", "edit", "--quantity", "20", "--", str(sale.id))
    assert oversell.exit_code == 1 and "sell of 20.0000 AAPL exceeds 10.0000 held" in oversell.output
    backdated = cli("txn", "edit", "--date", "2024-03-01", "--", str(buy.id))
    assert backdated.exit_code == 1 and f"transaction #{sale.id} on 2024-02-01" in backdated.output
    refused = cli("txn", "delete", "--yes", "--", str(buy.id))
    assert refused.exit_code == 1 and "Not deleted" in refused.output
    assert store.transactions() == [buy, sale]

    # Option values are taken verbatim, even ones that look like options.
    assert cli("txn", "edit", "--quantity", "6", "--note", "--typo", "--", str(sale.id)).exit_code == 0
    assert [(t.quantity, t.note) for t in store.transactions()] == [(10, ""), (6, "--typo")]
    assert cli("undo", "-y").exit_code == 0  # the sale, the latest recorded
    assert "Deleted #" in cli("txn", "delete", "--yes", "--", str(buy.id)).output
    assert cli("txn", "delete", "--yes", "--", str(buy.id)).exit_code == 1


def test_txn_edit_works_out_the_currency_again_for_a_new_symbol(cli, store):
    cli("buy", "AAPL", "1", "100", "--date", "2024-01-02")
    (buy,) = store.transactions()
    assert buy.currency == "USD"
    assert cli("txn", "edit", "--symbol", " xeqt.to", "--", str(buy.id)).exit_code == 0
    assert (store.transactions()[0].symbol, store.transactions()[0].currency) == ("XEQT.TO", "CAD")
    assert cli("txn", "edit", "--symbol", "AAPL", "--currency", "cad", "--", str(buy.id)).exit_code == 0
    assert store.transactions()[0].currency == "CAD"  # an explicit currency wins
    assert cli("txn", "edit", "--symbol", " aapl ", "--", str(buy.id)).exit_code == 0
    assert store.transactions()[0].currency == "CAD"  # the same symbol: the currency stays
    assert cli("txn", "edit", "--currency", "", "--", str(buy.id)).exit_code == 0
    assert store.transactions()[0].currency == "USD"  # blank: the listing currency


def test_txn_edit_accepts_what_the_app_edit_form_sends(cli, store):
    # `TransactionSheet.editArguments`: every field the form shows, a possibly blank currency,
    # the row's revision, then `--` id.
    cli("accounts", "add", "Fictional TFSA", "--type", "TFSA")
    cli("buy", "AAPL", "10", "100", "--date", "2024-01-02")
    cli("dividend", "AAPL", "5", "--date", "2024-02-01")
    cli("deposit", "500", "--date", "2024-01-01")
    buy, deposit, dividend = sorted(store.transactions(), key=lambda t: t.type.value)

    def edit(t, *fields):
        common = ("--account", str(t.account_id), "--date", "2024-01-03", "--currency", "", "--note", "- edited")
        return cli("txn", "edit", *common, *fields, "--revision", t.revision(store.restore_id), "--", str(t.id))

    stale = ("--revision", "0" * 16)
    assert "has changed since it was loaded" in cli("txn", "edit", "--note", "x", *stale, "--", str(buy.id)).output
    assert "has changed since it was loaded" in cli("txn", "delete", "--yes", *stale, "--", str(buy.id)).output
    trade = ("--symbol", "AAPL", "--quantity", "12.0", "--price", "99.5", "--fees", "1.0")
    assert edit(buy, *trade).exit_code == 0
    assert edit(dividend, "--symbol", "AAPL", "--amount", "6.25").exit_code == 0
    assert edit(deposit, "--amount", "750.0").exit_code == 0
    edited = {t.id: t for t in store.transactions()}
    b, d, c = edited[buy.id], edited[dividend.id], edited[deposit.id]
    assert (b.date, b.quantity, b.price, b.fees, b.currency, b.note) == ("2024-01-03", 12, 99.5, 1, "USD", "- edited")
    assert (d.amount, d.currency, d.type) == (6.25, "USD", dividend.type)
    assert (c.amount, c.currency, c.symbol) == (750, "CAD", "")
    assert edit(buy, *trade).exit_code == 1  # the revision it was loaded at is gone


def test_txn_edit_and_delete_refuse_an_entry_changed_meanwhile(cli, store, tracker, monkeypatch):
    # Without --revision, the CLI checks against the entry as it read it, so a change made in
    # another window meanwhile is refused rather than overwritten or deleted unseen.
    cli("buy", "AAPL", "10", "100", "--date", "2024-01-02")
    (buy,) = store.transactions()
    real = tracker.resolve_currency

    def edited_elsewhere_while_quoting(symbol, account):
        store.update_transaction(replace(store.transactions()[0], note="edited in another window"))
        return real(symbol, account)

    monkeypatch.setattr(tracker, "resolve_currency", edited_elsewhere_while_quoting)
    result = cli("txn", "edit", "--symbol", "XEQT.TO", "--", str(buy.id))  # looks the currency up again
    assert result.exit_code == 1 and "has changed since it was loaded" in result.output
    assert (store.transactions()[0].symbol, store.transactions()[0].note) == ("AAPL", "edited in another window")

    def edited_elsewhere_while_confirming(*args, **kwargs):
        current = store.transactions()[0]
        store.update_transaction(replace(current, quantity=current.quantity - 1))
        return True

    monkeypatch.setattr("click.confirm", edited_elsewhere_while_confirming)
    result = cli("txn", "delete", "--", str(buy.id))
    assert result.exit_code == 1 and "has changed since it was loaded" in result.output
    assert [t.quantity for t in store.transactions()] == [9]
    result = cli("undo")  # the same for undo's confirmation
    assert result.exit_code == 1 and "has changed since it was loaded" in result.output
    assert [t.quantity for t in store.transactions()] == [8]
