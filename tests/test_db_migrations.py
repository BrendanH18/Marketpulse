"""Schema versioning, migrations and backups (db.Store).

Migrations are exercised by swapping in a throwaway MIGRATIONS table, so the
tests keep working however many real migrations ship later.
"""

import os
import sqlite3
import time
from datetime import datetime, timedelta

import pytest

from marketpulse import db
from marketpulse.csvio import import_transactions
from marketpulse.db import BASELINE_VERSION, SchemaError, Store
from marketpulse.models import Account, Transaction, TxnType


def _seed(store: Store) -> Account:
    """One account with one buy: the smallest ledger worth backing up."""
    acct = store.add_account(Account(name="Main"))
    store.add_transaction(
        Transaction(account_id=acct.id, type=TxnType.BUY, date="2024-01-01", symbol="AAPL", quantity=1, price=10)
    )
    return acct


def _user_version(path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


# ── versioning ────────────────────────────────────────────────────────────────


def test_new_database_is_stamped_with_the_baseline_version(tmp_path):
    store = Store(tmp_path / "new.db")
    assert store.schema_version == BASELINE_VERSION
    assert store.get_meta("schema_version") == str(BASELINE_VERSION)
    assert store.backups() == []  # nothing to protect in a brand-new file


def test_unversioned_2_0_database_is_adopted_as_baseline(tmp_path):
    path = tmp_path / "old.db"
    store = Store(path)
    _seed(store)
    store._conn.execute("PRAGMA user_version = 0")  # what MarketPulse 2.0 left behind
    store.close()
    reopened = Store(path)
    assert reopened.schema_version == BASELINE_VERSION
    assert len(reopened.transactions()) == 1


def test_pending_migrations_run_in_order_after_a_backup(tmp_path, monkeypatch):
    path = tmp_path / "m.db"
    _seed(Store(path))  # an existing v1 database with data in it

    ran: list[int] = []

    def v3(conn: sqlite3.Connection) -> None:
        # Python migrations see v2's column already in place.
        ran.append(3)
        conn.execute("UPDATE transactions SET broker_ref = 'ref-' || id")

    monkeypatch.setattr(db, "MIGRATIONS", {2: "ALTER TABLE transactions ADD COLUMN broker_ref TEXT", 3: v3})
    store = Store(path)
    assert store.schema_version == 3 and ran == [3]
    assert store._query("SELECT broker_ref FROM transactions")[0]["broker_ref"] == "ref-1"
    (pre,) = store.backups()
    assert Store.backup_reason(pre) == "pre-v3"
    assert _user_version(pre) == 1  # the backup is the untouched pre-upgrade file

    # Re-opening is a no-op: nothing pending, no second backup.
    store.close()
    assert Store(path).backups() == [pre]


def test_failed_migration_rolls_back_and_keeps_old_version(tmp_path, monkeypatch):
    path = tmp_path / "f.db"
    _seed(Store(path))

    def boom(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM transactions")  # would be destructive...
        raise RuntimeError("bad migration")  # ...but is rolled back

    monkeypatch.setattr(db, "MIGRATIONS", {2: boom})
    with pytest.raises(RuntimeError, match="bad migration"):
        Store(path)
    assert _user_version(path) == 1
    monkeypatch.setattr(db, "MIGRATIONS", {})
    assert len(Store(path).transactions()) == 1


def test_failed_sql_migration_also_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / "s.db"
    _seed(Store(path))
    monkeypatch.setattr(db, "MIGRATIONS", {2: "DELETE FROM transactions; SELECT * FROM no_such_table"})
    with pytest.raises(sqlite3.OperationalError):
        Store(path)
    monkeypatch.setattr(db, "MIGRATIONS", {})
    store = Store(path)
    assert store.schema_version == 1 and len(store.transactions()) == 1


def test_database_from_a_newer_marketpulse_is_refused(tmp_path):
    path = tmp_path / "future.db"
    Store(path)._conn.execute("PRAGMA user_version = 99")
    with pytest.raises(SchemaError, match="schema version 99"):
        Store(path)


# ── backups ───────────────────────────────────────────────────────────────────


def test_backup_is_a_complete_consistent_copy(store, tmp_path):
    _seed(store)
    path = store.backup()
    assert path.parent == store.backup_dir and Store.backup_reason(path) == "manual"
    copy = Store(path)
    assert [t.symbol for t in copy.transactions()] == ["AAPL"]
    # An explicit destination is honoured verbatim.
    assert store.backup(dest=tmp_path / "elsewhere.db") == tmp_path / "elsewhere.db"


def test_same_second_backups_do_not_overwrite(store):
    _seed(store)
    first, second = store.backup(reason="daily"), store.backup(reason="daily")
    assert first != second and first.exists() and second.exists()
    assert Store.backup_reason(second) == "daily"  # the -2 counter isn't part of the reason


def test_automatic_backups_are_pruned_but_manual_ones_are_kept(store):
    _seed(store)
    store.backup_dir.mkdir()
    base = datetime(2026, 1, 1, 12)
    # 20 old daily backups and 2 manual ones, each a distinct timestamp.
    for i in range(20):
        (store.backup_dir / f"marketpulse-{base + timedelta(days=i):%Y%m%d-%H%M%S}-daily.db").touch()
    for i in range(2):
        (store.backup_dir / f"marketpulse-{base + timedelta(hours=i):%Y%m%d-%H%M%S}-manual.db").touch()
    store.backup(reason="daily")  # triggers pruning of the 'daily' set only
    reasons = [Store.backup_reason(p) for p in store.backups()]
    assert reasons.count("daily") == db.AUTO_BACKUP_KEEP
    assert reasons.count("manual") == 2
    assert store.backups()[0].name.endswith("-daily.db")  # the newest is the one just taken


def test_auto_backup_only_when_due_and_not_for_an_empty_ledger(store):
    assert store.auto_backup() is None  # empty ledger: nothing to lose
    _seed(store)
    first = store.auto_backup()
    assert first is not None and Store.backup_reason(first) == "daily"
    assert store.auto_backup() is None  # one already taken in the last 24h
    assert store.auto_backup(max_age_hours=0) is not None


def test_open_default_takes_the_daily_backup():
    _seed(Store.open_default())
    store = Store.open_default()
    assert [Store.backup_reason(p) for p in store.backups()] == ["daily"]


def test_csv_import_backs_up_first_but_dry_run_does_not(store, tmp_path):
    acct = _seed(store)
    csv_path = tmp_path / "in.csv"
    csv_path.write_text("date,type,symbol,quantity,price\n2024-02-01,buy,MSFT,1,300\n")
    preview = import_transactions(store, csv_path, default_account=acct, dry_run=True)
    assert preview.backup is None and store.backups() == []
    result = import_transactions(store, csv_path, default_account=acct)
    assert result.added == 1
    assert Store.backup_reason(result.backup) == "import"
    # The backup predates the import: restoring it undoes the whole thing.
    assert [t.symbol for t in Store(result.backup).transactions()] == ["AAPL"]


def test_backup_names_sort_by_time_not_by_reason(store):
    _seed(store)
    store.backup_dir.mkdir()
    (store.backup_dir / "marketpulse-20260101-000000-manual.db").touch()
    (store.backup_dir / "marketpulse-20250101-000000-pre-v2.db").touch()
    newest = store.backup(reason="import")
    names = [p.name for p in store.backups()]
    assert names[0] == newest.name and names[-1].startswith("marketpulse-2025")
    assert Store.backup_reason(store.backups()[-1]) == "pre-v2"
    # mtime plays no part in ordering (copies and restores reset it).
    os.utime(store.backups()[-1], (time.time() + 999, time.time() + 999))
    assert store.backups()[-1].name.startswith("marketpulse-2025")


# ── restore ───────────────────────────────────────────────────────────────────


def _names(store: Store) -> list[str]:
    return sorted(a.name for a in store.accounts(include_archived=True))


def test_restore_puts_a_backup_back_and_keeps_the_replaced_ledger(store):
    _seed(store)
    taken = store.backup()
    store.add_account(Account(name="Later"))
    # Another process (the TUI, the menu bar) with the ledger open sees the restore at once.
    other = Store(store.path)
    safety = store.restore(taken)
    assert _names(store) == ["Main"] and [t.symbol for t in store.transactions()] == ["AAPL"]
    assert _names(other) == ["Main"]
    assert Store.backup_reason(safety) == "pre-restore" and safety.parent == store.backup_dir
    assert _names(Store(safety)) == ["Later", "Main"]  # so the restore can itself be undone
    assert store._query("PRAGMA journal_mode")[0][0] == "wal"
    assert store.schema_version == BASELINE_VERSION
    # Writes after a restore land in the restored ledger.
    store.add_account(Account(name="After"))
    assert _names(Store(store.path)) == ["After", "Main"]


def test_restore_upgrades_an_older_backup_without_changing_it(tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    _seed(Store(old))
    original = old.read_bytes()
    (tmp_path / "live").mkdir()
    store = Store(tmp_path / "live" / "marketpulse.db")
    monkeypatch.setattr(db, "MIGRATIONS", {2: "ALTER TABLE accounts ADD COLUMN colour TEXT"})
    store._migrate(backup_first=False)
    store.restore(old)
    assert store.schema_version == 2 and _names(store) == ["Main"]
    assert "colour" in {r["name"] for r in store._query("PRAGMA table_info(accounts)")}
    assert old.read_bytes() == original
    # The upgrade ran on a scratch copy: its pre-v2 backup didn't land among the user's.
    assert [Store.backup_reason(p) for p in store.backups()] == ["pre-restore"]


def _unchanged_after(store: Store, source, match: str) -> None:
    """Restoring `source` fails with `match`, and neither the ledger nor the backups changed."""
    before = (_names(store), len(store.transactions()), store.backups())
    with pytest.raises(db.RestoreError, match=match):
        store.restore(source)
    assert (_names(store), len(store.transactions()), store.backups()) == before


def test_restore_rejects_a_corrupt_or_foreign_file(store, tmp_path):
    _seed(store)
    garbage = tmp_path / "notes.db"
    garbage.write_bytes(b"not a database at all" * 100)
    _unchanged_after(store, garbage, "isn't a readable database")

    damaged = store.backup(dest=tmp_path / "damaged.db")
    data = bytearray(damaged.read_bytes())
    page = 4096
    data[page + 8 : 2 * page] = b"\xff" * (page - 8)  # wreck the second page, keep the header
    damaged.write_bytes(bytes(data))
    _unchanged_after(store, damaged, "damaged|isn't a readable database")

    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE notes (body TEXT)")
    conn.commit()
    conn.close()
    _unchanged_after(store, other, "isn't a MarketPulse database")
    _unchanged_after(store, tmp_path / "missing.db", "doesn't exist")
    _unchanged_after(store, store.path, "the ledger itself")


def test_restore_rejects_a_backup_from_a_newer_marketpulse(store, tmp_path):
    _seed(store)
    newer = store.backup(dest=tmp_path / "newer.db")
    conn = sqlite3.connect(newer)
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()
    _unchanged_after(store, newer, "schema version 99")


def test_restore_rejects_a_backup_whose_tables_dont_match(store, tmp_path):
    _seed(store)
    missing = store.backup(dest=tmp_path / "missing-column.db")
    conn = sqlite3.connect(missing)
    conn.execute("ALTER TABLE accounts DROP COLUMN archived")
    conn.commit()
    conn.close()
    _unchanged_after(store, missing, "doesn't match this ledger's tables: no such column")

    # A transaction whose account is gone passes every check until the swap commits.
    orphan = store.backup(dest=tmp_path / "orphan.db")
    conn = sqlite3.connect(orphan)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM accounts")
    conn.commit()
    conn.close()
    _unchanged_after(store, orphan, "FOREIGN KEY constraint failed")


def test_no_other_process_can_write_between_the_safety_backup_and_the_swap(store, monkeypatch):
    _seed(store)
    taken = store.backup()
    real_backup = Store.backup
    blocked = []

    def backup_then_try_to_write(self, reason="manual", dest=None):
        path = real_backup(self, reason=reason, dest=dest)
        if reason == "pre-restore":
            other = sqlite3.connect(store.path, timeout=0)
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute(
                    "INSERT INTO accounts(name, type, currency, created_at) VALUES ('Sneaky', 'TFSA', 'CAD', '')"
                )
            other.close()
            blocked.append(True)
        return path

    monkeypatch.setattr(Store, "backup", backup_then_try_to_write)
    store.restore(taken)
    assert blocked == [True] and _names(store) == ["Main"]
