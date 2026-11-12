"""`allocation` targets, selection and rebalancing output, on fictional offline fixtures."""

import csv
import io
import json

import click
import pytest
from click.testing import CliRunner

from marketpulse import render
from marketpulse.cli import App, fail, main, pass_app
from marketpulse.models import Account, AccountType, AssetClass, Transaction, TxnType


@click.command()
@click.option("--by", type=click.Choice(["class", "account", "currency"]), default="class", show_default=True)
@click.option("--target", "targets", multiple=True)
@click.option("--clear-targets", is_flag=True)
@click.option("-q", "--quiet", is_flag=True)
@pass_app
def legacy_allocation(app: App, by: str, targets: tuple[str, ...], clear_targets: bool, quiet: bool) -> None:
    """The command body as it was before the move, to prove the defaults print the same."""
    from marketpulse.analytics import rebalance

    store = app.store
    if clear_targets and not targets:
        store.set_targets({})
        app.ok("Targets cleared.")
    if targets:
        parsed = {} if clear_targets else dict(store.targets())
        valid = {c.value for c in AssetClass}
        for item in targets:
            key, _, value = item.partition("=")
            key = key.strip().lower().replace(" ", "_")
            if key not in valid:
                fail(f"Unknown asset class '{key}'. Choose from: {', '.join(sorted(valid))}")
            try:
                parsed[key] = float(value)
            except ValueError:
                fail(f"Target for {key} must be a number.")
        total = sum(parsed.values())
        if total > 100.0001:
            fail(f"Targets add up to {total:g}% — keep them at or under 100%.")
        store.set_targets(parsed)
        app.ok(f"Targets saved ({total:g}% allocated).")
    if quiet:
        return
    view = app.tracker.valuation()
    breakdown = {"class": view.by_class, "account": view.by_account, "currency": view.by_currency}[by]
    app.title(f"Allocation by {by}")
    app.console.print(
        render.allocation(
            breakdown, app.palette, width=min(app.console.width - 4, 80), privacy=app.privacy, base=view.base
        )
    )
    current_targets = store.targets()
    if by == "class" and current_targets:
        app.console.print()
        app.console.print(
            render.rebalance_table(
                rebalance(view.by_class, current_targets, view.net_worth), view.base, privacy=app.privacy
            )
        )


@pytest.fixture
def cli(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "160")
    fake.set_quote("FICT.TO", 10.0, 10.0, "CAD", "Fictional Equity", "EQUITY")
    fake.set_quote("FETF.TO", 20.0, 20.0, "CAD", "Fictional ETF", "ETF")
    tfsa = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA, track_cash=True))
    rrsp = store.add_account(Account(name="Fictional RRSP", type=AccountType.RRSP))
    hidden = store.add_account(Account(name="Archived secret", archived=True))
    rows = [
        # TFSA: 1000 deposited, 600 in FETF.TO (30 x 20), 400 cash.
        (tfsa, TxnType.DEPOSIT, "2024-01-02", "", 0, 0, 1000, "CAD"),
        (tfsa, TxnType.BUY, "2024-01-03", "FETF.TO", 30, 20, 0, "CAD"),
        # RRSP (fully invested): 1000 in FICT.TO (100 x 10).
        (rrsp, TxnType.BUY, "2024-01-04", "FICT.TO", 100, 10, 0, "CAD"),
        (hidden, TxnType.BUY, "2024-01-05", "FICT.TO", 500, 10, 0, "CAD"),
    ]
    for acct, kind, day, symbol, quantity, price, amount, ccy in rows:
        store.add_transaction(Transaction(acct.saved_id, kind, day, symbol, quantity, price, amount, 0, currency=ccy))
    runner = CliRunner()

    def invoke(*args):
        return runner.invoke(main, list(args), catch_exceptions=False)

    return invoke


def legacy(*args):
    return CliRunner().invoke(legacy_allocation, list(args), catch_exceptions=False)


def records(cli, *args):
    result = cli("allocation", *args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


@pytest.fixture
def targeted(cli, store):
    # Equity 50% vs 40 (+10), ETF 30% vs 40 (-10), Cash 20% vs 20 (0).
    store.set_targets({"equity": 40.0, "etf": 40.0, "cash": 20.0})
    return cli


# Defaults and existing options are unchanged


@pytest.mark.parametrize("by", ["class", "account", "currency"])
def test_default_output_matches_the_command_before_the_move(cli, store, by):
    for saved in ({}, {"equity": 40.0, "etf": 40.0, "cash": 20.0}):
        store.set_targets(saved)
        new, old = cli("allocation", "--by", by), legacy("--by", by)
        assert new.exit_code == old.exit_code == 0
        assert new.output == old.output
    assert cli("allocation").output == legacy().output
    assert "Archived secret" not in cli("allocation", "--by", "account").output


def test_existing_target_options_behave_as_before(cli, store):
    assert "Targets saved (80% allocated)" in cli("allocation", "-q", "--target", "etf=80").output
    assert store.targets() == {"etf": 80.0}
    over = cli("allocation", "-q", "--target", "equity=30")
    assert over.exit_code == 1 and "add up to 110%" in over.output
    assert store.targets() == {"etf": 80.0}
    replaced = cli("allocation", "-q", "--clear-targets", "--target", "Fixed Income=60")
    assert replaced.exit_code == 0 and store.targets() == {"fixed_income": 60.0}
    assert "Targets cleared." in cli("allocation", "-q", "--clear-targets").output
    assert store.targets() == {}


@pytest.mark.parametrize("value", ["-20", "120", "nan", "inf"])
def test_targets_outside_0_to_100_are_rejected_before_preview_or_save(cli, store, value):
    for extra in ([], ["--dry-run"]):
        result = cli("allocation", "-q", "--target", f"etf={value}", *extra)
        assert result.exit_code == 1 and "between 0 and 100" in result.output, result.output
    assert store.targets() == {}


# 11. --show-targets reads saved targets without pricing


def test_show_targets_lists_saved_targets_offline(targeted, fake):
    fake.offline = True
    calls = len(fake.calls)
    out = targeted("allocation", "--show-targets").output
    for text in ("Allocation targets", "Equity", "ETF", "Cash", "40.00%", "100.00% targeted", "0.00% unallocated"):
        assert text in out
    payload = json.loads(targeted("allocation", "--show-targets", "--json").output)
    assert payload["targets"][0] == {"bucket": "cash", "label": "Cash", "target": 20.0}
    assert (payload["total"], payload["unallocated"]) == (100.0, 0.0)
    assert len(fake.calls) == calls  # never priced


def test_show_targets_when_none_and_partial(cli, store):
    assert "No targets set" in cli("allocation", "--show-targets").output
    assert json.loads(cli("allocation", "--show-targets", "--json").output) == {
        "targets": [],
        "total": 0,
        "unallocated": 100.0,
    }
    store.set_targets({"etf": 75.0})
    assert "25.00% unallocated" in cli("allocation", "--show-targets").output


@pytest.mark.parametrize(
    "extra", [("--csv",), ("--count",), ("--target", "etf=5"), ("-q",), ("--sort", "value"), ("--by", "account")]
)
def test_show_targets_rejects_other_options(cli, extra):
    result = cli("allocation", "--show-targets", *extra)
    assert result.exit_code == 2 and "--show-targets only combines with --json" in result.output


# 12. --remove-target


def test_remove_target_drops_classes_and_keeps_the_rest(targeted, store):
    result = targeted("allocation", "-q", "--remove-target", "ETF", "--remove-target", "cash")
    assert result.exit_code == 0 and "Targets saved (40% allocated)" in result.output
    assert store.targets() == {"equity": 40.0}


def test_remove_target_is_validated_before_saving(targeted, store):
    unknown = targeted("allocation", "-q", "--remove-target", "etf", "--remove-target", "nope")
    assert unknown.exit_code == 1 and "Unknown asset class 'nope'" in unknown.output
    missing = targeted("allocation", "-q", "--remove-target", "etf", "--remove-target", "crypto")
    assert missing.exit_code == 1 and "No target saved for crypto" in missing.output
    assert store.targets() == {"cash": 20.0, "equity": 40.0, "etf": 40.0}


def test_remove_target_combines_with_target_but_not_clear(targeted, store):
    result = targeted("allocation", "-q", "--remove-target", "cash", "--target", "fixed_income=20")
    assert result.exit_code == 0 and store.targets() == {"equity": 40.0, "etf": 40.0, "fixed_income": 20.0}
    same = targeted("allocation", "-q", "--remove-target", "etf", "--target", "etf=10")
    assert same.exit_code == 2 and "same class" in same.output
    clear = targeted("allocation", "-q", "--remove-target", "etf", "--clear-targets")
    assert clear.exit_code == 2
    assert store.targets() == {"equity": 40.0, "etf": 40.0, "fixed_income": 20.0}


# 13. --dry-run


def test_dry_run_previews_without_saving(targeted, store, fake):
    calls = len(fake.calls)
    result = targeted("allocation", "--dry-run", "--target", "crypto=0", "--remove-target", "cash")
    assert result.exit_code == 0, result.output
    assert "Would save targets (80% allocated). Nothing saved (dry run)." in result.output
    assert "Crypto: 0%" in result.output and "Cash" not in result.output
    cleared = targeted("allocation", "--dry-run", "--clear-targets")
    assert "Would clear all targets" in cleared.output
    over = targeted("allocation", "--dry-run", "--target", "etf=70")
    assert over.exit_code == 1 and "add up to 130%" in over.output
    assert store.targets() == {"cash": 20.0, "equity": 40.0, "etf": 40.0}
    assert len(fake.calls) == calls


def test_dry_run_needs_a_target_change(cli):
    assert cli("allocation", "--dry-run").exit_code == 2
    assert cli("allocation", "--dry-run", "--target", "etf=1", "--sort", "name").exit_code == 2


# 14. --json


def test_json_is_raw_unmasked_breakdown_and_rebalance(targeted):
    assert targeted("config", "set", "privacy", "true").exit_code == 0
    payload = records(targeted)
    assert (payload["by"], payload["base"], payload["total"]) == ("class", "CAD", 2000.0)
    assert payload["rows"][0] == {"key": "equity", "label": "Equity", "value": 1000.0, "weight": 50.0}
    by_bucket = {r["bucket"]: r for r in payload["rebalance"]}
    assert by_bucket["equity"]["drift"] == pytest.approx(10.0)
    assert by_bucket["etf"]["delta"] == pytest.approx(200.0)
    assert set(by_bucket["cash"]) == {"bucket", "label", "value", "weight", "target", "drift", "delta"}
    human = targeted("allocation").output
    assert "$1,000.00" not in human  # human output stays masked
    accounts = records(targeted, "--by", "account")
    assert [r["label"] for r in accounts["rows"]] == ["Fictional TFSA", "Fictional RRSP"]
    assert accounts["rebalance"] == []


# 15. --csv


def test_csv_writes_breakdown_or_rebalance_rows(targeted):
    out = targeted("allocation", "--csv").output
    assert "\r" not in out
    rows = list(csv.DictReader(io.StringIO(out)))
    assert [r["key"] for r in rows] == ["equity", "etf", "cash"]
    assert rows[1] == {"key": "etf", "label": "ETF", "value": "600.0", "weight": "30.0"}
    drift = list(csv.DictReader(io.StringIO(targeted("allocation", "--csv", "--drift-only").output)))
    assert list(drift[0]) == ["bucket", "label", "value", "weight", "target", "drift", "delta"]


def test_output_formats_conflict(targeted):
    for args in (("--json", "--csv"), ("--count", "--json"), ("--count", "--csv")):
        assert targeted("allocation", *args).exit_code == 2
    assert targeted("allocation", "--json", "--target", "etf=10").exit_code == 2
    assert targeted("allocation", "-q", "--json").exit_code == 2


# 16. --sort and --descending


def test_sort_and_descending(targeted):
    assert [r["key"] for r in records(targeted, "--sort", "name")["rows"]] == ["cash", "equity", "etf"]
    assert [r["key"] for r in records(targeted, "--sort", "value")["rows"]] == ["cash", "etf", "equity"]
    assert [r["key"] for r in records(targeted, "--sort", "weight", "--descending")["rows"]] == [
        "equity",
        "etf",
        "cash",
    ]
    assert [r["bucket"] for r in records(targeted, "--sort", "name")["rebalance"]] == ["cash", "equity", "etf"]
    assert [r["key"] for r in records(targeted, "--descending")["rows"]] == ["cash", "etf", "equity"]
    out = targeted("allocation", "--sort", "name").output
    assert out.index("■ Cash") < out.index("■ Equity") < out.index("■ ETF")


# 17. --min-weight


def test_min_weight_hides_small_rows_but_keeps_shares_of_the_whole(targeted):
    payload = records(targeted, "--min-weight", "25")
    assert [(r["key"], r["weight"]) for r in payload["rows"]] == [("equity", 50.0), ("etf", 30.0)]
    assert payload["total"] == 2000.0
    assert "No class weighs 90% or more." in targeted("allocation", "--min-weight", "90").output
    assert targeted("allocation", "--min-weight", "101").exit_code == 2
    assert targeted("allocation", "--min-weight", "nan").exit_code == 2


def test_hidden_groups_keep_their_share_of_the_bar():
    from marketpulse.themes import resolve_palette
    from marketpulse.valuation import Breakdown

    shown = [Breakdown("equity", "Equity", 1000.0, 50.0), Breakdown("etf", "ETF", 600.0, 30.0)]
    bar = render.allocation(shown, resolve_palette("auto"), width=20, hidden=400.0).renderables[0]
    # 50% / 30% / 20% of 20 cells, not 62.5% / 37.5% of the shown subtotal.
    assert [span.end - span.start for span in bar.spans] == [10, 6, 4]
    assert bar.spans[-1].style == "dim"


# 18. --drift-only


def test_drift_only_prints_just_the_rebalance_table(targeted, cli, store):
    out = targeted("allocation", "--drift-only").output
    assert "Allocation vs target" in out and "Allocation by class" not in out
    assert len(records(targeted, "--drift-only")) == 3
    store.set_targets({})
    assert "No targets set" in cli("allocation", "--drift-only").output
    assert records(cli, "--drift-only") == []
    assert cli("allocation", "--drift-only", "--by", "account").exit_code == 2
    assert cli("allocation", "--drift-only", "--min-weight", "5").exit_code == 2


# 19. --threshold and --exit-code


def test_threshold_keeps_classes_drifting_beyond_it(targeted):
    assert {r["bucket"] for r in records(targeted, "--drift-only", "--threshold", "5")} == {"equity", "etf"}
    assert records(targeted, "--drift-only", "--threshold", "10") == []  # strictly more than
    out = targeted("allocation", "--threshold", "15").output
    assert "Allocation by class" in out and "No class drifts more than 15%." in out


def test_exit_code_signals_drift_beyond_threshold(targeted):
    drifting = targeted("allocation", "--drift-only", "--threshold", "5", "--exit-code")
    assert drifting.exit_code == 1 and "Equity" in drifting.output
    calm = targeted("allocation", "--drift-only", "--threshold", "12", "--exit-code")
    assert calm.exit_code == 0
    assert targeted("allocation", "--exit-code").exit_code == 2  # needs --threshold
    assert targeted("allocation", "--threshold", "5", "--json", "--exit-code").exit_code == 1


# 20. --count


def test_count_prints_rows_that_would_be_shown(targeted):
    assert targeted("allocation", "--count").output == "3\n"
    assert targeted("allocation", "--count", "--min-weight", "25").output == "2\n"
    assert targeted("allocation", "--count", "--by", "account").output == "2\n"
    assert targeted("allocation", "--count", "--drift-only", "--threshold", "5").output == "2\n"
