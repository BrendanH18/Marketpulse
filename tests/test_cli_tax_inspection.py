"""Capital gains report inspection for `marketpulse tax` (#128, items 1–10) on a fictional ledger."""

import csv
import io
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Account, AccountType, Transaction, TxnType


def add(store, acct, kind, day, symbol, qty=0.0, price=0.0, ccy="CAD", **extra):
    store.add_transaction(
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
    monkeypatch.setenv("COLUMNS", "160")
    return lambda *args: CliRunner().invoke(main, list(args), catch_exceptions=False)


@pytest.fixture
def ledger(store, fake):
    """2024: a superficial loss, a pooled sale across two accounts, a return of capital past ACB,
    a deemed sale into a TFSA at a loss, and an unpriced transfer (a ledger issue).
    2025: the rebought shares sold at a gain, a USD sale with trade-date FX, a EUR sale with no
    FX rate, and a sale in an account archived since."""
    maple = store.add_account(Account(name="Maple Taxable", type=AccountType.NONREG))
    birch = store.add_account(Account(name="Birch Margin", type=AccountType.MARGIN))
    tfsa = store.add_account(Account(name="Maple TFSA", type=AccountType.TFSA))
    add(store, maple, TxnType.BUY, "2024-01-02", "XEQT.TO", 10, 30)
    add(store, maple, TxnType.SELL, "2024-03-01", "XEQT.TO", 10, 25)  # −$50…
    add(store, maple, TxnType.BUY, "2024-03-15", "XEQT.TO", 10, 26)  # …bought back within 30 days
    add(store, maple, TxnType.BUY, "2024-02-01", "VFV.TO", 10, 100)
    add(store, birch, TxnType.BUY, "2024-02-02", "VFV.TO", 10, 120)
    add(store, birch, TxnType.SELL, "2024-09-03", "VFV.TO", 5, 130)  # pooled ACB 110/unit, not Birch's 120
    add(store, maple, TxnType.ROC, "2024-12-02", "VFV.TO", amount=2000)  # pool ACB 1,650: 350 above it
    add(store, maple, TxnType.BUY, "2024-04-01", "HXT.TO", 10, 50)
    add(store, maple, TxnType.TRANSFER, "2024-05-01", "HXT.TO", 10, 40, target_account_id=tfsa.saved_id)
    add(store, maple, TxnType.BUY, "2024-06-03", "ZCN.TO", 5, 20)
    add(store, maple, TxnType.TRANSFER, "2024-07-02", "ZCN.TO", 5, 0, target_account_id=tfsa.saved_id)
    add(store, maple, TxnType.SELL, "2025-02-03", "XEQT.TO", 10, 35)  # ACB 260 + the denied 50
    add(store, birch, TxnType.BUY, "2025-01-02", "AAPL", 1, 100, "USD")  # US$100 × 1.30
    add(store, birch, TxnType.SELL, "2025-03-03", "AAPL", 1, 150, "USD")  # US$150 × 1.40
    add(store, maple, TxnType.BUY, "2025-01-10", "SAP.DE", 2, 100, "EUR")  # no EURCAD history
    add(store, maple, TxnType.SELL, "2025-04-01", "SAP.DE", 2, 120, "EUR")
    old = store.add_account(Account(name="Old Cedar", type=AccountType.MARGIN))
    add(store, old, TxnType.BUY, "2025-01-06", "ZAG.TO", 100, 15)
    add(store, old, TxnType.SELL, "2025-05-01", "ZAG.TO", 100, 16)
    old.archived = True
    store.update_account(old)
    fake.set_history("USDCAD=X", {"2024-12-20": 1.3, "2025-01-02": 1.3, "2025-03-01": 1.4}, currency="CAD")
    return maple


FIXTURES = Path(__file__).parent / "fixtures"


def rows(cli, *args) -> list[dict]:
    result = cli("tax", "--json", *args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def picked(cli, *args) -> list[tuple[str, str]]:
    return [(r["date"], r["symbol"]) for r in rows(cli, *args)]


def stripped(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines()]


# ── Defaults are unchanged ────────────────────────────────────────────────────


@pytest.mark.parametrize(("args", "golden"), [((), "tax_report_default.txt"), (("-y", "2024"), "tax_report_2024.txt")])
def test_plain_tax_report_is_exactly_as_before(cli, ledger, args, golden):
    result = cli("tax", *args)
    assert result.exit_code == 0
    assert stripped(result.output) == stripped((FIXTURES / golden).read_text(encoding="utf-8"))


def test_csv_file_export_is_unchanged(cli, ledger, tmp_path):
    path = tmp_path / "gains.csv"
    out = cli("tax", "--year", "2024", "--csv", str(path))
    assert out.exit_code == 0 and "Exported 4 disposition(s)" in out.output
    assert "1 issue(s) may leave sales out of this file" in out.output
    raw = path.read_bytes()
    assert b"\r\n" in raw  # the accountant file keeps its line endings
    file_rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    assert [r["Symbol"] for r in file_rows] == ["XEQT.TO", "HXT.TO", "VFV.TO", "VFV.TO"]
    missing = cli("tax", "--year", "1999", "--csv", str(tmp_path / "none.csv"))
    assert missing.exit_code == 1 and "No capital gains or losses in 1999." in missing.output


# ── 1. --json ─────────────────────────────────────────────────────────────────


def test_json_lists_every_disposition_in_ledger_order(cli, ledger):
    payload = rows(cli)
    assert [(r["year"], r["date"], r["symbol"], r["kind"]) for r in payload] == [
        (2024, "2024-03-01", "XEQT.TO", "sale"),
        (2024, "2024-05-01", "HXT.TO", "deemed"),
        (2024, "2024-09-03", "VFV.TO", "sale"),
        (2024, "2024-12-02", "VFV.TO", "roc"),
        (2025, "2025-02-03", "XEQT.TO", "sale"),
        (2025, "2025-03-03", "AAPL", "sale"),
        (2025, "2025-04-01", "SAP.DE", "sale"),
        (2025, "2025-05-01", "ZAG.TO", "sale"),
    ]
    aapl = payload[5]
    assert (aapl["account"], aapl["fx"], aapl["proceeds"], aapl["acb"], aapl["allowed_gain"]) == (
        "Birch Margin",
        1.4,
        pytest.approx(210),
        pytest.approx(130),
        pytest.approx(80),
    )
    sap = payload[6]
    assert sap["complete"] is False and sap["proceeds"] is None and sap["note"] == "FX missing"
    # Archived accounts still count, but are never named.
    zag = payload[7]
    assert (zag["account"], zag["archived"], zag["allowed_gain"]) == (None, True, pytest.approx(100))
    assert "Old Cedar" not in json.dumps(payload)
    assert picked(cli, "-y", "2025") == [d for d in picked(cli) if d[0].startswith("2025")]


def test_json_is_raw_even_with_privacy(cli, ledger, tracker):
    tracker.config.privacy = True
    payload = rows(cli, "--symbol", "AAPL")
    assert payload[0]["proceeds"] == pytest.approx(210)
    human = cli("tax", "--symbol", "AAPL").output
    assert "210.00" not in human and "••••" in human


# ── 2. --csv - ────────────────────────────────────────────────────────────────


def test_csv_to_stdout_uses_the_accountant_columns_and_lf(cli, ledger):
    result = cli("tax", "--csv", "-", "--symbol", "vfv")
    assert result.exit_code == 0
    assert "\r" not in result.stdout
    parsed = list(csv.DictReader(io.StringIO(result.stdout)))
    assert [(r["Date"], r["Type"]) for r in parsed] == [
        ("2024-09-03", "Sale"),
        ("2024-12-02", "Return of capital above ACB"),
    ]
    assert parsed[0]["ACB (CAD)"] == "550.00" and parsed[1]["Gain or loss (CAD)"] == "350.00"
    # Issues go to stderr, so stdout stays pure CSV.
    assert "ZCN.TO" in result.stderr and "ZCN.TO" not in result.stdout
    everything = cli("tax", "--csv", "-").stdout.splitlines()
    assert len(everything) == 9 and everything[0].startswith("Tax year,Date,Account")


def test_filtered_csv_file_keeps_the_file_format(cli, ledger, tmp_path):
    path = tmp_path / "birch.csv"
    out = cli("tax", "-a", "Birch Margin", "--csv", str(path))
    assert out.exit_code == 0 and "Exported 2 disposition(s)" in out.output
    assert b"\r\n" in path.read_bytes()
    assert [r["Symbol"] for r in csv.DictReader(path.open(encoding="utf-8"))] == ["VFV.TO", "AAPL"]


# ── 3. --symbol ───────────────────────────────────────────────────────────────


def test_symbol_matches_text_ignoring_case_and_repeats(cli, ledger):
    assert picked(cli, "--symbol", "xeqt") == [("2024-03-01", "XEQT.TO"), ("2025-02-03", "XEQT.TO")]
    assert [s for _, s in picked(cli, "--symbol", "aapl", "--symbol", "SAP")] == ["AAPL", "SAP.DE"]
    blank = cli("tax", "--symbol", "  ")
    assert blank.exit_code == 2 and "--symbol cannot be blank" in blank.output


def test_filters_never_change_pooled_acb(cli, ledger):
    full = {(r["date"], r["symbol"], r["kind"]): r for r in rows(cli)}
    for args in (("-a", "Birch Margin"), ("--symbol", "VFV"), ("--kind", "sale"), ("--gains-only",)):
        for r in rows(cli, *args):
            same = full[(r["date"], r["symbol"], r["kind"])]
            assert (r["acb"], r["proceeds"], r["gain"], r["denied"]) == (
                same["acb"],
                same["proceeds"],
                same["gain"],
                same["denied"],
            )
    # Birch's VFV sale uses the pooled cost (110/unit across both accounts), not Birch's own 120.
    (vfv,) = rows(cli, "-a", "Birch Margin", "--symbol", "VFV")
    assert vfv["acb"] == pytest.approx(550)


# ── 4. -a/--account ───────────────────────────────────────────────────────────


def test_account_selects_active_accounts_only(cli, ledger):
    assert picked(cli, "-a", "birch margin") == [("2024-09-03", "VFV.TO"), ("2025-03-03", "AAPL")]
    for ref in ("Old Cedar", "Nowhere"):
        result = cli("tax", "-a", ref)
        assert result.exit_code == 1 and f"No active account '{ref}'." in result.output


# ── 5. --kind ─────────────────────────────────────────────────────────────────


def test_kind_filters_and_repeats(cli, ledger):
    assert picked(cli, "--kind", "roc") == [("2024-12-02", "VFV.TO")]
    assert picked(cli, "--kind", "DEEMED", "--kind", "roc") == [("2024-05-01", "HXT.TO"), ("2024-12-02", "VFV.TO")]
    assert cli("tax", "--kind", "gift").exit_code == 2


# ── 6. --gains-only / --losses-only / --denied / --incomplete ─────────────────


def test_outcome_filters(cli, ledger):
    assert [s for _, s in picked(cli, "--gains-only")] == ["VFV.TO", "VFV.TO", "XEQT.TO", "AAPL", "ZAG.TO"]
    assert picked(cli, "--losses-only") == [("2024-03-01", "XEQT.TO"), ("2024-05-01", "HXT.TO")]
    denied = rows(cli, "--denied")
    assert [(r["symbol"], r["denied_reason"]) for r in denied] == [
        ("XEQT.TO", "superficial"),
        ("HXT.TO", "registered"),
    ]
    assert picked(cli, "--incomplete") == [("2025-04-01", "SAP.DE")]
    for args in (("--gains-only", "--losses-only"), ("--incomplete", "--denied")):
        assert cli("tax", *args).exit_code == 2


# ── 7. --sort / --descending ──────────────────────────────────────────────────


def test_sort_and_descending(cli, ledger):
    by_gain = [s for _, s in picked(cli, "--sort", "gain", "--descending")]
    # Reported gain: ROC 350, ZAG 100 and VFV 100 (ties reversed by date too), AAPL 80, XEQT 40, then
    # the fully denied losses at 0; the row missing an FX rate has no gain, so it stays last.
    assert by_gain == ["VFV.TO", "ZAG.TO", "VFV.TO", "AAPL", "XEQT.TO", "HXT.TO", "XEQT.TO", "SAP.DE"]
    assert picked(cli, "--sort", "acb")[-1] == ("2025-04-01", "SAP.DE")
    assert picked(cli, "--descending")[0] == ("2025-05-01", "ZAG.TO")
    assert [s for _, s in picked(cli, "--sort", "symbol")][:2] == ["AAPL", "HXT.TO"]
    # Archived accounts sort after the named ones, never by their name.
    assert picked(cli, "--sort", "account")[-1] == ("2025-05-01", "ZAG.TO")


# ── 8. --count / --limit / --offset / --page-info ─────────────────────────────


def test_count_and_paging(cli, ledger):
    assert cli("tax", "--count").output.strip() == "8"
    assert cli("tax", "--count", "-y", "2024", "--kind", "sale").output.strip() == "2"
    page = json.loads(cli("tax", "--json", "--limit", "2", "--offset", "3", "--page-info").output)
    assert (page["total"], page["offset"], page["limit"]) == (8, 3, 2)
    assert [r["symbol"] for r in page["rows"]] == ["VFV.TO", "XEQT.TO"]
    human = cli("tax", "--limit", "2", "--offset", "3").output
    assert "Showing 4–5 of 8 dispositions." in human
    assert "No dispositions on this page." in cli("tax", "--offset", "20").output
    assert "No dispositions match these filters." in cli("tax", "--symbol", "NOPE").output


# ── 9. --summary ──────────────────────────────────────────────────────────────


def test_summary_reuses_the_report_totals(cli, ledger, tracker):
    years, _ = tracker.tax_years()
    summary = json.loads(cli("tax", "--summary", "--json").output)
    assert [s["year"] for s in summary] == [y.year for y in years] == [2025, 2024]
    for got, want in zip(summary, years, strict=True):
        assert (got["proceeds"], got["acb"], got["denied"], got["net_gain"], got["taxable"]) == pytest.approx(
            (want.proceeds, want.cost, want.denied, want.net_gain, want.taxable)
        )
    assert (summary[0]["dispositions"], summary[0]["missing_fx"], summary[1]["superficial"]) == (4, 1, 1)
    (birch,) = json.loads(cli("tax", "--summary", "--json", "-a", "Birch Margin", "-y", "2025").output)
    assert (birch["proceeds"], birch["acb"], birch["net_gain"]) == pytest.approx((210, 130, 80))
    human = cli("tax", "--summary", "--symbol", "SAP").output
    assert "selected dispositions" in human and "Totals cover only the selected" in human


# ── 10. --issues / --exit-code / --room ───────────────────────────────────────


def test_issues_and_exit_code(cli, ledger):
    (issue,) = json.loads(cli("tax", "--issues", "--json").output)
    assert (issue["date"], issue["code"]) == ("2024-07-02", "transfer_to_registered_unpriced")
    flagged = cli("tax", "--issues", "--exit-code")
    assert flagged.exit_code == 1 and "ZCN.TO" in flagged.output
    clean = cli("tax", "--issues", "--exit-code", "-y", "2025")
    assert clean.exit_code == 0 and "No ledger issues affect the tax report." in clean.output
    assert cli("tax", "--exit-code").exit_code == 2


def test_room_alone_needs_no_fx_history(cli, ledger, store, fake):
    assert "No contribution room recorded" in cli("tax", "--room").output
    store.set_room("TFSA", 2025, 7000)
    fake.calls.clear()
    (room,) = json.loads(cli("tax", "--room", "--json").output)
    assert (room["account_type"], room["starting_room"], room["accounts"]) == ("TFSA", 7000, ["Maple TFSA"])
    assert room["remaining"] == pytest.approx(room["starting_room"] + room["new_limits"] - room["contributions"])
    assert "Contribution room" in cli("tax", "--room").output
    assert fake.calls == []


# ── Conflicting options ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "args",
    [
        ("--json", "--csv", "-"),
        ("--count", "--json"),
        ("--count", "--limit", "1"),
        ("--summary", "--issues"),
        ("--summary", "--sort", "gain"),
        ("--room", "--symbol", "VFV"),
        ("--room", "-y", "2024"),
        ("--issues", "--csv", "-"),
        ("--page-info",),
    ],
)
def test_conflicting_options_are_usage_errors(cli, ledger, args):
    result = cli("tax", *args)
    assert result.exit_code == 2 and "Traceback" not in result.output
