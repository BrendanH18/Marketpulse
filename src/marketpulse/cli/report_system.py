"""Read-only inspection of the local installation for the composable report command."""

from __future__ import annotations

import os
import platform
import sqlite3
import stat
import sys
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .. import __version__
from ..config import config_path
from .base import App

GROUP = "system"
SOURCES: dict[str, tuple[str, ...]] = {
    "schema": ("table", "position", "column", "type", "required", "default", "primary_key"),
    "paths": ("name", "path", "exists", "kind"),
    "data-files": ("name", "kind", "size_bytes", "modified_at"),
    "environment": ("name", "set", "value", "purpose"),
    "runtime": ("component", "version"),
}
DESCRIPTIONS: dict[str, str] = {
    "schema": "Tables and columns of the local database, without reading rows.",
    "paths": "Data, database, backup and configuration locations in use.",
    "data-files": "Entries directly inside the data directory.",
    "environment": "Environment overrides MarketPulse reads and whether they are set.",
    "runtime": "Versions of MarketPulse, Python, SQLite and installed dependencies.",
}

# Every environment variable the engine reads (see config.py).
_ENVIRONMENT = (
    ("MARKETPULSE_DATA", "Data directory for the database and its backups, instead of ~/.marketpulse."),
    ("MARKETPULSE_CONFIG", "Configuration file, instead of ~/.config/marketpulse/config.toml."),
    ("XDG_CONFIG_HOME", "Base configuration directory, instead of ~/.config, when MARKETPULSE_CONFIG is not set."),
)
# Dependencies reported after the interpreter, by distribution name.
_DISTRIBUTIONS = ("click", "rich", "textual", "curl_cffi", "tzdata")  # tzdata is installed on Windows only
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _kind(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "file"
    return "directory" if stat.S_ISDIR(mode) else "other"


def _utc_seconds(nanoseconds: int) -> str | None:
    """A file time as ISO 8601 UTC, truncated to the second; null outside the years a datetime can hold.

    Whole seconds are counted from the epoch, which gives the same answer on every platform:
    `datetime.fromtimestamp` only accepts what the C library does (Windows rejects times before 1970).
    """
    try:
        return (_EPOCH + timedelta(seconds=nanoseconds // 1_000_000_000)).isoformat()
    except OverflowError:
        return None


def _schema(database: Path) -> list[dict[str, Any]]:
    """Tables and columns, read through a second connection that cannot write; no table row is read."""
    rows: list[dict[str, Any]] = []
    with closing(sqlite3.connect(database.absolute().as_uri() + "?mode=ro", uri=True)) as connection:
        names = connection.execute("SELECT name FROM main.sqlite_master WHERE type = 'table' ORDER BY name")
        tables = [table for (table,) in names if not table.startswith("sqlite_")]
        for table in tables:
            # The name comes from the database, not from this program: quote it as an identifier.
            identifier = '"' + table.replace('"', '""') + '"'
            columns = connection.execute(f"PRAGMA main.table_info({identifier})")
            for cid, column, declared, not_null, default, primary_key in columns:
                rows.append(
                    {
                        "table": table,
                        "position": cid + 1,
                        "column": column,
                        "type": declared,
                        "required": bool(not_null),
                        "default": default,
                        "primary_key": bool(primary_key),
                    }
                )
    return rows


def _path(name: str, path: Path) -> dict[str, Any]:
    try:
        kind = _kind(path.stat().st_mode)
    except OSError:  # nothing there, a link to nothing, or a parent that cannot be searched
        kind = "missing"
    # realpath gives the text of `Path.resolve()`, which before Python 3.13 raises on a symlink loop.
    return {"name": name, "path": os.path.realpath(path), "exists": kind != "missing", "kind": kind}


def _data_files(directory: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in sorted(os.listdir(directory)):
        try:
            info = os.lstat(directory / name)  # the entry itself: a symlink is never followed
        except FileNotFoundError:
            continue  # SQLite's -wal and -shm files come and go while the directory is being read
        kind = _kind(info.st_mode)
        rows.append(
            {
                "name": name,
                "kind": kind,
                "size_bytes": info.st_size if kind == "file" else None,
                "modified_at": _utc_seconds(info.st_mtime_ns),
            }
        )
    return rows


def _environment() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, purpose in _ENVIRONMENT:
        value = os.environ.get(name) or None  # config.py treats an empty value as unset
        rows.append({"name": name, "set": value is not None, "value": value, "purpose": purpose})
    return rows


def _runtime() -> list[dict[str, Any]]:
    # Imported here: only this dataset reads distribution metadata, and the module is slow to load.
    from importlib import metadata

    versions: list[tuple[str, str | None]] = [
        ("marketpulse", __version__),
        ("python", platform.python_version()),
        ("implementation", platform.python_implementation()),
        ("platform", sys.platform),
        ("sqlite", sqlite3.sqlite_version),
    ]
    for distribution in _DISTRIBUTIONS:
        try:
            versions.append((distribution, metadata.version(distribution)))
        except metadata.PackageNotFoundError:
            versions.append((distribution, None))
    return [{"component": component, "version": version} for component, version in versions]


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    """Return raw script rows about local files and software; never reads ledger rows or the network."""
    if name not in SOURCES:
        raise KeyError(name)
    if name == "environment":
        return _environment()
    if name == "runtime":
        return _runtime()
    # The rest describe the data in use, so they open it the way every saved-data source does.
    store = app.store
    if name == "schema":
        return _schema(store.path)
    if name == "paths":
        return [
            _path("data", store.path.parent),
            _path("database", store.path),
            _path("backups", store.backup_dir),
            _path("config", config_path()),
        ]
    return _data_files(store.path.parent)
