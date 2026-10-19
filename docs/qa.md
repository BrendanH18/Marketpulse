# Native app QA checklist

[Back to the README](../README.md) · [App plan](app-plan.md) · [Native app guide](desktop.md)

Use this before merging any change to the native app, and to verify a release. It
works for a person or for an agent with computer use (screenshots, mouse, and
keyboard). Everything runs against a fictional scratch ledger: never test against a
real portfolio, and never toggle **Launch at login** on the QA app.

## Set up

```bash
uv sync --locked --dev
uv run --locked python scripts/qa_app.py --fresh      # desktop mode; add --menubar for menu bar mode
"$TMPDIR/marketpulse-qa/launch.sh"                     # opens "MarketPulse QA"
```

Add `--bundled` to build the QA app the way releases ship it, with its own Python
backend ([build guide](desktop.md#build-the-standalone-app)) instead of this checkout's
CLI. Use it for changes to the bundle or to how the app finds its backend, and when
verifying a release.

`--fresh` resets the scratch ledger, settings, and the QA app's preferences, and the
script quits any QA copy that's still running, so switching between desktop and menu
bar mode always tests the new build. It refuses an `--out` folder that overlaps your real data or
settings, one it didn't create itself, one owned by another user, or one containing symbolic
links, so it can never touch a real portfolio. It builds a separate app (`dev.marketpulse.qa`) with its own data in
`$TMPDIR/marketpulse-qa` (your per-user temp folder), so your installed app, its settings, and `~/.marketpulse`
are untouched. Wait about 5 seconds for the first refresh (it fetches live quotes).

The seeded ledger has two active accounts (**Everyday TFSA**, **Cash Account**), an
archived **Old RRSP** that still holds MSFT, buys, a sell, a deposit, a fee, a
dividend, a 2:1 split, an always-firing AAPL alert, and a watchlist (NVDA, VFV.TO).

## Checklist

Record PASS / FAIL / UNVERIFIED for each item, with what you actually saw (quote
on-screen text). UNVERIFIED means your tool couldn't check it, not that it failed.

1. **Launch.** Desktop mode: the portfolio window opens by itself and the app has
   its Dock icon (dark teal square, mint heartbeat line). Menu bar mode: no window
   at launch.
2. **Overview.** Metrics show values. "Your accounts" lists only Everyday TFSA and
   Cash Account. Recent activity shows + / − signs. A warning says "Archived account
   Old RRSP still holds investments or cash…". Charts or their empty states render
   without clipping.
3. **Holdings.** No Old RRSP or MSFT row. Search filters. The account filter has no
   Old RRSP. The sort toggle reorders rows. No striped empty rows below the data.
4. **Activity.** BUY and FEE are negative; SELL, DEPOSIT, and DIVIDEND are positive;
   the split shows "×2". No Old RRSP rows. The header reads "+ money in, − money out".
5. **Accounts.** Exactly the two active accounts.
6. **Watchlist and alerts.** Add then remove a symbol. In Create alert, threshold
   `12,5` shows "Enter a number, like 12.5." (on an English system) and disables
   Create; `1,000` shows "Reads as 1,000". Create an alert, then delete it.
7. **Income.** Month labels read like "Nov 25".
8. **Automation.** "Back up now" shows "Safety backup created". **About MarketPulse**
   shows the app version, "MarketPulse <version> · Python <version>" for the backend,
   and Runs: "Bundled with the app" with `--bundled`, otherwise "MARKETPULSE_CLI override".
9. **Record a transaction (⌘N).** The account picker has no Old RRSP. Record a BUY
   of AAPL in Everyday TFSA with the currency left blank ("Automatic"); Activity
   shows it in US dollars, negative.
10. **Import (⌘I).** Choose the sample CSV path the script printed (⌘⇧G to type
    the path), default account Everyday TFSA, Preview: 2 new, 0 duplicates, 2
    skipped (line 3 archived account, line 5 invalid date), new account New FHSA.
    Import shows "Imported 2 entries…". Previewing again shows 0 new, 2 duplicates.
11. **Privacy.** The eye button masks amounts as "••••" and hides charts; toggling
    back restores them.
12. **Menu bar.** The waveform item opens a popover with net worth and accounts (no
    Old RRSP); its Portfolio button brings the window forward.
13. **Reopen.** Close the window (⌘W) and click the Dock icon: exactly one window
    returns. Minimize (⌘M) and click the Dock icon: it restores. **File › Open
    Portfolio** (⌘0) also brings it back.
14. **General.** No crash, hang, endless spinner, clipped or overlapping text, or
    unreadable contrast. Note anything that looks unfinished.
15. **Failed transaction save.** With a QA-only CLI wrapper, let a transaction
    command finish successfully, then return an error. Save a fictional deposit:
    the sheet closes, the message reads "Transaction recorded. Its confirmation
    failed.", and Activity contains exactly one entry. Repeat while the wrapper
    also fails `desktop transaction-status`: fields and Cancel stay disabled,
    **Retry save** remains available, and the sheet cannot be dismissed. Restore
    the wrapper and retry: exactly one entry remains. Also reject a transaction
    before executing it while leaving receipt checks working: the form unlocks
    for correction/cancellation and Activity has no new entry. Never change the
    real CLI or point the wrapper at a real ledger.

16. **Fresh install** (release verification only). Use a new macOS user account
    (System Settings › Users & Groups), so no real portfolio or earlier install is
    involved; check macOS 14 and macOS 15 or later when you can. Run the one-line
    install from the [install guide](install.md) for the release under test, with
    `--version`: it prints "Checksum verified", installs to `~/Applications`, and the
    app opens with **no security dialog**. **About MarketPulse** shows that version and
    "Bundled with the app". Then delete the app, download the DMG in Safari, and follow
    the guide's DMG steps: macOS blocks the first launch, **Open Anyway** (macOS 15+) or
    Control-click › Open (macOS 14) opens it, and later launches don't ask. Finally,
    follow the guide's Uninstall steps. (Tampered downloads are covered by
    `tests/test_install_script.py`.)

Quit the QA app with ⌘Q when done.

## Tool limits and workarounds

Some computer-use tools only see the app's own window, not the Dock or the system
menu bar. Then:

- **Reopen (13):** run `"$TMPDIR/marketpulse-qa/launch.sh"` again instead of clicking the
  Dock. Relaunching a running app sends the same reopen event as a Dock click.
- **Dock icon (1) and menu bar (12):** report them as UNVERIFIED and say why. A
  person should check them before a release.

## Reporting

Post results on the PR (or the issue being verified) as a table of items 1–16 with
PASS / FAIL / UNVERIFIED and evidence, then any bugs with exact steps to reproduce.
Clean up with `rm -rf "$TMPDIR/marketpulse-qa"`.
