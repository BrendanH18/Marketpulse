"""New offline snapshot and backup exports on entirely fictional saved records."""

import csv
import io
import json
from hashlib import sha256

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.cli.base import App
from marketpulse.db import Snapshot, Store
from marketpulse.models import Account, Transaction, TxnType
from marketpulse.services import Tracker


@pytest.mark.parametrize("recent", [False, True])
def test_unrecognized_backup_names_allow_real_startup_and_inspection(recent):
    seed = Store()
    account = seed.add_account(Account(name="Fictional backup account"))
    seed.add_transaction(
        Transaction(account_id=account.id, type=TxnType.DEPOSIT, date="2024-01-01", amount=100, currency="CAD")
    )
    if recent:
        seed.backup(reason="manual")
    seed.backup_dir.mkdir(exist_ok=True)
    legacy = seed.backup_dir / "marketpulse-legacy.db"
    legacy.write_bytes(b"Fictional unrecognized backup")
    seed.close()

    tracker = Tracker.open()
    try:
        assert len(tracker.store.transactions()) == 1
        daily = [p for p in tracker.store.backups() if Store.backup_reason(p) == "daily"]
        assert len(daily) == (0 if recent else 1)
    finally:
        tracker.store.close()

    app = App()
    try:
        result = CliRunner().invoke(
            main, ["backup", "list", "--no-timestamp", "--json"], obj=app, catch_exceptions=False
        )
        assert result.exit_code == 0
        assert [r["file"] for r in json.loads(result.output)] == [legacy.name]
        assert legacy.read_bytes() == b"Fictional unrecognized backup"
    finally:
        if app._tracker is not None:
            app._tracker.store.close()


@pytest.fixture
def browse(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    snapshots = [
        Snapshot("2023-12-31", 100, 80, 70, "CAD", {}),  # Sunday, month end, unknown change
        Snapshot("2024-01-01", 120, 90, 75, "CAD", {}),  # Monday, month start, increase
        Snapshot("2024-01-02", 120, 90, 75, "CAD", {}),  # Tuesday, unchanged
        Snapshot("2024-02-28", 110, 95, 80, "USD", {}),  # Wednesday, currency switch
        Snapshot("2024-02-29", 100, 90, 75, "USD", {}),  # Thursday, leap month end, decrease
        Snapshot("2024-03-01", 130, 95, 80, "USD", {}),  # Friday, month start, increase
        Snapshot("2024-03-02", 130, 95, 80, "USD", {}),  # Saturday, unchanged
        Snapshot("2024-04-30", 140, 95, 80, "USD", {}),  # Tuesday, month end, increase
    ]
    store.upsert_snapshots(snapshots)
    store.backup_dir.mkdir(exist_ok=True)
    for name, size in [
        ("marketpulse-20240430-120000-manual.db", 100),
        ("marketpulse-20240302-120000-daily.db", 200),
        ("marketpulse-20240301-120000-import.db", 300),
        ("marketpulse-20240229-120000-manual.db", 400),
        ("marketpulse-20240101-120000-daily.db", 500),
        ("marketpulse-20231231-120000-manual.db", 600),
        ("marketpulse-legacy.db", 700),
    ]:
        (store.backup_dir / name).write_bytes(b"x" * size)
    fake.offline = True

    def state():
        return {p.name: sha256(p.read_bytes()).digest() for p in store.backup_dir.iterdir()}

    before = state()

    def invoke(*args):
        result = CliRunner().invoke(main, list(args), catch_exceptions=False)
        assert fake.calls == []
        assert store.snapshots() == snapshots
        assert state() == before
        return result

    return invoke


def snapshot_dates(browse, *args):
    result = browse("snapshots", *args, "--dates")
    assert result.exit_code == 0, result.output
    return result.output.splitlines()


def backup_rows(browse, *args):
    result = browse("backup", "list", *args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_snapshot_jsonl_dates_and_field_projection(browse):
    result = browse("snapshots", "--jsonl", "--on", "2024-02-29", "--fields", "change,date")
    assert result.exit_code == 0
    assert result.output == '{"change": -10.0, "date": "2024-02-29"}\n'
    assert snapshot_dates(browse, "--month", "2024-02") == ["2024-02-28", "2024-02-29"]
    result = browse("snapshots", "--json", "--earliest", "--fields", "currency,date,change")
    assert list(json.loads(result.output)) == ["currency", "date", "change"]
    assert json.loads(result.output)["change"] is None
    result = browse("snapshots", "--csv", "--on", "2023-12-31", "--fields", "change,date")
    assert list(csv.DictReader(io.StringIO(result.output))) == [{"change": "", "date": "2023-12-31"}]
    empty = browse("snapshots", "--csv", "--since", "2030-01-01", "--fields", "date,currency")
    assert list(csv.reader(io.StringIO(empty.output))) == [["date", "currency"]]
    assert browse("snapshots", "--jsonl", "--since", "2030-01-01").output == ""


def test_snapshot_weekday_filters_and_calendar_edges(browse):
    assert snapshot_dates(browse, "--exclude-weekday", "TUE", "--exclude-weekday", "thu") == [
        "2023-12-31",
        "2024-01-01",
        "2024-02-28",
        "2024-03-01",
        "2024-03-02",
    ]
    assert snapshot_dates(browse, "--weekdays-only") == [
        "2024-01-01",
        "2024-01-02",
        "2024-02-28",
        "2024-02-29",
        "2024-03-01",
        "2024-04-30",
    ]
    assert snapshot_dates(browse, "--weekends-only") == ["2023-12-31", "2024-03-02"]
    assert snapshot_dates(browse, "--month-start-only") == ["2024-01-01", "2024-03-01"]
    assert snapshot_dates(browse, "--month-end-only") == ["2023-12-31", "2024-02-29", "2024-04-30"]
    assert snapshot_dates(browse, "--month-end-only", "--weekdays-only", "--exclude-weekday", "tue") == ["2024-02-29"]


def test_snapshot_summaries_preserve_baseline_and_privacy(browse, tracker):
    result = browse("snapshots", "--summary", "weekday", "--json")
    assert {r["group"]: r["count"] for r in json.loads(result.output)} == {
        "sun": 1,
        "mon": 1,
        "tue": 2,
        "wed": 1,
        "thu": 1,
        "fri": 1,
        "sat": 1,
    }
    result = browse("snapshots", "--summary", "change-direction", "--json")
    assert json.loads(result.output) == [
        {"group": "decrease", "count": 1},
        {"group": "increase", "count": 3},
        {"group": "unchanged", "count": 2},
        {"group": "unknown", "count": 2},
    ]
    result = browse("snapshots", "--summary", "change-direction", "--on", "2024-02-29", "--csv")
    assert list(csv.DictReader(io.StringIO(result.output))) == [{"group": "decrease", "count": "1"}]
    tracker.config.privacy = True
    human = browse("snapshots", "--weekdays-only")
    assert human.exit_code == 0 and "120.00" not in human.output
    raw = browse("snapshots", "--jsonl", "--on", "2024-01-01")
    assert json.loads(raw.output)["net_worth"] == 120
    assert "increase" in browse("snapshots", "--summary", "change-direction").output


def test_snapshot_projection_page_and_single_selection(browse):
    result = browse("snapshots", "--weekdays-only", "--json", "--page-info", "--limit", "2", "--fields", "date")
    page = json.loads(result.output)
    assert page["total"] == 6 and page["rows"] == [{"date": "2024-01-01"}, {"date": "2024-01-02"}]
    assert snapshot_dates(browse, "--weekends-only", "--latest") == ["2024-03-02"]
    assert snapshot_dates(
        browse, "--weekdays-only", "--sort", "date", "--descending", "--offset", "1", "--limit", "1"
    ) == ["2024-03-01"]


@pytest.mark.parametrize(
    "args",
    [
        ["--fields", "date"],
        ["--json", "--fields", "nope"],
        ["--csv", "--fields", "date,date"],
        ["--json", "--fields", ""],
        ["--jsonl", "--json"],
        ["--dates", "--csv"],
        ["--dates", "--count"],
        ["--jsonl", "--page-info"],
        ["--summary", "weekday", "--jsonl"],
        ["--summary", "weekday", "--json", "--fields", "date"],
        ["--summary", "weekday", "--dates"],
        ["--weekdays-only", "--weekends-only"],
        ["--month-start-only", "--month-end-only"],
        ["--exclude-weekday", "noday"],
    ],
)
def test_snapshot_new_usage_errors(browse, args):
    assert browse("snapshots", *args).exit_code == 2


def test_backup_jsonl_paths_and_projection(browse, store):
    result = browse("backup", "list", "--jsonl", "--fields", "reason,file", "--month", "2024-02")
    assert result.exit_code == 0
    assert json.loads(result.output) == {"reason": "manual", "file": "marketpulse-20240229-120000-manual.db"}
    assert list(json.loads(result.output)) == ["reason", "file"]
    result = browse("backup", "list", "--paths", "--month", "2024-02")
    assert result.output == str((store.backup_dir / "marketpulse-20240229-120000-manual.db").resolve()) + "\n"
    result = browse("backup", "list", "--csv", "--fields", "file,size_bytes", "--month", "2024-02")
    assert list(csv.DictReader(io.StringIO(result.output))) == [
        {"file": "marketpulse-20240229-120000-manual.db", "size_bytes": "400"}
    ]
    result = browse("backup", "list", "--json", "--page-info", "--fields", "file", "--has-timestamp", "--limit", "2")
    page = json.loads(result.output)
    assert page["total"] == 6 and len(page["items"]) == 2 and list(page["items"][0]) == ["file"]
    assert browse("backup", "list", "--paths", "--since", "2030-01-01").output == ""
    assert browse("backup", "list", "--jsonl", "--since", "2030-01-01").output == ""


def test_backup_filename_and_date_exclusions(browse):
    rows = backup_rows(
        browse, "--exclude-file", "MARKETPULSE-LEGACY.DB", "--exclude-file", "marketpulse-20240101-120000-daily.db"
    )
    assert len(rows) == 5 and all(r["file"] != "marketpulse-legacy.db" for r in rows)
    rows = backup_rows(browse, "--exclude-date", "2024-03-02", "--exclude-date", "2024-03-01")
    assert len(rows) == 5 and any(r["taken_at"] is None for r in rows)
    rows = backup_rows(browse, "--filename-prefix", "MARKETPULSE-202403")
    assert len(rows) == 2 and all("202403" in r["file"] for r in rows)
    rows = backup_rows(browse, "--filename-suffix", "-MANUAL.DB")
    assert len(rows) == 3 and all(r["reason"] == "manual" for r in rows)


def test_backup_weekday_quarter_and_timestamp_filters(browse):
    rows = backup_rows(browse, "--weekday", "MON", "--weekday", "thu")
    assert {r["taken_at"][:10] for r in rows} == {"2024-01-01", "2024-02-29"}
    rows = backup_rows(browse, "--quarter", "2024-Q1")
    assert len(rows) == 4 and all(r["taken_at"].startswith("2024-0") for r in rows)
    assert len(backup_rows(browse, "--has-timestamp")) == 6
    assert [r["file"] for r in backup_rows(browse, "--no-timestamp")] == ["marketpulse-legacy.db"]
    assert backup_rows(browse, "--no-timestamp", "--quarter", "2024-Q1") == []
    assert (
        len(
            backup_rows(
                browse, "--quarter", "2024-Q1", "--exclude-date", "2024-01-01", "--filename-suffix", "manual.db"
            )
        )
        == 1
    )


def test_backup_date_and_weekday_summaries(browse):
    rows = backup_rows(browse, "--summary", "date", "--year", "2024")
    assert rows[0] == {"group": "2024-01-01", "count": 1} and len(rows) == 5
    rows = backup_rows(browse, "--summary", "weekday")
    assert {r["group"]: r["count"] for r in rows} == {
        "mon": 1,
        "tue": 1,
        "thu": 1,
        "fri": 1,
        "sat": 1,
        "sun": 1,
        "unknown": 1,
    }
    result = browse("backup", "list", "--summary", "date", "--csv", "--no-timestamp")
    assert result.output == "group,count\nunknown,1\n"
    assert "unknown" in browse("backup", "list", "--summary", "weekday").output


def test_backup_show_csv_field_and_several(browse, store):
    first = "marketpulse-20240229-120000-manual.db"
    other = "marketpulse-legacy.db"
    result = browse("backup", "show", first, "--csv")
    assert result.exit_code == 0
    assert list(csv.DictReader(io.StringIO(result.output)))[0]["size_bytes"] == "400"
    result = browse("backup", "show", first, "--field", "path")
    assert result.output.strip() == str((store.backup_dir / first).resolve())
    assert browse("backup", "show", other, "--field", "taken_at").output == "\n"
    result = browse("backup", "show", first, other, "--json")
    assert result.exit_code == 0 and [r["file"] for r in json.loads(result.output)] == [first, other]
    result = browse("backup", "show", first, other, "--field", "size_bytes")
    assert result.output.splitlines() == ["400", "700"]
    human = browse("backup", "show", first, other)
    assert human.exit_code == 0 and first in human.output and other in human.output
    single = json.loads(browse("backup", "show", first, "--json").output)
    assert isinstance(single, dict) and single["file"] == first
    missing = browse("backup", "show", first, "missing.db", "--csv")
    assert missing.exit_code == 1 and "file,path" not in missing.output


@pytest.mark.parametrize(
    "args",
    [
        ["--fields", "file"],
        ["--json", "--fields", "path,path"],
        ["--jsonl", "--fields", ""],
        ["--csv", "--fields", "unknown"],
        ["--jsonl", "--csv"],
        ["--paths", "--json"],
        ["--jsonl", "--count"],
        ["--paths", "--page-info"],
        ["--summary", "date", "--jsonl"],
        ["--summary", "date", "--paths"],
        ["--summary", "date", "--json", "--fields", "file"],
        ["--quarter", "0000-Q1"],
        ["--quarter", "2024-Q0"],
        ["--quarter", "2024-q1"],
        ["--exclude-date", "2024-02-30"],
        ["--weekday", "noday"],
        ["--filename-prefix", " "],
        ["--filename-suffix", ""],
        ["--exclude-file", "../fictional.db"],
        ["--exclude-file", ""],
    ],
)
def test_backup_new_usage_errors(browse, args):
    assert browse("backup", "list", *args).exit_code == 2


@pytest.mark.parametrize("args", [["--json", "--csv"], ["--field", "path", "--json"], ["--field", "invalid"]])
def test_backup_show_output_errors(browse, args):
    assert browse("backup", "show", "marketpulse-legacy.db", *args).exit_code == 2
