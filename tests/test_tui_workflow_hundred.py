"""Headless TUI tests for the 20 TUI improvements (81-100) in the 100 CLI & TUI workflow batch."""

from __future__ import annotations

import asyncio

from textual.widgets import DataTable, Static

from marketpulse import themes
from marketpulse.models import Account, AccountType, Alert, Asset, AssetKind, Transaction, TxnType
from marketpulse.tui.app import MarketPulseApp


def _run(coro):
    return asyncio.run(coro)


def test_tui_workflow_improvements_81_to_100(tracker, store, monkeypatch):
    tracker.config.theme = "tokyo-night"
    tfsa = store.add_account(Account(name="TFSA", type=AccountType.TFSA, currency="CAD", track_cash=True))
    rrsp = store.add_account(Account(name="RRSP", type=AccountType.RRSP, currency="CAD"))
    store.add_account(Account(name="Old", type=AccountType.NONREG, currency="CAD", archived=True))
    store.add_transaction(
        Transaction(account_id=tfsa.id, type=TxnType.DEPOSIT, date="2024-01-01", amount=2000, currency="CAD")
    )
    store.add_transaction(
        Transaction(
            account_id=tfsa.id,
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
            account_id=rrsp.id,
            type=TxnType.BUY,
            date="2024-01-03",
            symbol="AAPL",
            quantity=2,
            price=150,
            currency="USD",
        )
    )
    store.add_transaction(
        Transaction(
            account_id=tfsa.id, type=TxnType.DIVIDEND, date="2024-03-15", symbol="XEQT.TO", amount=25, currency="CAD"
        )
    )
    store.upsert_asset(
        Asset(
            symbol="GIC1",
            kind=AssetKind.FIXED_INCOME,
            name="1Y GIC",
            rate=5.0,
            start_date="2024-01-01",
            maturity_date="2025-01-01",
            currency="CAD",
        )
    )
    store.add_transaction(
        Transaction(
            account_id=tfsa.id,
            type=TxnType.BUY,
            date="2024-01-01",
            symbol="GIC1",
            quantity=1,
            price=1000,
            currency="CAD",
        )
    )
    store.add_watch(["AAPL", "XEQT.TO"])
    store.add_alert(Alert(symbol="XEQT.TO", condition="above", threshold=50.0, active=True, triggered_at="2024-05-01"))
    store.add_alert(Alert(symbol="AAPL", condition="below", threshold=100.0, active=False))

    copied: list[str] = []

    async def scenario():
        app = MarketPulseApp(tracker.config, tracker=tracker)
        app.copy_to_clipboard = lambda text: copied.append(text)  # type: ignore[method-assign]
        async with app.run_test(size=(170, 50)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            # 94: dashboard movers mode cycler (m)
            assert app.movers_mode == "day %"
            await pilot.press("m")
            assert app.movers_mode == "day $"
            await pilot.press("m")
            assert app.movers_mode == "unrealized"

            # 88: copy portfolio summary (Q)
            copied.clear()
            await pilot.press("Q")
            assert copied and "Net worth" in copied[-1] and "Positions:" in copied[-1]

            # 81, 82, 86, 87, 89, 91: holdings workspace
            await pilot.press("2")
            await pilot.pause()
            # 91: focus filter or chart input (F2)
            await pilot.press("f2")
            assert app.focused is not None and app.focused.id == "holdings-filter"
            await pilot.press("escape")

            # 81: reset sort (0)
            await pilot.press("o")
            assert app.table_sort["holdings"][0] != "account"
            await pilot.press("0")
            assert "holdings" not in app.table_sort

            # 82: half-page jump (ctrl+d / ctrl+u)
            await pilot.press("ctrl+d")
            await pilot.press("ctrl+u")

            # 86 & 87: copy table as CSV (#) and Markdown (X)
            copied.clear()
            await pilot.press("number_sign")
            assert copied and "Account,Symbol" in copied[-1]
            copied.clear()
            await pilot.press("X")
            assert copied and "| Account | Symbol |" in copied[-1]

            # 89: context filter mode cycler (M) on holdings
            holdings = app.query_one("#holdings-table", DataTable)
            await pilot.press("M")
            assert app.holdings_filter_mode == "gainers"
            assert all(not str(key.value).startswith("cash:") for key in holdings.rows)
            assert app._detail_key is not None
            await pilot.press("M")
            assert holdings.row_count == 0 and app._detail_key is None
            await pilot.press("escape")
            assert app.holdings_filter_mode == "all"

            # 85: jump to symbol in holdings (S) from watchlist
            await pilot.press("3")
            await pilot.pause()
            await pilot.press("S")
            await pilot.pause()
            assert app.workspace == "holdings"

            # 93: smart Y on chart workspace
            await pilot.press("4")
            await pilot.pause()
            app.open_chart("XEQT.TO")
            await app.workers.wait_for_complete()
            await pilot.pause()
            copied.clear()
            await pilot.press("Y")
            assert copied and "XEQT.TO" in copied[-1]

            # 90: activity account filter (@) + filter mode (M)
            await pilot.press("5")
            await pilot.pause()
            await pilot.press("commercial_at")
            assert app.activity_account_filter is not None
            await pilot.press("M")
            assert app.activity_filter_mode == "trades"
            await pilot.press("escape")
            assert app.activity_account_filter is None and app.activity_filter_mode == "all"

            # 83 & 96: income scroll (j/k/</>) and year stepper (-/+)
            await pilot.press("6")
            await pilot.pause()
            await pilot.press("j", "k", "greater_than_sign", "less_than_sign")
            await pilot.press("minus")
            assert app.income_year == 2024
            with app.console.capture() as report:
                app.console.print(app.query_one("#income-view", Static).content)
            assert "2024" in report.get() and "This year" not in report.get()
            await pilot.press("plus")
            assert app.income_year is None
            with app.console.capture() as report:
                app.console.print(app.query_one("#income-view", Static).content)
            assert "All time" in report.get()

            # 84, 92, 95: tax workspace — hide archived (I), today sort, tax year stepper (-/+)
            await pilot.press("7")
            await app.workers.wait_for_complete()
            await pilot.pause()
            accts_table = app.query_one("#accounts-table", DataTable)
            before_rows = accts_table.row_count
            await pilot.press("I")
            assert app.hide_archived is True and accts_table.row_count == before_rows - 1
            await pilot.press("I")
            assert app.hide_archived is False and accts_table.row_count == before_rows
            await pilot.press("minus")

            # 97 & 98: alerts workspace — re-arm triggered (U), pause/resume all
            await pilot.press("8")
            await pilot.pause()
            await pilot.press("U")
            await app.workers.wait_for_complete()
            assert all(not a.triggered_at for a in store.alerts())
            app.action_pause_all_alerts()
            await app.workers.wait_for_complete()
            assert all(not a.active for a in store.alerts())
            app.action_resume_all_alerts()
            await app.workers.wait_for_complete()
            assert all(a.active for a in store.alerts())

            # 99: create local database backup
            before_backups = len(store.backups())
            app.action_create_backup()
            await app.workers.wait_for_complete()
            assert len(store.backups()) >= before_backups + 1

            def fail_backup(*, reason):
                raise PermissionError("Fictional backup directory is read-only")

            received = []
            monkeypatch.setattr(store, "backup", fail_backup)
            monkeypatch.setattr(app, "notify", lambda message, **kwargs: received.append((message, kwargs)))
            app.action_create_backup()
            await app.workers.wait_for_complete()
            assert any(options.get("severity") == "error" for _, options in received)

            # 100: restore auto theme
            colors = {**themes.OMARCHY_PALETTES["tokyo-night"], "background": "#123456"}
            monkeypatch.setattr(themes, "omarchy_active", lambda: ("custom-test", colors))
            app.action_restore_auto_theme()
            assert app.config.theme == "auto" and app._auto_theme is True
            assert app.palette.name == "custom-test" and app.current_theme.background == "#123456"
            app.action_restore_auto_theme()
            assert app.current_theme.background == "#123456"
            await app.workers.wait_for_complete()
            await pilot.pause()

    _run(scenario())
