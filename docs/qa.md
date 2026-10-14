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
/tmp/marketpulse-qa/launch.sh                          # opens "MarketPulse QA"
```

`--fresh` resets the scratch ledger, settings, and the QA app's preferences, and the
script quits any QA copy that's still running, so switching between desktop and menu
bar mode always tests the new build. It builds a separate app (`dev.marketpulse.qa`) with its own data in
`/tmp/marketpulse-qa`, so your installed app, its settings, and `~/.marketpulse`
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
8. **Automation.** "Back up now" shows "Safety backup created".
9. **Record a transaction (⌘N).** The account picker has no Old RRSP. Record a BUY
   of AAPL in Everyday TFSA with the currency left blank ("Automatic"); Activity
   shows it in US dollars, negative.
10. **Import (⌘I).** Choose `/tmp/marketpulse-qa/sample-import.csv` (⌘⇧G to type
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

Quit the QA app with ⌘Q when done.

## Tool limits and workarounds

Some computer-use tools only see the app's own window, not the Dock or the system
menu bar. Then:

- **Reopen (13):** run `/tmp/marketpulse-qa/launch.sh` again instead of clicking the
  Dock. Relaunching a running app sends the same reopen event as a Dock click.
- **Dock icon (1) and menu bar (12):** report them as UNVERIFIED and say why. A
  person should check them before a release.

## Reporting

Post results on the PR (or the issue being verified) as a table of items 1–14 with
PASS / FAIL / UNVERIFIED and evidence, then any bugs with exact steps to reproduce.
Clean up with `rm -rf /tmp/marketpulse-qa`.
