"""SQLite persistence (stdlib only) plus migration from legacy JSON portfolios."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

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
MIGRATIONS: dict[int, Migration] = {}

# Where automatic backups go and how many to keep (see Store.backup).
BACKUP_DIRNAME = "backups"
AUTO_BACKUP_KEEP = 14  # automatic backups kept per reason (daily, import, ...)
AUTO_BACKUP_MAX_AGE_HOURS = 24.0  # take a fresh daily backup when the newest is older than this


class SchemaError(RuntimeError):
    """The database can't be opened safely by this version of MarketPulse."""


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


_TXN_COLS = "account_id, date, type, symbol, quantity, price, amount, fees, currency, note, ratio, target_account_id"
_SNAPSHOT_UPSERT = (
    "INSERT INTO snapshots(date, net_worth, book, contributions, currency, detail) VALUES (?,?,?,?,?,?)"
    " ON CONFLICT(date) DO UPDATE SET net_worth=excluded.net_worth, book=excluded.book,"
    " contributions=excluded.contributions, currency=excluded.currency, detail=excluded.detail"
)


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
        copy = sqlite3.connect(target)
        try:
            with self._lock:
                self._conn.backup(copy)
        finally:
            copy.close()
        if dest is None and reason in self._AUTO_REASONS:
            self.prune_backups(reason)
        return target

    def backups(self) -> list[Path]:
        """Backups in the backups directory, newest first."""
        if not self.backup_dir.is_dir():
            return []
        # The timestamp is at a fixed offset in the name, so sorting by name is sorting by time.
        return sorted(self.backup_dir.glob("marketpulse-*.db"), key=lambda p: p.name[12:27], reverse=True)

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
        newest = next(iter(self.backups()), None)
        if newest is not None:
            taken = datetime.strptime(newest.name[12:27], "%Y%m%d-%H%M%S")
            if (datetime.now() - taken).total_seconds() < max_age_hours * 3600:
                return None
        return self.backup(reason="daily")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock, self._conn:
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
        with self._lock, self._conn:
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
            )
            for r in self._query("SELECT * FROM assets")
        }

    def upsert_asset(self, asset: Asset) -> None:
        self._exec(
            "INSERT INTO assets(symbol, kind, name, asset_class, currency, rate, compounding, start_date,"
            " maturity_date) VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(symbol) DO UPDATE SET kind=excluded.kind, name=excluded.name,"
            " asset_class=excluded.asset_class, currency=excluded.currency, rate=excluded.rate,"
            " compounding=excluded.compounding, start_date=excluded.start_date, maturity_date=excluded.maturity_date",
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
            ),
        )

    def delete_asset(self, symbol: str) -> None:
        self._exec("DELETE FROM assets WHERE symbol = ?", (symbol.upper(),))

    # ── watchlist ─────────────────────────────────────────────────────────────

    def watchlist(self) -> list[str]:
        return [r["symbol"] for r in self._query("SELECT symbol FROM watchlist ORDER BY position, symbol")]

    def add_watch(self, symbols: list[str]) -> list[str]:
        current = self.watchlist()
        added = [s.upper() for s in symbols if s.upper() not in current]
        with self._lock, self._conn:
            for i, sym in enumerate(dict.fromkeys(added)):
                self._conn.execute(
                    "INSERT OR IGNORE INTO watchlist(symbol, position) VALUES (?, ?)", (sym, len(current) + i)
                )
        return list(dict.fromkeys(added))

    def remove_watch(self, symbols: list[str]) -> list[str]:
        current = set(self.watchlist())
        removed = [s.upper() for s in symbols if s.upper() in current]
        with self._lock, self._conn:
            self._conn.executemany("DELETE FROM watchlist WHERE symbol = ?", [(s,) for s in removed])
        return removed

    def move_watch(self, symbol: str, delta: int) -> None:
        items = self.watchlist()
        if symbol not in items:
            return
        i = items.index(symbol)
        j = max(0, min(len(items) - 1, i + delta))
        items.insert(j, items.pop(i))
        with self._lock, self._conn:
            self._conn.executemany("UPDATE watchlist SET position = ? WHERE symbol = ?", list(enumerate(items)))

    # ── alerts ────────────────────────────────────────────────────────────────

    def alerts(self, active_only: bool = False) -> list[Alert]:
        sql = "SELECT * FROM alerts" + (" WHERE active = 1" if active_only else "") + " ORDER BY symbol, id"
        return [
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

    def add_alert(self, alert: Alert) -> Alert:
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
        with self._lock, self._conn:
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
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM targets")
            self._conn.executemany("INSERT INTO targets(bucket, weight) VALUES (?, ?)", list(targets.items()))

    # ── quote cache (offline fallback) ────────────────────────────────────────

    def cache_quotes(self, quotes: list[Quote]) -> None:
        rows = []
        for q in quotes:
            data = asdict(q)
            data.pop("stale", None)
            rows.append((q.symbol, json.dumps(data), q.fetched_at))
        with self._lock, self._conn:
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
