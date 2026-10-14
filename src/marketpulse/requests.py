"""Durable receipts for native transaction saves, stored with the ledger write."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import Store
    from .models import Transaction


@dataclass
class TransactionReceipt:
    fingerprint: str
    transaction_id: int


class AlreadyRecorded(Exception):
    def __init__(self, transaction_id: int):
        self.transaction_id = transaction_id


def receipt(store: Store, request_id: str) -> TransactionReceipt | None:
    raw = store.get_meta(f"transaction_request:{request_id}")
    return TransactionReceipt(**json.loads(raw)) if raw is not None else None


def check_request(store: Store, request_id: str, fingerprint: str) -> None:
    saved = receipt(store, request_id)
    if saved is not None:
        if saved.fingerprint != fingerprint:
            raise ValueError(
                "This request ID already recorded a different transaction. Check Activity before saving again."
            )
        # Keep receipts even if an entry is later edited/deleted: retrying an old
        # request must never silently recreate it (including after a database reopen).
        raise AlreadyRecorded(saved.transaction_id)


def record_once(store: Store, request_id: str, fingerprint: str, create: Callable[[], Transaction]) -> Transaction:
    with store.transaction():
        # BEGIN IMMEDIATE serializes simultaneous saves, including separate CLI processes.
        check_request(store, request_id, fingerprint)
        txn = create()
        store.set_meta(
            f"transaction_request:{request_id}",
            json.dumps({"fingerprint": fingerprint, "transaction_id": txn.saved_id}),
        )
    return txn
