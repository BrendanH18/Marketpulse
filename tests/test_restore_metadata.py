"""Restore confirmation must notice saved portfolio edits outside the tax ledger."""

import pytest

from marketpulse.desktop import ledger_revision, storage_info
from marketpulse.models import Alert, Asset, AssetClass, Quote


@pytest.mark.parametrize("kind", ["asset", "watchlist", "alert", "targets"])
def test_restore_metadata_changes_even_when_ledger_revision_does_not(tracker, kind):
    store = tracker.store
    before = storage_info(store)["restore_revision"]
    ledger_before = ledger_revision(tracker)
    if kind == "asset":
        store.upsert_asset(Asset(symbol="QA-METADATA", asset_class=AssetClass.EQUITY))
    elif kind == "watchlist":
        store.add_watch(["QA-NO-QUOTE"])
    elif kind == "alert":
        store.add_alert(Alert(symbol="QA-ALERT", condition="above", threshold=10))
    else:
        store.set_targets({"equity": 75, "cash": 25})
    assert storage_info(store)["restore_revision"] != before
    assert ledger_revision(tracker) == ledger_before


def test_automatic_quotes_and_backups_do_not_invalidate_restore_metadata(store):
    before = storage_info(store)["restore_revision"]
    store.cache_quotes([Quote(symbol="QA-QUOTE", price=25, prev_close=24, currency="CAD")])
    store.backup()
    assert storage_info(store)["restore_revision"] == before
