"""Backup inventory selections, summaries and multi-file verification on fictional backups."""

import csv
import io
import json
from hashlib import sha256

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account

# Fictional backup names (newest first) and sizes in bytes. List commands never open these files.
FILES = {
    "marketpulse-20240301-130000-manual-2.db": 1536,
    "marketpulse-20240301-120000-pre-restore.db": 5120,
    "marketpulse-20240102-180000-daily.db": 3072,
    "marketpulse-20240102-120000-import.db": 4096,
    "marketpulse-20240101-120000-manual.db": 2048,
    "marketpulse-20230615-090000-daily.db": 1024,
}
NEWEST_FIRST = list(FILES)


def _state(directory):
    # Backup files only: opening a WAL database read-only may leave SQLite's -shm/-wal sidecars.
    return {p.name: sha256(p.read_bytes()).digest() for p in sorted(directory.glob("*.db"))}


@pytest.fixture
def inventory(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    store.backup_dir.mkdir(exist_ok=True)
    for name, size in FILES.items():
        (store.backup_dir / name).write_bytes(b"\0" * size)
    fake.offline = True
    before = _state(store.backup_dir)

    def invoke(*args):
        result = CliRunner().invoke(main, ["backup", "list", *args], catch_exceptions=False)
        assert fake.calls == []
        assert _state(store.backup_dir) == before
        return result

    return invoke


def names(inventory, *args):
    result = inventory(*args, "--json")
    assert result.exit_code == 0, result.output
    return [item["file"] for item in json.loads(result.output)]


def test_count_matches_filters(inventory):
    assert inventory("--count").output.strip() == "6"
    assert inventory("--count", "--reason", "manual").output.strip() == "2"
    assert inventory("--count", "--search", "nothing").output.strip() == "0"


def test_csv_rows_and_empty_header(inventory, store):
    result = inventory("--csv", "--reason", "import")
    assert result.exit_code == 0
    rows = list(csv.DictReader(io.StringIO(result.output)))
    assert rows == [
        {
            "file": "marketpulse-20240102-120000-import.db",
            "path": str((store.backup_dir / "marketpulse-20240102-120000-import.db").resolve()),
            "reason": "import",
            "size_bytes": "4096",
            "taken_at": "2024-01-02T12:00:00",
        }
    ]
    assert inventory("--csv", "--search", "nothing").output == "file,path,reason,size_bytes,taken_at\n"


def test_page_info_envelope(inventory):
    page = json.loads(inventory("--json", "--page-info", "--limit", "2", "--offset", "1").output)
    assert {k: v for k, v in page.items() if k != "items"} == {
        "total": 6,
        "offset": 1,
        "limit": 2,
        "returned": 2,
        "next_offset": 3,
    }
    assert [item["file"] for item in page["items"]] == NEWEST_FIRST[1:3]
    last = json.loads(inventory("--json", "--page-info", "--offset", "4").output)
    assert last["returned"] == 2 and last["next_offset"] is None and last["limit"] is None


def test_repeatable_reason_is_backwards_compatible(inventory):
    assert names(inventory, "--reason", "MANUAL") == [NEWEST_FIRST[0], NEWEST_FIRST[4]]
    assert names(inventory, "--reason", "manual", "--reason", " Import ") == [
        NEWEST_FIRST[0],
        NEWEST_FIRST[3],
        NEWEST_FIRST[4],
    ]


def test_repeatable_exclude_reason(inventory):
    kept = names(inventory, "--exclude-reason", "DAILY", "--exclude-reason", " pre-restore ")
    assert kept == [NEWEST_FIRST[0], NEWEST_FIRST[3], NEWEST_FIRST[4]]
    assert names(inventory, "--reason", "daily", "--exclude-reason", "daily") == []


def test_size_bounds_in_kb_are_inclusive(inventory):
    assert names(inventory, "--min-size", "2", "--max-size", "4") == [NEWEST_FIRST[2], NEWEST_FIRST[3], NEWEST_FIRST[4]]
    assert names(inventory, "--max-size", "1.5") == [NEWEST_FIRST[0], NEWEST_FIRST[5]]
    assert names(inventory, "--min-size", "5") == [NEWEST_FIRST[1]]


def test_sort_and_descending(inventory):
    by_size = names(inventory, "--sort", "size")
    assert [FILES[name] for name in by_size] == sorted(FILES.values())
    assert names(inventory, "--sort", "size", "--descending") == by_size[::-1]
    assert names(inventory, "--sort", "date") == NEWEST_FIRST[::-1]
    assert names(inventory, "--descending") == NEWEST_FIRST
    assert names(inventory, "--sort", "name") == sorted(FILES)
    assert names(inventory, "--sort", "reason") == [
        NEWEST_FIRST[5],
        NEWEST_FIRST[2],
        NEWEST_FIRST[3],
        NEWEST_FIRST[4],
        NEWEST_FIRST[0],
        NEWEST_FIRST[1],
    ]
    paged = names(inventory, "--sort", "size", "--reason", "daily", "--limit", "1")
    assert paged == [NEWEST_FIRST[5]]


def test_calendar_selections(inventory):
    assert names(inventory, "--year", "2023") == [NEWEST_FIRST[5]]
    january = names(inventory, "--year", "2024", "--month", "2024-01")
    assert january == [NEWEST_FIRST[2], NEWEST_FIRST[3], NEWEST_FIRST[4]]
    on = names(inventory, "--on", "2024-01-02", "--on", "2023-06-15", "--on", "2024-01-02")
    assert on == [NEWEST_FIRST[2], NEWEST_FIRST[3], NEWEST_FIRST[5]]
    assert names(inventory, "--month", "2024-03", "--on", "2024-01-02") == []


def test_latest_and_earliest_single_record(inventory):
    latest = json.loads(inventory("--latest", "--json").output)
    assert latest["file"] == NEWEST_FIRST[0]
    earliest = json.loads(inventory("--earliest", "--reason", "manual", "--json").output)
    assert earliest["file"] == NEWEST_FIRST[4]
    rows = list(csv.DictReader(io.StringIO(inventory("--earliest", "--csv").output)))
    assert [row["file"] for row in rows] == [NEWEST_FIRST[5]]
    human = inventory("--latest", "--reason", "daily")
    assert human.exit_code == 0 and "daily" in human.output
    missing = inventory("--latest", "--since", "2030-01-01", "--json")
    assert missing.exit_code == 1 and "No matching backups" in missing.output


@pytest.mark.parametrize(
    "group,expected",
    [
        ("reason", [("daily", 2), ("import", 1), ("manual", 2), ("pre-restore", 1)]),
        ("year", [("2023", 1), ("2024", 5)]),
        ("month", [("2023-06", 1), ("2024-01", 3), ("2024-03", 2)]),
    ],
)
def test_summary_groups(inventory, group, expected):
    rows = json.loads(inventory("--summary", group, "--json").output)
    assert [(row["group"], row["count"]) for row in rows] == expected


def test_summary_csv_human_and_empty(inventory):
    result = inventory("--summary", "reason", "--exclude-reason", "daily", "--csv")
    assert list(csv.DictReader(io.StringIO(result.output))) == [
        {"group": "import", "count": "1"},
        {"group": "manual", "count": "2"},
        {"group": "pre-restore", "count": "1"},
    ]
    human = inventory("--summary", "month")
    assert human.exit_code == 0 and "2024-03" in human.output
    assert json.loads(inventory("--summary", "year", "--since", "2030-01-01", "--json").output) == []
    assert inventory("--summary", "year", "--since", "2030-01-01", "--csv").output == "group,count\n"


def test_untimestamped_backup_summary(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    store.backup_dir.mkdir(exist_ok=True)
    (store.backup_dir / "marketpulse-20240101-120000-manual.db").write_bytes(b"\0" * 10)
    (store.backup_dir / "marketpulse-legacy.db").write_bytes(b"\0" * 10)

    def run(*args):
        return CliRunner().invoke(main, ["backup", "list", *args], catch_exceptions=False)

    summary = json.loads(run("--summary", "year", "--json").output)
    assert summary == [{"group": "2024", "count": 1}, {"group": "unknown", "count": 1}]
    assert run("--year", "2024", "--count").output.strip() == "1"
    assert run("--on", "2024-01-01", "--count").output.strip() == "1"
    assert fake.calls == []


@pytest.mark.parametrize(
    "args",
    [
        ["--json", "--csv"],
        ["--page-info"],
        ["--page-info", "--csv"],
        ["--reason", " "],
        ["--exclude-reason", ""],
        ["--min-size", "-1"],
        ["--min-size", "nan"],
        ["--max-size", "inf"],
        ["--min-size", "4", "--max-size", "2"],
        ["--sort", "bogus"],
        ["--oldest-first", "--sort", "size"],
        ["--oldest-first", "--descending"],
        ["--year", "2023", "--month", "2024-01"],
        ["--month", "2024-13"],
        ["--month", "2024-1"],
        ["--on", "2024-02-30"],
        ["--year", "0"],
        ["--latest", "--earliest"],
        ["--latest", "--count"],
        ["--latest", "--limit", "1"],
        ["--latest", "--offset", "0"],
        ["--earliest", "--sort", "date"],
        ["--earliest", "--oldest-first"],
        ["--count", "--json"],
        ["--count", "--csv"],
        ["--count", "--limit", "1"],
        ["--count", "--sort", "size"],
        ["--summary", "reason", "--count"],
        ["--summary", "reason", "--latest"],
        ["--summary", "reason", "--earliest"],
        ["--summary", "reason", "--limit", "1"],
        ["--summary", "reason", "--offset", "1"],
        ["--summary", "reason", "--sort", "size"],
        ["--summary", "reason", "--descending"],
        ["--summary", "reason", "--oldest-first"],
        ["--summary", "reason", "--json", "--page-info"],
        ["--summary", "bogus"],
    ],
)
def test_invalid_combinations(inventory, args):
    result = inventory(*args)
    assert result.exit_code == 2, result.output


@pytest.fixture
def cli(tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    return lambda *args: CliRunner().invoke(main, list(args), catch_exceptions=False)


@pytest.fixture
def copies(store):
    store.add_account(Account(name="Fictional Maple"))
    store.backup_dir.mkdir(exist_ok=True)
    paths = []
    for day, reason in (("20240101", "manual"), ("20240102", "import"), ("20240103", "pre-restore")):
        dest = store.backup_dir / f"marketpulse-{day}-120000-{reason}.db"
        store.backup(dest=dest)
        paths.append(dest)
    return paths


def test_verify_several_paths(cli, store, copies, tmp_path, fake):
    broken = tmp_path / "fictional-broken.db"
    broken.write_text("fictional invalid backup")
    before = _state(store.backup_dir)
    result = cli("backup", "verify", copies[0].name, str(copies[1]), "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == [
        {"ok": True, "path": str(copies[0].resolve()), "error": None},
        {"ok": True, "path": str(copies[1].resolve()), "error": None},
    ]
    mixed = cli("backup", "verify", str(copies[0]), str(broken), "--json")
    assert mixed.exit_code == 1
    payload = json.loads(mixed.output)
    assert [item["ok"] for item in payload] == [True, False] and payload[1]["error"]
    human = cli("backup", "verify", str(copies[0]), str(broken))
    assert human.exit_code == 1
    assert "Backup verified" in human.output and "fictional-broken.db:" in human.output
    assert _state(store.backup_dir) == before
    assert broken.read_text() == "fictional invalid backup"
    assert fake.calls == []


def test_verify_latest_matches_restore_choice(cli, store, copies, fake):
    before = _state(store.backup_dir)
    result = cli("backup", "verify", "--latest", "--json")
    assert result.exit_code == 0
    # The pre-restore copy is newer but is skipped, as `backup restore --latest` would.
    assert json.loads(result.output) == {"ok": True, "path": str(copies[1].resolve()), "error": None}
    assert "Backup verified: " + copies[1].name in cli("backup", "verify", "--latest").output
    assert _state(store.backup_dir) == before
    assert fake.calls == []


def test_verify_latest_without_backups(cli, store):
    result = cli("backup", "verify", "--latest")
    assert result.exit_code == 1 and "No backups to verify" in result.output


@pytest.mark.parametrize("args", [[], ["--latest", "fictional.db"]])
def test_verify_needs_one_source(cli, args):
    assert cli("backup", "verify", *args).exit_code == 2
