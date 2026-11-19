"""Offline backup discovery and read-only verification on fictional databases."""

import json
import os
import re
import sqlite3
from contextlib import closing
from hashlib import sha256

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.db import Store, latest_version
from marketpulse.models import Account, Transaction, TxnType


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    return lambda *args: CliRunner().invoke(main, list(args), catch_exceptions=False)


@pytest.fixture
def copies(store):
    store.add_account(Account(name="Fictional Maple"))
    store.backup_dir.mkdir(exist_ok=True)
    paths = []
    for day, reason in (("20240101", "manual"), ("20240102", "import"), ("20240103", "manual")):
        dest = store.backup_dir / f"marketpulse-{day}-120000-{reason}.db"
        store.backup(dest=dest)
        paths.append(dest)
    return paths


def test_backup_filters_compose_before_paging(cli, copies, fake):
    result = cli("backup", "list", "--reason", "MANUAL", "--oldest-first", "--offset", "1", "--limit", "1", "--json")
    assert result.exit_code == 0
    assert [item["file"] for item in json.loads(result.output)] == [copies[2].name]
    bounded = cli("backup", "list", "--since", "2024-01-02", "--until", "2024-01-02", "--search", "IMPORT", "--json")
    assert [item["file"] for item in json.loads(bounded.output)] == [copies[1].name]
    assert fake.calls == []
    assert json.loads(cli("backup", "list", "--search", "nothing", "--json").output) == []


@pytest.mark.parametrize(
    "args", [("--limit", "0"), ("--offset", "-1"), ("--since", "2024-02-01", "--until", "2024-01-01")]
)
def test_backup_invalid_filters(cli, args):
    assert cli("backup", "list", *args).exit_code == 2


def test_backup_show_matches_list_and_bare_name(cli, copies):
    listed = json.loads(cli("backup", "list", "--json").output)[0]
    assert json.loads(cli("backup", "show", copies[2].name, "--json").output) == listed
    assert "size_bytes" in cli("backup", "show", str(copies[2])).output
    missing = cli("backup", "show", "missing.db")
    assert missing.exit_code == 1 and "not found" in missing.output


def test_backup_verify_preserves_source_and_live_ledger(cli, store, copies, fake):
    source = copies[0]
    before = sha256(source.read_bytes()).digest()
    accounts = store.accounts(include_archived=True)
    result = cli("backup", "verify", str(source), "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == {"ok": True, "path": str(source.resolve()), "error": None}
    assert sha256(source.read_bytes()).digest() == before
    assert store.accounts(include_archived=True) == accounts
    assert len(store.backups()) == 3 and fake.calls == []
    assert "Backup verified" in cli("backup", "verify", source.name).output


@pytest.mark.parametrize("kind", ["text", "foreign", "future"])
def test_backup_verify_reports_invalid_without_modification(cli, tmp_path, kind):
    source = tmp_path / "candidate.db"
    if kind == "text":
        source.write_text("fictional invalid backup")
    elif kind == "foreign":
        with sqlite3.connect(source) as conn:
            conn.execute("CREATE TABLE unrelated (id INTEGER)")
    else:
        candidate = Store(source)
        try:
            candidate._conn.execute(f"PRAGMA user_version = {latest_version() + 1}")
        finally:
            candidate.close()
    before = sha256(source.read_bytes()).digest()
    result = cli("backup", "verify", str(source), "--json")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False and payload["error"]
    assert sha256(source.read_bytes()).digest() == before
    assert cli("backup", "verify", str(source)).exit_code == 1


def test_backup_verify_all_reports_corrupt_and_older_valid_copy(store, tmp_path):
    store.add_account(Account(name="Fictional Maple"))
    directory = tmp_path / "data" / "backups"
    older = store.backup(dest=directory / "marketpulse-20240101-120000-pre-restore.db")
    newest = directory / "marketpulse-20240102-120000-manual.db"
    newest.write_bytes(b"fictional invalid backup")
    files = {path: path.read_bytes() for path in directory.glob("*.db")}
    runner = CliRunner()
    args = ["backup", "verify", "--all"]

    result = runner.invoke(main, [*args, "--json"], catch_exceptions=False)
    assert result.exit_code == 1, result.output
    failed, passed = json.loads(result.stdout)
    assert failed["path"] == str(newest)
    assert failed["ok"] is False and failed["error"]
    assert passed == {"ok": True, "path": str(older), "error": None}

    human = runner.invoke(main, args, catch_exceptions=False)
    assert human.exit_code == 1
    assert human.stdout.index(newest.name) < human.stdout.index(f"Backup verified: {older.name}")
    assert {path: path.read_bytes() for path in directory.glob("*.db")} == files
    assert not (directory.parent / "marketpulse.db").exists()


def test_backup_verify_all_json_for_empty_and_single_backup(store, tmp_path):
    runner = CliRunner()
    args = ["backup", "verify", "--all", "--json"]
    directory = tmp_path / "data" / "backups"

    empty = runner.invoke(main, args, catch_exceptions=False)
    assert empty.exit_code == 1
    assert json.loads(empty.stdout) == []
    assert "No backups to verify" in empty.stderr
    assert not directory.parent.exists()

    source = store.backup(dest=directory / "marketpulse-20240101-120000-manual.db")
    one = runner.invoke(main, args, catch_exceptions=False)
    assert one.exit_code == 0, one.output
    assert json.loads(one.stdout) == [{"ok": True, "path": str(source), "error": None}]


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "loop"])
def test_backup_verify_all_reports_link_failures_and_continues(store, tmp_path, kind):
    live = tmp_path / "data" / "marketpulse.db"
    directory = live.parent / "backups"
    older = store.backup(dest=directory / "marketpulse-20240101-120000-manual.db")
    store.backup(dest=live)
    newest = directory / "marketpulse-20240102-120000-manual.db"
    if kind == "hardlink":
        newest.hardlink_to(live)
    else:
        newest.symlink_to(newest if kind == "loop" else live)

    result = CliRunner().invoke(main, ["backup", "verify", "--all", "--json"], catch_exceptions=False)

    assert result.exit_code == 1, result.output
    failed, passed = json.loads(result.stdout)
    assert failed["path"] == str(newest)
    assert failed["ok"] is False and failed["error"]
    if kind != "loop":
        assert "live ledger" in failed["error"]
    assert passed == {"ok": True, "path": str(older), "error": None}


def test_backup_verify_all_rechecks_live_ledger_identity(store, tmp_path, monkeypatch):
    from marketpulse.db import backup_verification_error

    live = tmp_path / "data" / "marketpulse.db"
    directory = live.parent / "backups"
    newest = store.backup(dest=directory / "marketpulse-20240102-120000-manual.db")
    older = directory / "marketpulse-20240101-120000-manual.db"
    older.symlink_to(live)

    def verify(source):
        if source == newest.resolve():
            store.backup(dest=live)
        return backup_verification_error(source)

    monkeypatch.setattr("marketpulse.db.backup_verification_error", verify)
    result = CliRunner().invoke(main, ["backup", "verify", "--all", "--json"], catch_exceptions=False)

    assert result.exit_code == 1, result.output
    passed, failed = json.loads(result.stdout)
    assert passed == {"ok": True, "path": str(newest), "error": None}
    assert failed["path"] == str(older)
    assert failed["ok"] is False and "live ledger" in failed["error"]


@pytest.mark.parametrize("other", ["--latest", "fictional.db"])
def test_backup_verify_all_rejects_other_selectors(other):
    result = CliRunner().invoke(main, ["backup", "verify", "--all", other], catch_exceptions=False)
    assert result.exit_code == 2
    assert "Choose one of" in result.stderr


def test_backup_now_json_creates_readable_copy(cli, store, tmp_path):
    destination = tmp_path / "explicit.db"
    result = cli("backup", "now", str(destination), "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["path"] == str(destination.resolve())
    assert payload["size_bytes"] == destination.stat().st_size
    assert payload["taken_at"] is None
    assert cli("backup", "verify", str(destination)).exit_code == 0
    assert "Backed up" in cli("backup").output


def test_backup_verify_reports_staging_sqlite_error(cli, copies, monkeypatch):
    source = copies[0]
    before = sha256(source.read_bytes()).digest()

    def fail_staging(source, staged):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr("marketpulse.db._stage_restore", fail_staging)
    result = cli("backup", "verify", str(source), "--json")
    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "ok": False,
        "path": str(source.resolve()),
        "error": "database or disk is full",
    }
    human = cli("backup", "verify", str(source))
    assert human.exit_code == 1 and "database or disk is full" in human.output
    assert sha256(source.read_bytes()).digest() == before


@pytest.mark.parametrize("selector", ["path", "name", "latest"])
def test_restore_preview_compares_ledgers_without_taking_a_backup(selector):
    # Exercise real startup: the old backup dates would normally trigger a daily backup.
    live = Store()
    try:
        first = live.add_account(Account(name="Fictional Maple"))
        live.add_transaction(Transaction(first.saved_id, TxnType.DEPOSIT, date="2024-01-02", amount=40))
        source = live.backup(dest=live.backup_dir / "marketpulse-20240103-090000-manual.db")
        second = live.add_account(Account(name="Fictional Cedar"))
        for day in ("2024-02-04", "2024-02-01"):
            live.add_transaction(Transaction(second.saved_id, TxnType.DEPOSIT, date=day, amount=20))
        # --latest must skip this newer pre-restore copy.
        live.backup(dest=live.backup_dir / "marketpulse-20240205-090000-pre-restore.db")
    finally:
        live.close()

    inventory = set(live.path.parent.rglob("*"))
    files = [live.path, *live.backups()]
    before = {p: p.read_bytes() for p in files}
    argument = {"path": str(source), "name": source.name, "latest": "--latest"}[selector]
    result = CliRunner().invoke(main, ["backup", "restore", "--dry-run", argument], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert source.name in result.output.replace("\n", "")
    for label, current, backup in (
        ("Accounts", "2", "1"),
        ("Transactions", "3", "1"),
        ("Latest transaction date", "2024-02-04", "2024-01-02"),
    ):
        assert re.search(rf"{label}\W+{current}\W+{backup}\b", result.output)
    assert set(live.path.parent.rglob("*")) == inventory
    assert {p: p.read_bytes() for p in files} == before


def test_restore_preview_empty_backup_without_a_current_database(store):
    source = store.backup_dir / "empty.db"
    store.backup(dest=source)
    result = CliRunner().invoke(main, ["backup", "restore", str(source), "--dry-run"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    for label in ("Accounts", "Transactions"):
        assert re.search(rf"{label}\W+0\W+0\b", result.output)
    assert re.search(r"Latest transaction date\W*—\W*—", result.output)
    assert not (store.path.parent / "data").exists()


def test_restore_preview_rejects_invalid_backup_without_creating_a_ledger(tmp_path):
    source = tmp_path / "damaged.db"
    source.write_bytes(b"fictional invalid backup")
    result = CliRunner().invoke(main, ["backup", "restore", "--dry-run", str(source)], catch_exceptions=False)
    assert result.exit_code == 1
    assert "database" in result.output.lower()
    assert source.read_bytes() == b"fictional invalid backup"
    assert not (tmp_path / "data").exists()


def test_restore_preview_includes_committed_wal_frames(tmp_path):
    live = Store()
    saved = Store(tmp_path / "saved.db")
    try:
        for store, name in ((live, "Maple"), (saved, "Cedar")):
            store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            store.add_account(Account(name=name))
        saved.add_account(Account(name="Aspen"))
        result = CliRunner().invoke(main, ["backup", "restore", "--dry-run", str(saved.path)], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert re.search(r"Accounts\W+1\W+2\b", result.output)
    finally:
        saved.close()
        live.close()


def test_restore_preview_rejects_device_file():
    result = CliRunner().invoke(main, ["backup", "restore", "--dry-run", os.devnull], catch_exceptions=False)
    assert result.exit_code == 1
    assert "not a regular file" in result.output


def test_desktop_restore_preview_returns_json_without_changing_files():
    live = Store()
    try:
        account = live.add_account(Account(name="Fictional Maple"))
        # An old backup would trigger a daily backup if the command opened the tracker.
        source = live.backup(dest=live.backup_dir / "marketpulse-20240101-090000-manual.db")
        live.add_account(Account(name="Fictional Cedar"))
        live.add_transaction(Transaction(account.saved_id, TxnType.DEPOSIT, date="2024-01-02", amount=40))
    finally:
        live.close()
    inventory = set(live.path.parent.rglob("*"))
    files = (live.path, source)
    before = {p: p.read_bytes() for p in files}

    result = CliRunner().invoke(main, ["desktop", "restore-preview", "--", str(source)], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert re.fullmatch(r"[0-9a-f]{64}", payload.pop("fingerprint"))
    assert payload == {
        "version": 1,
        "current": {"accounts": 2, "transactions": 1, "latest_date": "2024-01-02"},
        "backup": {"accounts": 1, "transactions": 0, "latest_date": None},
    }
    assert set(live.path.parent.rglob("*")) == inventory
    assert {p: p.read_bytes() for p in files} == before


def test_desktop_restore_preview_rejects_invalid_backup(tmp_path):
    source = tmp_path / "invalid backup.db"
    source.write_bytes(b"fictional invalid backup")

    result = CliRunner().invoke(main, ["desktop", "restore-preview", "--", str(source)], catch_exceptions=False)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "isn't a readable database" in result.stderr
    assert source.read_bytes() == b"fictional invalid backup"
    assert not (tmp_path / "data").exists()


def test_restore_refuses_replacement_backup_after_desktop_preview(tmp_path):
    runner = CliRunner()
    with closing(Store()) as live:
        account = live.add_account(Account(name="Fictional Maple"))
        live.add_transaction(Transaction(account.saved_id, TxnType.DEPOSIT, date="2024-01-02", amount=40))
        source = live.backup(dest=tmp_path / "selected.db")
        # Opening the tracker would start overdue maintenance and prune one of these copies.
        for day in range(1, 15):
            live.backup(dest=live.backup_dir / f"marketpulse-202401{day:02d}-090000-daily.db")
        live.add_transaction(Transaction(account.saved_id, TxnType.DEPOSIT, date="2024-01-03", amount=20))
        preview = runner.invoke(main, ["desktop", "restore-preview", "--", str(source)], catch_exceptions=False)
        assert preview.exit_code == 0, preview.output
        fingerprint = json.loads(preview.stdout)["fingerprint"]
        restore_args = ["backup", "restore", "--yes", "--expect-fingerprint", fingerprint, "--", str(source)]

        # Another valid ledger can take the original path and even match the displayed counts and date.
        original = source.replace(tmp_path / "original.db")
        with closing(Store(tmp_path / "other.db")) as other:
            other_account = other.add_account(Account(name="Fictional Cedar"))
            other.add_transaction(Transaction(other_account.saved_id, TxnType.DEPOSIT, date="2024-01-02", amount=80))
            other.backup(dest=source)

        before = live.backups()
        rejected = runner.invoke(main, restore_args, catch_exceptions=False)
        assert rejected.exit_code == 1
        assert "changed since the preview" in rejected.stderr
        assert [a.name for a in live.accounts()] == ["Fictional Maple"]
        assert [t.amount for t in live.transactions()] == [40, 20]
        assert live.backups() == before

        original.replace(source)
        restored = runner.invoke(main, restore_args, catch_exceptions=False)
        assert restored.exit_code == 0, restored.output
        assert [t.amount for t in live.transactions()] == [40]
        assert any(live.backup_reason(path) == "pre-restore" for path in live.backups())
