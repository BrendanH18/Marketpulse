import pytest

from marketpulse.ledger import CashFlow, contribution_room, replay, replay_by_day, superficial_losses, tfsa_limit
from marketpulse.models import Account, AccountType, Transaction, TxnType

ACCOUNTS = {
    1: Account(name="Main", id=1, currency="CAD"),
    2: Account(name="TFSA", id=2, type=AccountType.TFSA, currency="CAD", track_cash=True),
}


def txn(kind, day, symbol="", qty=0.0, price=0.0, amount=0.0, fees=0.0, account=1, ccy="CAD", **kw):
    return Transaction(
        account_id=account,
        type=kind,
        date=day,
        symbol=symbol,
        quantity=qty,
        price=price,
        amount=amount,
        fees=fees,
        currency=ccy,
        **kw,
    )


def test_buys_blend_average_cost_including_fees():
    s = replay(
        [txn(TxnType.BUY, "2024-01-01", "A", 10, 30, fees=5), txn(TxnType.BUY, "2024-02-01", "A", 10, 40)], ACCOUNTS
    )
    h = s.holdings[(1, "A")]
    assert h.quantity == 20
    assert h.book == pytest.approx(705)
    assert h.avg_cost == pytest.approx(35.25)
    assert h.first_date == "2024-01-01"


def test_sell_realizes_gain_at_average_cost():
    s = replay(
        [
            txn(TxnType.BUY, "2024-01-01", "A", 10, 30),
            txn(TxnType.BUY, "2024-01-02", "A", 10, 40),
            txn(TxnType.SELL, "2024-03-01", "A", 5, 50, fees=5),
        ],
        ACCOUNTS,
    )
    sale = s.realized[0]
    assert sale.cost == pytest.approx(175)
    assert sale.proceeds == pytest.approx(245)
    assert sale.gain == pytest.approx(70)
    assert s.holdings[(1, "A")].quantity == 15
    assert s.holdings[(1, "A")].avg_cost == pytest.approx(35)


def test_backdated_buy_replays_in_date_order():
    s = replay(
        [
            txn(TxnType.BUY, "2024-03-01", "A", 10, 20, id=1),
            txn(TxnType.SELL, "2024-03-02", "A", 10, 25, id=2),
            txn(TxnType.BUY, "2024-01-01", "A", 10, 10, id=3),
        ],
        ACCOUNTS,
    )
    # 20 shares averaging 15 when the sale happens
    assert s.realized[0].gain == pytest.approx(100)
    assert s.holdings[(1, "A")].quantity == 10


def test_oversell_is_reported_and_clamped():
    s = replay(
        [txn(TxnType.BUY, "2024-01-01", "A", 5, 10, id=1), txn(TxnType.SELL, "2024-01-02", "A", 10, 12, id=2)], ACCOUNTS
    )
    assert len(s.issues) == 1 and s.issues[0].txn_id == 2
    assert s.realized[0].quantity == 5
    assert not s.open_holdings()


def test_sell_with_nothing_held_is_an_issue():
    s = replay([txn(TxnType.SELL, "2024-01-02", "A", 1, 12)], ACCOUNTS)
    assert s.issues and not s.realized


def test_same_day_deposit_funds_buy_in_cash_account():
    s = replay(
        [
            txn(TxnType.BUY, "2024-01-02", "VFV.TO", 10, 100, account=2, id=1),
            txn(TxnType.DEPOSIT, "2024-01-02", amount=1000, account=2, id=2),
        ],
        ACCOUNTS,
    )
    assert s.cash[(2, "CAD")] == pytest.approx(0)
    assert s.flows[0].amount == 1000


def test_split_keeps_cost_base():
    s = replay([txn(TxnType.BUY, "2024-01-01", "A", 10, 100), txn(TxnType.SPLIT, "2024-06-01", "A", ratio=4)], ACCOUNTS)
    h = s.holdings[(1, "A")]
    assert h.quantity == 40 and h.book == pytest.approx(1000) and h.avg_cost == pytest.approx(25)


def test_return_of_capital_reduces_acb_and_excess_is_gain():
    s = replay(
        [
            txn(TxnType.BUY, "2024-01-01", "A", 1, 10),
            txn(TxnType.ROC, "2024-02-01", "A", amount=4),
            txn(TxnType.ROC, "2024-03-01", "A", amount=10),
        ],
        ACCOUNTS,
    )
    assert s.holdings[(1, "A")].book == 0
    assert s.realized[-1].gain == pytest.approx(4)


def test_transfer_moves_cost_base_between_accounts():
    s = replay(
        [txn(TxnType.BUY, "2024-01-01", "A", 10, 10), txn(TxnType.TRANSFER, "2024-02-01", "A", 4, target_account_id=2)],
        ACCOUNTS,
    )
    assert (s.holdings[(1, "A")].quantity, s.holdings[(1, "A")].book) == (6, pytest.approx(60))
    assert (s.holdings[(2, "A")].quantity, s.holdings[(2, "A")].book) == (4, pytest.approx(40))
    assert not s.realized


def test_drip_adds_shares_and_income():
    s = replay([txn(TxnType.DRIP, "2024-01-01", "A", 2, 50)], ACCOUNTS)
    assert s.holdings[(1, "A")].quantity == 2
    assert s.income[0].amount == pytest.approx(100)


def test_cash_is_tracked_only_for_cash_accounts():
    s = replay(
        [
            txn(TxnType.DIVIDEND, "2024-01-01", "A", amount=10, account=1),
            txn(TxnType.DIVIDEND, "2024-01-01", "A", amount=7, account=2),
            txn(TxnType.FEE, "2024-01-02", amount=2, account=2),
        ],
        ACCOUNTS,
    )
    assert s.cash_balances() == {(2, "CAD"): pytest.approx(5)}
    assert sum(i.amount for i in s.income) == 17


def test_valuation_marks_manual_assets_and_until_filter():
    txns = [
        txn(TxnType.BUY, "2020-01-01", "HOUSE", 1, 500_000),
        txn(TxnType.VALUATION, "2024-01-01", "HOUSE", price=650_000),
    ]
    assert replay(txns, ACCOUNTS).valuations["HOUSE"] == ("2024-01-01", 650_000)
    assert "HOUSE" not in replay(txns, ACCOUNTS, until="2023-12-31").valuations


def test_superficial_loss_flagged_when_rebought_within_30_days():
    txns = [
        txn(TxnType.BUY, "2024-01-01", "A", 10, 100, id=1),
        txn(TxnType.SELL, "2024-02-01", "A", 10, 80, id=2),
        txn(TxnType.BUY, "2024-02-15", "A", 10, 81, account=2, id=3),
    ]
    warnings = superficial_losses(txns, replay(txns, ACCOUNTS))
    assert len(warnings) == 1
    assert warnings[0].rebuy_date == "2024-02-15" and warnings[0].rebuy_account_id == 2


def test_gains_and_distant_rebuys_are_not_superficial():
    gain = [
        txn(TxnType.BUY, "2024-01-01", "A", 10, 100, id=1),
        txn(TxnType.SELL, "2024-02-01", "A", 10, 120, id=2),
        txn(TxnType.BUY, "2024-02-02", "A", 1, 1, id=3),
    ]
    assert superficial_losses(gain, replay(gain, ACCOUNTS)) == []
    later = [
        txn(TxnType.BUY, "2024-01-01", "A", 10, 100, id=1),
        txn(TxnType.SELL, "2024-02-01", "A", 10, 80, id=2),
        txn(TxnType.BUY, "2024-04-01", "A", 1, 1, id=3),
    ]
    assert superficial_losses(later, replay(later, ACCOUNTS)) == []


def test_tfsa_room_rolls_forward_with_limits_and_withdrawals():
    flows = [CashFlow("2025-03-01", 2, 5000, "CAD"), CashFlow("2025-06-01", 2, -2000, "CAD")]
    next_year = contribution_room("TFSA", 2025, 10000, flows, {2}, current_year=2026)
    assert next_year.new_limits == 7000
    assert next_year.withdrawals_added_back == 2000
    assert next_year.remaining == pytest.approx(14000)
    same_year = contribution_room("TFSA", 2025, 10000, flows, {2}, current_year=2025)
    assert same_year.remaining == pytest.approx(5000)


def test_rrsp_room_only_subtracts_contributions():
    flows = [CashFlow("2026-02-01", 5, 3000, "CAD"), CashFlow("2026-02-01", 9, 999, "CAD")]
    assert contribution_room("RRSP", 2026, 20000, flows, {5}, current_year=2027).remaining == pytest.approx(17000)


def test_tfsa_limits():
    assert tfsa_limit(2015) == 10000
    assert tfsa_limit(2008) == 0
    assert tfsa_limit(2031) == 7000


def test_replay_by_day_matches_replay_until():
    txns = [
        txn(TxnType.BUY, "2023-12-20", "A", 10, 100, id=1),  # before start: applied on day one
        txn(TxnType.DEPOSIT, "2024-01-02", amount=500, account=2, id=2),
        txn(TxnType.BUY, "2024-01-02", "B", 5, 100, account=2, id=3),  # same day as the deposit
        txn(TxnType.SELL, "2024-01-04", "A", 4, 120, id=4),
        txn(TxnType.VALUATION, "2024-01-05", "H", price=99, id=5),
        txn(TxnType.BUY, "2024-01-09", "C", 1, 1, id=6),  # after end: never applied
    ]

    def fingerprint(state):
        return (
            {k: (round(h.quantity, 9), round(h.book, 6)) for k, h in state.holdings.items()},
            dict(state.cash),
            dict(state.valuations),
            len(state.flows),
            len(state.realized),
        )

    days = [iso for iso, _ in replay_by_day(txns, ACCOUNTS, "2024-01-01", "2024-01-06")]
    assert days == [f"2024-01-0{d}" for d in range(1, 7)]
    for iso, state in replay_by_day(txns, ACCOUNTS, "2024-01-01", "2024-01-06"):
        assert fingerprint(state) == fingerprint(replay(txns, ACCOUNTS, until=iso)), iso
    final = list(replay_by_day(txns, ACCOUNTS, "2024-01-01", "2024-01-06"))[-1][1]
    assert (1, "C") not in final.holdings
