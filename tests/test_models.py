from datetime import date, timedelta

import pytest

from marketpulse.models import (
    Account,
    AccountType,
    Alert,
    Asset,
    AssetKind,
    FxRates,
    Quote,
    Transaction,
    TxnType,
    guess_currency,
    parse_date,
    parse_symbols,
)


def test_parse_date_forms():
    assert parse_date("2024-01-05") == "2024-01-05"
    assert parse_date("2024/01/05") == "2024-01-05"
    assert parse_date("2024-01-05T10:30:00") == "2024-01-05"
    assert parse_date("") == date.today().isoformat()
    assert parse_date("today") == date.today().isoformat()
    assert parse_date("yesterday") == (date.today() - timedelta(days=1)).isoformat()
    assert parse_date("-3d") == (date.today() - timedelta(days=3)).isoformat()
    assert parse_date("01/31/2024") == "2024-01-31"  # US broker export
    assert parse_date("31/01/2024") == "2024-01-31"
    assert parse_date("31-01-2024 09:30") == "2024-01-31"
    assert parse_date("05/05/2024") == "2024-05-05"
    with pytest.raises(ValueError, match="Ambiguous"):
        parse_date("01/02/2024")
    with pytest.raises(ValueError, match="Invalid date"):
        parse_date("31/02/2024")
    with pytest.raises(ValueError, match="Invalid date"):
        parse_date("next tuesday")


def test_parse_symbols_dedupes_and_uppercases():
    assert parse_symbols("aapl, msft  AAPL xeqt.to") == ["AAPL", "MSFT", "XEQT.TO"]


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [("XEQT.TO", "CAD"), ("BTC-USD", "USD"), ("ETH-CAD", "CAD"), ("VOD.L", "GBP"), ("AAPL", "USD"), ("SHOP.V", "CAD")],
)
def test_guess_currency(symbol, expected):
    assert guess_currency(symbol) == expected


def test_guess_currency_default():
    assert guess_currency("AAPL", default="CAD") == "CAD"


@pytest.mark.parametrize(
    ("txn", "message"),
    [
        (Transaction(account_id=1, type=TxnType.BUY, quantity=1, price=1), "needs a symbol"),
        (Transaction(account_id=1, type=TxnType.BUY, symbol="A", quantity=0, price=1), "Quantity"),
        (Transaction(account_id=1, type=TxnType.SPLIT, symbol="A"), "ratio"),
        (Transaction(account_id=1, type=TxnType.TRANSFER, symbol="A", quantity=1, target_account_id=1), "different"),
        (Transaction(account_id=1, type=TxnType.DEPOSIT, amount=-5), "Amount"),
        (Transaction(account_id=1, type=TxnType.BUY, symbol="A", quantity=1, price=1, fees=-1), "Fees"),
        (
            Transaction(
                account_id=1, type=TxnType.DEPOSIT, amount=1, date=(date.today() + timedelta(days=1)).isoformat()
            ),
            "future",
        ),
    ],
)
def test_transaction_validation(txn, message):
    with pytest.raises(ValueError, match=message):
        txn.validate()


def test_deposit_needs_no_symbol():
    Transaction(account_id=1, type=TxnType.DEPOSIT, amount=100).validate()


def test_transaction_normalizes_case():
    t = Transaction(account_id=1, type="buy".upper(), symbol="xeqt.to", currency="cad", quantity=1, price=1)
    assert (t.symbol, t.currency, t.type) == ("XEQT.TO", "CAD", TxnType.BUY)


def test_fixed_income_accrual():
    gic = Asset(
        "GIC",
        kind=AssetKind.FIXED_INCOME,
        rate=5,
        compounding="simple",
        start_date="2021-01-01",
        maturity_date="2023-01-01",
    )
    assert gic.accrual_factor("2022-01-01") == pytest.approx(1.05)
    # capped at maturity
    assert gic.accrual_factor("2030-01-01") == pytest.approx(gic.accrual_factor("2023-01-01"))
    annual = Asset("B", kind=AssetKind.FIXED_INCOME, rate=10, compounding="annual", start_date="2020-01-01")
    assert annual.accrual_factor("2021-12-31") == pytest.approx(1.21, rel=1e-3)
    assert Asset("X").accrual_factor() == 1.0


def test_alerts():
    q = Quote(symbol="AAPL", price=97, prev_close=100)
    assert Alert("aapl", "below", 98).is_met(q)
    assert not Alert("AAPL", "above", 98).is_met(q)
    assert Alert("AAPL", "down_pct", 2).is_met(q)
    assert not Alert("AAPL", "up_pct", 1).is_met(q)
    assert Alert("AAPL", "above", 100).describe() == "AAPL ≥ 100.00"
    with pytest.raises(ValueError):
        Alert("AAPL", "sideways", 1)


def test_fx_rates():
    fx = FxRates(base="CAD", rates={"USD": 1.35})
    assert fx.stale is False
    assert fx.convert(10, "USD") == pytest.approx(13.5)
    assert fx.convert(10, "CAD") == 10
    assert fx.convert(10, "") == 10
    assert fx.convert(10, "EUR") is None


def test_quote_change_handles_zero_prev():
    assert Quote(symbol="X", price=5, prev_close=0).change_pct == 0.0


def test_account_type_registered():
    assert AccountType.TFSA.registered and AccountType.FHSA.registered
    assert not AccountType.NONREG.registered and not Account(name="t").type.registered
    assert AccountType.NONREG.label == "Non-registered"
