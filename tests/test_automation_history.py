"""Automation run history (#180): recording, pruning, `automation history` and the doctor warning.

Every ledger, symbol and error here is fictional.
"""

import json
from datetime import datetime, timedelta

import pytest
from click.testing import CliRunner

from marketpulse.automation import run_cycle
from marketpulse.cli import main
from marketpulse.cli.doctor import _automation_check
from marketpulse.db import AUTOMATION_RUNS_KEEP
from marketpulse.desktop import snapshot
from marketpulse.models import Account, Alert, Transaction, TxnType


def holding(store) -> None:
    account = store.add_account(Account(name="Fictional Investing"))
    store.add_transaction(
        Transaction(account_id=account.saved_id, type=TxnType.BUY, symbol="AAPL", quantity=2, price=150, currency="USD")
    )


def report(when: datetime, *, errors=(), quote_errors=(), stale_count=0, fired=()) -> dict:
    return {
        "last_run": when.isoformat(timespec="seconds"),
        "stale": bool(stale_count),
        "stale_count": stale_count,
        "stale_since": None,
        "snapshot_date": None,
        "backup": None,
        "fired": list(fired),
        "errors": list(errors),
        "quote_errors": list(quote_errors),
    }


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "160")
    runner = CliRunner()
    return lambda *args: runner.invoke(main, list(args), catch_exceptions=False)


# ── recording ─────────────────────────────────────────────────────────────────


def test_every_cycle_is_recorded_and_the_latest_still_goes_to_meta(tracker, fake, notifications):
    holding(tracker.store)
    fake.set_quote("MSFT", 400)
    tracker.store.add_alert(Alert("MSFT", "above", 390))
    first = run_cycle(tracker, fresh=True).report
    second = run_cycle(tracker, fresh=True).report
    runs = tracker.store.automation_runs()
    assert [run.report for run in runs] == [second, first]  # newest first
    assert runs[0].id > runs[1].id
    assert [run.ran_at for run in runs] == [second["last_run"], first["last_run"]]
    assert not any(run.failed for run in runs)
    assert runs[1].report["fired"] == ["MSFT ≥ 390.00"]
    assert json.loads(tracker.store.get_meta("automation_last_run")) == second


def test_a_failed_backup_is_kept_after_a_later_success(tracker, monkeypatch):
    holding(tracker.store)
    real_backup = tracker.store.auto_backup

    def fail_backup():
        raise OSError("fictional disk full")

    monkeypatch.setattr(tracker.store, "auto_backup", fail_backup)
    run_cycle(tracker, fresh=True)
    monkeypatch.setattr(tracker.store, "auto_backup", real_backup)
    run_cycle(tracker, fresh=True)
    assert json.loads(tracker.store.get_meta("automation_last_run"))["errors"] == []
    latest, overnight = tracker.store.automation_runs()
    assert not latest.failed
    assert overnight.failed and overnight.report["errors"] == ["Backup failed: fictional disk full"]


def test_quote_errors_alone_do_not_mark_a_run_failed(store):
    run = store.record_automation_run(report(datetime(2026, 1, 1, 9), quote_errors=["DELISTED: symbol not found"]))
    assert not run.failed and store.automation_runs(failures_only=True) == []


def test_history_is_pruned_to_the_newest_50(store):
    start = datetime(2026, 1, 1, 9)
    for i in range(AUTOMATION_RUNS_KEEP + 7):
        store.record_automation_run(report(start + timedelta(minutes=i)))
    runs = store.automation_runs()
    assert AUTOMATION_RUNS_KEEP == 50 and len(runs) == 50
    assert runs[0].ran_at == (start + timedelta(minutes=56)).isoformat()
    assert runs[-1].ran_at == (start + timedelta(minutes=7)).isoformat()
    assert [run.ran_at for run in store.automation_runs(limit=2)] == [runs[0].ran_at, runs[1].ran_at]


def test_a_cycle_that_raises_is_recorded_too(cli, tracker, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("fictional provider meltdown")

    monkeypatch.setattr("marketpulse.automation.run_cycle", boom)
    result = cli("automation", "run", "--once", "--json", "--quiet")
    assert result.exit_code == 1
    # The printed report is unchanged; the history adds when it happened.
    assert json.loads(result.output) == {"errors": ["fictional provider meltdown"], "failed": True}
    (run,) = tracker.store.automation_runs()
    assert run.failed and run.report["errors"] == ["fictional provider meltdown"]
    datetime.fromisoformat(run.ran_at)


def test_desktop_bridge_automation_block_is_unchanged(tracker):
    holding(tracker.store)
    payload = snapshot(tracker, fresh=True)
    assert set(payload["automation"]) == {
        "last_run",
        "stale",
        "stale_count",
        "stale_since",
        "snapshot_date",
        "backup",
        "fired",
        "errors",
        "quote_errors",
    }
    assert "automation_runs" not in payload and "history" not in payload["automation"]
    # The app's refreshes are recorded like any other cycle.
    assert [run.report for run in tracker.store.automation_runs()] == [payload["automation"]]


# ── automation history ────────────────────────────────────────────────────────


def seed_history(store) -> None:
    store.record_automation_run(report(datetime(2026, 3, 1, 2), errors=["Backup failed: fictional disk full"]))
    store.record_automation_run(report(datetime(2026, 3, 1, 3), quote_errors=["DELISTED: symbol not found"]))
    store.record_automation_run(report(datetime(2026, 3, 1, 4), stale_count=2, fired=["AAPL ≥ 150.00"]))


def test_history_table_lists_runs_newest_first(cli, store):
    assert "No automation runs recorded yet." in cli("automation", "history").output
    store.record_automation_run(report(datetime(2026, 3, 1, 1)))
    assert "No failed automation runs recorded." in cli("automation", "history", "--failures").output
    seed_history(store)
    result = cli("automation", "history")
    assert result.exit_code == 0
    out = result.output
    assert out.index("2026-03-01 04:00") < out.index("2026-03-01 03:00") < out.index("2026-03-01 02:00")
    assert "✗ failed" in out and "Backup failed: fictional disk full" in out
    assert out.count("✓ ok") == 3 and "AAPL ≥ 150.00" in out
    failures = cli("automation", "history", "--failures").output
    assert "2026-03-01 02:00" in failures and "2026-03-01 03:00" not in failures
    assert "2026-03-01 04:00" in cli("automation", "history", "--limit", "1").output
    assert "2026-03-01 03:00" not in cli("automation", "history", "--limit", "1").output


def test_history_table_fits_a_narrow_terminal(cli, store, monkeypatch):
    seed_history(store)
    monkeypatch.setenv("COLUMNS", "80")
    out = cli("automation", "history").output
    assert "03-01 02:00" in out and "2026-03-01" not in out
    assert all(len(line) <= 80 for line in out.splitlines())


def test_history_json_and_failures_filter(cli, store):
    assert json.loads(cli("automation", "history", "--json").output) == []
    seed_history(store)
    rows = json.loads(cli("automation", "history", "--json").output)
    assert [row["ran_at"] for row in rows] == ["2026-03-01T04:00:00", "2026-03-01T03:00:00", "2026-03-01T02:00:00"]
    assert rows[0] == {
        "id": rows[0]["id"],
        "ran_at": "2026-03-01T04:00:00",
        "failed": False,
        "errors": [],
        "quote_error_count": 0,
        "stale_count": 2,
        "fired": ["AAPL ≥ 150.00"],
        "report": report(datetime(2026, 3, 1, 4), stale_count=2, fired=["AAPL ≥ 150.00"]),
    }
    assert rows[1]["quote_error_count"] == 1 and rows[1]["failed"] is False
    failures = json.loads(cli("automation", "history", "--failures", "--json").output)
    assert [(row["ran_at"], row["failed"], row["errors"]) for row in failures] == [
        ("2026-03-01T02:00:00", True, ["Backup failed: fictional disk full"])
    ]
    limited = json.loads(cli("automation", "history", "--json", "--limit", "2").output)
    assert [row["ran_at"] for row in limited] == ["2026-03-01T04:00:00", "2026-03-01T03:00:00"]
    assert cli("automation", "history", "--limit", "0").exit_code == 2


# ── doctor ────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 3, 2, 12)


def test_doctor_check_warns_only_for_failures_in_the_last_24_hours(store):
    assert _automation_check(store.automation_runs(), NOW).status == "info"
    store.record_automation_run(report(NOW - timedelta(hours=30), errors=["Backup failed: fictional disk full"]))
    store.record_automation_run(report(NOW - timedelta(hours=1), quote_errors=["DELISTED: symbol not found"]))
    older = _automation_check(store.automation_runs(), NOW)
    assert older.status == "ok" and "no failures in the last 24 hours" in older.detail
    store.record_automation_run(report(NOW - timedelta(hours=23), errors=["Backup failed: fictional read-only"]))
    store.record_automation_run(report(NOW - timedelta(minutes=5)))
    recent = _automation_check(store.automation_runs(), NOW)
    assert recent.status == "fail"
    assert "1 failed run(s) in the last 24 hours" in recent.detail
    assert "Backup failed: fictional read-only" in recent.detail and "disk full" not in recent.detail
    # The same history, a day later, has nothing to warn about.
    assert _automation_check(store.automation_runs(), NOW + timedelta(days=1)).status == "ok"


def test_doctor_reports_recent_automation_failures(cli, store):
    payload = json.loads(cli("doctor", "--offline", "--only", "automation", "--json").output)
    assert payload["checks"] == [{"check": "automation", "status": "info", "detail": "no runs recorded yet"}]
    now = datetime.now()
    store.record_automation_run(report(now - timedelta(hours=2)))
    assert cli("doctor", "--offline", "--only", "automation", "--strict").exit_code == 0
    store.record_automation_run(report(now - timedelta(hours=1), errors=["Backup failed: fictional disk full"]))
    store.record_automation_run(report(now))
    result = cli("doctor", "--offline", "--only", "automation", "--strict")
    assert result.exit_code == 1
    assert "✗ automation" in result.output and "Backup failed: fictional disk full" in result.output


def test_doctor_ignores_an_old_failure(cli, store):
    now = datetime.now()
    store.record_automation_run(report(now - timedelta(days=2), errors=["Backup failed: fictional disk full"]))
    store.record_automation_run(report(now - timedelta(hours=3)))
    result = cli("doctor", "--offline", "--only", "automation", "--strict")
    assert result.exit_code == 0 and "✓ automation" in result.output
