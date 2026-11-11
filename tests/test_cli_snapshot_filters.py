"""Additional snapshot filters preserve recorded history and remain offline."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.db import Snapshot


@pytest.fixture
def browse(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    source = [
        Snapshot("2024-01-01", 100, 80, 70, "CAD", {}),
        Snapshot("2024-01-02", 120, 90, 75, "CAD", {}),
        Snapshot("2024-01-03", 110, 95, 80, "CAD", {}),
        Snapshot("2024-01-04", 110, 100, 85, "CAD", {}),
        Snapshot("2024-01-05", 90, 70, 60, "USD", {}),
        Snapshot("2024-01-06", 95, 75, 65, "USD", {}),
    ]
    store.upsert_snapshots(source)
    fake.offline = True

    def invoke(*args, output="--json"):
        result = CliRunner().invoke(main, ["snapshots", *args, *([output] if output else [])], catch_exceptions=False)
        assert fake.calls == []
        assert store.snapshots() == source
        return result

    return invoke


def rows(browse, *args):
    result = browse(*args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


@pytest.mark.parametrize(
    "field,minimum,maximum,days",
    [
        ("book", "80", "95", [1, 2, 3]),
        ("contributions", "70", "80", [1, 2, 3]),
        ("change", "-10", "5", [3, 4, 6]),
    ],
)
def test_inclusive_ranges(browse, field, minimum, maximum, days):
    matches = rows(browse, f"--min-{field}", minimum, f"--max-{field}", maximum)
    assert [int(row["date"][-2:]) for row in matches] == days
    count = browse(f"--min-{field}", minimum, f"--max-{field}", maximum, output="--count")
    assert count.exit_code == 0 and count.output == f"{len(days)}\n"


@pytest.mark.parametrize(
    "option,changes",
    [
        ("--increases-only", [20, 5]),
        ("--decreases-only", [-10]),
        ("--unknown-change-only", [None, None]),
    ],
)
def test_direction_and_unknown_filters(browse, option, changes):
    assert [row["change"] for row in rows(browse, option)] == changes


def test_excluded_dates_do_not_change_comparison_baseline(browse):
    result = rows(browse, "--exclude-date", "2024-01-02", "--exclude-date", "2024-01-05", "--since", "2024-01-03")
    assert [r["change"] for r in result] == [-10, 0, 5]
    assert rows(browse, "--exclude-date", "2024-01-01", "--latest")["date"] == "2024-01-06"


def test_filters_before_paging_and_latest(browse):
    page = rows(browse, "--min-change", "0", "--sort", "change", "--offset", "1", "--limit", "1", "--page-info")
    assert page["total"] == 3 and page["rows"][0]["change"] == 5
    assert rows(browse, "--increases-only", "--latest")["date"] == "2024-01-06"
    assert rows(browse, "--min-book", "999") == []


def test_csv_and_privacy(browse, tracker):
    result = browse("--decreases-only", output="--csv")
    assert result.exit_code == 0
    assert list(csv.DictReader(io.StringIO(result.output)))[0]["change"] == "-10.0"
    tracker.config.privacy = True
    result = browse("--increases-only", output=None)
    assert result.exit_code == 0 and "120.00" not in result.output and "95.00" not in result.output
    assert rows(browse, "--min-change", "20")[0]["net_worth"] == 120


@pytest.mark.parametrize("field", ["book", "contributions", "change"])
@pytest.mark.parametrize("prefix,value", [("min", "nan"), ("max", "inf"), ("min", "-inf")])
def test_nonfinite_bounds_rejected(browse, field, prefix, value):
    assert browse(f"--{prefix}-{field}", value).exit_code == 2


@pytest.mark.parametrize("field", ["book", "contributions", "change"])
def test_reversed_range_rejected(browse, field):
    result = browse(f"--min-{field}", "10", f"--max-{field}", "0")
    assert result.exit_code == 2 and "must be at most" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["--exclude-date", "2024-02-30"],
        ["--exclude-date", "bad"],
        ["--increases-only", "--decreases-only"],
        ["--increases-only", "--unchanged-only"],
        ["--decreases-only", "--unknown-change-only"],
        ["--unknown-change-only", "--changed-only"],
        ["--unknown-change-only", "--min-change", "0"],
        ["--unknown-change-only", "--max-change", "0"],
    ],
)
def test_invalid_combinations(browse, args):
    assert browse(*args).exit_code == 2
