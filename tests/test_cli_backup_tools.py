"""Offline backup discovery and read-only verification on fictional databases."""

import json
import sqlite3
from hashlib import sha256

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.db import Store, latest_version
from marketpulse.models import Account


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
