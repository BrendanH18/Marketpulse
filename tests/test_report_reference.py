"""Reference catalogs describe the program itself: fixed tables, read without saved data or the network."""

from __future__ import annotations

import dataclasses
import json
import re
import socket
from collections import Counter
from decimal import Decimal

import pytest
from click.testing import CliRunner

from marketpulse import brokers, csvio, ledger, models
from marketpulse.cli import (
    main,
    report_derive,
    report_ledger,
    report_metrics,
    report_reference,
    report_system,
    reports,
)
from marketpulse.cli.base import App
from marketpulse.cli.report_reference import SOURCES, load_source
from marketpulse.config import config_path
from marketpulse.market import CurlTransport
from marketpulse.themes import OMARCHY_PALETTES, Palette, resolve_palette

# What docs/cli-report-summaries.md says each operation returns, kept apart from the catalog's own table.
RESULTS = {
    "integer": "count present missing empty nonempty distinct duplicates mode-count number-count number-distinct "
    "positive-count negative-count zero-count true-count false-count string-count array-count object-count "
    "length-sum length-min length-max",
    "decimal": "number-sum number-min number-max number-mean number-median number-range positive-sum negative-sum "
    "absolute-sum length-mean",
    "value": "first last first-present last-present mode",
    "list": "values distinct-values",
    "string": "text-min text-max",
}
ROLES = "background surface panel selection border foreground bright muted accent up down warn info".split()


def _forbidden(what: str):
    def fail(*args, **kwargs):
        pytest.fail(f"a reference catalog {what}")

    return fail


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Fail any test here in which the tracker is opened or the network is reached."""
    monkeypatch.setattr(App, "tracker", property(_forbidden("opened the tracker")))
    monkeypatch.setattr(CurlTransport, "get_json", _forbidden("requested market data"))
    monkeypatch.setattr(socket.socket, "connect", _forbidden("opened a network connection"))


@pytest.fixture
def app() -> App:
    return App()


def _plain(value) -> bool:
    """Whether a value is built from JSON's own types only; an enum member or a tuple is not."""
    if type(value) is list:
        return all(_plain(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _plain(item) for key, item in value.items())
    return value is None or type(value) in (str, int, float, bool)


def _cli(*args: str) -> str:
    result = CliRunner().invoke(main, list(args))
    assert result.exit_code == 0, result.output
    return result.output


@pytest.mark.parametrize("name", SOURCES)
def test_rows_follow_the_schema_as_plain_json_and_touch_nothing(name, app, tmp_path):
    files = sorted(tmp_path.rglob("*"))
    rows = load_source(name, app)
    assert rows
    assert all(tuple(row) == SOURCES[name] for row in rows)
    assert _plain(rows)
    assert json.loads(json.dumps(rows, allow_nan=False)) == rows
    # Rows are rebuilt on every call, so a caller that edits them cannot reach the engine's tables.
    saved = json.dumps(rows)
    for row in rows:
        for value in row.values():
            if isinstance(value, list):
                value.clear()
        row.clear()
    assert json.dumps(load_source(name, app)) == saved
    assert app._tracker is None
    assert sorted(tmp_path.rglob("*")) == files


@pytest.mark.parametrize("name", SOURCES)
def test_cli_serves_each_catalog_through_the_registry(name, app):
    rows = load_source(name, app)
    assert reports.load_source(name, app) == rows
    assert json.loads(_cli("report", name)) == rows
    assert json.loads(_cli("report", name, "--describe")) == {"source": name, "fields": list(SOURCES[name])}
    assert json.loads(_cli("summarize", name, "--metric", "rows=count")) == [{"rows": len(rows)}]


def test_registry_is_consistent_across_every_source_module():
    modules = reports.SOURCE_MODULES
    assert len(modules) == 5
    assert {report_ledger, report_system, report_reference} <= set(modules)
    for module in modules:
        assert isinstance(module.GROUP, str) and module.GROUP
        assert set(module.DESCRIPTIONS) == set(module.SOURCES)
        assert all(text and text.endswith(".") for text in module.DESCRIPTIONS.values())
    names = [name for module in modules for name in module.SOURCES]
    assert len(names) == len(set(names)) == 50
    assert sum(len(module.SOURCES) for module in (report_ledger, report_system, report_reference)) == 25
    assert set(reports.SOURCES) == set(names)


def test_sources_lists_every_dataset_by_name(app):
    rows = load_source("sources", app)
    names = [row["source"] for row in rows]
    assert len(rows) == 50
    assert names == sorted(names) == sorted(reports.SOURCES)
    assert all(row["fields"] == list(reports.SOURCES[row["source"]]) for row in rows)
    assert all(row["field_count"] == len(row["fields"]) for row in rows)
    assert Counter(row["group"] for row in rows) == {
        "portfolio": 13,
        "catalog": 12,
        "ledger": 9,
        "system": 5,
        "reference": 11,
    }
    by_name = {row["source"]: row for row in rows}
    assert by_name["sources"] == {
        "source": "sources",
        "group": "reference",
        "fields": ["source", "group", "fields", "field_count", "description"],
        "field_count": 5,
        "description": "Every report dataset with its group, fields and description.",
    }
    assert by_name["tfsa-limits"] == {
        "source": "tfsa-limits",
        "group": "reference",
        "fields": ["year", "limit"],
        "field_count": 2,
        "description": "Annual TFSA dollar limits used for contribution room.",
    }
    assert by_name["accounts"]["group"] == "portfolio"
    assert (by_name["watchlist"]["group"], by_name["watchlist"]["fields"]) == ("portfolio", ["position", "symbol"])
    assert (by_name["config"]["group"], by_name["config"]["fields"]) == ("catalog", ["key", "value"])
    assert (by_name["holdings"]["group"], by_name["schema"]["group"]) == ("ledger", "system")
    for module in reports.SOURCE_MODULES:
        for name, description in module.DESCRIPTIONS.items():
            assert (by_name[name]["group"], by_name[name]["description"]) == (module.GROUP, description)


def test_summary_operations_classify_all_forty_in_documented_order(app):
    rows = load_source("summary-operations", app)
    assert [row["position"] for row in rows] == list(range(1, 41))
    assert [row["operation"] for row in rows] == list(report_metrics.OPERATIONS)
    assert [row["operation"] for row in rows if not row["takes_field"]] == ["count"]
    expected = {operation: result for result, operations in RESULTS.items() for operation in operations.split()}
    assert {row["operation"]: row["result"] for row in rows} == expected
    # A classification for an operation that no longer exists would be as wrong as a missing one.
    assert set(report_reference._OPERATION_RESULTS) == set(report_metrics.OPERATIONS)
    # Numbered as in the Operations table of docs/cli-report-summaries.md.
    assert rows[0] == {"position": 1, "operation": "count", "takes_field": False, "result": "integer"}
    assert rows[11] == {"position": 12, "operation": "mode", "takes_field": True, "result": "value"}
    assert rows[13] == {"position": 14, "operation": "values", "takes_field": True, "result": "list"}
    assert rows[17] == {"position": 18, "operation": "number-sum", "takes_field": True, "result": "decimal"}
    assert rows[37] == {"position": 38, "operation": "length-mean", "takes_field": True, "result": "decimal"}
    assert rows[39] == {"position": 40, "operation": "text-max", "takes_field": True, "result": "string"}


def test_summary_operation_results_are_what_the_operations_return(app):
    cells = [3, 1.5, "alpha", "beta", [1, 2], {"k": 1}, False]
    holds = {
        "integer": lambda result: type(result) is int,
        "decimal": lambda result: type(result) is str and Decimal(result).is_finite(),
        "value": lambda result: any(result is cell for cell in cells),
        "list": lambda result: type(result) is list,
        "string": lambda result: type(result) is str and result in cells,
    }
    for row in load_source("summary-operations", app):
        result = report_metrics.summarize_values(row["operation"], cells)
        assert holds[row["result"]](result), (row, result)


def test_an_unclassified_summary_operation_fails_loudly(app, monkeypatch):
    monkeypatch.setattr(report_metrics, "OPERATIONS", (*report_metrics.OPERATIONS, "fictional-operation"))
    with pytest.raises(KeyError, match="fictional-operation"):
        load_source("summary-operations", app)


def test_derive_functions_list_all_fifty_in_documented_order(app):
    rows = load_source("derive-functions", app)
    assert [row["position"] for row in rows] == list(range(1, 51))
    assert len({row["function"] for row in rows}) == 50
    assert [row["function"] for row in rows] == [function.name for function in report_derive.FUNCTIONS]
    assert {row["family"] for row in rows} == {"date", "number", "text", "value"}
    assert all(row["argument"] is None or row["argument"] for row in rows)
    assert rows[0] == {
        "position": 1,
        "function": "year",
        "family": "date",
        "argument": None,
        "result": "integer",
        "description": "Calendar year.",
    }
    assert rows[-1] == {
        "position": 50,
        "function": "key",
        "family": "value",
        "argument": "NAME",
        "result": "value",
        "description": "Object member NAME.",
    }


def test_broker_profiles_list_detection_headers(app):
    rows = load_source("broker-profiles", app)
    assert [row["name"] for row in rows] == ["questrade", "wealthsimple", "generic"]
    questrade, wealthsimple, generic = rows
    assert (questrade["label"], questrade["has_accounts"]) == ("Questrade", True)
    assert questrade["required_headers"] == [
        "account #",
        "action",
        "activity type",
        "net amount",
        "symbol",
        "transaction date",
    ]
    assert questrade["limits"].startswith("Account activity export.")
    assert (wealthsimple["label"], wealthsimple["has_accounts"]) == ("Wealthsimple", False)
    assert wealthsimple["required_headers"] == ["amount", "balance", "currency", "date", "description", "transaction"]
    assert generic == {
        "name": "generic",
        "label": "Generic CSV",
        "required_headers": [],
        "has_accounts": False,
        "limits": "Common column names and transaction words; anything ambiguous is skipped.",
    }
    # A file with exactly a profile's required headers is detected as that profile.
    assert all(brokers.detect(row["required_headers"]).name == row["name"] for row in rows)


def test_import_aliases_number_each_fields_headers(app):
    rows = load_source("import-aliases", app)
    assert rows[0] == {"field": "date", "position": 1, "alias": "date"}
    assert rows[-1] == {"field": "target_account", "position": 3, "alias": "to account"}
    assert [row["alias"] for row in rows if row["field"] == "currency"] == ["currency", "ccy", "curr"]
    assert {"field": "fees", "position": 3, "alias": "commission"} in rows
    fields = list(dict.fromkeys(row["field"] for row in rows))
    assert fields == [
        "date",
        "type",
        "symbol",
        "quantity",
        "price",
        "amount",
        "fees",
        "currency",
        "account",
        "note",
        "ratio",
        "target_account",
    ]
    for field in fields:
        positions = [row["position"] for row in rows if row["field"] == field]
        assert positions == list(range(1, len(positions) + 1))
    assert len(rows) == sum(len(aliases) for aliases in brokers._ALIASES.values())
    # The importer maps every listed header onto the field it is listed under.
    assert all(brokers.map_headers([row["alias"]]) == {row["field"]: row["alias"]} for row in rows)


def test_import_type_keywords_keep_matching_order(app):
    rows = load_source("import-type-keywords", app)
    assert rows[0] == {"position": 1, "keyword": "reinvest", "type": "DRIP"}
    assert {"position": 5, "keyword": "dividend", "type": "DIVIDEND"} in rows
    assert [row["position"] for row in rows] == list(range(1, len(rows) + 1))
    assert len(rows) == sum(len(keywords) for keywords, _ in csvio._TYPE_KEYWORDS)
    position = {row["keyword"]: row["position"] for row in rows}
    assert position["transfer in cash"] < position["transfer"] < position["buy"] < position["sell"]
    # The importer reads every listed word as the listed type, and the earlier of two matches wins.
    assert all(csvio.parse_type(row["keyword"]) == row["type"] for row in rows)
    assert csvio.parse_type("Dividend Reinvestment") == "DRIP"


def test_exchange_suffixes_give_the_currency_the_engine_assumes(app):
    rows = load_source("exchange-suffixes", app)
    assert rows[0] == {"suffix": ".TO", "currency": "CAD"}
    assert {"suffix": ".L", "currency": "GBP"} in rows
    assert {"suffix": ".T", "currency": "JPY"} in rows
    assert [row["suffix"] for row in rows] == list(models._SUFFIX_CURRENCIES)
    assert all(models.guess_currency("FIC" + row["suffix"]) == row["currency"] for row in rows)


def test_instrument_classes_give_the_class_the_engine_assigns(app):
    rows = load_source("instrument-classes", app)
    assert rows[0] == {"instrument_type": "EQUITY", "asset_class": "equity", "label": "Equity"}
    assert rows[1] == {"instrument_type": "ETF", "asset_class": "etf", "label": "ETF"}
    assert {"instrument_type": "MUTUALFUND", "asset_class": "fund", "label": "Fund"} in rows
    assert {"instrument_type": "MONEYMARKET", "asset_class": "cash", "label": "Cash"} in rows
    assert [row["instrument_type"] for row in rows] == list(models._INSTRUMENT_CLASSES)
    assert all(models.asset_class_for_instrument(row["instrument_type"]) == row["asset_class"] for row in rows)


def test_tfsa_limits_list_every_year_in_order(app):
    rows = load_source("tfsa-limits", app)
    years = [row["year"] for row in rows]
    assert rows[0] == {"year": 2009, "limit": 5000}
    assert {"year": 2015, "limit": 10000} in rows
    assert {"year": 2024, "limit": 7000} in rows
    assert years == list(range(2009, years[-1] + 1)) == sorted(ledger.TFSA_LIMITS)
    assert all(ledger.tfsa_limit(row["year"]) == row["limit"] for row in rows)


def test_theme_colors_give_thirteen_hex_colors_per_embedded_theme(app):
    rows = load_source("theme-colors", app)
    themes = sorted(OMARCHY_PALETTES)
    assert len(rows) == 13 * len(themes)
    assert [row["theme"] for row in rows] == [theme for theme in themes for _ in ROLES]
    assert [row["role"] for row in rows] == ROLES * len(themes)
    assert all(re.fullmatch(r"#[0-9a-fA-F]{6}", row["color"]) for row in rows)
    # Every single color of a palette is a role: only its name, mode and chart series are left out.
    assert [f.name for f in dataclasses.fields(Palette) if f.name not in ("name", "dark", "series")] == ROLES
    for theme in themes:
        palette = resolve_palette(theme)
        colors = {row["role"]: row["color"] for row in rows if row["theme"] == theme}
        assert colors == {role: getattr(palette, role) for role in ROLES}
    assert {"theme": "tokyo-night", "role": "background", "color": "#1a1b26"} in rows
    assert {"theme": "tokyo-night", "role": "accent", "color": "#7aa2f7"} in rows
    assert {"theme": "catppuccin-latte", "role": "foreground", "color": "#4c4f69"} in rows


def test_market_strip_lists_configured_symbols_without_saving(app):
    assert load_source("market-strip", app) == [
        {"position": 1, "symbol": "^GSPC", "label": "S&P 500", "default": True},
        {"position": 2, "symbol": "^IXIC", "label": "Nasdaq", "default": True},
        {"position": 3, "symbol": "^GSPTSE", "label": "TSX", "default": True},
        {"position": 4, "symbol": "USDCAD=X", "label": "USD/CAD", "default": True},
        {"position": 5, "symbol": "BTC-USD", "label": "Bitcoin", "default": True},
        {"position": 6, "symbol": "GC=F", "label": "Gold", "default": True},
        {"position": 7, "symbol": "^TNX", "label": "US 10Y", "default": True},
    ]
    app.config.market_strip = ["FIC-A.TO", "^VIX", "BTC-USD"]
    assert load_source("market-strip", app) == [
        {"position": 1, "symbol": "FIC-A.TO", "label": "FIC-A.TO", "default": False},
        {"position": 2, "symbol": "^VIX", "label": "VIX", "default": False},
        {"position": 3, "symbol": "BTC-USD", "label": "Bitcoin", "default": True},
    ]
    app.config.market_strip = []
    assert load_source("market-strip", app) == []
    assert not config_path().exists()


def test_market_strip_labels_are_the_ones_the_dashboard_shows(app, tracker):
    """A hand-edited config may hold lower-case symbols; the strip looks them up in upper case."""
    app.config.market_strip = tracker.config.market_strip = ["^GSPC", "btc-usd", "fic-a.to"]
    rows = load_source("market-strip", app)
    assert [(row["symbol"], row["label"]) for row in rows] == [
        (item.symbol, item.label) for item in tracker.market_strip()
    ]
    assert rows == [
        {"position": 1, "symbol": "^GSPC", "label": "S&P 500", "default": True},
        {"position": 2, "symbol": "btc-usd", "label": "Bitcoin", "default": True},
        {"position": 3, "symbol": "fic-a.to", "label": "FIC-A.TO", "default": False},
    ]


def test_unknown_catalog_is_rejected(app):
    with pytest.raises(KeyError, match="nope"):
        load_source("nope", app)
    with pytest.raises(KeyError, match="nope"):
        reports.load_source("nope", app)


def test_cli_report_filters_and_exports_reference_rows():
    csv_text = _cli("report", "tfsa-limits", "--ge", "year=2024", "--le", "year=2026", "--format", "csv")
    assert csv_text.splitlines() == ["year,limit", "2024,7000", "2025,7000", "2026,7000"]
    tsv_text = _cli("report", "exchange-suffixes", "--where", "currency=CAD", "--format", "tsv")
    assert tsv_text.splitlines() == ["suffix\tcurrency", ".TO\tCAD", ".V\tCAD", ".NE\tCAD", ".CN\tCAD"]
    markdown = _cli("report", "sources", "--fields", "source,group,description", "--format", "markdown").splitlines()
    assert markdown[:2] == ["| source | group | description |", "| --- | --- | --- |"]
    assert len(markdown) == 52
    assert "| sources | reference | Every report dataset with its group, fields and description. |" in markdown
    assert _cli("report", "sources", "--where", "group=reference", "--count") == "11\n"
    assert json.loads(_cli("report", "summary-operations", "--where", "result=list", "--fields", "operation")) == [
        {"operation": "values"},
        {"operation": "distinct-values"},
    ]
    assert json.loads(_cli("report", "market-strip", "--where", "symbol=GC=F", "--omit", "position")) == [
        {"symbol": "GC=F", "label": "Gold", "default": True}
    ]


def test_cli_summarize_groups_reference_rows():
    assert json.loads(_cli("summarize", "derive-functions", "--group-by", "family", "--metric", "functions=count")) == [
        {"family": "date", "functions": 22},
        {"family": "number", "functions": 14},
        {"family": "text", "functions": 6},
        {"family": "value", "functions": 8},
    ]
    by_result = ["summarize", "summary-operations", "--group-by", "result", "--metric", "operations=count"]
    assert json.loads(_cli(*by_result, "--sort", "operations", "--descending")) == [
        {"result": "integer", "operations": 21},
        {"result": "decimal", "operations": 10},
        {"result": "value", "operations": 5},
        {"result": "list", "operations": 2},
        {"result": "string", "operations": 2},
    ]
    assert json.loads(_cli("summarize", "theme-colors", "--metric", "roles=distinct:role")) == [{"roles": 13}]
