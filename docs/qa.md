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

Add `--empty` to start from an empty ledger instead of the seeded one, as a new user
does (it implies `--fresh`). Only item 17 uses it; rebuild without it for the rest.

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
5. **Accounts.** Exactly the two active accounts, and a "1 archived" link (no names).
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
    the path), Broker format Auto-detect, default account Everyday TFSA, Preview:
    "Detected format: Generic CSV", 2 new, 0 duplicates, 2 skipped, new account New
    FHSA. The Skipped lines table shows line 3 (account, Old RRSP, archived) and
    line 5 (date, 2024-13-40, invalid date). Import shows "Imported 2 entries…".
    Previewing again shows 0 new, 2 duplicates, and the Duplicates disclosure lists
    lines 2 and 4 with a one-line summary each.
    - **Questrade:** import the printed `questrade-export.csv` with Auto-detect and
      "Use accounts named in the CSV": "Detected format: Questrade", 8 new, 3 skipped
      (line 6 amount -22.00 reversal; lines 8 and 12 type, with the reason), new
      accounts Questrade Individual TFSA 90001234 and Questrade Individual margin 90005678.
      Import, then check Holdings: XEQT.TO 100 in the TFSA, AAPL 3 in the margin account.
    - **Wealthsimple:** choose `wealthsimple-export.csv`, Broker format Questrade,
      Preview: the error says the file doesn't look like a Questrade export. Switch to
      Auto-detect, default account Everyday TFSA, Preview: "Detected format:
      Wealthsimple", 7 new, 2 skipped (lines 6 NRT and 9 LOAN). Import, then check
      Activity shows BUY XEQT.TO and BUY AAPL in CAD.
    - With privacy on, the Value column and duplicate summaries are masked.
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

16. **Fresh install** (release verification only). Only in a new, throwaway macOS
    user account (System Settings › Users & Groups), never your own: the DMG route
    launches from Finder, which can't set `MARKETPULSE_DATA`, so the app uses that
    account's `~/.marketpulse`, which must hold nothing real. Check macOS 14 and macOS
    15 or later when you can, and delete the account afterwards. Run the one-line
    install from the [install guide](install.md) for the release under test, with
    `--version` and `--no-open`: it prints "Checksum verified" and installs to
    `~/Applications`. Open it on scratch data with
    `S=$(mktemp -d); open --env MARKETPULSE_DATA="$S" --env MARKETPULSE_CONFIG="$S/config.toml" ~/Applications/MarketPulse.app`:
    it opens with **no security dialog**. **About MarketPulse** shows that version and
    "Bundled with the app". Then delete the app, download the DMG in Safari, and follow
    the guide's DMG steps: macOS blocks the first launch, **Open Anyway** (macOS 15+) or
    Control-click › Open (macOS 14) opens it, and later launches don't ask. Finally,
    follow the guide's Uninstall steps. (Tampered downloads are covered by
    `tests/test_install_script.py`.)

17. **First-run onboarding.** Build with `--empty` and launch. The window opens with
    a **Welcome to MarketPulse** sheet offering **Create your first account**, **Import
    a CSV**, and **Explore a demo portfolio**, and saying the portfolio stays on this
    Mac in the scratch `data` folder the script printed. The copy has no terminal
    commands. **Not now** closes it, and relaunching (quit with ⌘Q first) doesn't show
    it again; **Help › Welcome to MarketPulse** does. Then, from the welcome each time:
    - **Explore a demo portfolio:** a "Demo portfolio · Fictional data · Read-only" banner
      with **Leave demo**, three fictional accounts, ⌘N and the import and export buttons
      disabled, and a menu bar title starting with "Demo". The scratch `data` folder is
      unchanged afterwards (`ls -l` before and after). **Leave demo** returns to the
      empty ledger.
    - **Import a CSV:** a file panel opens; choose the sample CSV. The preview runs, and
      importing adds the rows and creates their accounts.
    - Rebuild with `--empty`, then **Create your first account:** the account form opens,
      and the new account appears on Overview. Changing **Show totals in** to USD before
      that changes the footer to "USD".
    With the seeded ledger (no `--empty`), the welcome never appears by itself. With the
    **Record transaction** sheet open, **Help › Welcome to MarketPulse** shows the welcome
    as soon as you cancel that sheet, not on top of it.

18. **Restore a backup.** In **Automation**, **Back up now**, then record a deposit
    (⌘N). **Backups** lists the new backup first ("Backed up by you"), with its date,
    time, and size; the magnifying glass shows it selected in Finder. **Restore…** on
    it asks "Restore the backup from <date>?" and says your current portfolio is saved
    first; **Cancel** changes nothing. Confirm: the window reloads, says "Restored the
    backup from <date>…", the deposit is gone from Activity, and a "Before a restore"
    backup is now first in the list. Restore that one: the deposit is back. In the
    demo, **Backups** says the demo has none.

19. **Settings and appearance.** **MarketPulse › Settings…** (⌘,) opens a window with
    General, Appearance, Portfolio, and Data tabs; the popover's gear and **Automation ›
    Open Settings…** bring back the same window. Each of the following applies without
    a restart:
    - **General:** set **Refresh quotes every** to 2 minutes; **Automation** now says
      "Every 120 seconds". Set the menu bar to **A symbol's price**, enter `xeqt.to`, and
      **Set**: the menu bar shows XEQT.TO's price. Leave **Launch at login** off.
    - **Appearance:** **Light** turns the portfolio window, Settings, and the ⌘N sheet
      light; **Dark** turns them dark; **System** follows System Settings › Appearance.
      In Light, visit every workspace and open each sheet (⌘N, New account, Create alert,
      Import, Welcome): all text, chart colours, warnings ("Archived account Old RRSP…")
      and errors are readable. The menu bar popover keeps its terminal theme.
    - **Portfolio:** **Show totals in** USD changes the footer to "USD". **Default
      account** Cash Account preselects it in ⌘N. **Hide amounts** masks amounts as
      "••••", the same as the eye button. `marketpulse config` (with the QA app's
      `MARKETPULSE_CONFIG`) shows the new values.
    - **Data:** the portfolio path is the scratch `data` folder; **Reveal in Finder**
      selects it. **Show Backups…** opens **Automation**.
    Quit and relaunch: every setting is kept. In the demo, General, Appearance, and Portfolio say
    "Settings are read-only" and their controls are disabled.

20. **Update check.** The QA app reads the fictional release in the scratch folder's
    `update-feed.json` (v99.0.0) instead of GitHub. After launch, the window shows
    "MarketPulse 99.0.0 is available." with **Release Notes** and **Copy Install Command**;
    the app menu has **Update Available: MarketPulse 99.0.0…** and the popover has a
    "↓ MarketPulse 99.0.0 is available" line. **Copy Install Command** says it was copied,
    and the clipboard holds `curl -fsSL https://github.com/BrendanH18/Marketpulse/releases/download/v99.0.0/install.sh | bash -s -- --version v99.0.0`
    (don't run it). Closing the banner (×) hides it in all three places, also after a
    relaunch; **Check for Updates…** brings it back and Settings says "MarketPulse 99.0.0
    is available." Turn off **Check for updates automatically**: the banner and menu item
    disappear and **Check Now** is disabled. In the demo, no banner appears.

21. **Edit and delete transactions.** In **Activity**, right-click the AAPL sell (Cash
    Account) and choose **Edit…**. The sheet reads "Edit transaction" with Type "Sell"
    (disabled), Quantity 1, Price 230, currency USD, and the sale's date. Set Quantity to 10
    and **Save changes**: the sheet says "Not saved: on <date>, sell of 10.0000 AAPL exceeds
    5.0000 held." and Activity is unchanged. Set it to 2 and save: the window says
    "Transaction updated" and the sale shows +460.00 USD. Double-click the dividend: the
    same sheet opens with its amount (45.5, or 45,5 in French); **Cancel**. Right-click the
    AAPL buy, **Delete…**, **Delete**: the window says "Not deleted: transaction #… would
    no longer add up…" and the buy is still listed. Select the fee and press Delete: the
    confirmation names it (its date, "Fee", the amount, "Cash Account"); **Cancel** changes nothing,
    **Delete** removes it and the totals refresh. On the split, **Edit…** is disabled and
    **Delete…** isn't (don't delete it). In the demo, both are disabled.

22. **Manage accounts and contribution room.** In **Accounts**, **Edit account…** on Cash
    Account opens "Edit account" with Cash Account, NONREG, USD and **Track cash balance**
    on. Rename it to `everyday tfsa` and **Save changes**: the sheet says "An account named
    'everyday tfsa' already exists." and nothing changes. Pick another type: a caution
    about tax and contribution room appears; pick NONREG again. Rename it to `Spending`
    and save: the window says "Account updated" and Overview, Holdings, Activity and the
    ⌘N picker show Spending. **Edit account…** › **Archive…**: the confirmation says
    Spending will be hidden everywhere and left out of totals, that its transactions are
    kept, and that snapshots pause while it still holds investments or cash. **Cancel**
    changes nothing. Archive it: Spending is gone from every workspace, picker and the menu
    bar, a warning says it still holds investments or cash, and the link reads "2
    archived". The link opens **Settings › Data**, where **Archived accounts (2)** expands
    to Old RRSP and Spending; **Unarchive** Spending brings it back everywhere. Under
    **Contribution room**, TFSA reads "Not set yet"; **Set…**, keep this year, enter
    `7000`, **Save room**: the row reads "From 7,000.00 on January 1, <year>" with 7,000.00
    remaining. **Update…** opens with that year and 7000 filled in. In the demo, Edit,
    Archive and Set are disabled.

23. **Tax.** Open **Tax**. After "Working out your capital gains…", the latest sale's year is
    selected and **AAPL** is listed with 1 sale from **Spending** (Cash Account renamed
    in item 22; the sell edited in item 21).
    Its gain is positive, and **Net capital gain** matches the year's "Net gain" from
    `MARKETPULSE_DATA="$TMPDIR/marketpulse-qa/data" MARKETPULSE_CONFIG="$TMPDIR/marketpulse-qa/config.toml" uv run marketpulse tax`
    (live exchange rates, so compare the two, not a fixed figure). **Taxable capital
    gain** is half of it. Expand AAPL: the sale shows "Sale · 2 units · USD at" a rate.
    MSFT in the archived Old RRSP never appears. **Contribution room** shows the TFSA
    room from item 22 with how it was worked out. The notes at the bottom say the figures
    are estimates and not tax advice. **Export CSV…** suggests
    `marketpulse-capital-gains-<year>.csv`; save it, then open it: one AAPL row with the
    same proceeds, cost, and gain. Turn on privacy (eye button): every amount and unit
    count shows ••••. Turn it off. Record a buy of 1 AAPL in Spending dated today:
    Tax reloads by itself; nothing else changes. Record a sale of `0.000125` AAPL in Spending:
    its expanded detail shows "0.000125 units", preserving every decimal, and privacy
    still masks it. In the demo, **NVDA** has 2 sales across the available years (use the
    year picker if they fall in different years), the first marked superficial, and
    **Denied losses** explains it ("bought 15 within 30 days … held 65"); **Export CSV…**
    is disabled.

24. **Transfers, DRIPs, splits, and return of capital.** Press ⌘N and choose **Transfer in
    kind**. The account picker becomes **From account**, with a **To account** picker that
    never lists the account it's moving from. From Spending (item 22 renamed Cash Account) to
    Everyday TFSA, symbol `aapl`: the caption reads "Spending holds … AAPL now." The price field reads
    **Market price per share** and explains the tax effect; **Save transaction** stays
    disabled until it has a price. Enter Quantity 99 and price 230, then save: the sheet
    says "Not recorded: on <date>, transfer of 99.0000 AAPL exceeds … held." Set Quantity
    to 1 and save: Activity shows "Transfer · AAPL · Spending → Everyday TFSA ·
    230.00 USD" with no sign, and Holdings lists 1 AAPL in Everyday TFSA. Record a
    **Reinvested dividend (DRIP)** in Everyday TFSA of 0.5 `XEQT.TO` at 31: Activity shows
    "DRIP" and 15.50 CAD with no sign. Record a **Stock split** of XEQT.TO in Everyday TFSA:
    with 1 and 1, Save is disabled; with 2 and 1, the caption says what the current
    quantity becomes. Save: Activity shows ×2, and Holdings shows twice the units at the same
    cost. A split of XEQT.TO in Spending says "Spending holds no XEQT.TO now…", and
    saving it says "Not recorded: on <date>, split of XEQT.TO with nothing held." Record a
    **Return of capital** of 12.5 on XEQT.TO in Everyday TFSA: Activity shows "ROC" and
    +12.50 CAD, and XEQT.TO's cost in Holdings is 12.50 lower. Right-click each new entry:
    **Edit…** is disabled and **Delete…** isn't. In the demo, Save is disabled.

25. **GICs, other assets, and allocation targets.** In **Holdings**, **Add asset › GIC or
    bond…**: with the maturity date on or before the start date, the sheet says so and
    **Add asset** stays disabled. Add `gic-qa` to Everyday TFSA, principal 10,000 at 4.5%
    annual, starting a year ago and maturing a year from now: Holdings lists GIC-QA under
    its name with "4.5% annual · matures <date>", worth about 10,450 CAD, and
    `marketpulse holdings` (with the QA app's `MARKETPULSE_DATA` and `MARKETPULSE_CONFIG`)
    shows the same value. Adding another asset with symbol `AAPL` says it's already in your
    portfolio. **Add asset › Property or other asset…**: `art-qa`, value 3,500, class
    Alternative, in Everyday TFSA. Right-click it: **Record a valuation…** of 3,800; the
    row shows 3,800 and "Valued by you · <today>". Right-click AAPL: there's no
    **Record a valuation…**, and **Change asset class…** to Fund moves AAPL under Fund in
    **Allocation**. Open **Allocation**: with no targets, it offers **Set targets…**. Enter
    ETF 70 and Equity 40: the sheet says they can't pass 100% and Save is disabled. Enter
    ETF 60, Fixed Income 30, and save: the table lists each class with its share now, its
    target, the drift, and "Add …" or "Reduce by …", and the note says these are
    suggestions only. Privacy mode hides the table. **Clear all** and save: the workspace
    offers **Set targets…** again. In the demo, Allocation shows the demo's targets with the
    fictional GIC under Fixed Income, and **Add asset** and **Change targets…** are disabled.

26. **Keyboard and VoiceOver.** ⌘1 to ⌘9 switch to each workspace in sidebar order, and the
    **Workspace** menu lists them; ⇧⌘H masks and unmasks amounts. In every form sheet, Return
    saves (when allowed) and Esc cancels; in Import, Return previews, then imports. With VoiceOver on (⌘F5): the toolbar's eye and
    refresh buttons, the watchlist's remove button, an alert's delete button, and a
    backup's magnifying glass each speak a name, not "button" or an icon name. The
    Overview chart speaks a summary such as "… to … , up 4.20%. Low …, high …", and the
    Income chart its total and highest month. A Holdings row's asset cell, an Overview
    account or recent-activity row, and a Tax security row each read as one line, with
    "gain" or "loss" spoken. Accessibility Inspector's audit (Xcode › Open Developer Tool)
    reports no errors on any workspace.

27. **Quote providers and stale prices.** **Automation › Quote providers** lists Yahoo
    Finance as Primary, with a status word (OK or Failing, not only a colour), when it
    last succeeded, and how many quotes it served. In **Settings › General › Market data**,
    pick Alpha Vantage, enter a made-up key such as `QAFICTIONAL1`, and save: the field
    clears and says "Key saved", and Automation lists Alpha Vantage as Fallback, "Not
    tried". `ps -ax | grep provider` while saving never shows the key, and
    `marketpulse config` (with the QA app's environment) shows `quote_api_key` as `(set)`.
    Turn off Wi-Fi and refresh: Yahoo shows Failing with its error, and Holdings shows a
    stale marker whose tooltip gives the price's age. Once a cached price is more than an
    hour old, Alpha Vantage is tried (with the made-up key it may answer or refuse; either
    way the key never appears in the error). Turn Wi-Fi back on, refresh, then **Remove
    key**: the fallback row disappears.

28. **French.** Quit the QA app, then run `"$TMPDIR/marketpulse-qa/launch.sh" -AppleLanguages
    '(fr)' -AppleLocale fr_CA` (or set the system language to Français). Walk through
    items 2–11, 17–25 and 27. Every label, button, menu, tooltip, sheet, alert and
    VoiceOver name reads in French, with no English left and no text truncated or
    overlapping. Amounts read like `1 234,56 $`, percentages like `5,25 %`, and dates are
    French. Account types show as CELI, REER, CELIAPP. A Tax note and an archived-account
    warning read in French. Typing `12,5` in an amount field records 12.5. Then relaunch
    with `-NSShowNonLocalizedStrings YES` added: no text appears in capitals (a capitalized
    string is a key missing from the French table).

Quit the QA app with ⌘Q when done.

## Windows app

Build the [Windows app](windows.md#windows-portfolio-app), run its bridge checks,
and create the fictional ledger with `scripts/qa_windows.py`. Launch with both
scratch path overrides. Record PASS / FAIL / UNVERIFIED with observed evidence:

| Item | Check |
| --- | --- |
| W1 Launch and overview | Launch on Windows 11 with scratch paths. Overview shows the fictional portfolio; compare totals to `desktop snapshot` with the same overrides. Empty-ledger launch explains how to add an account or import. |
| W2 Workspaces | Open Holdings, Activity, Accounts, Watchlist, Income and Automation. Check native/base currency labels, stale/error indicators, income, backup/refresh state and signed activity (buy/fee negative, deposit/sell/dividend positive). Archived QA account and its rows stay hidden and out of totals. |
| W3 Transactions | Record a fictional deposit, buy, sell and fee. Confirm account/date/currency/fees/notes in Activity and the scratch CLI. Invalid input reports an error without a write. Refresh after save does not record twice. |
| W4 Accounts | Add an account, edit its details, then archive it after confirmation. It disappears from workspaces, transaction choices and totals. |
| W5 Watchlist and alerts | Add/remove a fictional watch symbol; add an alert and disable/remove it. Quote requests may fail offline: errors/staleness remain visible; stale quotes never fire alerts. Windows toast delivery is not implemented. |
| W6 CSV | Preview the helper's sample CSV: valid/skipped rows and reasons appear without changing Activity. Import the preview and compare receipt counts to the preview. Change the file after preview and confirm it must be previewed again. Cancel leaves the ledger unchanged. |
| W7 Privacy | Hide details, visit every workspace and inspect tray text. No amounts, account names, symbols or notes remain. Relaunch on the same scratch settings and check privacy persists; reveal restores data. |
| W8 Refresh and failure | Refresh while navigating; controls remain responsive. Launch with a missing scratch Python path: show an error rather than a zero portfolio. A failed mutation must not claim success. |
| W9 Tray and reopen | Close the window; tray remains. Open restores one window, including after minimizing. Tray refresh updates status while preserving privacy. Exit during refresh stops both app and child Python. |
| W10 Keyboard and Narrator | Reach navigation, actions and form fields using Tab, activate with Space/Enter, dismiss dialogs with Escape. Narrator announces labels/errors. Check Windows text scaling and light/dark appearance for clipping and contrast. |
| W11 Demo and relocation | Run `--demo`: fictional data, writes unavailable, no real ledger/settings access. Copy the full published app to a path with spaces; with no Python/.NET on PATH, `--check-bridge` and demo launch work. |
| W12 Install with install.ps1 | On a test account without MarketPulse, run the release's `install.ps1` (`irm … \| iex`, or the script-block form with `-Version`). It prints "Checksum verified", installs to `%LOCALAPPDATA%\Programs\MarketPulse` with no administrator or SmartScreen prompt, and starts the app. The Start menu has MarketPulse; Settings › Apps › Installed apps lists it with the release version. |
| W13 Install with the setup exe | Download the setup exe in Edge and check it with the `Get-FileHash` snippet in the [install guide](install.md#verify-a-windows-download) (prints `True`). Opening it shows "Windows protected your PC"; **More info** names the file and **Run anyway** continues. Setup asks for no administrator rights and offers to start MarketPulse. Quote the dialog text. |
| W14 Portable zip | Download the zip in a browser and verify its hash. Extract it as is: `MarketPulse.exe` gets a SmartScreen prompt (record it). Then run `Unblock-File` on the zip, extract it again to a new folder: the exe starts without a prompt and shows the fictional portfolio. |
| W15 Upgrade while running | With an older release installed and running in the tray (window closed), run the newer release's install command or setup. It closes MarketPulse and its Python process without a prompt and installs into the same folder. Started again, the app shows the new version and the same portfolio. |
| W16 Uninstall keeps data | Uninstall from Settings › Apps › Installed apps (or `unins000.exe`) while the app runs in the tray. The app closes; the install folder, Start menu entry and Installed apps entry go; the scratch `MARKETPULSE_DATA` folder and `MARKETPULSE_CONFIG` file are unchanged. Reinstalling shows the same portfolio. |
| W17 Tax report | Open Tax on the helper's scratch ledger. A loading message precedes the report. Compare the selected year's proceeds, cost base, net gain, taxable gain and disposition details to `desktop tax` with the same scratch paths. In `--demo`, choose each available year and inspect the fictional NVDA sales and superficial-loss details. No financial values are calculated by the interface. |
| W18 Tax refresh, privacy and errors | Recalculate the report; navigate away and back during loading. Turn Privacy on during loading: no figures, symbols, account names, notes or error details appear after completion. Reveal restores the report. Record or edit a scratch transaction and revisit Tax: the report reflects the change. An empty ledger explains that no taxable sales exist. With a missing scratch backend, report failure offers retry and never shows zero figures as success. |
| W19 Tax CSV | Export the selected year to a path with spaces and non-ASCII characters. Open the CSV and compare rows, currency and amounts to `desktop tax` and `desktop tax-csv` with the same scratch paths. Cancel the picker: no file is written. A write failure shows an error; export warnings remain visible. Export is unavailable in `--demo` and while Privacy hides the report. |

| WB1 Backups | On the fictional scratch ledger, open Automation. Back up now and compare the new file's name, time, reason and size to `desktop snapshot` storage metadata with the same scratch overrides. Privacy hides the list and paths; the demo offers no backup writes. |
| WB2 Restore and recovery | Create a backup, record a fictional deposit, then choose Restore this backup. The confirmation identifies the file and replacement consequences; Cancel or leaving its checkbox clear changes nothing. Confirm restore: Activity and totals return to the saved state, configuration stays unchanged, and a Before a restore copy is listed. Restore that safety copy to recover the deposit. |
| WB3 Restore failures | Against scratch data only, remove or corrupt a listed backup before confirming. The app shows an explicit engine error and the ledger stays unchanged. A changed portfolio/list while a confirmation is open requires cancel and reselection. A timeout or interrupted restore requires refreshing and inspecting current state before retry. A completed restore followed by refresh failure says restored and shows a separate refresh error. |

W12–W16 install release builds, which the Start menu and Explorer launch without
`--data-dir`/`--config`. Point them at scratch data instead: run them on a Windows test
account or virtual machine without a real portfolio, and before W12 set both variables for
that account to the helper's fictional ledger, then sign out and back in so the Start menu
and Explorer pass them on:

```powershell
$qa = uv run --locked python scripts/qa_windows.py | ConvertFrom-Json
if (-not ($qa.data -and $qa.config)) { throw 'qa_windows.py printed no scratch paths; stop here.' }
[Environment]::SetEnvironmentVariable('MARKETPULSE_DATA', $qa.data, 'User')
[Environment]::SetEnvironmentVariable('MARKETPULSE_CONFIG', $qa.config, 'User')
```

"The same portfolio" in W15 and W16 means the helper's ledger. W16 checks that this scratch
folder and config are unchanged, and that `%USERPROFILE%\.marketpulse` was never created.
Afterwards remove both variables (set them to `$null` the same way).
`scripts/check_windows_install.py` automates the silent install, version and uninstall
checks of W12 in CI; it doesn't see SmartScreen, the tray, or the Start menu.

Linux/macOS visual checks are supplementary. Mark Windows items UNVERIFIED when
Windows desktop access is unavailable; do not infer them from a passing CI build.
The helper creates a new temporary directory each time; remove only its printed
root after closing the QA app.

### Windows custom assets and allocation

Use the same fictional scratch paths for both the app and CLI. These checks add
only fictional assets; no live quotes are needed for them.

| Item | Check |
| --- | --- |
| WA1 Fixed income | In Holdings, Add GIC or bond to Fictional TFSA: symbol `QA-GIC`, principal 1,000, rate 4.5%, start today, maturity a year later, annual compounding. Invalid maturity at/before start or nonpositive principal stays in the form without a write. After saving, Holdings shows the term/rate and matches the scratch CLI value. Adding the same symbol again is rejected without changing metadata or recording another purchase. |
| WA2 Manual assets | Add manually valued asset `QA-ART`, name `Fictional art`, value 300, class Alternative, to Fictional TFSA. Record a valuation of 350 dated today. Holdings shows the value and valuation date; scratch Activity has one new valuation. A nonmanual holding offers no valuation action. Change the art to Real Estate: Holdings and Allocation show the new class. Canceling any form changes nothing. |
| WA3 Allocation targets | Open Allocation and set Fixed Income 60 and Real Estate 40. Values, weights, target, drift and suggested amounts match `marketpulse allocation` against the same scratch paths. Targets above 100% combined, negative or nonnumeric values are rejected without replacing old targets. Reopen and check values; clear targets after confirmation and check holdings are unchanged. Archived QA holdings never enter allocation totals. |
| WA4 Privacy, demo and failure | Privacy hides all asset/allocation amounts and identifying details. In demo, Allocation shows fictional targets and every asset/target write action is disabled. While saving, duplicate submits and other write actions are disabled. With an unavailable backend a save reports an error; an uncertain retry keeps the same request and cannot add duplicate purchase/valuation rows. Check keyboard labels, scrolling and clipping at Windows text scaling. |

Report WA1–WA4 separately from build and bridge checks. Windows appearance,
Narrator and native window behavior require observed Windows evidence.

### Windows watchlists and alerts

Use fictional symbols and alerts with both scratch path overrides. Trigger-history
fixtures can be seeded in the scratch database; do not depend on live prices to
exercise lifecycle controls.

| Item | Check |
| --- | --- |
| WL1 Saved order | Add three fictional watched symbols, including one without a quote. Move the last to the first position, refresh and restart: the order persists and the unpriced symbol remains visible. Boundary moves are disabled; remove a symbol and check the remaining order. |
| WL2 Edit and validation | Edit a fictional alert's threshold and note; clear the note and try text beginning with `--` and non-ASCII characters. Refresh/restart and compare saved values with `alerts show --json`. Invalid, zero or nonfinite thresholds show an error without a write. Cancel changes nothing. |
| WL3 Lifecycle | On a scratch alert with trigger history, pause, edit and resume: the trigger time stays unchanged. Cancel rearming: unchanged. Confirm rearming: the alert becomes enabled and its trigger time clears. The explanation says a matching fresh price can fire again. |
| WL4 State filters | Armed shows enabled/untriggered alerts; Paused shows disabled alerts even with trigger history; Triggered shows enabled/triggered alerts. All restores the full list. A filter with no matching rows explains the empty result. Filtering never writes. |
| WL5 Safeguards | Privacy hides symbols, notes, values and error details; the demo disables all writes. While saving, duplicate writes are disabled. With a missing scratch backend, an action shows an error. Check keyboard labels, focus, clipping and native appearance on Windows. |

Report WL1–WL5 with PASS / FAIL / UNVERIFIED and observed evidence. Headless
checks and Linux rendering supplement Windows desktop QA; they do not establish
Windows Narrator, native focus or scaling behavior.

## Tool limits and workarounds

Some computer-use tools only see the app's own window, not the Dock or the system
menu bar. Then:

- **Reopen (13):** run `"$TMPDIR/marketpulse-qa/launch.sh"` again instead of clicking the
  Dock. Relaunching a running app sends the same reopen event as a Dock click.
- **Help menu (17):** the Help menu lives in the system menu bar. Use the Overview's
  empty-state **Other ways to start…** button, which opens the same welcome, and report
  the Help menu itself as UNVERIFIED.
- **Dock icon (1) and menu bar (12):** report them as UNVERIFIED and say why. A
  person should check them before a release.

## Reporting

Post results on the PR (or the issue being verified) as a table of items 1–26 with
PASS / FAIL / UNVERIFIED and evidence, then any bugs with exact steps to reproduce.
Clean up with `rm -rf "$TMPDIR/marketpulse-qa"`.
