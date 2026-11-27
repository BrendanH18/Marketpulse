"""Identical property under two symbols shares one ACB pool (#238), on fictional ledgers.

Each engine test runs the same ledger twice: without links (the result before #238, one
pool per symbol) and with the two lines linked. The figures are worked out by hand.
"""

import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.db import Store, _restore_revision, latest_version
from marketpulse.desktop import ledger_revision
from marketpulse.models import Account, AccountType, Asset, Transaction, TxnType
from marketpulse.tax import DENIED_SUPERFICIAL, compute, foreign_property, pool_symbol

QT = 1  # non-registered (taxable)
WS = 2  # a second non-registered account
TFSA = 3
ACCOUNTS = {
    QT: Account(name="Fictional Taxable", id=QT),
    WS: Account(name="Fictional Margin", id=WS),
    TFSA: Account(name="Fictional TFSA", id=TFSA, type=AccountType.TFSA),
}
CAD_LINE, USD_LINE = "FICT.TO", "FICT-U.TO"  # one fictional fund's CAD and USD listings
LINKED = {USD_LINE: CAD_LINE}
_ids = iter(range(1, 10_000))


def txn(kind, day, symbol, qty=0.0, price=0.0, *, account=QT, ccy="CAD", **kw):
    return Transaction(
        account_id=account,
        type=kind,
        date=day,
        symbol=symbol,
        quantity=qty,
        price=price,
        currency=ccy,
        id=next(_ids),
        **kw,
    )


def fx(day, ccy):
    return 1.35 if ccy == "USD" else 1.0


def both(txns, rates=fx):
    """(before: one pool per symbol, after: the lines linked)."""
    return (
        compute(txns, ACCOUNTS, rates, today="2030-01-01"),
        compute(txns, ACCOUNTS, rates, today="2030-01-01", identical=LINKED),
    )


def test_pool_symbol_maps_only_linked_symbols():
    assert pool_symbol(USD_LINE, LINKED) == CAD_LINE
    assert pool_symbol(CAD_LINE, LINKED) == CAD_LINE
    assert pool_symbol("OTHER", LINKED) == "OTHER" and pool_symbol("OTHER", None) == "OTHER"


def test_sale_of_one_line_uses_the_pooled_cost_of_both():
    # 100 CAD-line units @ CAD 13 = 1,300, and 100 USD-line units @ US$10 x 1.35 = CAD 1,350.
    txns = [
        txn(TxnType.BUY, "2024-01-02", CAD_LINE, 100, 13),
        txn(TxnType.BUY, "2024-02-01", USD_LINE, 100, 10, account=WS, ccy="USD"),
        txn(TxnType.SELL, "2024-06-03", CAD_LINE, 100, 13.5),
    ]
    before, after = both(txns)
    # Before: the CAD line's own cost, 1,300, against 1,350 of proceeds: a 50 gain.
    (d,) = before.dispositions
    assert d.acb == pytest.approx(1300) and d.gain == pytest.approx(50) and d.pool == CAD_LINE
    assert set(before.pools) == {USD_LINE}
    # After: 200 units cost 2,650 together, 13.25 each; 100 of them leave with 1,325: a 25 gain.
    (d,) = after.dispositions
    assert d.acb == pytest.approx(1325) and d.gain == pytest.approx(25)
    assert d.symbol == CAD_LINE and d.pool == CAD_LINE
    (pool,) = after.pools.values()
    assert pool.symbol == CAD_LINE and pool.quantity == pytest.approx(100) and pool.acb == pytest.approx(1325)
    assert pool.held(WS, USD_LINE) == pytest.approx(100)


def test_buying_the_other_line_after_a_loss_is_superficial():
    # Sold 100 CAD-line units at a 500 loss and bought 100 USD-line units two weeks later.
    txns = [
        txn(TxnType.BUY, "2024-01-02", CAD_LINE, 100, 20),
        txn(TxnType.SELL, "2024-03-01", CAD_LINE, 100, 15),
        txn(TxnType.BUY, "2024-03-15", USD_LINE, 100, 11, ccy="USD"),
    ]
    before, after = both(txns)
    (d,) = before.dispositions
    assert d.gain == pytest.approx(-500) and d.denied == 0 and before.pools[USD_LINE].acb == pytest.approx(1485)
    # After: the whole loss is denied and added to the replacement units' cost: 1,485 + 500.
    (d,) = after.dispositions
    assert d.denied == pytest.approx(500) and d.denied_reason == DENIED_SUPERFICIAL
    assert d.acquired_in_window == pytest.approx(100) and d.held_after_window == pytest.approx(100)
    assert after.pools[CAD_LINE].acb == pytest.approx(1985)


def test_split_rows_for_each_line_in_one_account_are_one_split():
    # One account holds both lines; the 2-for-1 split is recorded once for each line.
    # Pre-split purchase in the window: 50 USD-line units = 100 in sale-date units.
    txns = [
        txn(TxnType.BUY, "2024-01-02", CAD_LINE, 100, 10),
        txn(TxnType.BUY, "2024-02-20", USD_LINE, 50, 10),
        txn(TxnType.SPLIT, "2024-03-01", CAD_LINE, ratio=2),
        txn(TxnType.SPLIT, "2024-03-01", USD_LINE, ratio=2),
        txn(TxnType.SELL, "2024-03-10", CAD_LINE, 200, 4),
    ]
    _, after = both(txns, rates=lambda day, ccy: 1.0)
    # Pool: 300 post-split units costing 1,500, 5 each. The sale: 200 x 5 = 1,000 ACB, 800 proceeds.
    (d,) = after.dispositions
    assert d.quantity == pytest.approx(200) and d.acb == pytest.approx(1000) and d.gain == pytest.approx(-200)
    # Counted per account and line, the two rows are one split (x2), not two (x4).
    assert d.acquired_in_window == pytest.approx(100) and d.held_after_window == pytest.approx(100)
    assert d.denied == pytest.approx(200 * 100 / 200)
    assert after.pools[CAD_LINE].holdings == {(QT, CAD_LINE): pytest.approx(0), (QT, USD_LINE): pytest.approx(100)}


def test_one_split_dated_differently_on_each_line_is_one_split():
    txns = [
        txn(TxnType.BUY, "2024-01-02", CAD_LINE, 100, 10),
        txn(TxnType.BUY, "2024-01-02", USD_LINE, 100, 10, account=WS),
        # Pool: 200 units costing 2,000. The sale: ACB 500, proceeds 400, a 100 loss.
        txn(TxnType.SELL, "2024-02-20", CAD_LINE, 50, 8),
        # One 2-for-1 split, recorded on 03-01 for the CAD line and on 03-04 for the USD line.
        txn(TxnType.SPLIT, "2024-03-01", CAD_LINE, ratio=2),
        txn(TxnType.BUY, "2024-03-03", USD_LINE, 40, 8, account=WS),  # before the USD line's row
        txn(TxnType.SPLIT, "2024-03-04", USD_LINE, ratio=2, account=WS),
    ]
    before, after = both(txns, rates=lambda day, ccy: 1.0)
    # Before: the CAD line alone, with nothing bought back in its window.
    (d,) = before.dispositions
    assert d.gain == pytest.approx(-100) and d.denied == 0
    # After, in sale-date (pre-split) units, each line converted by its own split row:
    #   P = 40 USD-line units bought before that line's row = 40
    #   B = (100 CAD-line + 280 USD-line) / 2 = 190 at the end of day +30 (03-21)
    #   denied = 100 x min(50, 40, 190) / 50 = 80
    # Counting each row as its own split (x4) gave P = 20, B = 95 and denied 40.
    (d,) = after.dispositions
    assert d.gain == pytest.approx(-100)
    assert (d.acquired_in_window, d.held_after_window) == (40, 190)
    assert d.denied == pytest.approx(80)
    # The pool's 1,500 after the sale, the 80 denied, and the 320 replacement purchase.
    assert after.pools[CAD_LINE].acb == pytest.approx(1500 + 80 + 320)
    # The split dates no longer need to match, so nothing is flagged.
    assert after.issues == []


def test_a_sale_never_takes_units_of_the_other_line():
    # The account holds 100 of each line; selling 150 of the CAD line only finds its 100.
    txns = [
        txn(TxnType.BUY, "2024-01-02", CAD_LINE, 100, 10),
        txn(TxnType.BUY, "2024-01-02", USD_LINE, 100, 10),
        txn(TxnType.SELL, "2024-06-03", CAD_LINE, 150, 12),
    ]
    _, after = both(txns, rates=lambda day, ccy: 1.0)
    (d,) = after.dispositions
    assert d.quantity == pytest.approx(100) and d.acb == pytest.approx(1000)


def test_transfers_move_one_line_and_a_deemed_sale_uses_the_pooled_cost():
    txns = [
        txn(TxnType.BUY, "2024-01-02", CAD_LINE, 100, 10),
        txn(TxnType.BUY, "2024-01-03", USD_LINE, 100, 20, account=WS),
        # Taxable to taxable: the USD line moves; the pool and its cost are unchanged.
        txn(TxnType.TRANSFER, "2024-02-01", USD_LINE, 100, account=WS, target_account_id=QT),
        # Into the TFSA at 18: a deemed sale at the pooled 15 per unit.
        txn(TxnType.TRANSFER, "2024-03-01", CAD_LINE, 50, 18, target_account_id=TFSA),
    ]
    before, after = both(txns, rates=lambda day, ccy: 1.0)
    (d,) = before.dispositions
    assert d.kind == "deemed" and d.acb == pytest.approx(500) and d.gain == pytest.approx(400)
    (d,) = after.dispositions
    assert d.kind == "deemed" and d.acb == pytest.approx(750) and d.gain == pytest.approx(150)
    pool = after.pools[CAD_LINE]
    assert pool.held(QT, USD_LINE) == pytest.approx(100) and pool.held(WS, USD_LINE) == pytest.approx(0)
    assert pool.held(QT, CAD_LINE) == pytest.approx(50) and pool.acb == pytest.approx(2250)


def test_a_loss_guessed_without_a_rate_leaves_the_other_lines_later_sale_incomplete():
    # The USD line's sale has no rate, so its loss (and the part denied) is a guess. The denied
    # amount goes into the CAD line bought two weeks later, whose own rate is always known.
    def rates(day, ccy):
        return 1.0 if ccy == "CAD" else (1.35 if day < "2024-02-01" else None)

    txns = [
        txn(TxnType.BUY, "2024-01-02", USD_LINE, 100, 20, ccy="USD"),
        txn(TxnType.SELL, "2024-03-01", USD_LINE, 100, 15, ccy="USD"),
        txn(TxnType.BUY, "2024-03-15", CAD_LINE, 100, 20),
        txn(TxnType.SELL, "2024-06-03", CAD_LINE, 100, 21),
    ]
    _, after = both(txns, rates)
    guessed, later = after.dispositions
    assert not guessed.complete and guessed.denied == pytest.approx(2700)
    assert later.acb == pytest.approx(2000 + 2700) and not later.complete


def test_return_of_capital_on_a_line_not_held_leaves_the_pool_alone():
    txns = [
        txn(TxnType.BUY, "2024-01-02", CAD_LINE, 100, 10),
        txn(TxnType.ROC, "2024-02-01", USD_LINE, amount=50, ccy="USD"),
    ]
    _, after = both(txns)
    assert after.pools[CAD_LINE].acb == pytest.approx(1000) and after.dispositions == []


def test_t1135_shows_a_linked_pool_once_under_its_pool_symbol():
    # A fictional US company listed in New York (foreign by listing) and in Toronto.
    us, ca = "FICTCO", "FICTCO.TO"
    txns = [
        txn(TxnType.BUY, "2024-01-02", us, 500, 100, ccy="USD"),  # 67,500 CAD
        txn(TxnType.BUY, "2024-01-03", ca, 300, 135),  # 40,500 CAD
    ]
    run = lambda links: foreign_property(txns, ACCOUNTS, {}, fx, 2024, today="2025-06-01", identical=links)  # noqa: E731
    before, after = run(None), run({ca: us})
    assert [h.symbol for h in before.holdings] == [us] and before.max_cost == pytest.approx(67_500)
    assert before.status == "not_required"
    (h,) = after.holdings
    assert h.symbol == us and h.max_cost == pytest.approx(108_000) and after.status == "simplified"


# ── Store, CLI and bridge ─────────────────────────────────────────────────────


def test_links_are_one_level_deep_and_survive_reopening(tmp_path):
    path = tmp_path / "ledger.db"
    store = Store(path)
    assert store.schema_version == latest_version() >= 5
    for sym in ("FICT.TO", "FICT-U.TO", "FICT.NE"):
        store.upsert_asset(Asset(symbol=sym))
    with pytest.raises(ValueError, match="FICT.T0 has no transactions or asset entry"):
        store.link_identical("FICT-U.TO", "FICT.T0")
    store.link_identical("fict-u.to", " fict.to ")
    with pytest.raises(ValueError, match="linked to FICT.TO. Link OTHER to FICT.TO instead"):
        store.link_identical("OTHER", "FICT-U.TO")
    with pytest.raises(ValueError, match="FICT-U.TO is linked to FICT.TO"):
        store.link_identical("FICT.TO", "ELSE")
    with pytest.raises(ValueError, match="own pool"):
        store.link_identical("SAME", "same")
    store.link_identical("FICT.NE", "FICT.TO", dry_run=True)
    store.close()
    store = Store(path)
    assert store.identical_property() == {"FICT-U.TO": "FICT.TO"}
    assert store.unlink_identical("FICT-U.TO", dry_run=True) == "FICT.TO"
    assert store.unlink_identical("FICT-U.TO") == "FICT.TO" and store.unlink_identical("FICT-U.TO") is None
    assert store.identical_property() == {}
    store.close()


def test_links_change_the_restore_revision(tmp_path):
    store = Store(tmp_path / "ledger.db")
    for sym in (CAD_LINE, USD_LINE):
        store.upsert_asset(Asset(symbol=sym))
    unlinked = _restore_revision(store._conn)
    store.link_identical(USD_LINE, CAD_LINE)
    assert _restore_revision(store._conn) != unlinked
    store.unlink_identical(USD_LINE)
    assert _restore_revision(store._conn) == unlinked
    # A ledger from before schema 5 has no links, so its revision matches an empty table's.
    store._conn.execute("DROP TABLE identical_property")
    assert _restore_revision(store._conn) == unlinked
    store.close()


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "160")
    return lambda *args: CliRunner().invoke(main, list(args), catch_exceptions=False)


def test_cli_links_symbols_and_the_tax_report_pools_them(cli, tracker, store):
    acct = store.add_account(Account(name="Fictional Taxable", type=AccountType.NONREG))
    for kind, day, sym, qty, price in [
        (TxnType.BUY, "2024-01-02", CAD_LINE, 100, 10),
        (TxnType.BUY, "2024-01-03", "FICT.NE", 100, 20),
        (TxnType.SELL, "2024-06-03", CAD_LINE, 100, 18),
    ]:
        store.add_transaction(
            Transaction(account_id=acct.saved_id, type=kind, date=day, symbol=sym, quantity=qty, price=price)
        )
    gain = lambda: json.loads(cli("tax", "--json").output)[0]["gain"]  # noqa: E731
    revision = ledger_revision(tracker)
    assert gain() == pytest.approx(800)  # 1,800 - 1,000: the CAD line's own cost

    assert json.loads(cli("tax", "link", "fict.ne", "FICT.TO", "--dry-run", "--json").output) == {
        "symbol": "FICT.NE",
        "pool": "FICT.TO",
        "saved": False,
    }
    assert store.identical_property() == {}
    r = cli("tax", "link", "FICT.NE", "FICT.TO")
    assert r.exit_code == 0 and "FICT.NE now shares FICT.TO's cost base" in r.output
    assert gain() == pytest.approx(300)  # 1,800 - 100 x (3,000 / 200)
    assert ledger_revision(tracker) != revision

    r = cli("tax", "links")
    assert "Identical property" in r.output and "FICT.NE" in r.output
    assert json.loads(cli("tax", "links", "--json").output) == [{"symbol": "FICT.NE", "pool": "FICT.TO"}]

    r = cli("tax", "link", "FICT.TO", "OTHER")
    assert r.exit_code == 1 and "FICT.NE is linked to FICT.TO" in r.output

    r = cli("tax", "unlink", "FICT.NE", "--json")
    assert json.loads(r.output) == {"symbol": "FICT.NE", "pool": "FICT.TO", "saved": True}
    assert gain() == pytest.approx(800) and ledger_revision(tracker) == revision
    r = cli("tax", "unlink", "FICT.NE")
    assert r.exit_code == 1 and "isn't linked" in r.output
    assert "No linked symbols" in cli("tax", "links").output
