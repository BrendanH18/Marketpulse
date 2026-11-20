"""More automation and foreign property workflows (items 61–80) on fictional data.

Every ledger, symbol, error and alert here is fictional.
"""

import csv
import io
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Transaction, TxnType


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "160")
    return lambda *args: CliRunner().invoke(main, list(args), catch_exceptions=False)


# ── automation history ───────────────────────────────────────────────────────


def report(when: datetime, *, errors=(), quote_errors=(), stale_count=0, fired=()) -> dict:
    return {
        "last_run": when.isoformat(timespec="seconds"),
        "stale": bool(stale_count),
        "stale_count": stale_count,
        "stale_since": None,
        "snapshot_date": None,
        "backup": None,
        "fired": list(fired),
        "errors": list(errors),
        "quote_errors": list(quote_errors),
    }


@pytest.fixture
def runs(store):
    """Four runs, oldest first: ok, a failure, ok with an alert and a quote error, ok."""
    store.record_automation_run(report(datetime(2026, 11, 1, 9, 0)))
    store.record_automation_run(report(datetime(2026, 11, 2, 9, 0), errors=["Backup failed: fictional disk full"]))
    store.record_automation_run(
        report(datetime(2026, 11, 3, 9, 0), quote_errors=["FICTX: symbol not found"], fired=["FICT ≥ 10.00"])
    )
    store.record_automation_run(report(datetime(2026, 11, 4, 9, 0), stale_count=2))


def times(output: str) -> list[str]:
    return [item["ran_at"] for item in json.loads(output)]


def test_history_since_and_until(cli, runs):
    since = cli("automation", "history", "--json", "--since", "2026-11-02")
    assert times(since.output) == ["2026-11-04T09:00:00", "2026-11-03T09:00:00", "2026-11-02T09:00:00"]
    until = cli("automation", "history", "--json", "--until", "2026-11-02")
    assert times(until.output) == ["2026-11-02T09:00:00", "2026-11-01T09:00:00"]
    both = cli("automation", "history", "--json", "--since", "2026-11-02", "--until", "2026-11-03", "--limit", "1")
    assert times(both.output) == ["2026-11-03T09:00:00"]  # the limit applies after the filters
    assert cli("automation", "history", "--since", "2026-11-03", "--until", "2026-11-02").exit_code == 2
    assert cli("automation", "history", "--since", "not-a-date").exit_code == 2
    empty = cli("automation", "history", "--since", "2026-12-01")
    assert empty.exit_code == 0 and "No automation runs match these filters." in empty.output


def test_history_successes_and_with_alerts(cli, runs):
    ok = cli("automation", "history", "--json", "--successes")
    assert times(ok.output) == ["2026-11-04T09:00:00", "2026-11-03T09:00:00", "2026-11-01T09:00:00"]
    alerts = json.loads(cli("automation", "history", "--json", "--with-alerts").output)
    assert [a["fired"] for a in alerts] == [["FICT ≥ 10.00"]]
    assert cli("automation", "history", "--failures", "--successes").exit_code == 2


def test_history_jsonl_and_csv(cli, runs):
    lines = cli("automation", "history", "--jsonl", "--limit", "2").output.splitlines()
    assert [json.loads(line)["ran_at"] for line in lines] == ["2026-11-04T09:00:00", "2026-11-03T09:00:00"]
    assert json.loads(lines[1])["report"]["quote_errors"] == ["FICTX: symbol not found"]
    rows = list(csv.DictReader(io.StringIO(cli("automation", "history", "--csv").output)))
    assert list(rows[0]) == ["id", "ran_at", "failed", "errors", "quote_error_count", "stale_count", "fired"]
    assert [r["failed"] for r in rows] == ["false", "false", "true", "false"]
    assert rows[0]["stale_count"] == "2"
    assert rows[1]["fired"] == "FICT ≥ 10.00" and rows[1]["quote_error_count"] == "1"
    assert rows[2]["errors"] == "Backup failed: fictional disk full"
    assert cli("automation", "history", "--json", "--csv").exit_code == 2


def test_history_count(cli, runs):
    assert cli("automation", "history", "--count").output.strip() == "4"
    assert cli("automation", "history", "--count", "--failures").output.strip() == "1"
    assert cli("automation", "history", "--count", "--json").exit_code == 2


def test_history_summary(cli, runs):
    totals = json.loads(cli("automation", "history", "--summary", "--json").output)
    assert totals == {
        "runs": 4,
        "failed": 1,
        "succeeded": 3,
        "quote_errors": 1,
        "alerts_fired": 1,
        "first_run": "2026-11-01T09:00:00",
        "last_run": "2026-11-04T09:00:00",
        "last_failure": "2026-11-02T09:00:00",
    }
    human = cli("automation", "history", "--summary", "--since", "2026-11-03")
    assert human.exit_code == 0
    assert "Runs" in human.output and "Last failure" in human.output and "—" in human.output
    empty = json.loads(cli("automation", "history", "--summary", "--json", "--since", "2027-01-01").output)
    assert empty["runs"] == 0 and empty["last_run"] is None
    assert cli("automation", "history", "--summary", "--csv").exit_code == 2


def test_history_exit_code(cli, runs):
    assert cli("automation", "history", "--exit-code").exit_code == 1
    assert cli("automation", "history", "--exit-code", "--since", "2026-11-03").exit_code == 0
    assert cli("automation", "history", "--exit-code", "--count", "--failures").exit_code == 1


def test_history_since_accepts_relative_dates(cli, store):
    store.record_automation_run(report(datetime.now() - timedelta(days=10), errors=["fictional"]))
    store.record_automation_run(report(datetime.now()))
    assert cli("automation", "history", "--count", "--since", "-3d").output.strip() == "1"
    assert cli("automation", "history", "--since", "today", "--exit-code").exit_code == 0


# ── automation run ───────────────────────────────────────────────────────────


@pytest.fixture
def cycles(monkeypatch):
    """Fake cycles that return the queued reports in order, and record the sleeps between them."""
    queued: list[dict] = []
    sleeps: list[int] = []
    monkeypatch.setattr("marketpulse.automation.run_cycle", lambda tracker, **kw: SimpleNamespace(report=queued.pop(0)))
    monkeypatch.setattr("marketpulse.cli.native.time.sleep", sleeps.append)
    return SimpleNamespace(queued=queued, sleeps=sleeps)


def test_run_cycles_runs_n_times_then_exits(cli, cycles):
    now = datetime(2026, 11, 5, 9, 0)
    cycles.queued.extend([report(now), report(now), report(now)])
    result = cli("automation", "run", "--cycles", "3", "--interval", "30", "--json", "--quiet")
    assert result.exit_code == 0
    assert len(result.output.splitlines()) == 3
    assert cycles.sleeps == [30, 30]  # no sleep after the last cycle
    assert cli("automation", "run", "--once", "--cycles", "2").exit_code == 2


def test_run_cycles_fails_when_any_cycle_failed(cli, cycles):
    now = datetime(2026, 11, 5, 9, 0)
    cycles.queued.extend([report(now, errors=["Backup failed: fictional"]), report(now)])
    assert cli("automation", "run", "--cycles", "2", "--json", "--quiet").exit_code == 1


def test_run_strict_fails_on_quote_errors(cli, cycles):
    now = datetime(2026, 11, 5, 9, 0)
    cycles.queued.extend([report(now, quote_errors=["FICTX: symbol not found"])] * 2)
    assert cli("automation", "run", "--once", "--json", "--quiet").exit_code == 0
    assert cli("automation", "run", "--once", "--json", "--quiet", "--strict").exit_code == 1
    assert cli("automation", "run", "--strict").exit_code == 2


# ── tax foreign-property ─────────────────────────────────────────────────────


def trade(store, acct, kind, day, symbol, qty, price, ccy="CAD"):
    store.add_transaction(
        Transaction(
            account_id=acct.saved_id, type=kind, date=day, symbol=symbol, quantity=qty, price=price, currency=ccy
        )
    )


@pytest.fixture
def ledger(store, fake):
    """2023: CAD 52,000 of a US listing (not required). 2024: up to CAD 130,000 (simplified),
    half sold in September. 2025: a EUR listing with no rate (undetermined). Canadian and TFSA
    holdings never count."""
    taxable = store.add_account(Account(name="Fictional Taxable", type=AccountType.NONREG))
    tfsa = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
    trade(store, taxable, TxnType.BUY, "2023-06-01", "FICTUS", 400, 100, "USD")
    trade(store, taxable, TxnType.SELL, "2023-12-01", "FICTUS", 400, 100, "USD")
    trade(store, taxable, TxnType.BUY, "2024-03-04", "FICTUS", 1000, 100, "USD")
    trade(store, taxable, TxnType.SELL, "2024-09-03", "FICTUS", 500, 110, "USD")
    trade(store, taxable, TxnType.BUY, "2024-03-04", "XFIC.TO", 2000, 100)
    trade(store, tfsa, TxnType.BUY, "2024-03-04", "FICTTF", 5000, 100, "USD")
    trade(store, taxable, TxnType.BUY, "2025-02-03", "FICT.DE", 10, 100, "EUR")
    fake.set_history("USDCAD=X", {"2023-05-20": 1.3, "2024-02-20": 1.3, "2024-09-01": 1.4}, currency="CAD")
    return taxable


def fp(cli, *args):
    result = cli("tax", "foreign-property", *args)
    assert result.exit_code in (0, 1), result.output
    return result


def years_of(cli, *args) -> list[int]:
    return [y["year"] for y in json.loads(fp(cli, "--json", *args).output)["years"]]


def test_foreign_since_and_until_year(cli, ledger):
    every = years_of(cli)
    assert every[-3:] == [2025, 2024, 2023]
    assert years_of(cli, "--since-year", "2024") == [y for y in every if y >= 2024]
    assert years_of(cli, "--until-year", "2024") == [2024, 2023]
    assert years_of(cli, "--since-year", "2024", "--until-year", "2024") == [2024]
    assert cli("tax", "foreign-property", "--since-year", "2025", "--until-year", "2024").exit_code == 2
    assert cli("tax", "foreign-property", "--year", "2024", "--since-year", "2023").exit_code == 2
    empty = fp(cli, "--since-year", "2099")
    assert "No years match these filters." in empty.output


def test_foreign_status_filter(cli, ledger):
    assert years_of(cli, "--status", "simplified") == [2024]
    assert years_of(cli, "--status", "UNDETERMINED", "--until-year", "2025") == [2025]
    assert years_of(cli, "--status", "not_required", "--until-year", "2024") == [2023]
    assert years_of(cli, "--year", "2024", "--status", "detailed") == []
    assert "2024 doesn't match these filters." in fp(cli, "--year", "2024", "--status", "detailed").output


def test_foreign_jsonl(cli, ledger):
    lines = fp(cli, "--jsonl", "--until-year", "2024").output.splitlines()
    rows = [json.loads(line) for line in lines]
    assert [(r["year"], r["assessment"]) for r in rows] == [(2024, "simplified"), (2023, "not_required")]
    assert rows[0]["max_cost"] == pytest.approx(130_000)


def test_foreign_csv_stdout_and_file(cli, ledger, tmp_path):
    rows = list(csv.DictReader(io.StringIO(fp(cli, "--csv", "-", "--until-year", "2024").output)))
    assert [r["year"] for r in rows] == ["2024", "2023"]
    assert rows[0]["assessment"] == "simplified" and rows[0]["required"] == "true"
    assert float(rows[0]["max_cost"]) == pytest.approx(130_000)
    assert "holdings" not in rows[0]
    path = tmp_path / "t1135.csv"
    result = fp(cli, "--csv", str(path), "--year", "2025")
    assert "Exported 1 row(s)" in result.output
    (row,) = csv.DictReader(path.open(encoding="utf-8"))
    assert (row["year"], row["incomplete"], row["assessment"]) == ("2025", "true", "undetermined")
    assert cli("tax", "foreign-property", "--csv", "-", "--json").exit_code == 2


def test_foreign_holdings(cli, ledger):
    rows = json.loads(fp(cli, "--holdings", "--json", "--since-year", "2024", "--until-year", "2025").output)
    assert [(r["year"], r["symbol"]) for r in rows] == [(2025, "FICTUS"), (2025, "FICT.DE"), (2024, "FICTUS")]
    assert rows[2]["dispositions"] == 1 and rows[2]["gain"] == pytest.approx(12_000)
    table = fp(cli, "--holdings", "--until-year", "2024")
    assert "by holding" in table.output and "FICTUS" in table.output and "XFIC.TO" not in table.output
    csv_rows = list(csv.DictReader(io.StringIO(fp(cli, "--holdings", "--csv", "-", "--year", "2025").output)))
    assert [r["symbol"] for r in csv_rows] == ["FICTUS", "FICT.DE"]
    assert csv_rows[1]["incomplete"] == "true"
    assert len(fp(cli, "--holdings", "--jsonl", "--year", "2024").output.splitlines()) == 1


def test_foreign_count(cli, ledger):
    assert fp(cli, "--count", "--until-year", "2024").output.strip() == "2"
    assert fp(cli, "--count", "--holdings", "--year", "2025").output.strip() == "2"
    assert fp(cli, "--count", "--status", "detailed").output.strip() == "0"
    assert cli("tax", "foreign-property", "--count", "--jsonl").exit_code == 2


def test_foreign_exit_code(cli, ledger):
    assert cli("tax", "foreign-property", "--exit-code", "--year", "2023").exit_code == 0
    assert cli("tax", "foreign-property", "--exit-code", "--year", "2024").exit_code == 1
    assert cli("tax", "foreign-property", "--exit-code", "--year", "2025").exit_code == 1  # undetermined
    assert cli("tax", "foreign-property", "--exit-code", "--count", "--status", "not_required").exit_code == 0


def test_foreign_headroom(cli, ledger, tracker):
    (y,) = json.loads(fp(cli, "--headroom", "--json", "--year", "2023").output)["years"]
    assert y["headroom"] == pytest.approx(48_000)
    (over,) = json.loads(fp(cli, "--headroom", "--json", "--year", "2024").output)["years"]
    assert over["headroom"] == pytest.approx(-30_000)
    assert "headroom" not in json.loads(fp(cli, "--json", "--year", "2024").output)["years"][0]
    table = fp(cli, "--headroom", "--until-year", "2024").output
    assert "Headroom" in table and "-30,000.00" in table and " 48,000.00" in table
    assert "2024-03-04" in table and "T1135 likely required" in table  # the extra column still fits
    detail = fp(cli, "--headroom", "--year", "2024").output
    assert "Headroom to $100,000: -$30,000.00" in detail
    row = next(csv.DictReader(io.StringIO(fp(cli, "--headroom", "--csv", "-", "--year", "2023").output)))
    assert float(row["headroom"]) == pytest.approx(48_000)
    assert cli("tax", "foreign-property", "--headroom", "--holdings").exit_code == 2
    tracker.config.privacy = True
    masked = fp(cli, "--headroom", "--until-year", "2024").output
    assert "30,000" not in masked and "48,000" not in masked


def test_foreign_default_output_unchanged(cli, ledger):
    plain = fp(cli, "--year", "2024").output
    assert "Headroom" not in plain and "FICTUS" in plain
    payload = json.loads(fp(cli, "--json").output)
    assert set(payload) == {"currency", "threshold", "detailed_threshold", "years", "notes"}
    assert date.today().year in [y["year"] for y in payload["years"]]
