"""SQLite persistence (stdlib only) plus migration from legacy JSON portfolios."""

from __future__ import annotations

import json
import shutil
import sqlite3
import stat
import threading
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import file_digest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .config import DEFAULT_WATCHLIST, data_dir
from .ledger import LedgerState, replay
from .models import (
    EPSILON,
    Account,
    AccountType,
    Alert,
    Asset,
    Quote,
    Transaction,
    TxnType,
    guess_currency,
    parse_date,
)

# ── Schema & migrations ───────────────────────────────────────────────────────
#
# The schema version lives in SQLite's own header field, `PRAGMA user_version`
# (an integer SQLite reserves for applications and never touches itself). It
# is cheap to read, can't drift from the file it describes, and is updated
# inside the same transaction as each migration, so a crash mid-upgrade leaves
# the database at the old version rather than half-migrated.
#
# `SCHEMA` below is the *baseline* (version 1): the tables MarketPulse 2.0
# shipped with. It is only ever run with CREATE ... IF NOT EXISTS, so it never
# alters an existing table. Every later change goes into MIGRATIONS instead.

BASELINE_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    type TEXT NOT NULL,
    currency TEXT NOT NULL,
    institution TEXT NOT NULL DEFAULT '',
    track_cash INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    type TEXT NOT NULL,
    symbol TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 0,
    price REAL NOT NULL DEFAULT 0,
    amount REAL NOT NULL DEFAULT 0,
    fees REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    ratio REAL NOT NULL DEFAULT 0,
    target_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_txn_account ON transactions(account_id, date);
CREATE INDEX IF NOT EXISTS idx_txn_symbol ON transactions(symbol);
CREATE TABLE IF NOT EXISTS assets (
    symbol TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    asset_class TEXT,
    currency TEXT NOT NULL DEFAULT '',
    rate REAL NOT NULL DEFAULT 0,
    compounding TEXT NOT NULL DEFAULT 'annual',
    start_date TEXT NOT NULL DEFAULT '',
    maturity_date TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY, position INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    condition TEXT NOT NULL,
    threshold REAL NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    triggered_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS snapshots (
    date TEXT PRIMARY KEY,
    net_worth REAL NOT NULL,
    book REAL NOT NULL,
    contributions REAL NOT NULL,
    currency TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS room (account_type TEXT PRIMARY KEY, as_of_year INTEGER NOT NULL, amount REAL NOT NULL);
CREATE TABLE IF NOT EXISTS targets (bucket TEXT PRIMARY KEY, weight REAL NOT NULL);
CREATE TABLE IF NOT EXISTS quote_cache (symbol TEXT PRIMARY KEY, data TEXT NOT NULL, fetched_at REAL NOT NULL);
"""

# A migration is either a SQL script or a Python function that receives the
# open connection (for data rewrites that plain SQL can't express).
Migration = str | Callable[[sqlite3.Connection], None]

# Upgrade steps keyed by the version they migrate the database *to*. To change
# the schema: add the next integer here (e.g. 2: "ALTER TABLE ... ADD COLUMN
# ..."), never edit a step that has already shipped, and never edit SCHEMA to
# alter an existing table: databases created before your change won't see it.
# Keep the keys contiguous (2, 3, 4, ...) so every database walks the same path.
MIGRATIONS: dict[int, Migration] = {
    # Every automation cycle's report, so an overnight failure isn't lost to the next success (#180).
    2: """
CREATE TABLE IF NOT EXISTS automation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at TEXT NOT NULL,
    failed INTEGER NOT NULL,
    report TEXT NOT NULL
);
""",
    # 3: per-asset T1135 setting. NULL decides by listing, 1 counts as foreign property, 0 doesn't.
    3: "ALTER TABLE assets ADD COLUMN foreign_property INTEGER",
}

# Where automatic backups go and how many to keep (see Store.backup).
BACKUP_DIRNAME = "backups"
AUTO_BACKUP_KEEP = 14  # automatic backups kept per reason (daily, import, ...)
AUTO_BACKUP_MAX_AGE_HOURS = 24.0  # take a fresh daily backup when the newest is older than this
AUTOMATION_LAST_FAILURE_KEY = "automation_last_failure"
AUTOMATION_RUNS_KEEP = 50  # automation cycle reports kept in `automation_runs` (see Store.record_automation_run)


class SchemaError(RuntimeError):
    """The database can't be opened safely by this version of MarketPulse."""


class RestoreError(RuntimeError):
    """A backup can't be restored. The ledger is left exactly as it was."""


# `meta` key that changes on every restore. Work that read the ledger before a restore must not
# write what it derived from it into the restored one (see Store.restored_since).
RESTORE_ID_KEY = "restore_id"

# Tables every MarketPulse database has had since the baseline; a file without them isn't one.
_CORE_TABLES = frozenset({"meta", "accounts", "transactions"})


def latest_version(migrations: dict[int, Migration] | None = None) -> int:
    """The schema version this build of MarketPulse writes."""
    migrations = MIGRATIONS if migrations is None else migrations
    return max(migrations, default=BASELINE_VERSION)


def _apply_migration(conn: sqlite3.Connection, version: int, step: Migration) -> None:
    """Run one migration step and stamp the new version, atomically.

    Both the step and the `PRAGMA user_version` bump happen inside a single
    explicit transaction; if anything raises, it is rolled back and the
    database stays exactly as it was. (SQLite supports transactional DDL, so
    this covers CREATE/ALTER/DROP too. The one exception is PRAGMA
    foreign_keys, which is a no-op inside a transaction: don't toggle it in a
    migration.)
    """
    try:
        if isinstance(step, str):
            # executescript() COMMITs any open transaction before it starts, so
            # the BEGIN/COMMIT has to live inside the script itself.
            conn.executescript(f"BEGIN;\n{step}\n;\nPRAGMA user_version = {int(version)};\nCOMMIT;")
        else:
            conn.execute("BEGIN")
            step(conn)
            conn.execute(f"PRAGMA user_version = {int(version)}")
            conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def _stage_restore(source: Path, staged: Path) -> None:
    """Check that `source` is a MarketPulse database this build can open, and copy it to `staged`.

    The source is opened read-only, so checking a backup can't change it.
    """
    name = source.name
    try:
        conn = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise RestoreError(f"{name} can't be opened: {e}") from e
    try:
        try:
            problems = [row[0] for row in conn.execute("PRAGMA integrity_check")]
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        except sqlite3.DatabaseError as e:
            raise RestoreError(f"{name} isn't a readable database: {e}") from e
        if problems != ["ok"]:
            raise RestoreError(f"{name} is damaged and can't be restored: {'; '.join(problems[:3])}")
        if not _CORE_TABLES <= tables:
            raise RestoreError(f"{name} isn't a MarketPulse database.")
        if version > latest_version():
            raise RestoreError(
                f"{name} uses schema version {version}, but this MarketPulse only understands up to "
                f"{latest_version()}. Upgrade MarketPulse to restore it."
            )
        copy = sqlite3.connect(staged)
        try:
            conn.backup(copy)
        finally:
            copy.close()
    finally:
        conn.close()


def list_backups(directory: Path) -> list[Path]:
    """List backup files newest first without opening the live database."""
    if not directory.is_dir():
        return []

    groups: dict[tuple[str, str], list[tuple[int, Path]]] = {}
    for path in directory.glob("marketpulse-*.db"):
        reason = path.stem[28:]
        prefix, _, suffix = reason.rpartition("-")
        counter = 1
        if prefix and suffix.isdecimal():
            reason, counter = prefix, int(suffix)
        groups.setdefault((path.name[12:27], reason), []).append((counter, path))

    ranked = []
    for (stamp, reason), files in groups.items():
        newer_mtime = None
        for counter, path in sorted(files, reverse=True):
            try:
                modified = path.stat().st_mtime_ns
            except OSError:
                modified = 0
            # A touched older copy cannot be newer than its successor in this collision series.
            newer_mtime = modified if newer_mtime is None else min(modified, newer_mtime)
            ranked.append((stamp, newer_mtime, reason, counter, path))
    return [item[-1] for item in sorted(ranked, reverse=True)]


def backup_verification_error(source: Path) -> str | None:
    """Run the restore preflight on a temporary copy and report any failure."""
    try:
        with TemporaryDirectory(prefix="marketpulse-verify-") as scratch:
            _stage_restore(source, Path(scratch) / "checked.db")
    except (RestoreError, OSError, sqlite3.Error) as problem:
        return str(problem)
    return None


@dataclass(frozen=True)
class LedgerSummary:
    accounts: int
    transactions: int
    latest_date: str | None


@dataclass(frozen=True)
class RestorePreview:
    current: LedgerSummary
    backup: LedgerSummary
    fingerprint: str


def _staged_fingerprint(path: Path) -> str:
    with path.open("rb") as database:
        return file_digest(database, "sha256").hexdigest()


@contextmanager
def _prepared_restore(current: Path, source: Path, fingerprint: str | None = None) -> Iterator[Path]:
    if not source.is_file():
        raise RestoreError(f"{source} doesn't exist or isn't a file.")
    if source.resolve() == current.resolve():
        raise RestoreError(f"{source} is the ledger itself.")
    with TemporaryDirectory(prefix="marketpulse-restore-") as scratch:
        staged = Path(scratch) / "marketpulse.db"
        try:
            _stage_restore(source, staged)
            if fingerprint is not None and _staged_fingerprint(staged) != fingerprint:
                raise RestoreError(f"{source.name} changed since the preview. Preview it again before restoring.")
        except (OSError, sqlite3.Error) as e:
            raise RestoreError(f"{source.name} couldn't be prepared for restore: {e}") from e
        yield staged


def _ledger_summary(path: Path) -> LedgerSummary:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        row = conn.execute("SELECT (SELECT COUNT(*) FROM accounts), COUNT(*), MAX(date) FROM transactions").fetchone()
        return LedgerSummary(*row)


def _preview_copy(source: Path, directory: Path) -> Path:
    """Keep SQLite sidecars in scratch, including when it recovers a WAL."""
    source = source.resolve(strict=True)
    directory.mkdir()
    target = directory / source.name
    files = [source, Path(f"{source}-wal"), Path(f"{source}-journal")]

    def revisions() -> dict[Path, tuple[int, int, int, int]]:
        result = {}
        for path in files:
            try:
                st = path.stat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(st.st_mode):
                raise RestoreError(f"{path} is not a regular file.")
            result[path] = (st.st_dev, st.st_ino, st.st_size, st.st_ctime_ns)
        return result

    # Copy a stable set of files. A concurrent write/checkpoint invalidates the copy.
    before = revisions()
    for path in before:
        shutil.copyfile(path, directory / path.name)
    if before != revisions():
        raise RestoreError(f"{source.name} changed during preview. Please try again.")
    return target


def preview_restore(current: Path, source: Path) -> RestorePreview:
    """Read both summaries without running startup maintenance on the live database."""
    try:
        if current.exists() and source.is_file() and current.samefile(source):
            raise RestoreError(f"{source} is the ledger itself.")
        with TemporaryDirectory(prefix="marketpulse-preview-") as scratch:
            staged = Path(scratch) / "checked.db"
            _stage_restore(_preview_copy(source, Path(scratch) / "backup"), staged)
            before = LedgerSummary(0, 0, None)
            if current.exists():
                before = _ledger_summary(_preview_copy(current, Path(scratch) / "current"))
            return RestorePreview(before, _ledger_summary(staged), _staged_fingerprint(staged))
    except (OSError, sqlite3.Error) as error:
        raise RestoreError(str(error)) from error


_TXN_COLS = "account_id, date, type, symbol, quantity, price, amount, fees, currency, note, ratio, target_account_id"
_SNAPSHOT_UPSERT = (
    "INSERT INTO snapshots(date, net_worth, book, contributions, currency, detail) VALUES (?,?,?,?,?,?)"
    " ON CONFLICT(date) DO UPDATE SET net_worth=excluded.net_worth, book=excluded.book,"
    " contributions=excluded.contributions, currency=excluded.currency, detail=excluded.detail"
)


@dataclass
class AutomationRun:
    """One recorded automation cycle. `report` is what `automation run --json` printed for it."""

    id: int
    ran_at: str
    failed: bool
    report: dict


@dataclass
class Snapshot:
    date: str
    net_worth: float
    book: float
    contributions: float
    currency: str
    detail: dict


class Store:
    """Thread-safe SQLite store. One connection guarded by a lock; WAL lets the
    menu bar's CLI calls read while the TUI writes."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else data_dir() / "marketpulse.db"
        # Remember whether there was a real database here before we connect
        # (connecting creates an empty file). A brand-new database has nothing
        # worth backing up before it is migrated.
        existed = self.path.exists() and self.path.stat().st_size > 0
        self._lock = threading.RLock()
        self._in_transaction = False
        self._changes_at_begin = 0
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(SCHEMA)
            self._migrate(backup_first=existed)

    @classmethod
    def open_default(cls) -> Store:
        """Open ~/.marketpulse/marketpulse.db the way the app does: import any
        legacy JSON portfolios, then take the daily safety backup if one is due."""
        store = cls()
        migrate_legacy_json(store, store.path.parent)
        try:
            store.auto_backup()
        except (OSError, sqlite3.Error):
            # A failed backup (full disk, read-only dir) must never stop the
            # app from opening; `marketpulse doctor` reports the backup age.
            pass
        return store

    # ── schema version & migrations ───────────────────────────────────────────

    @property
    def schema_version(self) -> int:
        with self._lock:
            return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    def _migrate(self, *, backup_first: bool) -> None:
        """Bring the database up to `latest_version()`, one step at a time.

        Version 0 is what SQLite reports for a file that has never been
        stamped: either a database we just created or one written by
        MarketPulse 2.0 before versioning existed. Both hold exactly the
        baseline tables (SCHEMA just ran), so they are stamped as version 1.
        """
        current = self.schema_version
        if current == 0:
            self._conn.execute(f"PRAGMA user_version = {BASELINE_VERSION}")
            current = BASELINE_VERSION
        target = latest_version()
        if current > target:
            # Opening a newer file with an older app could silently drop data
            # the new columns carry, so refuse instead.
            raise SchemaError(
                f"{self.path} uses schema version {current}, but this MarketPulse only understands up to "
                f"{target}. Upgrade MarketPulse to open it."
            )
        pending = [v for v in sorted(MIGRATIONS) if current < v <= target]
        if pending and backup_first:
            # Snapshot the pre-upgrade file so a bad migration is always recoverable.
            self.backup(reason=f"pre-v{target}")
        for version in pending:
            _apply_migration(self._conn, version, MIGRATIONS[version])
        # Mirror the version into `meta` for humans poking at the file with the sqlite3 shell.
        self.set_meta("schema_version", str(self.schema_version))

    # ── backups ───────────────────────────────────────────────────────────────
    #
    # Backups are full copies of the database made with SQLite's online backup
    # API, which produces a consistent snapshot even while the TUI or menu bar
    # has the file open (a plain file copy could catch a half-written page or
    # miss data still sitting in the -wal file).
    #
    # Files are named  marketpulse-YYYYMMDD-HHMMSS-<reason>.db  so they sort by
    # time and say why they exist. Reasons:
    #   manual      `marketpulse backup` — never deleted automatically
    #   pre-vN      taken before a schema upgrade — never deleted automatically
    #   daily       taken on startup when the newest backup is >24h old
    #   import      taken right before a CSV import writes to the ledger
    #   pre-restore taken right before `restore` replaces the ledger — never deleted automatically
    # Automatic reasons (daily, import) are pruned to the newest
    # AUTO_BACKUP_KEEP each; the others are yours to manage.

    _AUTO_REASONS = ("daily", "import")

    @property
    def backup_dir(self) -> Path:
        return self.path.parent / BACKUP_DIRNAME

    def backup(self, reason: str = "manual", dest: Path | str | None = None) -> Path:
        """Write a consistent copy of the database and return its path.

        With `dest`, the copy goes exactly there (and is never pruned);
        otherwise it goes into the backups directory under a timestamped name.
        """
        if dest is None:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = self.backup_dir / f"marketpulse-{stamp}-{reason}.db"
            # Two backups in the same second (e.g. import right after startup):
            # add a counter rather than overwrite the first one.
            n = 2
            while target.exists():
                target = self.backup_dir / f"marketpulse-{stamp}-{reason}-{n}.db"
                n += 1
        else:
            target = Path(dest).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        try:
            copy = sqlite3.connect(target)
            try:
                with self._lock:
                    if self._in_transaction:
                        # The backup API can't read through a connection with its own transaction
                        # open (it waits forever); a second connection reads the committed state
                        # alongside it (WAL). That's only the right state, and only safe from a
                        # lock wait, before this transaction has written anything.
                        if self._conn.total_changes != self._changes_at_begin:
                            raise RuntimeError("Back up before writing inside a transaction.")
                        source = sqlite3.connect(self.path)
                        try:
                            source.backup(copy)
                        finally:
                            source.close()
                    else:
                        self._conn.backup(copy)
            finally:
                copy.close()
        except BaseException:
            # A partial copy (full disk, say) would be listed, and offered for restore, as a good backup.
            if not existed:
                target.unlink(missing_ok=True)
            raise
        if dest is None and reason in self._AUTO_REASONS:
            self.prune_backups(reason)
        return target

    def backups(self) -> list[Path]:
        """Backups in the backups directory, newest first."""
        return list_backups(self.backup_dir)

    @staticmethod
    def backup_reason(path: Path) -> str:
        """'daily' from marketpulse-20260101-120000-daily.db (or ...-daily-2.db)."""
        reason = path.stem[28:]
        head, _, tail = reason.rpartition("-")
        return head if tail.isdigit() and head else reason

    def prune_backups(self, reason: str, keep: int = AUTO_BACKUP_KEEP) -> list[Path]:
        """Delete all but the newest `keep` backups taken for `reason`; returns what was removed."""
        same = [p for p in self.backups() if self.backup_reason(p) == reason]
        removed = same[keep:]
        for p in removed:
            p.unlink(missing_ok=True)
        return removed

    def auto_backup(self, max_age_hours: float = AUTO_BACKUP_MAX_AGE_HOURS) -> Path | None:
        """Take the daily backup if the newest backup of any kind is older than
        `max_age_hours`. Skipped for an empty ledger (nothing to lose yet)."""
        if not self._query("SELECT 1 FROM transactions LIMIT 1"):
            return None
        for newest in self.backups():
            taken = self.backup_time(newest)
            if taken is None:
                continue
            if (datetime.now() - taken).total_seconds() < max_age_hours * 3600:
                return None
            break
        return self.backup(reason="daily")

    @staticmethod
    def backup_time(path: Path) -> datetime | None:
        """When a backup in the backups directory was taken, from its name."""
        try:
            return datetime.strptime(path.name[12:27], "%Y%m%d-%H%M%S")
        except ValueError:
            return None

    def restore(self, source: Path | str) -> Path:
        """Replace the ledger with the database at `source`; returns the pre-restore backup.

        The file must be an intact MarketPulse database this build can read: it passes
        `PRAGMA integrity_check`, has the core tables, and its schema version is not newer
        than `latest_version()`. It is copied to a scratch directory and upgraded there, so
        the backup itself is never modified and a failed upgrade never reaches the ledger.

        The swap is one write transaction on the ledger. It takes the write lock first, so
        no other process (the TUI, the menu bar) can write between the `pre-restore` backup
        and the swap, and readers see either the old ledger or the restored one. Each table
        is emptied and refilled from the checked copy using this ledger's own columns, so a
        copy missing a column, or breaking a constraint or foreign key, fails and rolls back.
        Any failure raises RestoreError and leaves the ledger as it was.
        """
        source = Path(source).expanduser()
        with _prepared_restore(self.path, source) as staged:
            return self._restore_staged(source, staged)

    @classmethod
    def restore_previewed(cls, source: Path, fingerprint: str) -> tuple[Path, LedgerSummary]:
        """Verify the copy before opening the default ledger. Restore takes its own safety backup."""
        current = data_dir(create=False) / "marketpulse.db"
        with _prepared_restore(current, source, fingerprint) as staged, closing(cls()) as store:
            safety = store._restore_staged(source, staged)
            return safety, _ledger_summary(store.path)

    def _restore_staged(self, source: Path, staged: Path) -> Path:
        try:
            Store(staged).close()  # brings the copy up to this build's schema
        except (SchemaError, sqlite3.Error) as e:
            raise RestoreError(f"{source.name} couldn't be upgraded for this version of MarketPulse: {e}") from e
        with self._lock:
            if self._in_transaction:
                raise RuntimeError("Restore can't run inside a transaction.")
            # ATTACH isn't allowed inside a transaction, so it comes first.
            self._conn.execute("ATTACH DATABASE ? AS restored", (str(staged),))
            safety: Path | None = None
            step = "lock"
            try:
                with self.transaction():
                    step = "safety"
                    safety = self.backup(reason="pre-restore")
                    step = "swap"
                    self._replace_from("restored")
                    self.set_meta(RESTORE_ID_KEY, uuid4().hex)
            except (OSError, sqlite3.Error) as e:
                # Rolled back: the safety copy is of a ledger that didn't change.
                if safety is not None:
                    safety.unlink(missing_ok=True)
                raise RestoreError(
                    {
                        "lock": f"The ledger is busy in another MarketPulse window, so {source.name} "
                        f"wasn't restored: {e}",
                        "safety": f"Couldn't back up the current ledger first, so {source.name} wasn't restored: {e}",
                        "swap": f"{source.name} doesn't match this ledger's tables: {e}",
                    }[step]
                ) from e
            finally:
                self._conn.execute("DETACH DATABASE restored")
        assert safety is not None
        return safety

    @property
    def restore_id(self) -> str:
        """Read before deriving something from the ledger; pass to `restored_since` before writing it.
        Empty for a ledger that has never been restored."""
        return self.get_meta(RESTORE_ID_KEY) or ""

    def restored_since(self, restore_id: str) -> bool:
        """Whether a restore replaced the ledger after `restore_id` was read. Check it inside
        `transaction()`, which keeps a restore from starting before the write commits."""
        return self.restore_id != restore_id

    def _replace_from(self, schema: str) -> None:
        """Inside a transaction, replace every table's rows with those of the attached `schema`."""
        tables = [
            r[0]
            for r in self._conn.execute("SELECT name FROM main.sqlite_master WHERE type = 'table'")
            if not r[0].startswith("sqlite_")
        ]
        # Rows are deleted and reinserted in any order; references are checked at commit.
        self._conn.execute("PRAGMA defer_foreign_keys = ON")
        # Every table is emptied before any is refilled, so ON DELETE CASCADE can't remove restored rows.
        for table in tables:
            self._conn.execute(f'DELETE FROM main."{table}"')
        for table in tables:
            names = [r[1] for r in self._conn.execute(f'PRAGMA main.table_info("{table}")')]
            # Qualified, because SQLite reads an unknown bare "name" as a string literal rather
            # than failing: a copy missing a column would be filled with its name.
            cols, picked = ", ".join(f'"{n}"' for n in names), ", ".join(f'src."{n}"' for n in names)
            self._conn.execute(f'INSERT INTO main."{table}" ({cols}) SELECT {picked} FROM {schema}."{table}" AS src')

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Run several writes as one: other processes can't write in between (BEGIN IMMEDIATE
        takes the write lock up front), and everything commits together or not at all."""
        with self._lock:
            if self._in_transaction:
                raise RuntimeError("Transactions don't nest.")
            self._conn.execute("BEGIN IMMEDIATE")
            self._in_transaction = True
            self._changes_at_begin = self._conn.total_changes
            try:
                yield
                self._conn.commit()
            except BaseException:
                # Includes a failed commit, which would otherwise leave SQLite mid-transaction
                # and let the next unrelated write commit these changes.
                if self._conn.in_transaction:
                    self._conn.rollback()
                raise
            finally:
                self._in_transaction = False

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """`transaction()`, or the one already open on this store (a caller's reads and writes join it)."""
        with self._lock:
            if self._in_transaction:
                yield
            else:
                with self.transaction():
                    yield

    @contextmanager
    def _read_snapshot(self) -> Iterator[None]:
        """Keep related reads on the same SQLite snapshot without taking a write lock."""
        with self._lock:
            if self._conn.in_transaction:
                raise RuntimeError("Transactions don't nest.")
            self._conn.execute("BEGIN")
            try:
                yield
            finally:
                self._conn.commit()

    @contextmanager
    def _write(self) -> Iterator[None]:
        """Each write commits on its own, unless it's part of an open `transaction()`."""
        with self._lock:
            if self._in_transaction:
                yield
            else:
                with self._conn:
                    yield

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._write():
            return self._conn.execute(sql, params)

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ── meta ──────────────────────────────────────────────────────────────────

    def get_meta(self, key: str) -> str | None:
        rows = self._query("SELECT value FROM meta WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def set_meta(self, key: str, value: str) -> None:
        self._exec(
            "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # ── automation history ────────────────────────────────────────────────────

    def record_automation_run(self, report: dict, *, keep: int = AUTOMATION_RUNS_KEEP) -> AutomationRun:
        """Append one automation cycle's report and keep only the newest `keep` runs.

        A run failed when its report lists `errors` (or says `failed`); quote errors alone are not failures.
        """
        ran_at = str(report.get("last_run") or datetime.now().isoformat(timespec="seconds"))
        failed = bool(report.get("failed") or report.get("errors"))
        with self.atomic():
            cursor = self._exec(
                "INSERT INTO automation_runs(ran_at, failed, report) VALUES (?, ?, ?)",
                (ran_at, int(failed), json.dumps(report, allow_nan=False)),
            )
            self._exec(
                "DELETE FROM automation_runs WHERE id NOT IN (SELECT id FROM automation_runs ORDER BY id DESC LIMIT ?)",
                (keep,),
            )
            run = AutomationRun(int(cursor.lastrowid or 0), ran_at, failed, report)
            if failed:
                # Kept apart from the capped history: a frequent timer can prune a recent failure from it.
                self.set_meta(AUTOMATION_LAST_FAILURE_KEY, json.dumps(asdict(run), allow_nan=False))
        return run

    def automation_status(self) -> tuple[list[AutomationRun], AutomationRun | None]:
        """The kept runs and, if it has been pruned from them, the latest failure: read from one
        snapshot, so a run recorded or a backup restored in between can't pair two ledgers' rows."""
        with self._read_snapshot():
            failure = self.latest_automation_failure()
            runs = self.automation_runs()
        pruned = failure if failure and all(r.id != failure.id for r in runs) else None
        return runs, pruned

    def latest_automation_failure(self) -> AutomationRun | None:
        """The newest failed automation run, even after it has been pruned from `automation_runs`."""
        raw = self.get_meta(AUTOMATION_LAST_FAILURE_KEY)
        return AutomationRun(**json.loads(raw)) if raw else None

    def automation_runs(self, *, failures_only: bool = False, limit: int | None = None) -> list[AutomationRun]:
        """Recorded automation runs, newest first."""
        sql = "SELECT * FROM automation_runs" + (" WHERE failed = 1" if failures_only else "") + " ORDER BY id DESC"
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return [
            AutomationRun(r["id"], r["ran_at"], bool(r["failed"]), json.loads(r["report"]))
            for r in self._query(sql, params)
        ]

    # ── accounts ──────────────────────────────────────────────────────────────

    @staticmethod
    def _account(row: sqlite3.Row) -> Account:
        return Account(
            id=row["id"],
            name=row["name"],
            type=AccountType(row["type"]),
            currency=row["currency"],
            institution=row["institution"],
            track_cash=bool(row["track_cash"]),
            archived=bool(row["archived"]),
            created_at=row["created_at"],
        )

    def accounts(self, include_archived: bool = False) -> list[Account]:
        sql = "SELECT * FROM accounts" + ("" if include_archived else " WHERE archived = 0") + " ORDER BY id"
        return [self._account(r) for r in self._query(sql)]

    def account_map(self) -> dict[int, Account]:
        return {a.saved_id: a for a in self.accounts(include_archived=True)}

    def get_account(self, ref: int | str) -> Account | None:
        """Find an account by id, name (case-insensitive) or unique type (e.g. 'tfsa')."""
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            rows = self._query("SELECT * FROM accounts WHERE id = ?", (int(ref),))
            return self._account(rows[0]) if rows else None
        rows = self._query("SELECT * FROM accounts WHERE name = ? COLLATE NOCASE", (ref,))
        if rows:
            return self._account(rows[0])
        rows = self._query("SELECT * FROM accounts WHERE type = ? AND archived = 0", (ref.upper(),))
        return self._account(rows[0]) if len(rows) == 1 else None

    def add_account(self, account: Account) -> Account:
        if not account.name.strip():
            raise ValueError("Account name is required.")
        try:
            cur = self._exec(
                "INSERT INTO accounts(name, type, currency, institution, track_cash, archived, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    account.name.strip(),
                    AccountType(account.type).value,
                    account.currency.upper(),
                    account.institution,
                    int(account.track_cash),
                    int(account.archived),
                    account.created_at,
                ),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"An account named '{account.name}' already exists.") from None
        account.id = cur.lastrowid
        return account

    def update_account(self, account: Account) -> None:
        account.name = account.name.strip()
        if not account.name:
            raise ValueError("Account name is required.")
        try:
            self._exec(
                "UPDATE accounts SET name=?, type=?, currency=?, institution=?, track_cash=?, archived=? WHERE id=?",
                (
                    account.name,
                    AccountType(account.type).value,
                    account.currency.upper(),
                    account.institution,
                    int(account.track_cash),
                    int(account.archived),
                    account.id,
                ),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"An account named '{account.name}' already exists.") from None

    def delete_account(self, account_id: int) -> None:
        self._exec("DELETE FROM accounts WHERE id = ?", (account_id,))

    def ensure_default_account(self, currency: str = "CAD") -> Account:
        accounts = self.accounts()
        if accounts:
            return accounts[0]
        return self.add_account(Account(name="Main", type=AccountType.NONREG, currency=currency))

    # ── transactions ──────────────────────────────────────────────────────────

    @staticmethod
    def _txn(row: sqlite3.Row) -> Transaction:
        return Transaction(
            id=row["id"],
            account_id=row["account_id"],
            date=row["date"],
            type=TxnType(row["type"]),
            symbol=row["symbol"],
            quantity=row["quantity"],
            price=row["price"],
            amount=row["amount"],
            fees=row["fees"],
            currency=row["currency"],
            note=row["note"],
            ratio=row["ratio"],
            target_account_id=row["target_account_id"],
        )

    def transactions(self, account_id: int | None = None, symbol: str | None = None) -> list[Transaction]:
        where: list[str] = []
        params: list[int | str] = []
        if account_id is not None:
            where.append("(account_id = ? OR target_account_id = ?)")
            params += [account_id, account_id]
        if symbol:
            where.append("symbol = ?")
            params.append(symbol.upper())
        sql = "SELECT * FROM transactions" + (f" WHERE {' AND '.join(where)}" if where else "")
        return [self._txn(r) for r in self._query(sql + " ORDER BY date, id", tuple(params))]

    def activity_snapshot(self) -> tuple[list[Account], list[Transaction]]:
        """Read active accounts and their originating transactions from one ledger snapshot."""
        with self._read_snapshot():
            accounts = self.accounts()
            active_ids = {account.saved_id for account in accounts}
            transactions = [txn for txn in self.transactions() if txn.account_id in active_ids]
        return accounts, transactions

    def _txn_params(self, txn: Transaction) -> tuple:
        txn.date = parse_date(txn.date)
        txn.validate()
        return (
            txn.account_id,
            txn.date,
            txn.type.value,
            txn.symbol,
            txn.quantity,
            txn.price,
            txn.amount,
            txn.fees,
            txn.currency,
            txn.note,
            txn.ratio,
            txn.target_account_id,
        )

    def add_transaction(self, txn: Transaction) -> Transaction:
        cur = self._exec(
            f"INSERT INTO transactions({_TXN_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", self._txn_params(txn)
        )
        txn.id = cur.lastrowid
        return txn

    def add_transactions(self, txns: list[Transaction]) -> int:
        params = [self._txn_params(t) for t in txns]
        with self._write():
            self._conn.executemany(f"INSERT INTO transactions({_TXN_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", params)
        return len(params)

    def update_transaction(self, txn: Transaction) -> None:
        if txn.id is None:
            raise ValueError("Transaction has no id.")
        sets = ", ".join(f"{c.strip()} = ?" for c in _TXN_COLS.split(","))
        self._exec(f"UPDATE transactions SET {sets} WHERE id = ?", (*self._txn_params(txn), txn.id))

    def delete_transaction(self, txn_id: int) -> None:
        self._exec("DELETE FROM transactions WHERE id = ?", (txn_id,))

    def ledger(self) -> LedgerState:
        return replay(self.transactions(), self.account_map())

    # ── assets ────────────────────────────────────────────────────────────────

    def assets(self) -> dict[str, Asset]:
        return {
            r["symbol"]: Asset(
                symbol=r["symbol"],
                kind=r["kind"],
                name=r["name"],
                asset_class=r["asset_class"],
                currency=r["currency"],
                rate=r["rate"],
                compounding=r["compounding"],
                start_date=r["start_date"],
                maturity_date=r["maturity_date"],
                foreign_property=None if r["foreign_property"] is None else bool(r["foreign_property"]),
            )
            for r in self._query("SELECT * FROM assets")
        }

    def upsert_asset(self, asset: Asset) -> None:
        self._exec(
            "INSERT INTO assets(symbol, kind, name, asset_class, currency, rate, compounding, start_date,"
            " maturity_date, foreign_property) VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(symbol) DO UPDATE SET kind=excluded.kind, name=excluded.name,"
            " asset_class=excluded.asset_class, currency=excluded.currency, rate=excluded.rate,"
            " compounding=excluded.compounding, start_date=excluded.start_date, maturity_date=excluded.maturity_date,"
            # Forms and purchase paths don't carry the T1135 setting: keep a saved one unless
            # the new row sets it. `set_foreign_property` is how it is cleared.
            " foreign_property=COALESCE(excluded.foreign_property, assets.foreign_property)",
            (
                asset.symbol,
                asset.kind.value,
                asset.name,
                asset.asset_class.value if asset.asset_class else None,
                asset.currency.upper(),
                asset.rate,
                asset.compounding,
                asset.start_date,
                asset.maturity_date,
                None if asset.foreign_property is None else int(asset.foreign_property),
            ),
        )

    def set_foreign_property(self, asset: Asset) -> None:
        """Save `asset` with exactly its foreign property setting (None: decide by listing)."""
        with self.atomic():
            self.upsert_asset(asset)
            self._exec(
                "UPDATE assets SET foreign_property = ? WHERE symbol = ?",
                (None if asset.foreign_property is None else int(asset.foreign_property), asset.symbol),
            )

    def delete_asset(self, symbol: str) -> None:
        self._exec("DELETE FROM assets WHERE symbol = ?", (symbol.upper(),))

    # ── watchlist ─────────────────────────────────────────────────────────────

    def watchlist(self) -> list[str]:
        return [r["symbol"] for r in self._query("SELECT symbol FROM watchlist ORDER BY position, symbol")]

    def add_watch(self, symbols: list[str]) -> list[str]:
        current = self.watchlist()
        added = [s.upper() for s in symbols if s.upper() not in current]
        with self._write():
            for i, sym in enumerate(dict.fromkeys(added)):
                self._conn.execute(
                    "INSERT OR IGNORE INTO watchlist(symbol, position) VALUES (?, ?)", (sym, len(current) + i)
                )
        return list(dict.fromkeys(added))

    def remove_watch(self, symbols: list[str]) -> list[str]:
        current = set(self.watchlist())
        removed = [s.upper() for s in symbols if s.upper() in current]
        with self._write():
            self._conn.executemany("DELETE FROM watchlist WHERE symbol = ?", [(s,) for s in removed])
        return removed

    def move_watch(self, symbol: str, delta: int) -> None:
        items = self.watchlist()
        if symbol not in items:
            return
        i = items.index(symbol)
        j = max(0, min(len(items) - 1, i + delta))
        items.insert(j, items.pop(i))
        with self._write():
            self._conn.executemany("UPDATE watchlist SET position = ? WHERE symbol = ?", list(enumerate(items)))

    # ── alerts ────────────────────────────────────────────────────────────────

    def alerts(self, active_only: bool = False) -> list[Alert]:
        sql = "SELECT * FROM alerts" + (" WHERE active = 1" if active_only else "") + " ORDER BY symbol, id"
        alerts = [
            Alert(
                id=r["id"],
                symbol=r["symbol"],
                condition=r["condition"],
                threshold=r["threshold"],
                note=r["note"],
                active=bool(r["active"]),
                triggered_at=r["triggered_at"],
            )
            for r in self._query(sql)
        ]
        for alert in alerts:
            try:
                alert.validate()
            except ValueError:
                # Preserve legacy rows for inspection/removal, but never evaluate
                # or notify on a blank symbol or invalid threshold. No data rewrite.
                alert.active = False
        return [a for a in alerts if a.active] if active_only else alerts

    def add_alert(self, alert: Alert) -> Alert:
        alert.validate()
        cur = self._exec(
            "INSERT INTO alerts(symbol, condition, threshold, note, active, triggered_at) VALUES (?,?,?,?,?,?)",
            (alert.symbol, alert.condition, alert.threshold, alert.note, int(alert.active), alert.triggered_at),
        )
        alert.id = cur.lastrowid
        return alert

    def update_alert(self, alert: Alert) -> None:
        self._exec(
            "UPDATE alerts SET symbol=?, condition=?, threshold=?, note=?, active=?, triggered_at=? WHERE id=?",
            (
                alert.symbol,
                alert.condition,
                alert.threshold,
                alert.note,
                int(alert.active),
                alert.triggered_at,
                alert.id,
            ),
        )

    def delete_alert(self, alert_id: int) -> None:
        self._exec("DELETE FROM alerts WHERE id = ?", (alert_id,))

    # ── snapshots ─────────────────────────────────────────────────────────────

    @staticmethod
    def _snapshot_params(snap: Snapshot) -> tuple:
        return (snap.date, snap.net_worth, snap.book, snap.contributions, snap.currency, json.dumps(snap.detail))

    @staticmethod
    def _snapshot(r: sqlite3.Row) -> Snapshot:
        return Snapshot(
            r["date"], r["net_worth"], r["book"], r["contributions"], r["currency"], json.loads(r["detail"])
        )

    def upsert_snapshot(self, snap: Snapshot) -> None:
        self._exec(_SNAPSHOT_UPSERT, self._snapshot_params(snap))

    def upsert_snapshots(self, snaps: list[Snapshot]) -> None:
        """Write many snapshots in one transaction (backfill writes years of days)."""
        if not snaps:
            return
        with self._write():
            self._conn.executemany(_SNAPSHOT_UPSERT, [self._snapshot_params(s) for s in snaps])

    def snapshots(self, since: str | None = None) -> list[Snapshot]:
        rows = self._query(
            "SELECT * FROM snapshots" + (" WHERE date >= ?" if since else "") + " ORDER BY date",
            (since,) if since else (),
        )
        return [self._snapshot(r) for r in rows]

    def latest_snapshot(self, before: str | None = None) -> Snapshot | None:
        """Most recent snapshot, optionally strictly before an ISO date."""
        rows = self._query(
            "SELECT * FROM snapshots" + (" WHERE date < ?" if before else "") + " ORDER BY date DESC LIMIT 1",
            (before,) if before else (),
        )
        return self._snapshot(rows[0]) if rows else None

    # ── contribution room & targets ───────────────────────────────────────────

    def rooms(self) -> dict[str, tuple[int, float]]:
        return {r["account_type"]: (r["as_of_year"], r["amount"]) for r in self._query("SELECT * FROM room")}

    def set_room(self, account_type: str, as_of_year: int, amount: float) -> None:
        self._exec(
            "INSERT INTO room(account_type, as_of_year, amount) VALUES (?,?,?) ON CONFLICT(account_type)"
            " DO UPDATE SET as_of_year=excluded.as_of_year, amount=excluded.amount",
            (account_type.upper(), as_of_year, amount),
        )

    def targets(self) -> dict[str, float]:
        return {r["bucket"]: r["weight"] for r in self._query("SELECT * FROM targets ORDER BY bucket")}

    def set_targets(self, targets: dict[str, float]) -> None:
        with self._write():
            self._conn.execute("DELETE FROM targets")
            self._conn.executemany("INSERT INTO targets(bucket, weight) VALUES (?, ?)", list(targets.items()))

    # ── quote cache (offline fallback) ────────────────────────────────────────

    def cache_quotes(self, quotes: list[Quote]) -> None:
        rows = []
        for q in quotes:
            data = asdict(q)
            data.pop("stale", None)
            rows.append((q.symbol, json.dumps(data), q.fetched_at))
        with self._write():
            self._conn.executemany(
                "INSERT INTO quote_cache(symbol, data, fetched_at) VALUES (?,?,?) ON CONFLICT(symbol)"
                " DO UPDATE SET data=excluded.data, fetched_at=excluded.fetched_at",
                rows,
            )

    def cached_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        if not symbols:
            return {}
        marks = ",".join("?" * len(symbols))
        out = {}
        for r in self._query(
            f"SELECT data FROM quote_cache WHERE symbol IN ({marks})", tuple(s.upper() for s in symbols)
        ):
            q = Quote(**json.loads(r["data"]))
            q.stale = True
            out[q.symbol] = q
        return out

    def all_cached_quotes(self) -> dict[str, Quote]:
        """Every cached quote by symbol (A–Z), marked stale; read-only."""
        out = {}
        for r in self._query("SELECT data FROM quote_cache ORDER BY symbol"):
            q = Quote(**json.loads(r["data"]))
            q.stale = True
            out[q.symbol] = q
        return out


# ── Legacy JSON migration ─────────────────────────────────────────────────────


def migrate_legacy_json(store: Store, directory: Path) -> list[str]:
    """Import pre-SQLite portfolio files (schema 1 and 2) as accounts, once.

    The JSON files are left untouched. Positions the old app removed without a
    matching sell are closed with a zero-gain SELL at average cost, so the
    replayed ledger matches what the old app showed.
    """
    if store.get_meta("legacy_json_migrated") is not None:
        return []
    imported = []
    watch: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or "positions" not in data:
            continue
        name = str(data.get("name") or path.stem)
        name = "Main" if name == "default" else name
        currency = str(data.get("currency") or "CAD").upper()
        if store.get_account(name) is not None:
            name = f"{name} (imported)"
        acct = store.add_account(Account(name=name, type=AccountType.NONREG, currency=currency))
        created = str(data.get("created_at") or "")[:10] or datetime.now().date().isoformat()
        positions = data.get("positions") or {}
        txns: list[Transaction] = []
        for raw in data.get("transactions") or []:
            try:
                sym = str(raw["ticker"]).upper()
                txns.append(
                    Transaction(
                        account_id=acct.saved_id,
                        type=TxnType(raw["action"]),
                        date=parse_date(str(raw.get("date") or created)[:10]),
                        symbol=sym,
                        quantity=float(raw["shares"]),
                        price=float(raw["price"]),
                        fees=float(raw.get("fees") or 0.0),
                        currency=(raw.get("currency") or "").upper() or guess_currency(sym),
                        note=str(raw.get("note") or ""),
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        if not txns:
            for pos in positions.values():
                sym = str(pos["ticker"]).upper()
                txns.append(
                    Transaction(
                        account_id=acct.saved_id,
                        type=TxnType.BUY,
                        date=created,
                        symbol=sym,
                        quantity=float(pos["shares"]),
                        price=float(pos["avg_cost"]),
                        currency=(pos.get("currency") or "").upper() or guess_currency(sym),
                        note="opening balance (migrated)",
                    )
                )
        state = replay(txns, {acct.saved_id: acct})
        for h in state.open_holdings():
            pos = positions.get(h.symbol)
            target = float(pos["shares"]) if pos else 0.0
            if h.quantity - target > EPSILON:
                txns.append(
                    Transaction(
                        account_id=acct.saved_id,
                        type=TxnType.SELL,
                        date=datetime.now().date().isoformat(),
                        symbol=h.symbol,
                        quantity=h.quantity - target,
                        price=h.avg_cost,
                        currency=h.currency,
                        note="position removed in MarketPulse 0.1 (migrated, zero gain)",
                    )
                )
        store.add_transactions(txns)
        watch += [str(s).upper() for s in data.get("watchlist") or []]
        imported.append(path.name)
    if imported:
        store.add_watch(watch)
    elif not store.watchlist() and not store.accounts():
        store.add_watch(DEFAULT_WATCHLIST)
    store.set_meta("legacy_json_migrated", json.dumps(imported))
    return imported
