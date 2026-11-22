"""Read saved watchlists and alerts with fictional cached quotes."""

from __future__ import annotations

import math

import pytest

from marketpulse.cli.base import App
from marketpulse.cli.report_quote_coverage import SOURCES, load_source
from marketpulse.db import Store
from marketpulse.models import Alert, Quote


@pytest.fixture
def quote_app(tracker, monkeypatch):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    return App()


def test_watchlist_coverage_preserves_order_and_distinguishes_missing_quotes(quote_app, fake):
    store = quote_app.store
    store.add_watch(["MOONSEED.TO", "BERRY", "NODATE.TO", "BADDATE"])
    store.cache_quotes(
        [
            Quote("MOONSEED.TO", 2, 1, source="fictional", currency="CAD", fetched_at=1700000000.5),
            Quote("NODATE.TO", 5, 5, currency="CAD"),
            Quote("BADDATE", 4, 4, fetched_at=math.inf),
            Quote("UNWATCHED", 3, 3),
        ]
    )
    changes = store._conn.total_changes
    source = "watchlist-quote-coverage"
    rows = load_source(source, quote_app)
    expected = [
        (1, "MOONSEED.TO", True, "fictional", "CAD", "2023-11-14T22:13:20.500000+00:00", True),
        (2, "BERRY", False, None, None, None, None),
        (3, "NODATE.TO", True, "yahoo", "CAD", None, False),
        (4, "BADDATE", True, "yahoo", "USD", None, False),
    ]
    assert all(tuple(row) == SOURCES[source] for row in rows)
    assert [tuple(row.values()) for row in rows] == expected
    assert not fake.calls
    assert store._conn.total_changes == changes


def test_alert_coverage_uses_saved_state_and_keeps_each_rule(quote_app, fake, notifications):
    store = quote_app.store
    triggered_at = "2026-01-01T08:00:00+00:00"
    triggered = store.add_alert(Alert("MOONSEED.TO", "above", 10, triggered_at=triggered_at))
    disabled = store.add_alert(Alert("BERRY", "below", 3, active=False))
    untriggered = store.add_alert(Alert("MOONSEED.TO", "below", 3))
    store.cache_quotes([Quote("MOONSEED.TO", 2, 1, currency="CAD")])
    changes = store._conn.total_changes
    source = "alert-quote-coverage"
    rows = load_source(source, quote_app)
    expected = [
        (disabled.saved_id, "BERRY", "below", False, None, False, None, None, None, None),
        (triggered.saved_id, "MOONSEED.TO", "above", True, triggered_at, True, "yahoo", "CAD", None, False),
        (untriggered.saved_id, "MOONSEED.TO", "below", True, None, True, "yahoo", "CAD", None, False),
    ]
    assert all(tuple(row) == SOURCES[source] for row in rows)
    assert [tuple(row.values()) for row in rows] == expected
    assert not fake.calls
    assert not notifications
    assert store._conn.total_changes == changes


@pytest.mark.parametrize("source", SOURCES)
def test_quote_coverage_empty_saved_list(source, quote_app):
    assert load_source(source, quote_app) == []


def test_quote_coverage_joins_data_from_one_read_snapshot(quote_app, monkeypatch):
    store = quote_app.store
    store.add_watch(["BERRY"])
    watchlist = store.watchlist
    other = Store(store.path)

    def read_then_add_quote():
        watched = watchlist()
        other.cache_quotes([Quote("BERRY", 2, 1)])
        return watched

    monkeypatch.setattr(store, "watchlist", read_then_add_quote)
    try:
        assert load_source("watchlist-quote-coverage", quote_app)[0]["has_cached_quote"] is False
        assert "BERRY" in store.cached_quotes(["BERRY"])
    finally:
        other.close()
