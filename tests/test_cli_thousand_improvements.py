"""The 16 standalone CLI improvements in issue #153, on fictional, offline data.

Each test states its expected output independently of the code, and checks that
a preview (`--dry-run`) or a refused command leaves the saved data unchanged.
"""

import json
import os
from dataclasses import asdict
from datetime import date

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Alert, Asset, AssetClass, AssetKind, Transaction, TxnType

# Room can be given as of Jan 1 of next year at the latest.
NEXT_YEAR = date.today().year + 1


@pytest.fixture
def cli(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "160")
    fake.offline = True
    runner = CliRunner()

    def invoke(*args, input=None):
        result = runner.invoke(main, list(args), input=input, catch_exceptions=False)
        assert fake.calls == []  # every improvement is offline
        return result

    return invoke


@pytest.fixture
def ledger(store):
    """Two fictional accounts, one with a transaction, plus an archived one."""
    maple = store.add_account(Account(name="Fictional Maple", institution="Fictional Bank"))
    gull = store.add_account(Account(name="Fictional Gull", type=AccountType.TFSA, currency="USD"))
    store.add_account(Account(name="Hidden Fiction", archived=True))
    store.add_transaction(Transaction(maple.saved_id, TxnType.BUY, "2024-01-02", "MAPL", 10, 10, currency="CAD"))
    return maple, gull


def _accounts(store):
    return [asdict(a) for a in store.accounts(include_archived=True)]


def _alerts(store):
    return [asdict(a) for a in store.alerts()]


def _alert(store, symbol="ALPHA", condition="above", threshold=50.0, **kwargs):
    return store.add_alert(Alert(symbol=symbol, condition=condition, threshold=threshold, **kwargs)).saved_id


# 1 ── accounts add --dry-run ───────────────────────────────────────────────────


def test_1_accounts_add_dry_run_previews_without_saving(cli, store, ledger):
    before = _accounts(store)
    result = cli("accounts", "add", "Fictional Wren", "-t", "rrsp", "-c", "usd", "--dry-run")
    assert result.exit_code == 0
    assert "Would add Fictional Wren (RRSP, USD); nothing saved." in result.output
    assert _accounts(store) == before


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("   ", "Account name is required."),
        ("fictional maple", "An account named 'fictional maple' already exists."),
        ("HIDDEN FICTION", "An account named 'HIDDEN FICTION' already exists."),  # archived names are taken too
    ],
)
def test_1_accounts_add_dry_run_reports_the_errors_a_real_add_would(cli, store, ledger, name, message):
    before = _accounts(store)
    dry = cli("accounts", "add", name, "--dry-run")
    assert dry.exit_code == 1
    assert message in dry.output
    assert _accounts(store) == before
    real = cli("accounts", "add", name)
    assert real.exit_code == 1
    assert message in real.output


# 2 ── accounts add --json ──────────────────────────────────────────────────────


def test_2_accounts_add_json_prints_the_saved_account(cli, store, ledger):
    result = cli("accounts", "add", "  Fictional Wren  ", "-t", "fhsa", "-i", "Fictional Credit", "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["id"] == 4
    assert payload["saved"] is True
    assert {k: payload[k] for k in ("name", "type", "currency", "institution", "track_cash", "archived")} == {
        "name": "Fictional Wren",
        "type": "FHSA",
        "currency": "CAD",
        "institution": "Fictional Credit",
        "track_cash": False,
        "archived": False,
    }
    assert store.get_account(4).name == "Fictional Wren"


def test_2_accounts_add_json_with_dry_run_has_no_id(cli, store, ledger):
    before = _accounts(store)
    result = cli("accounts", "add", "Fictional Wren", "--track-cash", "--json", "--dry-run")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert (payload["id"], payload["saved"], payload["track_cash"], payload["type"]) == (None, False, True, "NONREG")
    assert _accounts(store) == before


# 3 ── account currencies must be 3-letter codes ────────────────────────────────


@pytest.mark.parametrize("bad", ["usdollar", "US", "C4D", "  ", "ÉUR"])
def test_3_accounts_add_and_edit_refuse_a_currency_that_is_not_a_code(cli, store, ledger, bad):
    before = _accounts(store)
    for args in (("accounts", "add", "Fictional Wren", "-c", bad), ("accounts", "edit", "Fictional Gull", "-c", bad)):
        result = cli(*args)
        assert result.exit_code == 2
        assert "is not a 3-letter currency code like CAD" in result.output
    assert _accounts(store) == before


def test_3_account_currencies_are_trimmed_and_upper_cased(cli, store, ledger):
    assert cli("accounts", "add", "Fictional Wren", "-c", " eur ").exit_code == 0
    assert store.get_account("Fictional Wren").currency == "EUR"
    assert cli("accounts", "edit", "Fictional Gull", "-c", " gbp").exit_code == 0
    assert store.get_account("Fictional Gull").currency == "GBP"


# 4 ── accounts edit --dry-run ──────────────────────────────────────────────────


def test_4_accounts_edit_dry_run_lists_each_change_and_saves_nothing(cli, store, ledger):
    before = _accounts(store)
    result = cli(
        "accounts", "edit", "Fictional Gull", "--name", "Fictional Tern", "-c", "cad", "--track-cash", "--dry-run"
    )
    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "✓ Would update Fictional Gull (#2); nothing saved:",
        "  name: Fictional Gull → Fictional Tern",
        "  currency: USD → CAD",
        "  track_cash: False → True",
    ]
    assert _accounts(store) == before


def test_4_accounts_edit_dry_run_without_changes_says_so(cli, store, ledger):
    result = cli("accounts", "edit", "Fictional Gull", "-t", "tfsa", "--dry-run")
    assert result.exit_code == 0
    assert "No changes to Fictional Gull; nothing saved." in result.output


def test_4_accounts_edit_dry_run_reports_name_clashes_and_stale_revisions(cli, store, ledger):
    before = _accounts(store)
    clash = cli("accounts", "edit", "Fictional Gull", "--name", "FICTIONAL MAPLE", "--dry-run")
    assert clash.exit_code == 1
    assert "An account named 'FICTIONAL MAPLE' already exists." in clash.output
    stale = cli("accounts", "edit", "Fictional Gull", "--name", "Fictional Tern", "--revision", "stale", "--dry-run")
    assert stale.exit_code == 1
    assert "Fictional Gull has changed since it was loaded" in stale.output
    assert _accounts(store) == before


# 5 ── accounts remove --dry-run ────────────────────────────────────────────────


def test_5_accounts_remove_dry_run_counts_transactions_and_deletes_nothing(cli, store, ledger):
    before = _accounts(store)
    transactions = store.transactions()
    result = cli("accounts", "remove", "Fictional Maple", "--dry-run")
    assert result.exit_code == 0
    assert "Would delete Fictional Maple (#1) and its 1 transaction(s); nothing deleted." in result.output
    assert "accounts edit Fictional Maple --archive" in result.output
    assert _accounts(store) == before
    assert store.transactions() == transactions


def test_5_accounts_remove_dry_run_never_prompts(cli, store, ledger):
    # No input is given: a confirmation prompt would abort with exit code 1.
    result = cli("accounts", "remove", "Fictional Gull", "--dry-run")
    assert result.exit_code == 0
    assert "Would delete Fictional Gull (#2) and its 0 transaction(s)" in result.output
    assert store.get_account("Fictional Gull") is not None


# 6 ── accounts room validation ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("year", "amount", "message"),
    [
        ("2026", "nan", "Contribution room must be a finite amount."),
        ("2026", "inf", "Contribution room must be a finite amount."),
        ("2026", "-inf", "Contribution room must be a finite amount."),
        ("26", "7000", f"Year must be between 1957 and {NEXT_YEAR}; give all four digits, like 2026."),
        ("1956", "7000", f"Year must be between 1957 and {NEXT_YEAR}"),
        (str(NEXT_YEAR + 1), "7000", f"Year must be between 1957 and {NEXT_YEAR}"),
    ],
)
def test_6_accounts_room_refuses_bad_amounts_and_years(cli, store, year, amount, message):
    result = cli("accounts", "room", "--", "TFSA", year, amount)
    assert result.exit_code == 1
    assert message in result.output
    assert store.rooms() == {}


@pytest.mark.parametrize(("year", "amount"), [("1957", "0"), (str(NEXT_YEAR), "7000"), ("2026", "-250.5")])
def test_6_accounts_room_still_saves_plausible_room(cli, store, year, amount):
    # CRA can report negative room after an over-contribution, so only non-finite amounts are refused.
    result = cli("accounts", "room", "--", "rrsp", year, amount)
    assert result.exit_code == 0
    assert store.rooms() == {"RRSP": (int(year), float(amount))}


# 7 ── alerts add --dry-run ─────────────────────────────────────────────────────


def test_7_alerts_add_dry_run_validates_and_saves_nothing(cli, store):
    result = cli("alerts", "add", "alpha", ">", "50", "--dry-run")
    assert result.exit_code == 0
    assert "Would add alert: ALPHA ≥ 50.00 (not saved)." in result.output
    assert store.alerts() == []
    bad = cli("alerts", "add", "--dry-run", "--", "alpha", "above", "-5")
    assert bad.exit_code == 1
    assert "Alert threshold must be finite and positive." in bad.output
    assert store.alerts() == []


# 8 ── alerts add --json ────────────────────────────────────────────────────────


def test_8_alerts_add_json_prints_the_saved_alert(cli, store):
    _alert(store, "OMEGA")
    result = cli("alerts", "add", "beta", "down", "4.5", "-m", "Fictional note", "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "symbol": "BETA",
        "condition": "down_pct",
        "threshold": 4.5,
        "note": "Fictional note",
        "active": True,
        "triggered_at": "",
        "id": 2,
        "state": "armed",
        "saved": True,
    }
    assert [a.symbol for a in store.alerts()] == ["BETA", "OMEGA"]


def test_8_alerts_add_json_with_dry_run(cli, store):
    result = cli("alerts", "add", "beta", "<", "12", "--json", "--dry-run")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert (payload["id"], payload["condition"], payload["saved"]) == (None, "below", False)
    assert store.alerts() == []


# 9 ── alert symbols are trimmed ────────────────────────────────────────────────


def test_9_alerts_add_trims_spaces_around_the_symbol(cli, store):
    result = cli("alerts", "add", "  gamma.to ", "above", "10")
    assert result.exit_code == 0
    assert "Alert #1: GAMMA.TO ≥ 10.00" in result.output
    assert [a.symbol for a in store.alerts()] == ["GAMMA.TO"]


# 10 ── alerts edit --dry-run ───────────────────────────────────────────────────


def test_10_alerts_edit_dry_run_previews_without_saving(cli, store):
    alert_id = _alert(store, "DELTA", note="Fictional")
    before = _alerts(store)
    result = cli("alerts", "edit", str(alert_id), "--condition", "below", "--threshold", "7", "--dry-run")
    assert result.exit_code == 0
    assert "Would update alert #1: DELTA ≤ 7.00 (not saved)." in result.output
    assert _alerts(store) == before
    bad = cli("alerts", "edit", str(alert_id), "--threshold", "0", "--dry-run")
    assert bad.exit_code == 1
    assert "Alert threshold must be finite and positive." in bad.output
    assert _alerts(store) == before


# 11 ── alerts rm reports a missing id ──────────────────────────────────────────


def test_11_alerts_rm_fails_for_an_alert_that_does_not_exist(cli, store):
    _alert(store)
    before = _alerts(store)
    result = cli("alerts", "rm", "9")
    assert result.exit_code == 1
    assert "No alert #9; nothing changed." in result.output
    assert "Removed" not in result.output
    assert _alerts(store) == before


def test_11_alerts_rm_still_removes_one_alert(cli, store):
    keep = _alert(store, "KEEP")
    gone = _alert(store, "GONE")
    result = cli("alerts", "rm", str(gone))
    assert result.exit_code == 0
    assert "Removed alert #2." in result.output
    assert [a.id for a in store.alerts()] == [keep]


# 12 ── several alert ids at once ───────────────────────────────────────────────


def test_12_alerts_pause_resume_rearm_and_rm_take_several_ids(cli, store):
    first = _alert(store, "AAA")
    second = _alert(store, "BBB", triggered_at="2026-11-14T10:00:00")
    third = _alert(store, "CCC")

    def states():
        return {a.id: (a.active, a.triggered_at) for a in store.alerts()}

    result = cli("alerts", "pause", str(first), str(second), str(first))
    assert result.exit_code == 0
    assert "Paused alerts #1, #2." in result.output
    assert states() == {1: (False, ""), 2: (False, "2026-11-14T10:00:00"), 3: (True, "")}

    assert "Resumed alerts #2, #1." in cli("alerts", "resume", str(second), str(first)).output
    assert states() == {1: (True, ""), 2: (True, "2026-11-14T10:00:00"), 3: (True, "")}

    assert "Rearmed alerts #2, #3." in cli("alerts", "rearm", str(second), str(third)).output
    assert states() == {1: (True, ""), 2: (True, ""), 3: (True, "")}

    assert "Removed alerts #1, #3." in cli("alerts", "rm", str(first), str(third)).output
    assert list(states()) == [second]


@pytest.mark.parametrize("command", ["pause", "resume", "rearm", "rm"])
def test_12_one_missing_id_changes_none_of_them(cli, store, command):
    _alert(store, "AAA", active=False)
    _alert(store, "BBB", triggered_at="2026-11-14T10:00:00")
    before = _alerts(store)
    result = cli("alerts", command, "1", "7", "2", "8")
    assert result.exit_code == 1
    assert "No alert #7, #8; nothing changed." in result.output
    assert _alerts(store) == before


# 13 ── asset classify is forgiving about case and spaces ───────────────────────


def test_13_asset_classify_accepts_any_case_and_trims_the_symbol(cli, store):
    result = cli("asset", "classify", "  fict.to ", "ETF")
    assert result.exit_code == 0
    assert "FICT.TO → ETF" in result.output
    assert list(store.assets()) == ["FICT.TO"]
    assert store.assets()["FICT.TO"].asset_class is AssetClass.ETF
    assert cli("asset", "classify", "FICT.TO", "Real_Estate").exit_code == 0
    assert store.assets()["FICT.TO"].asset_class is AssetClass.REAL_ESTATE


def test_13_asset_classify_refuses_a_blank_symbol(cli, store):
    result = cli("asset", "classify", "   ", "etf")
    assert result.exit_code == 2
    assert "cannot be blank" in result.output
    assert store.assets() == {}


# 14 ── asset remove reports a missing symbol ───────────────────────────────────


def test_14_asset_remove_fails_for_a_symbol_without_metadata(cli, store):
    store.upsert_asset(Asset("FICT-A", AssetKind.MANUAL, "Fictional art"))
    result = cli("asset", "remove", "FICT-B")
    assert result.exit_code == 1
    assert "No configured asset 'FICT-B'; nothing removed." in result.output
    assert list(store.assets()) == ["FICT-A"]


def test_14_asset_remove_trims_the_symbol(cli, store):
    store.upsert_asset(Asset("FICT-A", AssetKind.MANUAL, "Fictional art"))
    result = cli("asset", "remove", " fict-a ")
    assert result.exit_code == 0
    assert "Removed metadata for FICT-A." in result.output
    assert store.assets() == {}


def test_14_asset_remove_still_removes_a_legacy_padded_key(cli, store):
    store.upsert_asset(Asset(" FICT-A ", AssetKind.MANUAL, "Fictional legacy row"))
    store.upsert_asset(Asset("FICT-A", AssetKind.MANUAL, "Fictional art"))
    assert sorted(store.assets()) == [" FICT-A ", "FICT-A"]
    assert cli("asset", "remove", "FICT-A").exit_code == 0
    assert list(store.assets()) == [" FICT-A "]
    assert cli("asset", "remove", " fict-a ").exit_code == 0
    assert store.assets() == {}


# 15 ── watch add/rm --dry-run ──────────────────────────────────────────────────


def test_15_watch_add_and_rm_dry_run_preview_without_saving(cli, store):
    store.add_watch(["ALPHA", "BETA"])
    add = cli("watch", "add", "beta,gamma", "delta", "--dry-run")
    assert add.exit_code == 0
    assert "Would watch GAMMA, DELTA (not saved)." in add.output
    assert "Already on the watchlist." in cli("watch", "add", "alpha", "--dry-run").output
    rm = cli("watch", "rm", "alpha", "omega", "--dry-run")
    assert rm.exit_code == 0
    assert "Would remove ALPHA (not saved)." in rm.output
    assert "Nothing would be removed." in cli("watch", "rm", "omega", "--dry-run").output
    assert store.watchlist() == ["ALPHA", "BETA"]


# 16 ── backup now refuses the live database ────────────────────────────────────


def test_16_backup_now_refuses_to_back_up_onto_the_live_database(cli, store, ledger, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for target in (str(store.path), "test.db", "./sub/../test.db"):
        result = cli("backup", "now", target)
        assert result.exit_code == 1
        assert "is the live database; choose another file" in result.output
    assert not store.backup_dir.exists()
    assert [a.name for a in store.accounts()] == ["Fictional Maple", "Fictional Gull"]


def test_16_backup_now_refuses_a_hard_link_to_the_live_database(cli, store, ledger, tmp_path):
    link = tmp_path / "fictional-link.db"
    os.link(store.path, link)
    result = cli("backup", "now", str(link))
    assert result.exit_code == 1
    assert "is the live database; choose another file" in result.output
    assert link.samefile(store.path)


def test_16_backup_now_still_writes_to_another_path(cli, store, ledger, tmp_path):
    target = tmp_path / "copies" / "fictional-backup.db"
    result = cli("backup", "now", str(target), "--json")
    assert result.exit_code == 0
    assert json.loads(result.output)["path"] == str(target.resolve())
    assert target.stat().st_size > 0
