"""Overview improvements 61–70 for `status` and `summary` (#130) on a fictional ledger (fake quotes only)."""

import io
import json
from datetime import date, timedelta

import pytest
from click.testing import CliRunner
from rich.console import Console
from rich.text import Text
from rich.theme import Theme as RichTheme

from marketpulse import fmt, render
from marketpulse.cli import main
from marketpulse.cli.overview import _months_before
from marketpulse.db import Snapshot
from marketpulse.models import Account, Transaction, TxnType
from marketpulse.themes import resolve_palette, rich_styles


@pytest.fixture
def cli(store, tracker, fake, monkeypatch):
    """Fictional Growth (tracks cash): XEQT.TO 100 @ 30 and 7000 CAD cash. Fictional Income: AAPL 10 @ 150 USD.

    Fake quotes: XEQT.TO 40 (prev 40.5), AAPL 200 USD (prev 190), USD/CAD 1.35."""
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    monkeypatch.setenv("COLUMNS", "180")
    growth = store.add_account(Account(name="Fictional Growth", track_cash=True))
    income = store.add_account(Account(name="Fictional Income"))
    for account, kind, day, symbol, quantity, price, amount, currency in [
        (growth, TxnType.DEPOSIT, "2024-01-02", "", 0, 0, 10000, "CAD"),
        (growth, TxnType.BUY, "2024-01-03", "XEQT.TO", 100, 30, 0, "CAD"),
        (income, TxnType.BUY, "2024-01-05", "AAPL", 10, 150, 0, "USD"),
    ]:
        store.add_transaction(
            Transaction(account.saved_id, kind, day, symbol, quantity, price, amount, currency=currency)
        )

    def invoke(*args):
        return CliRunner().invoke(main, list(args), catch_exceptions=False)

    return invoke


def console() -> Console:
    return Console(
        file=io.StringIO(), width=180, theme=RichTheme(rich_styles(resolve_palette("auto"))), highlight=False
    )


def archive_with_value(store):
    old = store.add_account(Account(name="Fictional Old", archived=True))
    store.add_transaction(Transaction(old.saved_id, TxnType.BUY, "2024-02-01", "XEQT.TO", 1, 30, 0, currency="CAD"))


# ── defaults stay byte-for-byte the same ─────────────────────────────────────


def test_plain_status_short_and_waybar_are_unchanged(cli, tracker):
    plain = cli("status")
    view = tracker.valuation(record=False)
    c = console()
    c.print(render.summary(view, privacy=False))
    assert plain.exit_code == 0 and plain.output == c.file.getvalue()
    day = f"{fmt.arrow(view.day_change)} {fmt.pct(view.day_change_pct)}"
    assert cli("status", "--short").output == f"{day} · {fmt.compact(view.net_worth, view.base)}\n"
    waybar = json.loads(cli("status", "--waybar").output)
    assert list(waybar) == ["text", "alt", "tooltip", "class", "percentage"]
    assert waybar["text"] == f"󰄨 {day}" and waybar["percentage"] == round(view.day_change_pct, 2)
    tooltip = waybar["tooltip"].splitlines()
    assert tooltip[0] == f"Net worth  {fmt.money(view.net_worth, view.base)} {view.base}"
    assert tooltip[4:] == [
        f"{b.label:<16} {fmt.money(b.value, view.base):>14}  {fmt.pct(b.day_change_pct)}" for b in view.by_account
    ]


def test_status_json_is_the_stable_payload(cli, tracker):
    payload = json.loads(cli("status", "--json").output)
    expected = tracker.status_payload()
    payload.pop("generated_at"), expected.pop("generated_at")
    assert payload == expected


def expected_summary(tracker, store) -> str:
    view = tracker.valuation(record=False)
    perf = tracker.performance(view)
    strip = tracker.market_strip()
    today = date.today()
    snaps = [s for s in store.snapshots(today.replace(year=today.year - 1).isoformat()) if s.currency == view.base]
    c = console()
    palette = resolve_palette("auto")
    c.print(render.strip_text(strip), render.market_state_text(view.market_state))
    c.print()
    c.print(render.summary(view, perf, privacy=False))
    c.print()
    c.print(Text("▍Net worth · 1y", style="title"))
    c.print(render.net_worth_chart(snaps, palette, width=110, privacy=False))
    c.print()
    c.print(Text("▍Allocation", style="title"))
    c.print(render.allocation(view.by_class, palette, width=80, privacy=False, base=view.base))
    movers = view.movers(6)
    if movers:
        c.print()
        c.print(Text("▍Today's movers", style="title"))
        line = Text()
        for p in movers:
            line.append(f"{p.symbol} ", style="bright")
            line.append(
                f"{fmt.arrow(p.day_change_pct)}{abs(p.day_change_pct or 0):.2f}%   ",
                style=fmt.trend_style(p.day_change_pct),
            )
        c.print(line)
    return c.file.getvalue()


def test_plain_summary_is_unchanged(cli, tracker, store):
    result = cli("summary")
    assert result.exit_code == 0
    assert result.output == expected_summary(tracker, store)
    assert "Today's movers" in result.output and "AAPL" in result.output


# ── 61 status --field ─────────────────────────────────────────────────────────


def test_status_field_prints_one_raw_unmasked_value(cli, tracker):
    tracker.config.privacy = True
    assert cli("status", "--field", "net-worth").output == "13700.0\n"  # 4000 + 7000 cash + 2700 (AAPL in CAD)
    assert cli("status", "--field", "day-change").output == "85.0\n"  # −50 XEQT.TO, +135 AAPL
    assert cli("status", "--field", "invested").output == "5025.0\n"  # 3000 + 1500 × 1.35
    assert cli("status", "--field", "cash").output == "7000.0\n"
    assert cli("status", "--field", "base").output == "CAD\n"
    assert cli("status", "--field", "stale").output == "false\n"
    assert cli("status", "--field", "unrealized-pct").output == f"{round(1675 / 5025 * 100, 4)}\n"
    bad = cli("status", "--field", "colour")
    assert bad.exit_code == 2 and "Invalid value for '--field'" in bad.output


def test_status_output_modes_are_exclusive(cli):
    for args in (["--json", "--short"], ["--field", "base", "--format", "{base}"], ["--waybar", "--field", "cash"]):
        result = cli("status", *args)
        assert result.exit_code == 2 and "Choose one of" in result.output


# ── 62 status --format ────────────────────────────────────────────────────────


def test_status_format_fills_placeholders_and_honours_privacy(cli, tracker):
    result = cli("status", "--format", "{arrow} {day_change_pct} · {net_worth} {base}{stale}")
    assert result.exit_code == 0 and result.output == "▲ +0.62% · $13,700.00 CAD\n"
    assert cli("status", "--format", "{net_worth_compact} | {unrealized}").output == "$13.7K | +$1,675.00\n"
    tracker.config.privacy = True
    assert cli("status", "--format", "{net_worth} {day_change} {day_change_pct}").output == "•••• •••• +0.62%\n"


@pytest.mark.parametrize("template", ["{nope}", "{net_worth.real}", "{0}", "{}", "{net_worth", "}"])
def test_status_format_rejects_unknown_placeholders_and_bad_braces(cli, template):
    result = cli("status", "--format", template)
    assert result.exit_code == 2 and ("Unknown placeholder" in result.output or "Invalid --format" in result.output)


# ── 63 status --exit-code ─────────────────────────────────────────────────────


def test_exit_code_is_zero_when_complete_and_one_when_stale(cli, tracker, fake):
    fresh = cli("status", "--short", "--exit-code")
    assert fresh.exit_code == 0
    fake.offline = True
    tracker.market._quote_cache.clear()
    stale = cli("status", "--exit-code")
    assert stale.exit_code == 1 and "NET WORTH" in stale.output and "◌" in stale.output
    assert cli("status").exit_code == 0  # without the flag nothing changes
    payload = cli("status", "--json", "--exit-code")
    assert payload.exit_code == 1 and json.loads(payload.output)["stale"] is True


def test_exit_code_is_one_when_totals_leave_something_out(cli, store):
    archive_with_value(store)
    assert cli("status", "--field", "net-worth", "--exit-code").exit_code == 1
    assert cli("status", "--field", "net-worth").exit_code == 0


# ── 64 status --accounts ──────────────────────────────────────────────────────


def test_status_accounts_adds_a_table_after_the_unchanged_summary(cli, tracker):
    plain = cli("status").output
    result = cli("status", "--accounts")
    assert result.exit_code == 0 and result.output.startswith(plain)
    table = result.output[len(plain) :]
    assert "Accounts" in table and "Fictional Growth" in table and "Fictional Income" in table
    assert "$11,000.00" in table and "$2,700.00" in table and "+$135.00" in table
    tracker.config.privacy = True
    assert "$2,700.00" not in cli("status", "--accounts").output
    assert cli("status", "--accounts", "--short").exit_code == 2


def test_status_accounts_leaves_archived_accounts_out(cli, store):
    archive_with_value(store)
    assert "Fictional Old" not in cli("status", "--accounts").output.split("Accounts")[1]


# ── 65 status -a ACCOUNT ──────────────────────────────────────────────────────


def test_status_for_one_account_records_no_snapshot(cli, store):
    assert cli("status", "-a", "Fictional Income", "--field", "net-worth").output == "2700.0\n"
    assert cli("status", "-a", "1", "--format", "{net_worth}").output == "$11,000.00\n"
    human = cli("status", "-a", "Fictional Income")
    assert human.exit_code == 0 and "$2,700.00" in human.output and "13,700" not in human.output
    assert store.snapshots() == []  # a one-account view is never recorded as net worth


def test_status_account_rejects_archived_accounts_and_stable_contracts(cli, store):
    archive_with_value(store)
    hidden = cli("status", "-a", "Fictional Old")
    assert hidden.exit_code == 1 and "No active account 'Fictional Old'" in hidden.output
    for flag in ("--json", "--waybar"):
        result = cli("status", "-a", "Fictional Income", flag)
        assert result.exit_code == 2 and "cannot be combined" in result.output


# ── 66 summary --json ─────────────────────────────────────────────────────────


def test_summary_json_is_raw_and_unmasked(cli, tracker):
    tracker.config.privacy = True
    result = cli("summary", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert list(data) == [
        "base_currency", "stale", "market_state", "markets", "net_worth", "day_change", "day_change_pct", "invested",
        "unrealized", "unrealized_pct", "realized", "income_ytd", "cash", "returns", "history", "allocation",
        "movers", "excluded", "archived_with_value",
    ]  # fmt: skip
    assert data["base_currency"] == "CAD" and data["stale"] is False
    assert data["net_worth"] == pytest.approx(13700) and data["cash"] == pytest.approx(7000)
    assert data["unrealized"] == pytest.approx(1675) and data["day_change"] == pytest.approx(85)
    usdcad = next(m for m in data["markets"] if m["symbol"] == "USDCAD=X")
    assert usdcad["price"] == 1.35 and usdcad["label"]
    assert next(m for m in data["markets"] if m["symbol"] == "^GSPC")["price"] is None  # no fake quote
    assert data["history"] == [{"date": date.today().isoformat(), "net_worth": pytest.approx(13700)}]
    assert data["allocation"]["by"] == "class"
    assert sum(r["value"] for r in data["allocation"]["rows"]) == pytest.approx(13700)
    assert [m["symbol"] for m in data["movers"]] == ["AAPL", "XEQT.TO"]
    assert data["movers"][0]["day_change_pct"] == pytest.approx(10 / 190 * 100)
    assert set(data["returns"]) == {"since", "xirr_pct", "twr_pct"}
    assert data["excluded"] == [] and data["archived_with_value"] == []


def test_summary_json_lists_what_the_totals_leave_out(cli, store):
    archive_with_value(store)
    data = json.loads(cli("summary", "--json", "--section", "totals").output)
    assert data["archived_with_value"] == ["Fictional Old"] and data["net_worth"] == pytest.approx(13700)


# ── 67 summary --section ──────────────────────────────────────────────────────


def strip_fetched(fake) -> bool:
    return any("^GSPC" in str(params.get("symbols", "")) for _, params in fake.calls)


def test_summary_section_shows_only_chosen_sections_in_dashboard_order(cli, fake):
    result = cli("summary", "--section", "movers", "--section", "totals")
    assert result.exit_code == 0
    out = result.output
    assert "NET WORTH" in out and "Today's movers" in out and out.index("NET WORTH") < out.index("Today's movers")
    assert "Allocation" not in out and "Net worth · 1y" not in out
    assert not strip_fetched(fake)  # markets weren't shown, so their quotes weren't fetched
    assert "Allocation" in cli("summary", "--section", "allocation").output
    data = json.loads(cli("summary", "--json", "--section", "chart").output)
    assert list(data) == ["base_currency", "stale", "history", "excluded", "archived_with_value"]
    assert not strip_fetched(fake)
    assert cli("summary", "--section", "markets").exit_code == 0
    assert strip_fetched(fake)
    assert cli("summary", "--section", "news").exit_code == 2


def test_summary_section_movers_says_so_when_there_are_none(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    result = CliRunner().invoke(main, ["summary", "--section", "movers"], catch_exceptions=False)
    assert result.exit_code == 0 and result.output == "No movers today.\n"


# ── 68 summary --top ──────────────────────────────────────────────────────────


def test_summary_top_limits_movers(cli):
    out = cli("summary", "--top", "1", "--section", "movers").output
    assert "AAPL" in out and "XEQT.TO" not in out
    data = json.loads(cli("summary", "--json", "--top", "1").output)
    assert [m["symbol"] for m in data["movers"]] == ["AAPL"]
    assert cli("summary", "--top", "0").exit_code == 2


# ── 69 summary --months ───────────────────────────────────────────────────────


def test_summary_months_sets_the_history_window(cli, store):
    recent = (date.today() - timedelta(days=90)).isoformat()
    older = (date.today() - timedelta(days=540)).isoformat()
    for day, value in ((recent, 12000.0), (older, 9000.0)):
        store.upsert_snapshot(Snapshot(day, value, value, value, "CAD", {}))
    six = json.loads(cli("summary", "--json", "--months", "6", "--section", "chart").output)["history"]
    assert [h["date"] for h in six] == [recent, date.today().isoformat()]
    two_years = json.loads(cli("summary", "--json", "--months", "24", "--section", "chart").output)["history"]
    assert [h["date"] for h in two_years][:2] == [older, recent]
    assert "Net worth · 6m" in cli("summary", "--months", "6", "--section", "chart").output
    assert "Net worth · 2y" in cli("summary", "--months", "24", "--section", "chart").output
    assert cli("summary", "--months", "121").exit_code == 2


def test_months_before_clamps_to_month_end():
    assert _months_before(date(2024, 3, 31), 1) == date(2024, 2, 29)
    assert _months_before(date(2024, 2, 29), 12) == date(2023, 2, 28)
    assert _months_before(date(2025, 1, 15), 13) == date(2023, 12, 15)
    assert _months_before(date(2025, 6, 10), 12) == date(2024, 6, 10)  # the plain dashboard's one year


# ── 70 summary --allocation-by ────────────────────────────────────────────────


def test_summary_allocation_by_account_and_currency(cli, tracker):
    out = cli("summary", "--allocation-by", "account", "--section", "allocation").output
    assert "Allocation by account" in out and "Fictional Growth" in out and "Fictional Income" in out
    data = json.loads(cli("summary", "--json", "--allocation-by", "currency", "--section", "allocation").output)
    rows = {r["key"]: r for r in data["allocation"]["rows"]}
    assert data["allocation"]["by"] == "currency" and set(rows) == {"CAD", "USD"}
    assert rows["USD"]["value"] == pytest.approx(2700) and rows["CAD"]["value"] == pytest.approx(11000)
    tracker.config.privacy = True
    assert "$2,700.00" not in cli("summary", "--allocation-by", "currency", "--section", "allocation").output
