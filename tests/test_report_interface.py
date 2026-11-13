"""The alert, chart, terminal app and operation catalogs (#143) mirror engine constants offline."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from marketpulse import market, models
from marketpulse.cli import main, report_interface, report_operations
from marketpulse.cli.base import App
from marketpulse.cli.report_interface import SOURCES, load_source
from marketpulse.tui import constants


def _native(value) -> bool:
    """Exact JSON types only: a tuple, an enum member or any other subclass must not reach a row."""
    if type(value) is list:
        return all(_native(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _native(item) for key, item in value.items())
    return type(value) in (str, int, float, bool, type(None))


@pytest.fixture
def cli(monkeypatch):
    def no_tracker(*args, **kwargs):
        raise AssertionError("These catalogs must not open the ledger or market client")

    monkeypatch.setattr("marketpulse.services.Tracker.open", no_tracker)
    runner = CliRunner()
    return lambda *args: runner.invoke(main, list(args), catch_exceptions=False)


def _rows(result) -> list[dict]:
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


@pytest.mark.parametrize("name", SOURCES)
def test_catalog_schema_native_values_and_offline(name, fake):
    app = App()
    rows = load_source(name, app)
    assert rows
    assert all(tuple(row) == SOURCES[name] for row in rows)
    assert all(_native(value) for row in rows for value in row.values())
    json.dumps(rows, allow_nan=False)
    assert app._tracker is None
    assert fake.calls == []


@pytest.mark.parametrize("name", SOURCES)
def test_each_load_builds_fresh_rows(name):
    """Callers own what they get: no row or nested list is the engine's own object."""
    first, second = load_source(name, App()), load_source(name, App())
    assert first == second
    for one, other in zip(first, second, strict=True):
        assert one is not other
        assert all(a is not b for a, b in zip(one.values(), other.values(), strict=True) if isinstance(a, list | dict))


def test_unknown_catalog_is_rejected():
    with pytest.raises(KeyError, match="unknown"):
        load_source("unknown", App())


def test_alert_conditions_are_described_in_engine_order():
    assert load_source("alert-conditions", App()) == [
        {"value": "above", "description": "Price at or above the threshold.", "percent": False},
        {"value": "below", "description": "Price at or below the threshold.", "percent": False},
        {"value": "up_pct", "description": "Day change at or above the threshold percent.", "percent": True},
        {"value": "down_pct", "description": "Day change at or below minus the threshold percent.", "percent": True},
    ]


def test_alert_condition_without_a_description_fails_loudly(monkeypatch):
    monkeypatch.setattr(report_interface, "ALERT_CONDITIONS", (*models.ALERT_CONDITIONS, "fictional_condition"))
    with pytest.raises(KeyError, match="fictional_condition"):
        load_source("alert-conditions", App())


def test_chart_periods_cover_the_engine_periods():
    rows = load_source("chart-periods", App())
    assert [row["period"] for row in rows] == market.PERIODS
    assert all(row["interval"] == market.PERIOD_INTERVALS[row["period"]] for row in rows)
    assert all(row["bars_per_year"] == market.BARS_PER_YEAR[row["interval"]] for row in rows)
    assert rows[0] == {"period": "1d", "interval": "5m", "bars_per_year": 252 * 78}


def test_tui_keys_list_global_then_workspace_bindings():
    rows = load_source("tui-keys", App())
    assert rows[:4] == [
        {"workspace": "global", "key": "backspace", "action": "previous workspace"},
        {"workspace": "global", "key": "{ / }", "action": "previous / next workspace"},
        {"workspace": "global", "key": "N", "action": "record any transaction type"},
        {"workspace": "global", "key": "F1", "action": "keys for this workspace"},
    ]
    assert [(row["workspace"], row["key"], row["action"]) for row in rows[4:]] == [
        (workspace, key, action)
        for workspace in constants.HINTS
        for key, action in constants.WORKSPACE_KEYS.get(workspace, [])
    ]
    assert rows[4] == {"workspace": "dashboard", "key": "z", "action": "zoom: hide the side column"}


def test_workspaces_describe_tables_and_sort_modes():
    rows = {row["name"]: row for row in load_source("workspaces", App())}
    assert [(name, row["hint"]) for name, row in rows.items()] == list(constants.HINTS.items())
    assert {name: row["table"] for name, row in rows.items() if row["table"] is not None} == constants.TABLES
    assert {name: row["sort_modes"] for name, row in rows.items() if row["sort_modes"]} == {
        name: [column for column, _ in modes] for name, modes in constants.SORT_MODES.items()
    }
    assert rows["holdings"]["table"] == "#holdings-table"
    assert rows["holdings"]["sort_modes"] == ["account", "symbol", "value", "day %", "gain", "gain %"]
    assert rows["dashboard"]["table"] is None and rows["dashboard"]["sort_modes"] == []


def test_report_operations_are_the_operation_catalog():
    assert load_source("report-operations", App()) == report_operations.rows()


@pytest.mark.parametrize("name", SOURCES)
def test_report_and_summarize_serve_every_catalog(name, cli):
    rows = load_source(name, App())
    assert _rows(cli("report", name)) == rows
    assert _rows(cli("summarize", name, "--metric", "rows=count")) == [{"rows": len(rows)}]


def test_typed_values_survive_the_report_pipeline(cli):
    percent = cli("report", "alert-conditions", "--is-type", "percent=boolean", "--where", "percent=true")
    assert [row["value"] for row in _rows(percent)] == ["up_pct", "down_pct"]
    untabled = cli("report", "workspaces", "--is-type", "table=null", "--fields", "name")
    assert _rows(untabled) == [{"name": name} for name in constants.HINTS if name not in constants.TABLES]
    sortable = cli("report", "workspaces", "--has-item", 'sort_modes="gain %"', "--fields", "name")
    assert _rows(sortable) == [{"name": "holdings"}]
    daily = cli(
        "summarize", "chart-periods", "--group-by", "interval", "--metric", "periods=count", "--having", "gt:periods=1"
    )
    assert _rows(daily) == [
        {"interval": interval, "periods": count}
        for interval, count in {
            interval: list(market.PERIOD_INTERVALS.values()).count(interval)
            for interval in market.PERIOD_INTERVALS.values()
        }.items()
        if count > 1
    ]
