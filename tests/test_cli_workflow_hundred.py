"""Tests for the 80 CLI improvements (1-80) in the 100 CLI & TUI workflow batch."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from marketpulse.cli import App, main
from marketpulse.db import Snapshot, Store
from marketpulse.models import (
    Account,
    AccountType,
    Alert,
    Asset,
    AssetClass,
    AssetKind,
    Transaction,
    TxnType,
)


@pytest.fixture
def cli_store(isolated_env) -> Store:
    s = Store()
    yield s
    s.close()


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    runner = CliRunner()

    def invoke(*args: str, input_text: str | None = None):
        return runner.invoke(main, list(args), input=input_text, catch_exceptions=False)

    return invoke


def _cli(*args: str, input_text: str | None = None):
    return CliRunner().invoke(main, list(args), input=input_text, catch_exceptions=False)


# ── Track 1: Tax (1-10) & Allocation / Targets (11-20) ────────────────────────


def test_tax_improvements_1_to_10(store, cli):
    acct = store.add_account(Account(name="Taxable", type=AccountType.NONREG, currency="CAD"))
    # CAD gain in 2024
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.BUY,
            date="2024-01-10",
            symbol="XEQT.TO",
            quantity=10,
            price=25,
            currency="CAD",
        )
    )
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.SELL,
            date="2024-06-15",
            symbol="XEQT.TO",
            quantity=10,
            price=35,
            currency="CAD",
        )
    )
    # Superficial loss in 2024
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.BUY,
            date="2024-07-01",
            symbol="VFV.TO",
            quantity=10,
            price=100,
            currency="CAD",
        )
    )
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.SELL,
            date="2024-07-10",
            symbol="VFV.TO",
            quantity=10,
            price=90,
            currency="CAD",
        )
    )
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.BUY,
            date="2024-07-20",
            symbol="VFV.TO",
            quantity=10,
            price=92,
            currency="CAD",
        )
    )
    # USD gain in 2025
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.BUY,
            date="2025-01-05",
            symbol="AAPL",
            quantity=5,
            price=100,
            currency="USD",
        )
    )
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.SELL,
            date="2025-03-01",
            symbol="AAPL",
            quantity=5,
            price=120,
            currency="USD",
        )
    )

    # 1-2: --since / --until
    r = cli("tax", "--since", "2024-07-01", "--until", "2024-12-31", "--json")
    assert r.exit_code == 0
    rows = json.loads(r.output)
    assert [row["symbol"] for row in rows] == ["VFV.TO"]

    # 3-4: --currency / --exclude-currency
    r = cli("tax", "--currency", "USD", "--json")
    assert r.exit_code == 0 and [row["symbol"] for row in json.loads(r.output)] == ["AAPL"]
    r = cli("tax", "--exclude-currency", "USD", "--json")
    assert r.exit_code == 0 and all(row["currency"] == "CAD" for row in json.loads(r.output))

    # 5-6: --exclude-symbol / --exact-symbol
    r = cli("tax", "--exclude-symbol", "vfv", "--json")
    assert r.exit_code == 0 and all(row["symbol"] != "VFV.TO" for row in json.loads(r.output))
    r = cli("tax", "--exact-symbol", "xeqt.to", "--json")
    assert r.exit_code == 0 and [row["symbol"] for row in json.loads(r.output)] == ["XEQT.TO"]

    # 7: --superficial
    r = cli("tax", "--superficial", "--json")
    assert r.exit_code == 0
    sup = json.loads(r.output)
    assert len(sup) == 1 and sup[0]["symbol"] == "VFV.TO"

    # 8-9: --min-gain / --max-gain
    r = cli("tax", "--min-gain", "50", "--json")
    assert r.exit_code == 0 and all(row["allowed_gain"] >= 50 for row in json.loads(r.output))
    r = cli("tax", "--max-gain", "10", "--json")
    assert r.exit_code == 0 and all(row["allowed_gain"] <= 10 for row in json.loads(r.output))

    # 10: --jsonl
    r = cli("tax", "--jsonl")
    assert r.exit_code == 0
    lines = [json.loads(line) for line in r.output.strip().splitlines()]
    assert len(lines) == 3


def test_allocation_and_targets_improvements_11_to_20(store, cli):
    acct = store.add_account(Account(name="TFSA", type=AccountType.TFSA, currency="CAD"))
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.BUY,
            date="2024-01-02",
            symbol="XEQT.TO",
            quantity=10,
            price=30,
            currency="CAD",
        )
    )
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.BUY,
            date="2024-01-02",
            symbol="AAPL",
            quantity=2,
            price=150,
            currency="USD",
        )
    )
    store.upsert_asset(Asset(symbol="XEQT.TO", asset_class=AssetClass.ETF))
    store.upsert_asset(Asset(symbol="AAPL", asset_class=AssetClass.EQUITY))
    store.set_targets({"etf": 70.0, "equity": 20.0})

    # 11: --max-weight
    r = cli("allocation", "--max-weight", "60", "--json")
    assert r.exit_code == 0
    assert all(row["weight"] <= 60 for row in json.loads(r.output)["rows"])

    # 12-13: --search / --exclude
    r = cli("allocation", "--search", "etf", "--json")
    assert r.exit_code == 0 and [row["key"] for row in json.loads(r.output)["rows"]] == ["etf"]
    r = cli("allocation", "--exclude", "etf", "--json")
    assert r.exit_code == 0 and all(row["key"] != "etf" for row in json.loads(r.output)["rows"])

    # 14: --jsonl
    r = cli("allocation", "--jsonl")
    assert r.exit_code == 0
    assert len([json.loads(line) for line in r.output.strip().splitlines()]) == 2

    # 15-16: --limit / --offset
    r = cli("allocation", "--sort", "name", "--offset", "1", "--limit", "1", "--json")
    assert r.exit_code == 0 and len(json.loads(r.output)["rows"]) == 1

    # 17: --drift-only --sort [target|drift|abs-drift|delta]
    for key in ("target", "drift", "abs-drift", "delta"):
        r = cli("allocation", "--drift-only", "--sort", key, "--json")
        assert r.exit_code == 0 and len(json.loads(r.output)) >= 2

    # 18: targets --summary
    r = cli("targets", "--summary", "--json")
    assert r.exit_code == 0
    summary = json.loads(r.output)
    assert (
        summary["count"] == 2
        and summary["total"] == 90.0
        and summary["unallocated"] == 10.0
        and not summary["complete"]
    )

    # 19: targets --untargeted
    r = cli("targets", "--untargeted", "--buckets-only")
    assert r.exit_code == 0
    untargeted = r.output.strip().splitlines()
    assert "etf" not in untargeted and "equity" not in untargeted and "cash" in untargeted

    # 20: targets --require-100
    assert cli("targets", "--require-100").exit_code == 1
    store.set_targets({"etf": 70.0, "equity": 30.0})
    assert cli("targets", "--require-100").exit_code == 0


# ── Track 2: Doctor (21-25), Provider (26-30), Discovery (31-35), Settings (36-40) ──


def test_doctor_and_provider_improvements_21_to_30(cli):
    # 21: doctor --quiet
    r = cli("doctor", "--offline", "--quiet")
    assert r.exit_code == 0 and r.output == ""

    # 22: doctor --exclude-status
    r = cli("doctor", "--offline", "--exclude-status", "skipped", "--json")
    assert r.exit_code == 0
    assert all(c["status"] != "skipped" for c in json.loads(r.output)["checks"])

    # 23: doctor --sort
    r = cli("doctor", "--offline", "--sort", "check", "--json")
    names = [c["check"] for c in json.loads(r.output)["checks"]]
    assert names == sorted(names)

    # 24: doctor --names-only
    r = cli("doctor", "--offline", "--names-only")
    assert r.exit_code == 0 and "database" in r.output.splitlines()

    # 25: doctor --jsonl
    r = cli("doctor", "--offline", "--jsonl")
    assert r.exit_code == 0
    assert all("check" in json.loads(line) for line in r.output.strip().splitlines())

    # 26: provider status --supported
    r = cli("provider", "status", "--supported", "--json")
    assert r.exit_code == 0 and len(json.loads(r.output)) >= 1
    assert cli("provider", "status", "--supported", "--count").exit_code == 0

    # 27-28: provider status --search / --exit-code
    r = cli("provider", "status", "--search", "yahoo", "--json")
    assert r.exit_code == 0 and len(json.loads(r.output)) == 1
    assert cli("provider", "status", "--exit-code").exit_code == 0

    # 29-30: provider key / clear --dry-run --json
    r = cli("provider", "key", "alphavantage", "--dry-run", "--json", input_text="demo-key-123\n")
    assert r.exit_code == 0
    payload = json.loads(r.output)
    assert payload["provider"] == "alphavantage" and payload["saved"] is False and "demo-key-123" not in r.output
    r = cli("provider", "clear", "--dry-run", "--json")
    assert r.exit_code == 0 and json.loads(r.output)["cleared"] is False


def test_discovery_and_settings_improvements_31_to_40(tmp_path: Path):
    # 31: commands --has-options / --no-options
    r = _cli("commands", "--leaves", "--no-options", "--json")
    assert r.exit_code == 0
    assert all(isinstance(row["command"], str) for row in json.loads(r.output))

    # 32: commands --exclude-option
    r = _cli("commands", "--leaves", "--exclude-option", "--json", "--paths")
    assert r.exit_code == 0 and "doctor" not in r.output.splitlines()

    # 33: commands --param-type
    r = _cli("commands", "--param-type", "choice", "--count")
    assert r.exit_code == 0 and int(r.output.strip()) > 0

    # 34: commands --sort
    r = _cli("commands", "--sort", "depth", "--json")
    depths = [row["depth"] for row in json.loads(r.output)]
    assert depths == sorted(depths)

    # 35: commands --jsonl
    r = _cli("commands", "--limit", "3", "--jsonl")
    assert r.exit_code == 0 and len([json.loads(line) for line in r.output.strip().splitlines()]) == 3

    # 36: theme list --json --page-info
    r = _cli("theme", "list", "--limit", "2", "--json", "--page-info")
    assert r.exit_code == 0
    page = json.loads(r.output)
    assert len(page["rows"]) == 2 and page["total"] >= 2

    # 37: theme set --dry-run --json
    r = _cli("theme", "set", "nord", "--dry-run", "--json")
    assert r.exit_code == 0 and json.loads(r.output)["saved"] is False

    # 38: config diff --details
    assert _cli("config", "set", "base_currency", "USD").exit_code == 0
    r = _cli("config", "diff", "--details", "--json")
    assert r.exit_code == 0
    diffs = json.loads(r.output)
    assert diffs == [{"key": "base_currency", "default": "CAD", "value": "USD"}]

    # 39: config defaults --value
    r = _cli("config", "defaults", "base_currency", "--value")
    assert r.exit_code == 0 and r.output.strip() == "CAD"

    # 40: config validate --file
    good = tmp_path / "good.toml"
    good.write_text('base_currency = "CAD"\n', encoding="utf-8")
    assert _cli("config", "validate", "--file", str(good), "--quiet").exit_code == 0
    bad = tmp_path / "bad.toml"
    bad.write_text('base_currency = "INVALID"\n', encoding="utf-8")
    assert _cli("config", "validate", "--file", str(bad), "--quiet").exit_code == 1


# ── Track 3: Accounts (41-50), Watchlist & Alerts (51-60) ─────────────────────


def test_accounts_improvements_41_to_50(store, cli):
    a1 = store.add_account(Account(name="TFSA", type=AccountType.TFSA, currency="CAD"))
    a2 = store.add_account(Account(name="Old", type=AccountType.NONREG, currency="CAD", archived=True))

    # 41-44: accounts list --jsonl / --names / --ids / --archived-only
    r = cli("accounts", "list", "--jsonl")
    assert r.exit_code == 0 and len([json.loads(line) for line in r.output.strip().splitlines()]) == 1
    assert cli("accounts", "list", "--names").output.strip() == "TFSA"
    assert cli("accounts", "list", "--ids").output.strip() == str(a1.id)
    r = cli("accounts", "list", "--archived-only", "--names")
    assert r.exit_code == 0 and r.output.strip() == "Old"

    # 45-46: accounts show --archived / --exists
    r = cli("accounts", "show", str(a2.id), "--archived", "--json")
    assert r.exit_code == 0 and json.loads(r.output)["name"] == "Old"
    assert cli("accounts", "show", "TFSA", "--exists").exit_code == 0
    assert cli("accounts", "show", "Nope", "--exists").exit_code == 1

    # 47-48: accounts edit --json / accounts remove --json
    r = cli("accounts", "edit", "TFSA", "--institution", "Questrade", "--dry-run", "--json")
    assert r.exit_code == 0
    edited = json.loads(r.output)
    assert edited["saved"] is False and edited["changes"]["institution"]["to"] == "Questrade"
    r = cli("accounts", "remove", "TFSA", "--dry-run", "--json")
    assert r.exit_code == 0 and json.loads(r.output)["deleted"] is False

    # 49-50: accounts room --dry-run / --json
    r = cli("accounts", "room", "TFSA", "2026", "20000", "--dry-run", "--json")
    assert r.exit_code == 0 and json.loads(r.output)["saved"] is False
    r = cli("accounts", "room", "TFSA", "2026", "20000", "--json")
    assert r.exit_code == 0 and json.loads(r.output)["saved"] is True
    r = cli("accounts", "room", "--json")
    assert r.exit_code == 0 and len(json.loads(r.output)) == 1


def test_watchlist_and_alerts_improvements_51_to_60(store, cli):
    acct = store.add_account(Account(name="TFSA", type=AccountType.TFSA, currency="CAD"))
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.BUY,
            date="2024-01-02",
            symbol="XEQT.TO",
            quantity=10,
            price=30,
            currency="CAD",
        )
    )
    store.remove_watch(store.watchlist())
    store.add_watch(["AAPL", "XEQT.TO", "VFV.TO"])
    al1 = store.add_alert(Alert(symbol="XEQT.TO", condition="above", threshold=40.0))
    al2 = store.add_alert(Alert(symbol="AAPL", condition="below", threshold=100.0))

    # 51-52: watch list --prefix / --jsonl
    r = cli("watch", "list", "--prefix", "xe", "--lines")
    assert r.exit_code == 0 and r.output.strip() == "XEQT.TO"
    r = cli("watch", "list", "--jsonl")
    assert r.exit_code == 0 and len([json.loads(line) for line in r.output.strip().splitlines()]) == 3

    # 53: watch move --dry-run --json
    r = cli("watch", "move", "VFV.TO", "--to", "1", "--dry-run", "--json")
    assert r.exit_code == 0 and json.loads(r.output) == {"symbol": "VFV.TO", "from": 3, "to": 1, "saved": False}

    # 54-55: watch add --from-holdings / watch rm --json
    store.remove_watch(["XEQT.TO"])
    r = cli("watch", "add", "--from-holdings", "--dry-run", "--json")
    assert r.exit_code == 0 and json.loads(r.output) == {"added": ["XEQT.TO"], "saved": False}
    r = cli("watch", "rm", "AAPL", "--dry-run", "--json")
    assert r.exit_code == 0 and json.loads(r.output) == {"removed": ["AAPL"], "saved": False}

    # 56-58: alerts list --jsonl / --ids / --held / --not-held
    r = cli("alerts", "list", "--jsonl")
    assert r.exit_code == 0 and len([json.loads(line) for line in r.output.strip().splitlines()]) == 2
    r = cli("alerts", "list", "--held", "--ids")
    assert r.exit_code == 0 and r.output.strip() == str(al1.id)
    r = cli("alerts", "list", "--not-held", "--ids")
    assert r.exit_code == 0 and r.output.strip() == str(al2.id)

    # 59: alerts show --exists
    assert cli("alerts", "show", str(al1.id), "--exists").exit_code == 0
    assert cli("alerts", "show", "999", "--exists").exit_code == 1

    # 60: alerts pause/resume/rearm/rm --dry-run --json
    r = cli("alerts", "pause", str(al1.id), "--dry-run", "--json")
    assert r.exit_code == 0 and json.loads(r.output) == {"action": "pause", "ids": [al1.id], "saved": False}
    r = cli("alerts", "rm", str(al1.id), "--dry-run", "--json")
    assert r.exit_code == 0 and json.loads(r.output) == {"removed": [al1.id], "deleted": False}


# ── Track 4: Positions (61-65), Snapshots (66-70), Assets (71-75), Data (76-80) ──


def test_positions_and_snapshots_improvements_61_to_70(store, cli):
    acct = store.add_account(Account(name="CashTFSA", type=AccountType.TFSA, currency="CAD", track_cash=True))
    store.add_transaction(
        Transaction(account_id=acct.id, type=TxnType.DEPOSIT, date="2024-01-01", amount=1000, currency="CAD")
    )
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.BUY,
            date="2024-01-02",
            symbol="XEQT.TO",
            quantity=10,
            price=30,
            currency="CAD",
        )
    )
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.BUY,
            date="2024-01-02",
            symbol="AAPL",
            quantity=2,
            price=100,
            currency="USD",
        )
    )
    store.upsert_snapshots(
        [
            Snapshot(date="2024-01-01", net_worth=1000.0, book=1000.0, contributions=1000.0, currency="CAD", detail=""),
            Snapshot(date="2024-03-31", net_worth=1200.0, book=1000.0, contributions=1000.0, currency="CAD", detail=""),
            Snapshot(date="2024-04-01", net_worth=950.0, book=1000.0, contributions=1000.0, currency="CAD", detail=""),
        ]
    )

    # 61-64: positions --jsonl / --symbols-only / --symbol-suffix / --totals
    r = cli("positions", "--jsonl")
    assert r.exit_code == 0 and len([json.loads(line) for line in r.output.strip().splitlines()]) == 2
    r = cli("positions", "--symbol-suffix", ".TO", "--symbols-only")
    assert r.exit_code == 0 and r.output.strip() == "XEQT.TO"
    r = cli("positions", "--totals", "--json")
    assert r.exit_code == 0
    totals = {row["currency"]: row["book"] for row in json.loads(r.output)}
    assert totals == {"CAD": 300.0, "USD": 200.0}

    # 65: cash --totals
    r = cli("cash", "--totals", "--json")
    assert r.exit_code == 0
    cash_totals = {row["currency"]: row["balance"] for row in json.loads(r.output)}
    assert cash_totals["CAD"] == 700.0

    # 66-70: snapshots --quarter-start-only / --quarter-end-only / --above-book / --below-book / --stats
    assert cli("snapshots", "--quarter-start-only", "--dates").output.strip().splitlines() == [
        "2024-01-01",
        "2024-04-01",
    ]
    assert cli("snapshots", "--quarter-end-only", "--dates").output.strip().splitlines() == ["2024-03-31"]
    assert cli("snapshots", "--above-book", "--dates").output.strip().splitlines() == ["2024-03-31"]
    assert cli("snapshots", "--below-book", "--dates").output.strip().splitlines() == ["2024-04-01"]
    r = cli("snapshots", "--stats", "--json")
    assert r.exit_code == 0
    st = json.loads(r.output)
    assert st["count"] == 3 and st["min_net_worth"] == 950.0 and st["max_net_worth"] == 1200.0


def test_assets_and_data_improvements_71_to_80(cli_store, tmp_path: Path):
    acct = cli_store.add_account(Account(name="TFSA", type=AccountType.TFSA, currency="CAD"))
    cli_store.upsert_asset(
        Asset(symbol="HOUSE", kind=AssetKind.MANUAL, name="Home", asset_class=AssetClass.REAL_ESTATE, currency="CAD")
    )
    cli_store.upsert_asset(
        Asset(symbol="UNUSED", kind=AssetKind.MANUAL, name="Unused", asset_class=AssetClass.ALTERNATIVE, currency="CAD")
    )
    cli_store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.BUY,
            date="2024-01-02",
            symbol="HOUSE",
            quantity=1,
            price=500000,
            currency="CAD",
        )
    )

    # 71-72: asset list --jsonl / --held / --not-held
    r = _cli("asset", "list", "--jsonl")
    assert r.exit_code == 0 and len([json.loads(line) for line in r.output.strip().splitlines()]) == 2
    assert _cli("asset", "list", "--held", "--symbols-only").output.strip() == "HOUSE"
    assert _cli("asset", "list", "--not-held", "--symbols-only").output.strip() == "UNUSED"

    # 73-75: asset classify --clear / asset remove --dry-run / asset value -a --dry-run
    r = _cli("asset", "classify", "UNUSED", "--clear", "--dry-run", "--json")
    assert r.exit_code == 0 and json.loads(r.output) == {"symbol": "UNUSED", "asset_class": None, "saved": False}
    r = _cli("asset", "remove", "HOUSE", "--dry-run", "--json")
    assert r.exit_code == 0 and json.loads(r.output) == {"symbol": "HOUSE", "active_holdings": 1, "removed": False}
    r = _cli("asset", "value", "HOUSE", "525000", "-a", "TFSA", "--dry-run", "--json")
    assert r.exit_code == 0 and json.loads(r.output)["saved"] is False

    # 76: import --strict
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text(
        "date,account,type,symbol,quantity,price,amount,fees,currency,note\n"
        "2024-02-01,TFSA,BUY,XEQT.TO,5,30,,,CAD,\n"
        "2024-02-02,TFSA,SELL,MISSING,5,30,,,CAD,\n",
        encoding="utf-8",
    )
    before_count = len(cli_store.transactions())
    r = _cli("import", str(bad_csv), "--strict", "--json")
    assert r.exit_code == 1
    assert json.loads(r.output)["strict_aborted"] is True
    assert len(cli_store.transactions()) == before_count

    # 77-78: export --no-overwrite / --dry-run
    out_csv = tmp_path / "out.csv"
    r = _cli("export", str(out_csv), "--dry-run")
    assert r.exit_code == 0 and not out_csv.exists()
    out_csv.write_text("existing", encoding="utf-8")
    assert _cli("export", str(out_csv), "--no-overwrite").exit_code == 1

    # 79-80: backup verify --quiet / --csv & backup restore --dry-run --json
    bak = cli_store.backup(reason="manual")
    r = _cli("backup", "verify", str(bak), "--quiet")
    assert r.exit_code == 0 and r.output == ""
    r = _cli("backup", "verify", str(bak), "--csv")
    assert r.exit_code == 0
    rows = list(csv.DictReader(io.StringIO(r.output)))
    assert len(rows) == 1 and rows[0]["ok"] == "True"
    r = _cli("backup", "restore", str(bak), "--dry-run", "--json")
    assert r.exit_code == 0
    preview = json.loads(r.output)
    assert preview["restored"] is False and "current" in preview and "backup" in preview
