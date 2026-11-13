"""System reports describe the installation in use: local files and software, never ledger rows or the network."""

from __future__ import annotations

import csv
import io
import json
import os
import platform
import re
import sqlite3
import sys
from contextlib import closing
from importlib import metadata
from pathlib import Path

import pytest
from click.testing import CliRunner

import marketpulse
from marketpulse.cli import main, report_system
from marketpulse.cli.base import App
from marketpulse.cli.report_system import SOURCES, load_source
from marketpulse.db import SCHEMA
from marketpulse.market import CurlTransport
from marketpulse.models import Account, Transaction, TxnType

NAMES = ["schema", "paths", "data-files", "environment", "runtime"]
# The baseline tables, read from the engine's own CREATE statements rather than from the report.
BASELINE_TABLES = sorted(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA))
# table, position, column, type, required, default, primary_key: read off db.SCHEMA by hand.
BASELINE_COLUMNS = [
    ("accounts", 1, "id", "INTEGER", False, None, True),
    ("accounts", 2, "name", "TEXT", True, None, False),
    ("alerts", 6, "active", "INTEGER", True, "1", False),
    ("assets", 4, "asset_class", "TEXT", False, None, False),
    ("assets", 7, "compounding", "TEXT", True, "'annual'", False),
    ("meta", 1, "key", "TEXT", False, None, True),
    ("snapshots", 6, "detail", "TEXT", True, "'{}'", False),
    ("transactions", 2, "account_id", "INTEGER", True, None, False),
    ("transactions", 6, "quantity", "REAL", True, "0", False),
    ("transactions", 13, "target_account_id", "INTEGER", False, None, False),
]
VARIABLES = ["MARKETPULSE_DATA", "MARKETPULSE_CONFIG", "XDG_CONFIG_HOME"]
COMPONENTS = [
    "marketpulse",
    "python",
    "implementation",
    "platform",
    "sqlite",
    "click",
    "rich",
    "textual",
    "curl_cffi",
    "tzdata",
]
UTC_SECONDS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00")
needs_symlinks = pytest.mark.skipif(sys.platform == "win32", reason="creating a symlink needs a privilege on Windows")


def _forbidden(what: str):
    def fail(*args, **kwargs):
        pytest.fail(f"a system report {what}")

    return fail


def _json(value) -> str:
    """JSON text, for comparisons that must tell true from 1 and null from an empty string."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Fail any test here in which a market request is made, including through a tracker opened for real."""
    monkeypatch.setattr(CurlTransport, "get_json", _forbidden("requested market data"))


@pytest.fixture
def app(tracker) -> App:
    """An App on the fixture tracker. Its database is tmp_path/test.db, so tmp_path is the data directory."""
    app = App()
    app._tracker = tracker
    return app


@pytest.fixture
def detached(tmp_path, monkeypatch) -> App:
    """An App that fails the test if the tracker is opened, with the real home directory out of reach."""
    app = App()
    monkeypatch.setattr(App, "tracker", property(_forbidden("opened the tracker")))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "fictional-home"))
    return app


def test_sources_and_fields_are_the_documented_ones():
    assert list(SOURCES) == NAMES
    assert SOURCES == {
        "schema": ("table", "position", "column", "type", "required", "default", "primary_key"),
        "paths": ("name", "path", "exists", "kind"),
        "data-files": ("name", "kind", "size_bytes", "modified_at"),
        "environment": ("name", "set", "value", "purpose"),
        "runtime": ("component", "version"),
    }
    assert report_system.GROUP == "system"
    assert list(report_system.DESCRIPTIONS) == NAMES
    assert all(text.endswith(".") for text in report_system.DESCRIPTIONS.values())


@pytest.mark.parametrize("name", NAMES)
def test_rows_follow_the_schema_as_plain_json_without_network_or_writes(name, app, fake, tmp_path):
    store = app.store
    changes = store._conn.total_changes
    entries = sorted(os.listdir(tmp_path))
    rows = load_source(name, app)
    assert rows
    assert all(tuple(row) == SOURCES[name] for row in rows)
    assert all(value is None or type(value) in (str, int, bool) for row in rows for value in row.values())
    assert json.loads(json.dumps(rows, allow_nan=False)) == rows
    assert _json(load_source(name, app)) == _json(rows)  # the same answer, in the same order, every time
    assert fake.calls == []
    assert store._conn.total_changes == changes
    assert sorted(os.listdir(tmp_path)) == entries


def test_schema_lists_every_table_and_column_in_order(app):
    rows = load_source("schema", app)
    assert {"accounts", "meta", "transactions"} <= set(BASELINE_TABLES)  # the engine's statements were found
    tables = list(dict.fromkeys(row["table"] for row in rows))
    assert tables == sorted(tables)
    assert set(BASELINE_TABLES) <= set(tables)
    for table in tables:
        positions = [row["position"] for row in rows if row["table"] == table]
        assert positions == list(range(1, len(positions) + 1))
    assert [(row["table"], row["position"]) for row in rows] == sorted((row["table"], row["position"]) for row in rows)
    assert [row["column"] for row in rows if row["table"] == "transactions"] == [
        "id",
        "account_id",
        "date",
        "type",
        "symbol",
        "quantity",
        "price",
        "amount",
        "fees",
        "currency",
        "note",
        "ratio",
        "target_account_id",
    ]


@pytest.mark.parametrize("expected", BASELINE_COLUMNS, ids=[f"{column[0]}.{column[2]}" for column in BASELINE_COLUMNS])
def test_schema_describes_baseline_columns(expected, app):
    fields = ("table", "position", "column", "type", "required", "default", "primary_key")
    table, _, column, *_ = expected
    found = [row for row in load_source("schema", app) if (row["table"], row["column"]) == (table, column)]
    assert _json(found) == _json([dict(zip(fields, expected, strict=True))])


def test_schema_reads_no_table_row_and_cannot_write(app, tmp_path, monkeypatch):
    store = app.store
    account = store.add_account(Account("Fictional Schema Account", institution="Fictional Credit Union"))
    store.add_transaction(
        Transaction(account.saved_id, TxnType.BUY, "2024-01-02", "FICSCHEMA.TO", 3, 12.34, note="fictional schema note")
    )
    connect = sqlite3.connect
    opened = []
    reads = []

    def authorizer(action, first, second, database, source):
        if action == sqlite3.SQLITE_READ:
            reads.append(first)
        return sqlite3.SQLITE_OK

    def recording_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.set_authorizer(authorizer)
        opened.append((args, kwargs, connection))
        return connection

    changes = store._conn.total_changes
    version = store._conn.execute("PRAGMA data_version").fetchone()[0]
    entries = sorted(os.listdir(tmp_path))
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", recording_connect)
        rows = load_source("schema", app)

    text = _json(rows)
    for saved in ("Fictional Schema Account", "Fictional Credit Union", "FICSCHEMA.TO", "fictional schema note"):
        assert saved not in text
    assert "12.34" not in text and "2024-01-02" not in text
    # Only SQLite's own catalog was read: no column of any ledger table.
    assert reads and all(table.startswith("sqlite_") for table in reads)
    # Nothing changed through the store, through any other connection, or on disk.
    assert store._conn.total_changes == changes
    assert store._conn.execute("PRAGMA data_version").fetchone()[0] == version
    assert sorted(os.listdir(tmp_path)) == entries
    assert len(store.transactions()) == 1
    # One connection was opened, it is closed, and one opened the same way refuses to write.
    assert len(opened) == 1
    args, kwargs, connection = opened[0]
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    with closing(connect(*args, **kwargs)) as again:
        assert again.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1  # the same database
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            again.execute("CREATE TABLE fictional_write (value)")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            again.execute("DELETE FROM accounts")
    assert store.get_account("Fictional Schema Account") is not None


def test_schema_quotes_unusual_table_names_and_hides_sqlite_tables(app):
    store = app.store
    odd = 'fictional "odd"; table'
    store._exec(
        'CREATE TABLE "fictional ""odd""; table" '
        "(code TEXT NOT NULL, serial INTEGER NOT NULL DEFAULT 7, untyped, PRIMARY KEY (code, serial))"
    )
    store._exec("CREATE TABLE fictional_counter (id INTEGER PRIMARY KEY AUTOINCREMENT)")
    saved = {row["name"] for row in store._query("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "sqlite_sequence" in saved  # AUTOINCREMENT made an internal table, so hiding it is really tested

    rows = load_source("schema", app)

    assert {row["table"] for row in rows} == saved - {"sqlite_sequence"}
    assert not any(row["table"].startswith("sqlite_") for row in rows)
    assert _json([row for row in rows if row["table"] == odd]) == _json(
        [
            {
                "table": odd,
                "position": 1,
                "column": "code",
                "type": "TEXT",
                "required": True,
                "default": None,
                "primary_key": True,
            },
            {
                "table": odd,
                "position": 2,
                "column": "serial",
                "type": "INTEGER",
                "required": True,
                "default": "7",
                "primary_key": True,
            },
            {
                "table": odd,
                "position": 3,
                "column": "untyped",
                "type": "",
                "required": False,
                "default": None,
                "primary_key": False,
            },
        ]
    )
    tables = list(dict.fromkeys(row["table"] for row in rows))
    assert tables == sorted(tables)


def test_paths_name_the_locations_in_use(app, tmp_path):
    root = tmp_path.resolve()
    rows = load_source("paths", app)
    assert _json(rows) == _json(
        [
            {"name": "data", "path": str(root), "exists": True, "kind": "directory"},
            {"name": "database", "path": str(root / "test.db"), "exists": True, "kind": "file"},
            {"name": "backups", "path": str(root / "backups"), "exists": False, "kind": "missing"},
            {"name": "config", "path": str(root / "config.toml"), "exists": False, "kind": "missing"},
        ]
    )
    assert all(Path(row["path"]).is_absolute() for row in rows)
    assert all(root == Path(row["path"]) or root in Path(row["path"]).parents for row in rows)

    (tmp_path / "backups").mkdir()
    (tmp_path / "config.toml").write_text('theme = "tokyo-night"\n', encoding="utf-8")
    assert [(row["name"], row["exists"], row["kind"]) for row in load_source("paths", app)] == [
        ("data", True, "directory"),
        ("database", True, "file"),
        ("backups", True, "directory"),
        ("config", True, "file"),
    ]


def test_paths_report_a_relative_override_as_an_absolute_path(app, tmp_path, monkeypatch):
    (tmp_path / "fictional-settings").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MARKETPULSE_CONFIG", "fictional-settings")
    assert _json(load_source("paths", app)[3]) == _json(
        {"name": "config", "path": str(tmp_path.resolve() / "fictional-settings"), "exists": True, "kind": "directory"}
    )


@needs_symlinks
def test_paths_follow_links_and_survive_broken_ones(app, tmp_path, monkeypatch):
    root = tmp_path.resolve()
    target = tmp_path / "fictional-settings.toml"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "linked.toml"
    link.symlink_to(target)
    monkeypatch.setenv("MARKETPULSE_CONFIG", str(link))
    resolved = str(root / "fictional-settings.toml")
    assert _json(load_source("paths", app)[3]) == _json(
        {"name": "config", "path": resolved, "exists": True, "kind": "file"}
    )
    target.unlink()  # the link now points at nothing
    assert _json(load_source("paths", app)[3]) == _json(
        {"name": "config", "path": resolved, "exists": False, "kind": "missing"}
    )
    loop = tmp_path / "loop.toml"
    loop.symlink_to(loop)  # Path.resolve() raises on this before Python 3.13
    monkeypatch.setenv("MARKETPULSE_CONFIG", str(loop))
    assert _json(load_source("paths", app)[3]) == _json(
        {"name": "config", "path": str(root / "loop.toml"), "exists": False, "kind": "missing"}
    )


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs a named pipe")
def test_paths_and_data_files_call_anything_else_other(app, tmp_path, monkeypatch):
    pipe = tmp_path / "fictional-pipe"
    os.mkfifo(pipe)
    monkeypatch.setenv("MARKETPULSE_CONFIG", str(pipe))
    assert _json(load_source("paths", app)[3]) == _json(
        {"name": "config", "path": str(tmp_path.resolve() / "fictional-pipe"), "exists": True, "kind": "other"}
    )
    row = next(row for row in load_source("data-files", app) if row["name"] == "fictional-pipe")
    assert (row["kind"], row["size_bytes"]) == ("other", None)


def test_data_files_list_direct_entries_sorted_by_name(app, tmp_path):
    statements = tmp_path / "Fictional-Statements"
    statements.mkdir()
    (statements / "nested.csv").write_text("never listed", encoding="utf-8")
    (tmp_path / "fictional-empty.txt").write_bytes(b"")
    notes = tmp_path / "fictional-notes.txt"
    notes.write_bytes(b"fictional ledger notes\n")
    os.utime(notes, (1_700_000_000, 1_700_000_000))

    rows = load_source("data-files", app)

    names = [row["name"] for row in rows]
    assert names == sorted(names)
    assert set(names) == set(os.listdir(tmp_path))
    assert "nested.csv" not in names
    # Code-point order, the same under every locale and file system: a capital sorts before lower case.
    assert [name for name in names if name.casefold().startswith("fictional")] == [
        "Fictional-Statements",
        "fictional-empty.txt",
        "fictional-notes.txt",
    ]
    found = {row["name"]: row for row in rows}
    assert _json(found["fictional-notes.txt"]) == _json(
        {"name": "fictional-notes.txt", "kind": "file", "size_bytes": 23, "modified_at": "2023-11-14T22:13:20+00:00"}
    )
    assert _json({key: found["fictional-empty.txt"][key] for key in ("kind", "size_bytes")}) == _json(
        {"kind": "file", "size_bytes": 0}
    )
    assert _json({key: found["Fictional-Statements"][key] for key in ("kind", "size_bytes")}) == _json(
        {"kind": "directory", "size_bytes": None}
    )
    assert (found["test.db"]["kind"], found["test.db"]["size_bytes"]) == ("file", (tmp_path / "test.db").stat().st_size)
    assert all(UTC_SECONDS.fullmatch(row["modified_at"]) for row in rows)


@needs_symlinks
def test_data_files_never_follow_links(app, tmp_path):
    notes = tmp_path / "fictional-notes.txt"
    notes.write_bytes(b"fictional ledger notes\n")
    folder = tmp_path / "fictional-folder"
    folder.mkdir()
    (tmp_path / "link-to-file").symlink_to(notes)
    (tmp_path / "link-to-folder").symlink_to(folder, target_is_directory=True)
    (tmp_path / "link-to-nothing").symlink_to(tmp_path / "fictional-missing")

    found = {row["name"]: row for row in load_source("data-files", app)}

    for name in ("link-to-file", "link-to-folder", "link-to-nothing"):
        assert (found[name]["kind"], found[name]["size_bytes"]) == ("other", None)
        assert UTC_SECONDS.fullmatch(found[name]["modified_at"])
    assert (found["fictional-notes.txt"]["kind"], found["fictional-notes.txt"]["size_bytes"]) == ("file", 23)
    assert found["fictional-folder"]["kind"] == "directory"


def test_data_files_skip_an_entry_that_disappears_while_listing(app, tmp_path, monkeypatch):
    listdir = os.listdir
    with monkeypatch.context() as patch:
        # As when SQLite removes a -wal file between the listing and the look at each entry.
        patch.setattr(os, "listdir", lambda path: [*listdir(path), "fictional-gone.db-wal"])
        rows = load_source("data-files", app)
    assert rows
    assert {row["name"] for row in rows} == set(listdir(tmp_path))


@pytest.mark.parametrize(
    ("nanoseconds", "expected"),
    [
        (0, "1970-01-01T00:00:00+00:00"),
        (1_700_000_000_000_000_000, "2023-11-14T22:13:20+00:00"),
        (1_700_000_000_999_999_999, "2023-11-14T22:13:20+00:00"),  # truncated, never rounded up
        (-1, "1969-12-31T23:59:59+00:00"),  # before 1970, which the C library on Windows refuses
        (-11_644_473_600 * 10**9, "1601-01-01T00:00:00+00:00"),  # the zero Windows file time
        (10**21, None),  # about the year 33658: no datetime can hold it
        (-(10**21), None),
        (10**40, None),
    ],
)
def test_file_times_are_whole_utc_seconds_on_every_platform(nanoseconds, expected):
    assert report_system._utc_seconds(nanoseconds) == expected


@pytest.mark.parametrize("variable", VARIABLES)
@pytest.mark.parametrize(("state", "is_set"), [("set", True), ("empty", False), ("unset", False)])
def test_environment_reports_each_override(detached, tmp_path, monkeypatch, variable, state, is_set):
    values = {name: str(tmp_path / f"fictional {name.lower()}") for name in VARIABLES}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    if state == "empty":
        monkeypatch.setenv(variable, "")
    elif state == "unset":
        monkeypatch.delenv(variable)

    expected = [{"name": name, "set": True, "value": values[name]} for name in VARIABLES]
    if not is_set:
        expected[VARIABLES.index(variable)] = {"name": variable, "set": False, "value": None}

    rows = load_source("environment", detached)

    assert _json([{key: row[key] for key in ("name", "set", "value")} for row in rows]) == _json(expected)
    for row in rows:
        purpose = row["purpose"]
        assert len(purpose) > 20 and purpose == purpose.strip() and purpose.endswith(".") and "\n" not in purpose
    # Reading the environment neither opens nor creates a data directory, even with the override gone.
    assert not (tmp_path / "fictional-home").exists()
    assert not any(Path(value).exists() for value in values.values())


def test_environment_lists_no_other_variable(detached, monkeypatch):
    monkeypatch.setenv("MARKETPULSE_FICTIONAL_TOKEN", "fictional-secret-that-must-not-appear")
    monkeypatch.setenv("MARKETPULSE_DATA_EXTRA", "fictional-extra-that-must-not-appear")
    rows = load_source("environment", detached)
    assert [row["name"] for row in rows] == VARIABLES
    assert "must-not-appear" not in _json(rows)


def test_runtime_reports_versions_in_order(detached):
    rows = load_source("runtime", detached)
    assert [row["component"] for row in rows] == COMPONENTS
    versions = {row["component"]: row["version"] for row in rows}
    assert versions["marketpulse"] == marketpulse.__version__
    assert versions["python"] == platform.python_version()
    assert versions["python"].startswith(f"{sys.version_info.major}.{sys.version_info.minor}.")
    assert versions["implementation"] == platform.python_implementation()
    assert versions["platform"] == sys.platform
    assert versions["sqlite"] == sqlite3.sqlite_version
    # The dependencies are installed wherever the tests run, so each has a dotted version number;
    # tzdata only where the project declares it, on Windows.
    for distribution in COMPONENTS[5:]:
        if distribution == "tzdata" and sys.platform != "win32" and versions[distribution] is None:
            continue
        assert re.match(r"\d+\.\d+", versions[distribution]), distribution


def test_runtime_reports_null_for_a_distribution_that_is_not_installed(detached, monkeypatch):
    version = metadata.version

    def without_textual(name):
        if name == "textual":
            raise metadata.PackageNotFoundError(name)
        return version(name)

    monkeypatch.setattr(metadata, "version", without_textual)
    rows = load_source("runtime", detached)
    assert [row["component"] for row in rows] == COMPONENTS
    assert [row["component"] for row in rows if row["version"] is None and row["component"] != "tzdata"] == ["textual"]
    assert _json(rows[7]) == '{"component": "textual", "version": null}'


def test_unknown_source_is_rejected_before_opening_the_tracker(detached):
    with pytest.raises(KeyError, match="nope"):
        load_source("nope", detached)


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))

    def invoke(*args: str):
        result = CliRunner().invoke(main, list(args))
        assert result.exit_code == 0, result.output
        return result.output

    return invoke


def test_report_command_filters_projects_and_exports_schema(cli, fake):
    output = cli("report", "schema", "--where", "table=accounts", "--fields", "column,type", "--format", "csv")
    assert list(csv.reader(io.StringIO(output))) == [
        ["column", "type"],
        ["id", "INTEGER"],
        ["name", "TEXT"],
        ["type", "TEXT"],
        ["currency", "TEXT"],
        ["institution", "TEXT"],
        ["track_cash", "INTEGER"],
        ["archived", "INTEGER"],
        ["created_at", "TEXT"],
    ]
    output = cli("report", "schema", "--where", "primary_key=true", "--prefix", "table=a", "--fields", "table,column")
    assert json.loads(output) == [
        {"table": "accounts", "column": "id"},
        {"table": "alerts", "column": "id"},
        {"table": "assets", "column": "symbol"},
    ]
    assert fake.calls == []


def test_summarize_command_groups_schema_columns(cli, fake):
    output = cli("summarize", "schema", "--group-by", "table", "--metric", "columns=count")
    summary = json.loads(output)
    assert [row["table"] for row in summary] == sorted(row["table"] for row in summary)
    for expected in (
        {"table": "accounts", "columns": 8},
        {"table": "meta", "columns": 2},
        {"table": "transactions", "columns": 13},
    ):
        assert expected in summary
    output = cli(
        "summarize",
        "schema",
        "--where",
        "table=accounts",
        "--metric",
        "required=true-count:required",
        "--metric",
        "keys=true-count:primary_key",
        "--metric",
        "defaults=present:default",
    )
    assert _json(json.loads(output)) == _json([{"required": 7, "keys": 1, "defaults": 3}])
    assert fake.calls == []


def test_commands_report_files_in_the_data_directory(cli, tmp_path):
    (tmp_path / "fictional-notes.txt").write_bytes(b"fictional ledger notes\n")
    (tmp_path / "fictional-plan.txt").write_bytes(b"plan\n")
    (tmp_path / "fictional-exports").mkdir()
    output = cli("report", "data-files", "--where", "name=fictional-notes.txt", "--fields", "name,kind,size_bytes")
    assert _json(json.loads(output)) == _json([{"name": "fictional-notes.txt", "kind": "file", "size_bytes": 23}])
    output = cli(
        "summarize",
        "data-files",
        "--glob",
        "name=fictional-*",
        "--group-by",
        "kind",
        "--metric",
        "entries=count",
        "--metric",
        "bytes=number-sum:size_bytes",
    )
    assert _json(json.loads(output)) == _json(
        [{"kind": "directory", "entries": 1, "bytes": "0"}, {"kind": "file", "entries": 2, "bytes": "28"}]
    )
    output = cli("report", "paths", "--where", "kind=missing", "--fields", "name")
    assert json.loads(output) == [{"name": "backups"}, {"name": "config"}]


def test_commands_read_environment_and_runtime_without_the_tracker(detached, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "fictional xdg"))
    result = CliRunner().invoke(
        main, ["report", "environment", "--where", "name=XDG_CONFIG_HOME", "--fields", "set,value"]
    )
    assert result.exit_code == 0, result.output
    assert _json(json.loads(result.output)) == _json([{"set": True, "value": str(tmp_path / "fictional xdg")}])
    result = CliRunner().invoke(
        # tzdata is left out: it is installed on Windows only.
        main,
        [
            "summarize",
            "runtime",
            "--ine",
            "component=tzdata",
            "--metric",
            "components=count",
            "--metric",
            "known=present:version",
        ],
    )
    assert result.exit_code == 0, result.output
    assert _json(json.loads(result.output)) == _json([{"components": 9, "known": 9}])
    result = CliRunner().invoke(main, ["report", "runtime", "--where", "component=marketpulse", "--format", "jsonl"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"component": "marketpulse", "version": marketpulse.__version__}


def test_default_startup_reports_the_data_directory_in_use(tmp_path):
    """No fixture tracker: the command opens the data directory named by MARKETPULSE_DATA, as an installation does."""
    root = tmp_path.resolve()
    app = App()
    try:
        result = CliRunner().invoke(main, ["report", "paths"], obj=app, catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert _json(json.loads(result.output)) == _json(
            [
                {"name": "data", "path": str(root / "data"), "exists": True, "kind": "directory"},
                {"name": "database", "path": str(root / "data" / "marketpulse.db"), "exists": True, "kind": "file"},
                {"name": "backups", "path": str(root / "data" / "backups"), "exists": False, "kind": "missing"},
                {"name": "config", "path": str(root / "config.toml"), "exists": False, "kind": "missing"},
            ]
        )
        result = CliRunner().invoke(
            main, ["report", "data-files", "--where", "name=marketpulse.db", "--fields", "name,kind"], obj=app
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == [{"name": "marketpulse.db", "kind": "file"}]
        result = CliRunner().invoke(main, ["report", "schema", "--unique", "table", "--fields", "table"], obj=app)
        assert result.exit_code == 0, result.output
        assert set(BASELINE_TABLES) <= {row["table"] for row in json.loads(result.output)}
        result = CliRunner().invoke(
            main, ["report", "environment", "--where", "name=MARKETPULSE_DATA", "--fields", "value"], obj=app
        )
        assert json.loads(result.output) == [{"value": str(tmp_path / "data")}]
    finally:
        if app._tracker is not None:
            app._tracker.store.close()
