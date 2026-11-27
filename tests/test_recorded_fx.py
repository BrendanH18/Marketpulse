"""A transaction can record the FX rate the broker charged (#241).

Tax (capital gains, transfers, T1135 cost) and contribution room then convert it at that rate
instead of the one looked up for its date, and it no longer counts as missing a rate. Each
test shows the looked-up result first, then the recorded one. All data here is fictional."""

import asyncio
import io
import json
import math
from dataclasses import replace
from datetime import date

import pytest
from click.testing import CliRunner
from textual.widgets import Input

from marketpulse import tax
from marketpulse.cli import main
from marketpulse.config import Config
from marketpulse.csvio import export_transactions, import_transactions
from marketpulse.desktop import activity_row
from marketpulse.ledger import contribution_room, replay
from marketpulse.models import Account, AccountType, CodedError, Transaction, TxnType
from marketpulse.services import Tracker
from marketpulse.tui.app import MarketPulseApp
from marketpulse.tui.screens import TransactionForm

LOOKED_UP = {"2025-01-02": 1.30, "2025-03-03": 1.40}


def _taxable(store) -> Account:
    return store.add_account(Account(name="Fictional Taxable"))


def _trade(acct, kind, day, price, fx_rate=None, **fields) -> Transaction:
    return Transaction(
        account_id=acct.saved_id,
        type=kind,
        date=day,
        symbol="AAPL",
        quantity=fields.pop("quantity", 1),
        price=price,
        currency="USD",
        fx_rate=fx_rate,
        **fields,
    )


# ── capital gains ─────────────────────────────────────────────────────────────


def test_a_usd_buy_and_sell_gain_in_cad_at_the_recorded_rates(tracker, store, fake):
    acct = _taxable(store)
    buy = tracker.add_transaction(_trade(acct, TxnType.BUY, "2025-01-02", 100))
    sell = tracker.add_transaction(_trade(acct, TxnType.SELL, "2025-03-03", 150))
    fake.set_history("USDCAD=X", LOOKED_UP, currency="CAD")

    # Before: US$100 at the looked-up 1.30 and US$150 at 1.40 give C$210 - C$130 = C$80.
    (year,), _ = tracker.tax_years()
    assert year.net_gain == pytest.approx(80)

    # After: the broker charged 1.32 on the buy and 1.45 on the sale, so C$217.50 - C$132.
    buy.fx_rate, sell.fx_rate = 1.32, 1.45
    tracker.update_transaction(buy)
    tracker.update_transaction(sell)
    (year,), report = tracker.tax_years()
    assert year.net_gain == pytest.approx(85.5)
    (d,) = report.dispositions
    assert d.fx == 1.45 and d.acb == pytest.approx(132) and d.proceeds == pytest.approx(217.5) and d.complete


def test_one_recorded_rate_is_used_and_the_other_leg_is_looked_up(store):
    acct = _taxable(store)
    txns = [
        _trade(acct, TxnType.BUY, "2025-01-02", 100, id=1),
        _trade(acct, TxnType.SELL, "2025-03-03", 150, fx_rate=1.45, id=2),
    ]
    fx = tax.fx_lookup({"USD": LOOKED_UP}, "CAD")
    accounts = store.account_map()
    # A recorded rate is CAD per unit, so it is used only when fx_on converts into CAD too.
    assert tax.compute(txns, accounts, fx).dispositions[0].gain == pytest.approx(80)
    assert tax.compute(txns, accounts, fx, fx_currency="USD").dispositions[0].gain == pytest.approx(80)
    (d,) = tax.compute(txns, accounts, fx, fx_currency="CAD").dispositions
    assert d.gain == pytest.approx(150 * 1.45 - 130)


def test_a_trade_with_a_recorded_rate_is_complete_without_any_historical_rate(tracker, store, fake):
    acct = _taxable(store)
    tracker.add_transaction(_trade(acct, TxnType.BUY, "2025-01-02", 100))
    sell = tracker.add_transaction(_trade(acct, TxnType.SELL, "2025-03-03", 150))
    fake.offline = True  # no USD/CAD history at all

    # Before: neither leg has a rate, so the sale is incomplete and left out of the total.
    (year,), _ = tracker.tax_years()
    assert len(year.missing_fx) == 1 and year.net_gain == 0

    # After: with both legs recorded, nothing is missing and no rate is even requested.
    for t in store.transactions():
        t.fx_rate = 1.32 if t.id != sell.id else 1.45
        tracker.update_transaction(t)
    fake.calls.clear()
    (year,), report = tracker.tax_years()
    assert year.missing_fx == [] and year.net_gain == pytest.approx(85.5)
    assert report.dispositions[0].complete
    assert not [url for url, _ in fake.calls if "USDCAD" in url]


def test_recorded_rates_apply_to_drip_roc_acb_increase_and_transfers(store):
    acct = _taxable(store)
    tfsa = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
    accounts = store.account_map()

    def amount(kind, day, value, fx_rate, i):
        return Transaction(
            id=i,
            account_id=acct.saved_id,
            type=kind,
            date=day,
            symbol="AAPL",
            amount=value,
            currency="USD",
            fx_rate=fx_rate,
        )

    txns = [
        _trade(acct, TxnType.BUY, "2025-01-02", 100, fx_rate=1.25, quantity=4, id=1),
        _trade(acct, TxnType.DRIP, "2025-02-03", 100, fx_rate=1.5, id=2),
        amount(TxnType.ACB_INCREASE, "2025-02-10", 10, 2.0, 3),
        amount(TxnType.ROC, "2025-02-20", 20, 1.5, 4),
        _trade(acct, TxnType.TRANSFER, "2025-03-03", 120, fx_rate=1.6, quantity=5, target_account_id=tfsa.id, id=5),
    ]
    fx = tax.fx_lookup({}, "CAD")  # no historical rates at all
    looked_up = tax.compute(txns, accounts, fx)
    assert not looked_up.dispositions[0].complete
    (d,) = tax.compute(txns, accounts, fx, fx_currency="CAD").dispositions
    # ACB: 400 x 1.25 + 100 x 1.5 + 10 x 2 - 20 x 1.5 = 640; proceeds 5 x 120 x 1.6 = 960.
    assert d.kind == "deemed" and d.complete
    assert d.acb == pytest.approx(640) and d.proceeds == pytest.approx(960) and d.fx == 1.6


def test_t1135_cost_uses_recorded_rates(tracker, store, fake):
    acct = _taxable(store)
    tracker.add_transaction(_trade(acct, TxnType.BUY, "2025-01-02", 100, fx_rate=1.32, quantity=1000))
    fake.offline = True
    (year,) = [y for y in tracker.foreign_property() if y.year == 2025]
    assert year.max_cost == pytest.approx(132000) and not year.incomplete
    # The estimate is in CAD, so a rate looked up in another currency would be ignored.
    accounts = store.account_map()
    fx = tax.fx_lookup({"USD": {"2025-01-02": 1.30}}, "CAD")
    (looked_up,) = [
        y
        for y in tax.foreign_property_years(store.transactions(), accounts, {}, fx, today="2025-12-31", currency="USD")
        if y.year == 2025
    ]
    assert looked_up.max_cost == pytest.approx(130000)


def test_recorded_rates_mean_cad_whatever_the_base_currency(tracker, store, fake):
    """Changing the base currency never reinterprets a saved rate (CAD per unit)."""
    year = date.today().year
    acct = _taxable(store)
    tfsa = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
    store.set_room("TFSA", year, 7000)
    tracker.add_transaction(_trade(acct, TxnType.BUY, "2025-01-02", 100, fx_rate=1.32, quantity=1000))
    tracker.add_transaction(_trade(acct, TxnType.SELL, "2025-03-03", 150, fx_rate=1.45, quantity=1))
    tracker.add_transaction(
        Transaction(tfsa.saved_id, TxnType.DEPOSIT, f"{year}-01-01", amount=1000, currency="USD", fx_rate=1.38)
    )
    fake.offline = True
    usd = Tracker(store, tracker.market, Config(base_currency="USD"))

    # Capital gains in USD don't convert USD trades, so the CAD rates are left out: US$150 - US$100.
    (gains,), _ = usd.tax_years()
    assert gains.net_gain == pytest.approx(50)
    # T1135 and contribution room are always in CAD, so they still use the recorded rates.
    (t1135,) = [y for y in usd.foreign_property() if y.year == 2025]
    assert t1135.max_cost == pytest.approx(132000) and not t1135.incomplete
    [(room, _)] = usd.room()
    assert room.contributions == pytest.approx(1380) and room.missing_fx == []


# ── contribution room ─────────────────────────────────────────────────────────


def test_a_usd_tfsa_contribution_counts_at_its_recorded_rate(tracker, store, fake):
    year = date.today().year
    tfsa = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
    store.set_room("TFSA", year, 7000)
    deposit = tracker.add_transaction(
        Transaction(tfsa.saved_id, TxnType.DEPOSIT, f"{year}-01-01", amount=1000, currency="USD")
    )
    fake.set_history("USDCAD=X", {f"{year}-01-01": 1.30}, currency="CAD")

    # Before: US$1,000 at the looked-up 1.30.
    [(status, _)] = tracker.room()
    assert status.contributions == pytest.approx(1300) and status.remaining == pytest.approx(5700)

    # After: the broker converted at 1.38, and that rate needs no lookup at all.
    deposit.fx_rate = 1.38
    tracker.update_transaction(deposit)
    fake.calls.clear()
    [(status, _)] = tracker.room()
    assert status.contributions == pytest.approx(1380) and status.remaining == pytest.approx(5620)
    assert status.missing_fx == [] and not [url for url, _ in fake.calls if "USDCAD" in url]
    [(offline, _)] = tracker.room(offline=True)
    assert offline.remaining == pytest.approx(5620)


def test_room_uses_recorded_rates_for_withdrawals_and_in_kind_contributions():
    year = date.today().year
    accounts = {
        1: Account(name="Fictional Taxable", id=1),
        2: Account(name="Fictional TFSA", type=AccountType.TFSA, id=2),
    }
    txns = [
        Transaction(1, TxnType.BUY, f"{year - 1}-01-02", "AAPL", 10, 100, currency="USD", id=1),
        Transaction(
            1,
            TxnType.TRANSFER,
            f"{year - 1}-02-03",
            "AAPL",
            10,
            120,
            currency="USD",
            target_account_id=2,
            id=2,
            fx_rate=1.25,
        ),
        Transaction(2, TxnType.WITHDRAWAL, f"{year - 1}-03-04", amount=500, currency="USD", id=3, fx_rate=1.4),
    ]

    def flows(entries):
        state = replay(entries, accounts)
        return [*state.flows, *state.in_kind_contributions]

    unrecorded = [replace(t, fx_rate=None) for t in txns]
    looked_up = contribution_room("TFSA", year - 1, 7000, flows(unrecorded), {2}, current_year=year)
    assert looked_up.remaining is None and len(looked_up.missing_fx) == 2
    status = contribution_room("TFSA", year - 1, 7000, flows(txns), {2}, current_year=year)
    assert status.contributions == pytest.approx(1500)  # 10 x US$120 x 1.25
    assert status.withdrawals_added_back == pytest.approx(700)  # US$500 x 1.4
    assert status.remaining == pytest.approx(7000 + status.new_limits + 700 - 1500)


# ── validation ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rate", [0.0, -1.3, math.nan, math.inf])
def test_a_rate_must_be_positive_and_finite(rate):
    txn = Transaction(1, TxnType.BUY, "2025-01-02", "AAPL", 1, 100, currency="USD", fx_rate=rate)
    with pytest.raises(CodedError, match="FX rate must be a positive number") as e:
        txn.validate()
    assert e.value.code == "fx_rate_not_positive"


@pytest.mark.parametrize("kind", [TxnType.DIVIDEND, TxnType.INTEREST, TxnType.FEE, TxnType.SPLIT, TxnType.VALUATION])
def test_types_that_never_convert_refuse_a_rate(kind):
    txn = Transaction(1, kind, "2025-01-02", "AAPL", 1, 100, amount=5, ratio=2, currency="USD", fx_rate=1.3)
    with pytest.raises(CodedError, match="doesn't use an FX rate") as e:
        txn.validate()
    assert e.value.code == "fx_rate_unused" and e.value.details == {"type": kind.value}


def test_a_rate_on_an_entry_in_cad_is_refused(tracker, store):
    acct = _taxable(store)
    with pytest.raises(CodedError, match="only applies to an entry in a currency other than CAD") as e:
        tracker.add_transaction(
            Transaction(acct.saved_id, TxnType.BUY, "2025-01-02", "XEQT.TO", 1, 30, currency="CAD", fx_rate=1.0)
        )
    assert e.value.code == "fx_rate_cad_entry"
    # The currency is worked out first: XEQT.TO is listed in CAD.
    with pytest.raises(ValueError, match="other than CAD"):
        tracker.add_transaction(Transaction(acct.saved_id, TxnType.BUY, "2025-01-02", "XEQT.TO", 1, 30, fx_rate=1.2))
    saved = tracker.add_transaction(_trade(acct, TxnType.BUY, "2025-01-02", 100, fx_rate=1.3))
    saved.currency = "CAD"
    with pytest.raises(ValueError, match="other than CAD"):
        tracker.update_transaction(saved)
    assert [t.fx_rate for t in store.transactions()] == [1.3]
    # The rate is CAD per unit whatever the base: with a USD base, a CAD entry still can't have one.
    usd = Tracker(store, tracker.market, Config(base_currency="USD"))
    with pytest.raises(ValueError, match="other than CAD"):
        usd.add_transaction(
            Transaction(acct.saved_id, TxnType.BUY, "2025-01-02", "XEQT.TO", 1, 30, currency="CAD", fx_rate=0.74)
        )
    usd.add_transaction(_trade(acct, TxnType.BUY, "2025-01-02", 100, fx_rate=1.36))


def test_an_edit_cant_carry_a_rate_to_another_currency(tracker, store):
    """The TUI and Mac app save through the tracker, so it refuses what `txn edit` does."""
    acct = _taxable(store)
    tfsa = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
    deposit = tracker.add_transaction(
        Transaction(tfsa.saved_id, TxnType.DEPOSIT, "2025-01-02", amount=1000, currency="USD", fx_rate=1.38)
    )
    deposit.currency = "EUR"
    with pytest.raises(CodedError, match="has an FX rate for USD") as e:
        tracker.update_transaction(deposit)
    assert e.value.code == "fx_rate_currency_changed" and e.value.details == {"from": "USD", "to": "EUR"}
    assert [(t.currency, t.fx_rate) for t in store.transactions()] == [("USD", 1.38)]
    # A new rate, or none, goes with the new currency; other edits keep the rate.
    for rate in (1.52, None):
        deposit.fx_rate = rate
        tracker.update_transaction(deposit)
        assert [(t.currency, t.fx_rate) for t in store.transactions()] == [("EUR", rate)]
    buy = tracker.add_transaction(_trade(acct, TxnType.BUY, "2025-01-02", 100, fx_rate=1.3))
    buy.note = "fictional"
    tracker.update_transaction(buy)
    assert store.transactions()[-1].fx_rate == 1.3


# ── CSV ───────────────────────────────────────────────────────────────────────

CSV = """date,account,type,symbol,quantity,price,currency,fx_rate_to_cad
2025-01-02,Fictional Taxable,BUY,AAPL,1,100,USD,1.32
2025-03-03,Fictional Taxable,SELL,AAPL,1,150,USD,1.45
2025-03-04,Fictional Taxable,BUY,XEQT.TO,1,30,CAD,1.1
2025-03-05,Fictional Taxable,DIVIDEND,AAPL,,,USD,1.4
2025-03-06,Fictional Taxable,BUY,AAPL,1,150,USD,-2
2025-03-07,Fictional Taxable,BUY,AAPL,1,150,USD,
2025-03-08,Fictional Taxable,BUY,AAPL,1,150,USD,"1,3612"
"""


def test_csv_import_reads_the_rate_and_skips_rows_it_cant_use(store):
    _taxable(store)
    preview = import_transactions(store, io.StringIO(CSV), dry_run=True)
    assert store.transactions() == []
    result = import_transactions(store, io.StringIO(CSV), expect_fingerprint=preview.fingerprint)
    # The preview runs the real import, so it reports exactly what the import then does.
    assert (preview.added, preview.skipped, preview.issues) == (result.added, result.skipped, result.issues)
    assert result.added == 3
    assert [(t.symbol, t.fx_rate) for t in store.transactions()] == [("AAPL", 1.32), ("AAPL", 1.45), ("AAPL", None)]
    assert [(i.line, i.field, i.value, i.code) for i in result.issues] == [
        (4, "fx_rate_to_cad", "1.1", "fx_rate_cad_entry"),
        (5, "fx_rate_to_cad", "1.4", "fx_rate_unused"),
        (6, "fx_rate_to_cad", "-2", "fx_rate_not_positive"),
        (8, "fx_rate_to_cad", "1,3612", "not_a_number"),  # a decimal comma, which would otherwise read as 13612
    ]


def test_a_brokers_own_fx_rate_column_is_not_taken_as_the_recorded_rate(store):
    # Brokers quote their column either way round and fill it on CAD and dividend rows too.
    _taxable(store)
    broker = """date,account,type,symbol,quantity,price,amount,currency,FX Rate
2025-01-02,Fictional Taxable,BUY,AAPL,1,100,,USD,0.7353
2025-01-03,Fictional Taxable,DIVIDEND,XEQT.TO,,,5,CAD,1.0000
"""
    result = import_transactions(store, io.StringIO(broker))
    assert (result.added, result.issues) == (2, [])
    assert [t.fx_rate for t in store.transactions()] == [None, None]


def test_csv_export_round_trips_the_rate(tmp_path, store):
    from marketpulse.db import Store

    acct = _taxable(store)
    store.add_transaction(_trade(acct, TxnType.BUY, "2025-01-02", 100, fx_rate=1.3612345678))
    store.add_transaction(_trade(acct, TxnType.SELL, "2025-03-03", 150))
    out = io.StringIO()
    assert export_transactions(store, out) == 2
    lines = out.getvalue().splitlines()
    assert lines[0].endswith(",target_account,fx_rate_to_cad")
    assert lines[1].endswith(",1.3612345678") and lines[2].endswith(",,")
    fresh = Store(tmp_path / "fresh.db")
    try:
        result = import_transactions(fresh, io.StringIO(out.getvalue()))
        assert result.added == 2 and result.issues == []
        assert [t.fx_rate for t in fresh.transactions()] == [1.3612345678, None]
        # Importing the export again finds every row already there.
        assert import_transactions(fresh, io.StringIO(out.getvalue())).duplicates == 2
    finally:
        fresh.close()


# ── CLI ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "200")
    return lambda *args: CliRunner().invoke(main, list(args), catch_exceptions=False)


def test_cli_records_and_edits_the_rate(cli, store):
    taxable = _taxable(store)
    tfsa = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
    for args in (
        ("buy", "AAPL", "10", "100", "-d", "2025-01-02", "-a", "Fictional Taxable", "--fx-rate", "1.32"),
        ("sell", "AAPL", "2", "150", "-d", "2025-03-03", "-a", "Fictional Taxable", "--fx-rate", "1.45"),
        ("deposit", "500", "-c", "USD", "-d", "2025-03-04", "-a", "Fictional TFSA", "--fx-rate", "1.4"),
        ("withdraw", "100", "-c", "USD", "-d", "2025-03-05", "-a", "Fictional TFSA", "--fx-rate", "1.41"),
        ("drip", "AAPL", "1", "140", "-d", "2025-03-06", "-a", "Fictional Taxable", "--fx-rate", "1.42"),
        ("roc", "AAPL", "5", "-d", "2025-03-07", "-a", "Fictional Taxable", "--fx-rate", "1.43"),
        ("acb-increase", "AAPL", "3", "-d", "2025-03-08", "-a", "Fictional Taxable", "--fx-rate", "1.44"),
        (
            "transfer",
            "AAPL",
            "1",
            "--from",
            "Fictional Taxable",
            "--to",
            "Fictional TFSA",
            "-p",
            "160",
            "--fx-rate",
            "1.46",
        ),
    ):
        result = cli(*args)
        assert result.exit_code == 0, result.output
    assert [(t.type.value, t.fx_rate) for t in store.transactions()] == [
        ("BUY", 1.32),
        ("SELL", 1.45),
        ("DEPOSIT", 1.4),
        ("WITHDRAWAL", 1.41),
        ("DRIP", 1.42),
        ("ROC", 1.43),
        ("ACB_INCREASE", 1.44),
        ("TRANSFER", 1.46),
    ]
    assert store.transactions()[-1].target_account_id == tfsa.saved_id

    buy = store.transactions()[0]
    dry = cli("txn", "edit", str(buy.id), "--fx-rate", "1.3", "--dry-run")
    assert dry.exit_code == 0 and "fx_rate" in dry.output and "1.32" in dry.output and "1.3" in dry.output
    assert store.transactions()[0].fx_rate == 1.32
    assert cli("txn", "edit", str(buy.id), "--fx-rate", "1.3").exit_code == 0
    assert store.transactions()[0].fx_rate == 1.3
    shown = json.loads(cli("txn", "show", str(buy.id), "--json").output)
    assert shown["fx_rate"] == 1.3
    assert cli("txn", "edit", str(buy.id), "--fx-rate", "").exit_code == 0
    assert store.transactions()[0].fx_rate is None
    assert taxable.saved_id == buy.account_id


def test_cli_edit_refuses_to_carry_a_rate_to_another_currency(cli, store):
    _taxable(store)
    assert cli("buy", "AAPL", "1", "100", "-d", "2025-01-02", "--fx-rate", "1.32").exit_code == 0
    (buy,) = store.transactions()
    hint = 'Give a new --fx-rate, or remove it with --fx-rate "".'
    for args in (("--currency", "EUR"), ("--symbol", "XEQT.TO"), ("--currency", "EUR", "--dry-run")):
        refused = cli("txn", "edit", str(buy.id), *args)
        assert refused.exit_code == 1, args
        assert (
            "has an FX rate for USD, and this edit changes its currency to" in refused.output and hint in refused.output
        )
    assert (store.transactions()[0].currency, store.transactions()[0].fx_rate) == ("USD", 1.32)
    # The Mac editor sends every field, with a blank currency worked out again: the same one keeps the rate.
    assert cli("txn", "edit", str(buy.id), "--currency", "", "--note", "kept").exit_code == 0
    assert (store.transactions()[0].currency, store.transactions()[0].fx_rate) == ("USD", 1.32)
    assert cli("txn", "edit", str(buy.id), "--currency", "EUR", "--fx-rate", "1.5").exit_code == 0
    assert (store.transactions()[0].currency, store.transactions()[0].fx_rate) == ("EUR", 1.5)
    # A rate given for the new currency is kept even when it equals the old one, as the preview says.
    for extra in (("--dry-run",), ()):
        assert cli("txn", "edit", str(buy.id), "--currency", "GBP", "--fx-rate", "1.5", *extra).exit_code == 0
    assert (store.transactions()[0].currency, store.transactions()[0].fx_rate) == ("GBP", 1.5)
    assert cli("txn", "edit", str(buy.id), "--currency", "CAD", "--fx-rate", "").exit_code == 0
    assert (store.transactions()[0].currency, store.transactions()[0].fx_rate) == ("CAD", None)


def test_cli_edit_preview_works_out_a_blank_currency_as_the_save_does(cli, store):
    acct = _taxable(store)
    # A USD purchase of a Toronto listing: an ACB increase takes the holding's USD, not the CAD
    # that the .TO suffix suggests.
    store.add_transaction(Transaction(acct.saved_id, TxnType.BUY, "2025-01-02", "FICT.TO", 10, 10, currency="USD"))
    assert cli("acb-increase", "FICT.TO", "5", "-d", "2025-02-03").exit_code == 0
    increase = store.transactions()[-1]
    assert increase.currency == "USD"
    args = ("txn", "edit", str(increase.id), "--currency", "", "--fx-rate", "1.3")
    preview = cli(*args, "--dry-run")
    assert preview.exit_code == 0 and "would update" in preview.output, preview.output
    assert cli(*args).exit_code == 0
    assert (store.transactions()[-1].currency, store.transactions()[-1].fx_rate) == ("USD", 1.3)


def test_cli_refuses_a_rate_it_cant_use(cli, store):
    _taxable(store)
    for value in ("0", "-1", "nan", "inf"):
        bad = cli("buy", "AAPL", "1", "100", "-d", "2025-01-02", "--fx-rate", value)
        assert bad.exit_code == 2 and "must be a positive number" in bad.output
    cad = cli("buy", "XEQT.TO", "1", "30", "-d", "2025-01-02", "--fx-rate", "1.1")
    assert cad.exit_code == 1 and "other than CAD" in cad.output
    dry = cli("buy", "XEQT.TO", "1", "30", "-d", "2025-01-02", "--fx-rate", "1.1", "--dry-run")
    assert dry.exit_code == 1 and "other than CAD" in dry.output
    assert store.transactions() == []
    assert cli("buy", "AAPL", "1", "100", "-d", "2025-01-02").exit_code == 0
    (buy,) = store.transactions()
    edit = cli("txn", "edit", str(buy.id), "--fx-rate", "abc")
    assert edit.exit_code == 2 and "is not a number" in edit.output
    refused = cli("txn", "edit", str(buy.id), "--currency", "CAD", "--fx-rate", "1.3", "--dry-run")
    assert refused.exit_code == 1 and "other than CAD" in refused.output
    assert store.transactions()[0].fx_rate is None


def test_cli_receipt_and_export_include_the_rate(cli, store):
    _taxable(store)
    receipt = json.loads(cli("buy", "AAPL", "1", "100", "-d", "2025-01-02", "--fx-rate", "1.3", "--json").output)
    assert receipt["fx_rate"] == 1.3
    exported = cli("export", "--columns", "symbol,fx_rate_to_cad").output.splitlines()
    assert exported == ["symbol,fx_rate_to_cad", "AAPL,1.3"]
    jsonl = cli("export", "--columns", "symbol,fx_rate_to_cad", "--jsonl").output.splitlines()
    assert [json.loads(line) for line in jsonl] == [{"symbol": "AAPL", "fx_rate_to_cad": 1.3}]


def test_retry_fingerprint_without_a_rate_is_unchanged(cli, store):
    """A save retried by the app gets the same fingerprint it had before `--fx-rate` existed."""
    import hashlib

    from marketpulse.requests import AlreadyRecorded, check_request

    _taxable(store)
    request_id = "7d5e1b4c-0000-4000-8000-000000000241"
    assert cli("deposit", "--request-id", request_id, "-c", "CAD", "--", "12.5").exit_code == 0
    fields = {"account": None, "amount": 12.5, "currency": "CAD", "note": "", "when": None}
    legacy = hashlib.sha256(json.dumps(["deposit", fields], sort_keys=True).encode()).hexdigest()
    with pytest.raises(AlreadyRecorded):
        check_request(store, request_id, legacy)


# ── desktop bridge and TUI ────────────────────────────────────────────────────


def test_desktop_activity_rows_carry_the_rate(store):
    acct = _taxable(store)
    saved = store.add_transaction(_trade(acct, TxnType.BUY, "2025-01-02", 100, fx_rate=1.32))
    row = activity_row(saved, store.account_map())
    assert row["fx_rate"] == 1.32
    assert activity_row(_trade(acct, TxnType.BUY, "2025-01-02", 100), store.account_map())["fx_rate"] is None


def test_tui_form_records_the_rate_for_types_that_use_it(tracker, store):
    acct = _taxable(store)

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            form = TransactionForm(tracker, kind=TxnType.BUY, account_id=acct.saved_id)
            results: list[Transaction | None] = []
            await app.push_screen(form, results.append)
            await pilot.pause()
            fx = form.query_one("#f-fx", Input)
            assert fx.display and fx.placeholder == "FX rate to CAD (optional)"
            form.query_one("#f-symbol", Input).value = "AAPL"
            form.query_one("#f-quantity", Input).value = "3"
            form.query_one("#f-price", Input).value = "150"
            form.query_one("#f-currency", Input).value = "USD"
            form.query_one("#f-date", Input).value = "2025-01-02"
            fx.value = "0"
            form.action_save()
            await pilot.pause()
            assert results == [] and "FX rate must be a positive number" in str(form.query_one("#form-error").content)
            form.query_one("#f-currency", Input).value = "CAD"
            fx.value = "1.36"
            form.action_save()
            await pilot.pause()
            assert results == [] and "other than CAD" in str(form.query_one("#form-error").content)
            form.query_one("#f-currency", Input).value = "USD"
            form.action_save()
            await pilot.pause()
            assert len(results) == 1 and results[0] is not None and results[0].fx_rate == 1.36

            # A dividend never converts, so the field is hidden and its value isn't kept.
            dividend = TransactionForm(tracker, kind=TxnType.DIVIDEND, account_id=acct.saved_id)
            await app.push_screen(dividend, results.append)
            await pilot.pause()
            assert not dividend.query_one("#f-fx", Input).display
            dividend.query_one("#f-fx", Input).value = "1.36"
            dividend.query_one("#f-symbol", Input).value = "AAPL"
            dividend.query_one("#f-amount", Input).value = "5"
            dividend.query_one("#f-currency", Input).value = "USD"
            dividend.action_save()
            await pilot.pause()
            assert len(results) == 2 and results[1] is not None and results[1].fx_rate is None

            # Editing shows the stored rate exactly.
            saved = tracker.add_transaction(_trade(acct, TxnType.BUY, "2025-01-02", 100, fx_rate=1.3612345))
            edit = TransactionForm(tracker, txn=saved)
            await app.push_screen(edit, results.append)
            await pilot.pause()
            assert edit.query_one("#f-fx", Input).value == "1.3612345"

    asyncio.run(scenario())
