"""Catalog reports retain schema, native types and secret redaction offline."""

from __future__ import annotations

import json

import pytest

from marketpulse.cli.base import App
from marketpulse.cli.report_catalog import SOURCES, load_source
from marketpulse.config import Config
from marketpulse.models import AccountType, AssetClass, AssetKind, TxnType


@pytest.mark.parametrize("name", SOURCES)
def test_catalog_schema_and_offline(name, tracker, fake):
    app = App()
    app._tracker = tracker
    app.config.theme = "tokyo-night"  # make the defaults diff nonempty
    before = tracker.store._conn.total_changes
    rows = load_source(name, app)
    assert rows
    assert all(tuple(row) == SOURCES[name] for row in rows)
    json.dumps(rows, allow_nan=False)
    assert tracker.store._conn.total_changes == before
    assert fake.calls == []


@pytest.mark.parametrize("name", ["config", "config-defaults", "config-diff"])
def test_configuration_keys_always_redacted(name):
    app = App()
    app.config.quote_api_key = "fictional-key-that-must-not-leak"
    rows = load_source(name, app)
    assert app.config.quote_api_key not in json.dumps(rows)
    value = next(row["value"] for row in rows if row["key"] == "quote_api_key")
    assert value == ("" if name == "config-defaults" else "(set)")
    assert app._tracker is None


def test_config_defaults_diff_and_native_values():
    app = App()
    app.config = Config()
    assert load_source("config-diff", app) == []
    app.config.privacy = True
    app.config.market_strip = ["FIC-A", "FIC-B"]
    assert load_source("config-diff", app) == [
        {"key": "privacy", "value": True},
        {"key": "market_strip", "value": ["FIC-A", "FIC-B"]},
    ]
    assert next(row["value"] for row in load_source("config-defaults", app) if row["key"] == "privacy") is False


def test_all_non_provider_catalogs_leave_tracker_unopened():
    app = App()
    for name in SOURCES:
        if name != "providers":
            load_source(name, app)
    assert app._tracker is None


@pytest.mark.parametrize(
    ("source", "enum"),
    [
        ("account-types", AccountType),
        ("transaction-types", TxnType),
        ("asset-kinds", AssetKind),
        ("asset-classes", AssetClass),
    ],
)
def test_enum_catalogs_match_engine(source, enum):
    assert [row["value"] for row in load_source(source, App())] == [item.value for item in enum]


def test_compounding_and_theme_catalogs():
    app = App()
    assert [row["value"] for row in load_source("compounding", app)] == [
        "annual",
        "semiannual",
        "quarterly",
        "monthly",
        "simple",
    ]
    themes = load_source("themes", app)
    assert all(row["mode"] in ("light", "dark") and row["label"] for row in themes)
    assert load_source("compounding", app)[-1] == {"value": "simple", "periods_per_year": None}
    assert load_source("asset-kinds", app)[1] == {"value": "fixed_income", "label": "Fixed Income"}
    assert [row["name"] for row in themes] == sorted(row["name"] for row in themes)


def test_provider_status_reads_saved_attempt_without_network(tracker, fake):
    from marketpulse.market import STATUS_META

    tracker.store.set_meta(STATUS_META, json.dumps({"yahoo": {"ok": False, "last_error": "fictional failure"}}))
    app = App()
    app._tracker = tracker
    rows = load_source("providers", app)
    assert len(rows) == 1
    assert rows[0]["name"] == "yahoo"
    assert rows[0]["ok"] is False
    assert rows[0]["last_error"] == "fictional failure"
    assert fake.calls == []


def test_config_keys_and_command_catalog_metadata():
    app = App()
    types = {row["key"]: row["type"] for row in load_source("config-keys", app)}
    assert types["privacy"] == "bool"
    assert types["market_strip"] == "list"
    rows = {row["command"]: row for row in load_source("commands", app)}
    assert rows["accounts"]["group"] is True
    assert rows["accounts list"]["depth"] == 2
    assert any("--json" in parameter["flags"] for parameter in rows["accounts list"]["parameters"])


def test_unknown_catalog_is_rejected():
    with pytest.raises(ValueError, match="Unknown report catalog"):
        load_source("unknown", App())
