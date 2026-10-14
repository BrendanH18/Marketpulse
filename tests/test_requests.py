from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from marketpulse.db import Store
from marketpulse.models import Account, Transaction, TxnType
from marketpulse.requests import AlreadyRecorded, check_request, receipt, record_once


def test_receipt_write_failure_rolls_back_the_transaction(store, monkeypatch):
    acct = store.add_account(Account(name="Fictional TFSA"))
    request_id = str(uuid4())

    def fail_receipt(*args):
        raise OSError("Simulated receipt write failure")

    with monkeypatch.context() as patch:
        patch.setattr(store, "set_meta", fail_receipt)
        with pytest.raises(OSError, match="receipt write failure"):
            record_once(
                store,
                request_id,
                "intent",
                lambda: store.add_transaction(Transaction(account_id=acct.saved_id, type=TxnType.DEPOSIT, amount=100)),
            )
    assert store.transactions() == [] and receipt(store, request_id) is None


def test_receipt_survives_database_reopen(store):
    acct = store.add_account(Account(name="Fictional TFSA"))
    request_id = str(uuid4())
    txn = record_once(
        store,
        request_id,
        "intent",
        lambda: store.add_transaction(Transaction(account_id=acct.saved_id, type=TxnType.DEPOSIT, amount=100)),
    )
    reopened = Store(store.path)
    try:
        with pytest.raises(AlreadyRecorded) as saved:
            check_request(reopened, request_id, "intent")
        assert saved.value.transaction_id == txn.saved_id
        assert len(reopened.transactions()) == 1
    finally:
        reopened.close()


def test_simultaneous_connections_record_the_request_once(store):
    acct = store.add_account(Account(name="Fictional TFSA"))
    other = Store(store.path)
    request_id = str(uuid4())
    ready = Barrier(2)

    def attempt(connection):
        ready.wait(timeout=5)
        try:
            txn = record_once(
                connection,
                request_id,
                "intent",
                lambda: connection.add_transaction(
                    Transaction(account_id=acct.saved_id, type=TxnType.DEPOSIT, amount=100)
                ),
            )
            return ("created", txn.saved_id)
        except AlreadyRecorded as saved:
            return ("existing", saved.transaction_id)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt, connection) for connection in (store, other)]
            results = [future.result(timeout=10) for future in futures]
        assert {state for state, _ in results} == {"created", "existing"}
        assert len({txn_id for _, txn_id in results}) == 1
        assert len(store.transactions()) == 1
    finally:
        other.close()
