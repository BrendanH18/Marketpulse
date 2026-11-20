"""Items 1–20 of the 100 CLI/TUI batch: recording shortcuts and realized/payout outputs (fictional data)."""

from __future__ import annotations

import csv
import io
import json
import uuid
from dataclasses import replace
from datetime import date, timedelta

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Transaction, TxnType

DAY = ["-a", "Maple Cash", "-d", "2025-01-08"]


@pytest.fixture
def cli(tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "200")
    fake.offline = True

    def run(*args, input=None):
        return CliRunner().invoke(main, list(args), input=input, catch_exceptions=False)

    return run


@pytest.fixture
def maple(store):
    """Maple Cash tracks cash: $1000 in, 10 XEQT.TO bought at $40, so $600 is left. Maple TFSA doesn't."""
    cash = store.add_account(Account(name="Maple Cash", type=AccountType.NONREG, track_cash=True))
    store.add_account(Account(name="Maple TFSA", type=AccountType.TFSA))
    store.add_transaction(Transaction(cash.saved_id, TxnType.DEPOSIT, "2025-01-02", amount=1000, currency="CAD"))
    store.add_transaction(
        Transaction(cash.saved_id, TxnType.BUY, "2025-01-06", "XEQT.TO", quantity=10, price=40, currency="CAD")
    )
    return cash


def receipt(result) -> dict:
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def latest(store) -> Transaction:
    return max(store.transactions(), key=lambda t: t.saved_id)


# ── Recording (items 1–11) ────────────────────────────────────────────────────


def test_1_buy_max_spends_the_cash_on_whole_units(cli, store, maple):
    got = receipt(cli("buy", "XEQT.TO", "max", "41", "-f", "9.99", *DAY, "--json"))
    assert got["quantity"] == 14  # 14 × 41 + 9.99 = 583.99 of the 600 available
    assert got["after"]["cash"]["CAD"] == pytest.approx(16.01)
    store.add_transaction(Transaction(maple.saved_id, TxnType.DEPOSIT, "2025-01-08", amount=100, currency="CAD"))
    got = receipt(cli("buy", "XEQT.TO", "MAX", "41", *DAY, "--dry-run", "--json"))
    assert got["quantity"] == 2 and got["dry_run"] is True  # 116.01 left covers two more


def test_1_buy_max_refusals(cli, store, maple):
    before = store.transactions()
    result = cli("buy", "XEQT.TO", "max", "41", "-a", "Maple TFSA", "-d", "2025-01-08")
    assert result.exit_code == 1 and "doesn't track cash" in result.output
    result = cli("buy", "XEQT.TO", "max", "700", *DAY)
    assert result.exit_code == 1 and "doesn't cover one unit" in result.output
    result = cli("buy", "XEQT.TO", "max", "--total", "500", *DAY)
    assert result.exit_code == 2 and "can't be combined" in result.output
    assert cli("buy", "XEQT.TO", "all", "41", *DAY).exit_code == 2  # `all` stays a sell word
    assert store.transactions() == before


def test_1_buy_max_with_fee_pct(cli, store, maple):
    got = receipt(cli("buy", "XEQT.TO", "max", "41", "--fee-pct", "1", *DAY, "--json"))
    assert got["quantity"] == 14 and got["fees"] == pytest.approx(5.74)


def test_2_sell_and_transfer_a_percentage(cli, store, maple):
    got = receipt(cli("sell", "XEQT.TO", "50%", "42", *DAY, "--json"))
    assert got["quantity"] == 5 and got["after"]["position"]["quantity"] == 5
    args = ["transfer", "XEQT.TO", "20 %", "--from", "Maple Cash", "--to", "Maple TFSA", "-p", "42"]
    got = receipt(cli(*args, "-d", "2025-01-09", "--json"))
    assert got["quantity"] == 1 and got["after"]["target_position"]["quantity"] == 1
    for bad in ("0%", "150%"):
        result = cli("sell", "XEQT.TO", bad, "42", *DAY)
        assert result.exit_code == 2 and "percentage" in result.output


def test_3_sell_all_but_keep(cli, store, maple):
    got = receipt(cli("sell", "XEQT.TO", "all", "42", "--keep", "3", *DAY, "--json"))
    assert got["quantity"] == 7 and got["after"]["position"]["quantity"] == 3
    result = cli("sell", "XEQT.TO", "2", "42", "--keep", "1", *DAY)
    assert result.exit_code == 2 and "--keep needs QUANTITY `all`" in result.output
    result = cli("sell", "XEQT.TO", "all", "42", "--keep", "3", *DAY)
    assert result.exit_code == 1 and "nothing is left to sell" in result.output
    assert cli("sell", "XEQT.TO", "all", "42", "--keep", "-1", *DAY).exit_code == 2


def test_4_fee_pct(cli, store, maple):
    result = cli("buy", "XEQT.TO", "10", "41", "--fee-pct", "0.5", *DAY)
    assert result.exit_code == 0, result.output
    assert latest(store).fees == pytest.approx(2.05)
    assert "(fees 2.05 CAD)" in result.output
    assert cli("buy", "XEQT.TO", "1", "41", "-f", "1", "--fee-pct", "1", *DAY).exit_code == 2
    assert cli("buy", "XEQT.TO", "1", "41", "--fee-pct", "100", *DAY).exit_code == 2


def test_5_net_works_out_the_fees(cli, store, maple):
    assert receipt(cli("buy", "XEQT.TO", "10", "41", "--net", "419.99", *DAY, "--json"))["fees"] == pytest.approx(9.99)
    got = receipt(cli("sell", "XEQT.TO", "10", "42", "--net", "410.01", *DAY, "--json"))
    assert got["fees"] == pytest.approx(9.99)
    got = receipt(cli("buy", "XEQT.TO", "2", "--total", "82", "--net", "83", *DAY, "--dry-run", "--json"))
    assert got["price"] == 41 and got["fees"] == pytest.approx(1)
    result = cli("buy", "XEQT.TO", "10", "41", "--net", "400", *DAY)
    assert result.exit_code == 1 and "is below quantity × price" in result.output
    assert cli("buy", "XEQT.TO", "10", "41", "--net", "420", "-f", "1", *DAY).exit_code == 2
    assert cli("buy", "XEQT.TO", "10", "41", "--net", "0", *DAY).exit_code == 2


def test_6_max_value_guard(cli, store, maple):
    before = store.transactions()
    result = cli("buy", "XEQT.TO", "100", "41", "--max-value", "1000", *DAY)
    assert result.exit_code == 1 and "above --max-value" in result.output
    assert store.transactions() == before
    assert cli("buy", "XEQT.TO", "5", "41", "--max-value", "205", *DAY).exit_code == 0
    assert cli("sell", "XEQT.TO", "all", "41", "--max-value", "500", *DAY).exit_code == 1


def test_7_dividend_withholding(cli, store, maple):
    result = cli("dividend", "XEQT.TO", "10", "--withholding", "15", *DAY)
    assert result.exit_code == 0, result.output
    assert latest(store).amount == pytest.approx(8.5)
    assert "gross 10.00 less 15% withheld: 1.50" in result.output
    got = receipt(cli("dividend", "XEQT.TO", "0.1", "--per-unit", "--withholding", "15", *DAY, "--json"))
    assert got["amount"] == pytest.approx(0.85)
    assert cli("dividend", "XEQT.TO", "10", "--withholding", "-1", *DAY).exit_code == 2


def test_8_dividend_require_holding(cli, store, maple):
    before = store.transactions()
    result = cli("dividend", "XEQT.TO", "5", "--require-holding", "-a", "Maple TFSA", "-d", "2025-01-08")
    assert result.exit_code == 1 and "holds no XEQT.TO" in result.output
    result = cli("dividend", "XEQT.TO", "5", "--require-holding", "-a", "Maple Cash", "-d", "2025-01-03")
    assert result.exit_code == 1  # bought on the 6th
    assert store.transactions() == before
    assert cli("dividend", "XEQT.TO", "5", "--require-holding", *DAY).exit_code == 0


def test_9_withdraw_all_but_leave(cli, store, maple):
    got = receipt(cli("withdraw", "all", "--leave", "100", *DAY, "--json"))
    assert got["amount"] == 500 and got["after"]["cash"]["CAD"] == pytest.approx(100)
    assert "leaving 100.00 CAD" in got["message"]
    result = cli("withdraw", "50", "--leave", "10", *DAY)
    assert result.exit_code == 2 and "--leave needs AMOUNT `all`" in result.output
    result = cli("withdraw", "all", "--leave", "100", *DAY)
    assert result.exit_code == 1 and "not more than --leave" in result.output


def test_10_split_reverse(cli, store, maple):
    got = receipt(cli("split", "XEQT.TO", "10", "--reverse", *DAY, "--json"))
    assert got["ratio"] == pytest.approx(0.1)
    assert got["after"]["position"]["quantity"] == pytest.approx(1)
    got = receipt(cli("split", "XEQT.TO", "2:1", "--reverse", *DAY, "--dry-run", "--json"))
    assert got["ratio"] == pytest.approx(0.5)


def test_11_receipt_file(cli, store, maple, tmp_path):
    path = tmp_path / "receipt.json"
    result = cli("deposit", "50", *DAY, "--receipt-file", str(path))
    assert result.exit_code == 0 and "Deposit 50.00 CAD" in result.output
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["recorded"] is True and saved["id"] == latest(store).saved_id and saved["amount"] == 50
    cli("deposit", "60", *DAY, "--dry-run", "--receipt-file", str(path))
    assert json.loads(path.read_text(encoding="utf-8"))["dry_run"] is True
    cli("deposit", "50", *DAY, "--once", "--receipt-file", str(path))
    assert json.loads(path.read_text(encoding="utf-8"))["duplicate"] is True
    result = cli("deposit", "1", *DAY, "--receipt-file", str(tmp_path / "missing" / "r.json"))
    assert result.exit_code == 2 and "existing folder" in result.output
    result = cli("deposit", "1", *DAY, "--receipt-file", str(path), "--request-id", str(uuid.uuid4()))
    assert result.exit_code == 2 and "--request-id can't be combined with --receipt-file" in result.output


def test_new_recording_options_refuse_request_id_and_keep_plain_fingerprints(cli, store, maple):
    result = cli("buy", "XEQT.TO", "1", "41", "--fee-pct", "1", *DAY, "--request-id", str(uuid.uuid4()))
    assert result.exit_code == 2 and "--request-id can't be combined with --fee-pct" in result.output
    request = str(uuid.uuid4())
    assert cli("buy", "XEQT.TO", "1", "41", *DAY, "--request-id", request).exit_code == 0
    again = cli("buy", "XEQT.TO", "1", "41", *DAY, "--request-id", request)
    assert again.exit_code == 0 and "already recorded" in again.output
    assert sum(t.type is TxnType.BUY for t in store.transactions()) == 2


# ── Realized and payouts (items 12–20) ────────────────────────────────────────


@pytest.fixture
def ledger(store):
    maple = store.add_account(Account(name="Fictional Maple"))
    gull = store.add_account(Account(name="Fictional Gull", type=AccountType.TFSA, currency="USD"))
    hidden = store.add_account(Account(name="Hidden Fiction", archived=True))

    def add(acct, kind, day, symbol="", qty=0, price=0, amount=0, currency="CAD"):
        store.add_transaction(Transaction(acct.saved_id, kind, day, symbol, qty, price, amount, currency=currency))

    add(maple, TxnType.BUY, "2024-01-01", "MAPL", 10, 10)
    add(maple, TxnType.SELL, "2024-02-01", "MAPL", 2, 20)  # +20 on 20
    add(maple, TxnType.SELL, "2024-04-01", "MAPL", 2, 5)  # -10 on 20
    add(gull, TxnType.BUY, "2024-01-02", "GULL", 10, 100, currency="USD")
    add(gull, TxnType.SELL, "2024-06-03", "GULL", 2, 130, currency="USD")  # +60 on 200
    add(maple, TxnType.DIVIDEND, "2024-02-02", "MAPL", amount=12)
    add(maple, TxnType.INTEREST, "2024-04-01", amount=3)
    add(maple, TxnType.DIVIDEND, "2024-04-02", "MAPL", amount=8)
    add(gull, TxnType.DIVIDEND, "2024-01-16", "GULL", amount=20, currency="USD")
    add(gull, TxnType.DRIP, "2024-04-03", "GULL", 1, 100, currency="USD")
    add(hidden, TxnType.BUY, "2024-01-01", "HIDDEN", 10, 10)
    add(hidden, TxnType.SELL, "2024-02-01", "HIDDEN", 1, 100)
    add(hidden, TxnType.DIVIDEND, "2024-02-02", "HIDDEN", amount=900)
    return maple


@pytest.fixture
def browse(cli, ledger, store):
    def run(*args):
        before = store.transactions()
        result = cli(*args)
        assert store.transactions() == before
        assert "HIDDEN" not in result.output and "Hidden Fiction" not in result.output
        return result

    return run


def test_12_realized_by_group(browse):
    got = receipt(browse("realized", "--by", "quarter", "--json"))
    assert [(g["group"], g["currency"], g["count"]) for g in got["groups"]] == [
        ("2024-Q1", "CAD", 1),
        ("2024-Q2", "CAD", 1),
        ("2024-Q2", "USD", 1),
    ]
    assert [g["gain"] for g in got["groups"]] == [20, -10, 60]
    assert got["totals"]["CAD"]["gain"] == 10
    rows = list(csv.DictReader(io.StringIO(browse("realized", "--by", "account", "--csv").stdout)))
    assert [(r["account"], r["gain"]) for r in rows] == [("Fictional Maple", "10.0"), ("Fictional Gull", "60.0")]
    assert browse("realized", "--by", "currency", "--count").stdout.strip() == "2"
    text = browse("realized", "--by", "symbol").output
    assert "Realized gains by symbol" in text and "Totals by currency" in text
    assert browse("realized", "--by", "year", "--sort", "gain").exit_code == 2


def test_13_realized_gross_split(browse):
    totals = receipt(browse("realized", "--gross", "--json"))["totals"]
    assert totals["CAD"]["gains"] == 20 and totals["CAD"]["losses"] == -10 and totals["CAD"]["gain"] == 10
    assert totals["USD"]["gains"] == 60 and totals["USD"]["losses"] == 0
    assert "losses" not in receipt(browse("realized", "--json"))["totals"]["CAD"]
    text = browse("realized", "--gross").output
    assert "Gains" in text and "Losses" in text
    assert browse("realized", "--gross", "--summary", "year").exit_code == 2


def test_14_realized_return_pct(browse):
    rows = receipt(browse("realized", "--return", "--json"))["rows"]
    assert [r["return_pct"] for r in rows] == pytest.approx([100, -50, 30])
    assert "+100.00%" in browse("realized", "--return").output
    header = browse("realized", "--return", "--csv").stdout.splitlines()[0]
    assert header.endswith(",txn_id,return_pct")
    assert browse("realized", "--return", "--by", "year").exit_code == 2


def test_15_realized_totals_only(browse):
    assert receipt(browse("realized", "--totals-only", "--json")) == {
        "totals": {
            "CAD": {"count": 2, "proceeds": 50.0, "cost": 40.0, "gain": 10.0},
            "USD": {"count": 1, "proceeds": 260.0, "cost": 200.0, "gain": 60.0},
        }
    }
    lines = browse("realized", "--totals-only", "--gross", "--csv").stdout.splitlines()
    assert lines[0] == "currency,count,proceeds,cost,gain,gains,losses"
    text = browse("realized", "--totals-only").output
    assert "Totals by currency" in text and "MAPL" not in text
    assert browse("realized", "--totals-only", "--limit", "1").exit_code == 2


def test_16_jsonl(browse):
    lines = browse("realized", "--jsonl").stdout.splitlines()
    assert [json.loads(line)["gain"] for line in lines] == [20, -10, 60]
    lines = browse("payouts", "--jsonl", "--kind", "dividend").stdout.splitlines()
    assert [json.loads(line)["amount"] for line in lines] == [20, 12, 8]
    groups = [json.loads(line) for line in browse("payouts", "--by", "kind", "--jsonl").stdout.splitlines()]
    assert {(g["group"], g["currency"]) for g in groups} >= {("interest", "CAD"), ("drip", "USD")}
    summary = [json.loads(line) for line in browse("realized", "--summary", "year", "--jsonl").stdout.splitlines()]
    assert summary == [{"group": "2024", "count": 3}]
    assert browse("realized", "--jsonl", "--json").exit_code == 2
    assert browse("payouts", "--jsonl", "--count").exit_code == 2


def test_17_fields(browse):
    lines = browse("realized", "--csv", "--fields", "date, symbol,gain").stdout.splitlines()
    assert lines == ["date,symbol,gain", "2024-02-01,MAPL,20.0", "2024-04-01,MAPL,-10.0", "2024-06-03,GULL,60.0"]
    rows = receipt(browse("payouts", "--json", "--fields", "symbol,amount", "--kind", "interest"))["rows"]
    assert rows == [{"symbol": "", "amount": 3.0}]
    assert "return_pct" in json.loads(browse("realized", "--jsonl", "--fields", "return_pct").stdout.splitlines()[0])
    result = browse("realized", "--csv", "--fields", "date,colour")
    assert result.exit_code == 2 and "Unknown field 'colour'" in result.output
    assert browse("payouts", "--fields", "date").exit_code == 2  # needs a machine format
    assert browse("payouts", "--csv", "--fields", "date,date").exit_code == 2
    assert browse("payouts", "--csv", "--fields", "date", "--by", "kind").exit_code == 2


def test_18_last_days(cli, store):
    acct = store.add_account(Account(name="Fictional Recent"))
    today = date.today()

    def day(n):
        return (today - timedelta(days=n)).isoformat()

    for kind, n, qty, price, amount in (
        (TxnType.BUY, 60, 10, 10, 0),
        (TxnType.SELL, 30, 1, 12, 0),
        (TxnType.SELL, 2, 1, 14, 0),
        (TxnType.DIVIDEND, 40, 0, 0, 5),
        (TxnType.DIVIDEND, 6, 0, 0, 7),
    ):
        store.add_transaction(Transaction(acct.saved_id, kind, day(n), "RCNT", qty, price, amount, currency="CAD"))
    rows = receipt(cli("realized", "--last-days", "7", "--json"))["rows"]
    assert [r["date"] for r in rows] == [day(2)]
    assert len(receipt(cli("realized", "--last-days", "31", "--json"))["rows"]) == 2
    assert [r["amount"] for r in receipt(cli("payouts", "--last-days", "7", "--json"))["rows"]] == [7]
    assert cli("payouts", "--last-days", "6", "--count").stdout.strip() == "0"
    assert cli("payouts", "--last-days", "7", "--since", "2020-01-01").exit_code == 2
    assert cli("payouts", "--last-days", "0").exit_code == 2


def test_19_payouts_group_sort(browse):
    groups = receipt(browse("payouts", "--by", "symbol", "--group-sort", "amount", "--json"))["groups"]
    assert [(g["group"], g["amount"]) for g in groups] == [("GULL", 120), ("MAPL", 20), ("", 3)]
    groups = receipt(browse("payouts", "--by", "symbol", "--group-sort", "count", "--json"))["groups"]
    assert [g["count"] for g in groups] == [2, 2, 1]
    named = receipt(browse("payouts", "--by", "symbol", "--group-sort", "group", "--json"))["groups"]
    assert named == receipt(browse("payouts", "--by", "symbol", "--json"))["groups"]
    result = browse("payouts", "--group-sort", "amount")
    assert result.exit_code == 2 and "--group-sort needs --by" in result.output


def test_20_markdown(browse, tracker, monkeypatch):
    lines = browse("realized", "--markdown", "--fields", "date,symbol,quantity,gain").stdout.splitlines()
    assert lines[:3] == [
        "| date | symbol | quantity | gain |",
        "| --- | --- | --- | --- |",
        "| 2024-02-01 | MAPL | 2 | 20.00 |",
    ]
    lines = browse("payouts", "--markdown", "--by", "kind").stdout.splitlines()
    assert lines[0] == "| group | currency | count | amount |"
    assert browse("payouts", "--markdown", "--csv").exit_code == 2
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: replace(tracker.config, privacy=True))
    lines = browse("payouts", "--markdown", "--kind", "interest").stdout.splitlines()
    assert lines[2] == "| 2024-04-01 | 1 | Fictional Maple |  | interest | •••• | CAD |"


def test_default_outputs_are_unchanged(browse):
    rows = list(csv.DictReader(io.StringIO(browse("realized", "--csv").stdout)))
    assert list(rows[0]) == ["date", "account_id", "account", "symbol", "quantity", "proceeds", "cost", "gain"] + [
        "currency",
        "txn_id",
    ]
    payload = receipt(browse("payouts", "--json"))
    assert set(payload) == {"rows", "totals"} and "return_pct" not in payload["rows"][0]


# ── Review fixes: exact cents and a safe receipt path ─────────────────────────


def test_receipt_file_refuses_the_ledger_database(cli, store, maple, tmp_path, monkeypatch):
    data = tmp_path / "ledger-home"
    data.mkdir()
    monkeypatch.setenv("MARKETPULSE_DATA", str(data))
    before = store.transactions()
    for name in ("marketpulse.db", "marketpulse.db-wal"):
        result = cli("deposit", "1", *DAY, "--receipt-file", str(data / name))
        assert result.exit_code == 2 and "must not be the ledger database" in result.output
    assert store.transactions() == before


def test_buy_max_counts_the_fee_rounded_to_the_cent(cli, store):
    acct = store.add_account(Account(name="Maple Cash", type=AccountType.NONREG, track_cash=True))
    store.add_transaction(Transaction(acct.saved_id, TxnType.DEPOSIT, "2025-01-02", amount=11.04, currency="CAD"))
    got = receipt(cli("buy", "XEQT.TO", "max", "10", "--fee-pct", "10.42", *DAY, "--dry-run", "--json"))
    assert got["quantity"] == 1 and got["fees"] == pytest.approx(1.04)  # 10 + 1.04 is exactly the cash


def test_net_and_max_value_compare_exact_amounts(cli, store, maple):
    before = store.transactions()
    result = cli("buy", "XEQT.TO", "1", "10.004", "--net", "10", *DAY)
    assert result.exit_code == 1 and "is below quantity × price" in result.output
    result = cli("buy", "XEQT.TO", "1", "10.004", "--max-value", "10", *DAY)
    assert result.exit_code == 1 and "above --max-value" in result.output
    assert store.transactions() == before
    got = receipt(cli("buy", "XEQT.TO", "3", "10.001", "--net", "30.01", *DAY, "--dry-run", "--json"))
    assert 3 * got["price"] + got["fees"] == pytest.approx(30.01, abs=1e-9)  # the supplied net is kept


def test_withdraw_all_leave_keeps_at_least_the_reserve(cli, store, maple):
    got = receipt(cli("withdraw", "all", "--leave", "10.125", *DAY, "--json"))
    assert got["amount"] == pytest.approx(589.87) and got["after"]["cash"]["CAD"] >= 10.125


def test_percentage_keeps_its_precision(cli, store):
    acct = store.add_account(Account(name="Maple Cash", type=AccountType.NONREG))
    store.add_transaction(
        Transaction(acct.saved_id, TxnType.BUY, "2025-01-06", "XEQT.TO", quantity=1_000_000, price=1, currency="CAD")
    )
    got = receipt(cli("sell", "XEQT.TO", "33.333333%", "1", *DAY, "--dry-run", "--json"))
    assert got["quantity"] == pytest.approx(333_333.33)


def test_receipt_file_refuses_sidecars_of_a_symlinked_ledger(cli, store, maple, tmp_path, monkeypatch):
    data = tmp_path / "ledger-home"
    data.mkdir()
    real = tmp_path / "elsewhere" / "ledger.sqlite"
    real.parent.mkdir()
    real.write_bytes(b"")
    (data / "marketpulse.db").symlink_to(real)
    monkeypatch.setenv("MARKETPULSE_DATA", str(data))
    result = cli("deposit", "1", *DAY, "--receipt-file", str(real.parent / "ledger.sqlite-wal"))
    assert result.exit_code == 2 and "must not be the ledger database" in result.output


def test_buy_max_settles_quickly_on_a_tiny_price(cli, store, maple):
    result = cli("buy", "XEQT.TO", "max", "1e-20", *DAY, "--dry-run", "--json")
    assert result.exit_code in (0, 1)  # finishes either way instead of stepping one unit at a time


def test_buy_max_finds_the_exact_count_far_from_the_estimate(cli, store, maple):
    got = receipt(cli("buy", "XEQT.TO", "max", "0.0001", "--fee-pct", "0.0005", *DAY, "--dry-run", "--json"))
    assert got["quantity"] == 6_000_000  # the fee rounds to $0.00, so the whole $600 buys units
