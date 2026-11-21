import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.cli.base import App
from marketpulse.cli.report_automation import SOURCES


@pytest.fixture
def cli(tracker, fake):
    app = App()
    app._tracker = tracker

    def run(*args: str):
        result = CliRunner().invoke(main, list(args), obj=app, catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert not fake.calls
        return json.loads(result.output)

    return run


def test_automation_report_counts_saved_outcomes_and_includes_pruned_failure(store, cli):
    failure = store.record_automation_run({"last_run": "2026-03-01T03:00:00", "errors": ["Fictional failure"]}, keep=2)
    healthy = store.record_automation_run(
        {"last_run": "2026-03-01T04:00:00", "stale": False, "fired": [], "errors": [], "quote_errors": []}, keep=2
    )
    stale = store.record_automation_run(
        {
            "last_run": "2026-03-01T05:00:00",
            "stale": True,
            "stale_count": 2,
            "stale_since": "2026-03-01T04:00:00",
            "snapshot_date": "2026-03-01",
            "fired": ["Fictional alert"],
            "errors": [],
            "quote_errors": ["Fictional quote error"],
        },
        keep=2,
    )

    rows = cli("report", "automation-runs")
    assert [row["id"] for row in rows] == [stale.id, healthy.id, failure.id]
    assert all(tuple(row) == SOURCES["automation-runs"] for row in rows)
    assert rows[0] == {
        "id": stale.id,
        "ran_at": "2026-03-01T05:00:00",
        "failed": False,
        "retained_failure": False,
        "stale": True,
        "stale_count": 2,
        "stale_since": "2026-03-01T04:00:00",
        "snapshot_date": "2026-03-01",
        "fired_count": 1,
        "error_count": 0,
        "quote_error_count": 1,
    }
    assert rows[1]["fired_count"] == 0
    assert rows[2] == {
        "id": failure.id,
        "ran_at": "2026-03-01T03:00:00",
        "failed": True,
        "retained_failure": True,
        "stale": None,
        "stale_count": None,
        "stale_since": None,
        "snapshot_date": None,
        "fired_count": None,
        "error_count": 1,
        "quote_error_count": None,
    }
    assert cli("summarize", "automation-runs", "--group-by", "failed", "--metric", "runs=count") == [
        {"failed": False, "runs": 2},
        {"failed": True, "runs": 1},
    ]


def test_failure_in_the_rolling_history_appears_once(store, cli):
    assert cli("report", "automation-runs") == []
    failed = store.record_automation_run({"last_run": "2026-03-01T03:00:00", "failed": True})
    assert cli("report", "automation-runs", "--fields", "id,failed,retained_failure") == [
        {"id": failed.id, "failed": True, "retained_failure": False}
    ]
