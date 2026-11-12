"""CSV import, export and history backfill options (#130, items 31–40) on a fictional ledger."""

import csv
import io
import json
import re
from datetime import date, timedelta

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Transaction, TxnType


def add(store, acct, kind, day, symbol="", qty=0.0, price=0.0, ccy="CAD", **extra):
    return store.add_transaction(
        Transaction(
            account_id=acct.saved_id,
            type=kind,
            date=day,
            symbol=symbol,
            quantity=qty,
            price=price,
            currency=ccy,
            **extra,
        )
    )


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "1000")  # golden output names temp paths, which are long on macOS
    return lambda *args, **kw: CliRunner().invoke(main, list(args), catch_exceptions=False, **kw)


@pytest.fixture
def ledger(store):
    maple = store.add_account(Account(name="Maple Cash", type=AccountType.NONREG, track_cash=True))
    birch = store.add_account(Account(name="Birch TFSA", type=AccountType.TFSA))
    cedar = store.add_account(Account(name="Old Cedar", type=AccountType.MARGIN))
    add(store, cedar, TxnType.BUY, "2024-12-02", "ZAG.TO", 10, 15)
    add(store, cedar, TxnType.SELL, "2024-12-20", "ZAG.TO", 10, 15.5)
    add(store, maple, TxnType.DEPOSIT, "2025-01-02", amount=5000)
    add(store, maple, TxnType.BUY, "2025-01-03", "XEQT.TO", 50, 30, fees=4.95, note="first lot, rounded")
    add(store, birch, TxnType.BUY, "2025-01-06", "VFV.TO", 10, 100)
    add(store, maple, TxnType.DIVIDEND, "2025-03-31", "XEQT.TO", amount=25)
    add(store, birch, TxnType.BUY, "2025-05-01", "AAPL", 2, 150, "USD", note="top-up")
    add(store, maple, TxnType.TRANSFER, "2025-06-02", "XEQT.TO", 10, 31, target_account_id=birch.saved_id)
    add(store, maple, TxnType.SPLIT, "2025-07-02", "XEQT.TO", ratio=2)
    cedar.archived = True
    store.update_account(cedar)
    return store


def csv_rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


IMPORT_CSV = (
    "date,account,type,symbol,quantity,price,amount,fees,currency,note\n"
    "2025-08-01,Maple Cash,BUY,XEQT.TO,5,33,,,CAD,\n"
    "2025-08-01,Maple Cash,BUY,XEQT.TO,5,33,,,CAD,\n"
    "2025-01-02,Maple Cash,DEPOSIT,,,,5000,,CAD,\n"
    "2025-08-02,Pine RRSP,DEPOSIT,,,,100,,CAD,\n"
    "2025-08-03,Maple Cash,BOGUS,,,,1,,CAD,\n"
)


@pytest.fixture
def incoming(tmp_path):
    """Two identical new fills, a row already in the ledger, a row for a new account, a bad type."""
    path = tmp_path / "incoming.csv"
    path.write_text(IMPORT_CSV)
    return path


# ── defaults stay byte-for-byte the same ──────────────────────────────────────

EXPORT = (
    "date,account,type,symbol,quantity,price,amount,fees,currency,note,ratio,target_account\n"
    "2024-12-02,Old Cedar,BUY,ZAG.TO,10,15,,,CAD,,,\n"
    "2024-12-20,Old Cedar,SELL,ZAG.TO,10,15.5,,,CAD,,,\n"
    "2025-01-02,Maple Cash,DEPOSIT,,,,5000,,CAD,,,\n"
    '2025-01-03,Maple Cash,BUY,XEQT.TO,50,30,,4.95,CAD,"first lot, rounded",,\n'
    "2025-01-06,Birch TFSA,BUY,VFV.TO,10,100,,,CAD,,,\n"
    "2025-03-31,Maple Cash,DIVIDEND,XEQT.TO,,,25,,CAD,,,\n"
    "2025-05-01,Birch TFSA,BUY,AAPL,2,150,,,USD,top-up,,\n"
    "2025-06-02,Maple Cash,TRANSFER,XEQT.TO,10,31,,,CAD,,,Birch TFSA\n"
    "2025-07-02,Maple Cash,SPLIT,XEQT.TO,,,,,CAD,,2,\n"
)
IMPORT_DRY_RUN = (
    "✓ Would import 3 transaction(s); 1 duplicate(s) skipped. (Generic CSV)\n"
    "! created account Pine RRSP\n"
    "  duplicate, line 4: 2025-01-02 DEPOSIT 5,000.00 CAD · Maple Cash\n"
    "! line 6, type 'BOGUS': unrecognized type 'BOGUS'\n"
)
IMPORT_DONE = (
    "✓ Imported 3 transaction(s); 1 duplicate(s) skipped. (Generic CSV)\n"
    "  pre-import backup: TMP/backups/marketpulse-STAMP-import.db\n"
    "! created account Pine RRSP\n"
    "  duplicate, line 4: 2025-01-02 DEPOSIT 5,000.00 CAD · Maple Cash\n"
    "! line 6, type 'BOGUS': unrecognized type 'BOGUS'\n"
)


def test_plain_export_is_unchanged(cli, ledger, tmp_path):
    assert cli("export").output == EXPORT
    out = tmp_path / "ledger.csv"
    assert cli("export", str(out)).output == f"✓ Exported 9 transactions to {out}\n"
    assert out.read_bytes() == EXPORT.replace("\n", "\r\n").encode()


def test_plain_import_is_unchanged(cli, ledger, incoming, tmp_path):
    result = cli("import", "--dry-run", str(incoming))
    assert (result.exit_code, result.output) == (0, IMPORT_DRY_RUN)
    result = cli("import", str(incoming))
    shown = re.sub(r"marketpulse-[0-9-]+-import", "marketpulse-STAMP-import", result.output)
    assert (result.exit_code, shown.replace(str(tmp_path), "TMP")) == (0, IMPORT_DONE)


# ── 31. export -a ──────────────────────────────────────────────────────────────


def test_export_account_filter(cli, ledger, tmp_path):
    rows = csv_rows(cli("export", "-a", "birch tfsa").output)
    assert [(r["date"], r["symbol"]) for r in rows] == [("2025-01-06", "VFV.TO"), ("2025-05-01", "AAPL")]
    rows = csv_rows(cli("export", "-a", "Old Cedar", "-a", "TFSA").output)  # archived, and a unique type
    assert [r["account"] for r in rows] == ["Old Cedar", "Old Cedar", "Birch TFSA", "Birch TFSA"]
    result = cli("export", "-a", "Nowhere")
    assert result.exit_code == 1 and "No account 'Nowhere'." in result.output


def test_filtered_export_reimports_as_duplicates(cli, ledger, tmp_path):
    out = tmp_path / "maple.csv"
    assert cli("export", "-a", "Maple Cash", str(out)).output == f"✓ Exported 5 transactions to {out}\n"
    report = json.loads(cli("import", "--json", "--dry-run", str(out)).output)
    assert (report["added"], report["duplicates"], report["issues"]) == (0, 5, [])


# ── 32. export --symbol / --type ───────────────────────────────────────────────


def test_export_symbol_and_type_filters(cli, ledger):
    rows = csv_rows(cli("export", "-s", " xeqt.to", "--type", "buy", "--type", "SPLIT").output)
    assert [(r["type"], r["symbol"]) for r in rows] == [("BUY", "XEQT.TO"), ("SPLIT", "XEQT.TO")]
    rows = csv_rows(cli("export", "--symbol", "AAPL", "--symbol", "ZAG.TO").output)
    assert [r["symbol"] for r in rows] == ["ZAG.TO", "ZAG.TO", "AAPL"]
    assert cli("export", "--symbol", " ").exit_code == 2
    assert cli("export", "--type", "bogus").exit_code == 2


# ── 33. export --since / --until ───────────────────────────────────────────────


def test_export_date_window(cli, ledger, tmp_path):
    rows = csv_rows(cli("export", "--since", "2025-01-03", "--until", "2025-05-01").output)
    assert [r["date"] for r in rows] == ["2025-01-03", "2025-01-06", "2025-03-31", "2025-05-01"]
    assert cli("export", "--since", "1900-01-01").output == EXPORT  # filtered output keeps the exact format
    out = tmp_path / "all.csv"
    cli("export", "--until", "2099-12-31", str(out))
    assert out.read_bytes() == EXPORT.replace("\n", "\r\n").encode()
    assert cli("export", "--since", "2025-06-01", "--until", "2025-01-01").exit_code == 2
    assert cli("export", "--since", "not a date").exit_code == 2


# ── 34. export --columns ───────────────────────────────────────────────────────


def test_export_columns(cli, ledger):
    text = cli("export", "--columns", "Symbol, date,amount", "--type", "DIVIDEND").output
    assert text == "symbol,date,amount\nXEQT.TO,2025-03-31,25\n"
    every = "date,account,type,symbol,quantity,price,amount,fees,currency,note,ratio,target_account"
    assert cli("export", "--columns", every).output == EXPORT
    result = cli("export", "--columns", "date,cost")
    assert result.exit_code == 2 and "Unknown column 'cost'" in result.output
    assert cli("export", "--columns", "date,date").exit_code == 2


# ── 35. export --count ─────────────────────────────────────────────────────────


def test_export_count(cli, ledger, tmp_path):
    assert cli("export", "--count").output == "9\n"
    assert cli("export", "--count", "-a", "Maple Cash", "--since", "2025-02-01").output == "3\n"
    assert cli("export", "--count", str(tmp_path / "x.csv")).exit_code == 2
    assert not (tmp_path / "x.csv").exists()
    assert cli("export", "--count", "--jsonl").exit_code == 2


# ── 36. export --jsonl ─────────────────────────────────────────────────────────


def test_export_json_lines(cli, ledger, tmp_path):
    lines = cli("export", "--jsonl").output.splitlines()
    assert len(lines) == 9
    first, transfer = json.loads(lines[0]), json.loads(lines[7])
    assert first == {
        "date": "2024-12-02",
        "account": "Old Cedar",
        "type": "BUY",
        "symbol": "ZAG.TO",
        "quantity": 10.0,
        "price": 15.0,
        "amount": 0.0,
        "fees": 0.0,
        "currency": "CAD",
        "note": "",
        "ratio": 0.0,
        "target_account": None,
    }
    assert transfer["type"] == "TRANSFER" and transfer["target_account"] == "Birch TFSA"
    picked = [
        json.loads(line)
        for line in cli("export", "--jsonl", "--columns", "date,note", "-s", "XEQT.TO").output.splitlines()
    ]
    assert picked[0] == {"date": "2025-01-03", "note": "first lot, rounded"}
    out = tmp_path / "ledger.jsonl"
    assert cli("export", "--jsonl", "--type", "BUY", str(out)).output == f"✓ Exported 4 transactions to {out}\n"
    assert len(out.read_text().splitlines()) == 4


# ── 37. import --summary ───────────────────────────────────────────────────────


def test_import_summary_preview_equals_import(cli, ledger, incoming):
    preview = cli("import", "--dry-run", "--summary", "account", str(incoming))
    assert preview.exit_code == 0
    assert preview.output.startswith(IMPORT_DRY_RUN)
    assert "Would import" in preview.output.split("\n", 4)[-1] and "Pine RRSP" in preview.output
    assert ledger.get_account("Pine RRSP") is None and len(ledger.transactions()) == 9
    planned = json.loads(cli("import", "--json", "--dry-run", "--summary", "account", str(incoming)).output)
    assert planned["summary"] == [{"group": "Maple Cash", "count": 2}, {"group": "Pine RRSP", "count": 1}]
    assert planned["backup"] is None and planned["dry_run"] is True and planned["added"] == 3
    plain = json.loads(cli("import", "--json", "--dry-run", str(incoming)).output)
    assert "summary" not in plain and plain["fingerprint"] == planned["fingerprint"]
    done = json.loads(cli("import", "--json", "--summary", "account", str(incoming)).output)
    assert done["summary"] == planned["summary"] and done["backup"] is not None
    assert len(ledger.transactions()) == 12


def test_import_summary_by_type_month_and_symbol(cli, ledger, incoming):
    by_type = json.loads(cli("import", "--json", "--dry-run", "--summary", "type", str(incoming)).output)
    assert by_type["summary"] == [{"group": "BUY", "count": 2}, {"group": "DEPOSIT", "count": 1}]
    by_month = json.loads(cli("import", "--json", "--dry-run", "--summary", "month", str(incoming)).output)
    assert by_month["summary"] == [{"group": "2025-08", "count": 3}]
    text = cli("import", "--summary", "symbol", str(incoming)).output
    assert "Imported" in text.split("\n", 4)[-1] and "(no symbol)" in text and "XEQT.TO" in text


# ── 38. import --exit-code ─────────────────────────────────────────────────────


def test_import_exit_code_on_skipped_rows(cli, ledger, incoming, tmp_path):
    result = cli("import", "--dry-run", "--exit-code", str(incoming))
    assert (result.exit_code, result.output) == (1, IMPORT_DRY_RUN)
    result = cli("import", "--json", "--dry-run", "--exit-code", str(incoming))
    assert result.exit_code == 1 and json.loads(result.output)["issues"][0]["line"] == 6
    clean = tmp_path / "clean.csv"
    clean.write_text(IMPORT_CSV.rsplit("2025-08-03", 1)[0])
    assert cli("import", "--exit-code", str(clean)).exit_code == 0
    assert len(ledger.transactions()) == 12


# ── 39 and 40. backfill --dry-run and --json ───────────────────────────────────


@pytest.fixture
def history(store, fake):
    days = [(date.today() - timedelta(days=n)).isoformat() for n in (3, 2, 1, 0)]
    acct = store.add_account(Account(name="Spruce Margin", type=AccountType.MARGIN))
    add(store, acct, TxnType.BUY, days[0], "AAPL", 10, 100, "USD")
    fake.set_history("AAPL", dict(zip(days, [100, 110, 120, 130], strict=True)))
    fake.set_history("USDCAD=X", dict.fromkeys(days, 1.3), currency="CAD")
    return days


def test_plain_backfill_is_unchanged(cli, store, history):
    assert cli("backfill").output == "✓ Rebuilt 4 daily snapshots.\n"


def test_backfill_dry_run_writes_nothing(cli, store, history):
    result = cli("backfill", "--dry-run")
    assert result.exit_code == 0
    assert result.output == (
        f"✓ Would rebuild 4 daily snapshots ({history[0]} to {history[-1]}): 4 new, 0 replacing existing ones. "
        "Nothing was written.\n"
    )
    assert store.snapshots() == []
    assert cli("backfill").exit_code == 0
    assert "0 new, 4 replacing" in cli("backfill", "--dry-run").output


def test_backfill_json(cli, store, history):
    preview = json.loads(cli("backfill", "--json", "--dry-run").output)
    assert preview == {
        "dry_run": True,
        "snapshots": 4,
        "new": 4,
        "replaced": 0,
        "first": history[0],
        "last": history[-1],
        "currency": "CAD",
    }
    assert store.snapshots() == []
    done = json.loads(cli("backfill", "--json").output)
    assert done == {**preview, "dry_run": False}
    assert [s.date for s in store.snapshots()] == history
    again = json.loads(cli("backfill", "--json").output)
    assert (again["new"], again["replaced"]) == (0, 4)


def test_backfill_options_on_an_empty_ledger_and_a_refusal(cli, store, fake):
    assert json.loads(cli("backfill", "--json", "--dry-run").output)["snapshots"] == 0
    assert "Would rebuild 0 daily snapshots: 0 new" in cli("backfill", "--dry-run").output
    old = store.add_account(Account(name="Old Cedar", type=AccountType.MARGIN))
    add(store, old, TxnType.BUY, (date.today() - timedelta(days=2)).isoformat(), "AAPL", 1, 100, "USD")
    old.archived = True
    store.update_account(old)
    for args in (("--dry-run",), ("--json",)):
        result = cli("backfill", *args)
        assert result.exit_code == 1 and "Archived account Old Cedar still holds" in result.output
    assert store.snapshots() == []
