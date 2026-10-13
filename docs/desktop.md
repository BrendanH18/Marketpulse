# Native macOS app

MarketPulse now includes a full SwiftUI portfolio window alongside its menu bar.
It uses your existing SQLite ledger through the Python CLI. Requires macOS 14+,
the Xcode Command Line Tools, and an editable source checkout.

## Install from this checkout

```bash
uv tool install --python 3.11 --editable .
marketpulse desktop install
```

The installer builds and opens `~/Applications/MarketPulse Bar.app`. Desktop
installation adds a Dock presence. `marketpulse menubar install` installs the
same interface as a menu bar utility. The menu bar's **Portfolio** button opens
the full window. Both install paths replace the same bundle.

The installer records the absolute CLI path and any `MARKETPULSE_DATA` directory
and `MARKETPULSE_CONFIG` file overrides. Reinstall after moving the checkout or
changing which portfolio/configuration the app should use. Installing with no
overrides resets it to the default paths. Launch-at-login preferences remain
under your control in Automation.

## Workspaces

- **Overview:** net worth, daily change, unrealized gain, snapshot history,
  asset allocation, account balances, and recent activity.
- **Holdings:** search, account filters, value/symbol ordering, and native/base
  currency labels. Missing prices remain unavailable rather than becoming zero.
- **Activity:** searchable ledger entries and amounts in the original currency.
- **Accounts:** account creation, holdings/cash tracking details, and entered
  contribution-room summaries.
- **Watchlist:** add/remove symbols and create/delete price or daily-change alerts.
- **Income:** recorded monthly distributions and interest, converted at current FX.
- **Automation:** refresh interval, login setting, backup action, errors, and
  snapshot/backup status.

Use **⌘N** to record a transaction, **⌘R** to refresh, **⌘I** to import, and **⌘E**
to export. Import first previews new entries, duplicates, skipped lines, and new
accounts. Select a default account for files without an account column. Clicking
Import adds the valid new entries, skipping the reported invalid ones, and takes
a safety backup first.

Privacy mode masks portfolio amounts and quantities, and hides amount-bearing
charts. Quotes and percentage changes remain visible. CSV and JSON exports
contain the original data. The desktop app currently uses a dedicated dark
palette; the menu bar continues to follow configured Omarchy themes.

Advanced asset definitions, transfers, transaction edits/deletions, tax reports,
and historical backfills remain in the CLI/TUI. Portfolio charts show net worth,
which includes contributions; they are not a time-weighted return chart.

## Automation

While the app runs, every refresh checks quotes and alerts, records a daily
snapshot when valuation is fresh and complete, and takes a daily backup when
the latest backup is at least 24 hours old. Missing or stale prices are visible;
stale quotes do not fire alerts or create performance snapshots.

Closing the window leaves the menu bar running. Quitting the app stops its
maintenance timer. Only enable launch at login if you want that behavior.
For a terminal worker or an external scheduler:

```bash
marketpulse automation run --interval 60
marketpulse automation run --once --json
marketpulse automation run --once --json --quiet
```

Continuous execution retries failed cycles at the next interval. One-shot runs
exit nonzero when a cycle fails or reports errors. Use one worker per ledger to
avoid duplicate alert notifications. Automation does not create ledger entries.
Backups are local; see [data and restoration](data.md) for retention and recovery.

## Read-only demo

Build without installing, then launch with a fictional portfolio:

```bash
uv sync --locked --dev
swift build --package-path macos/MarketPulseBar
NATIVE_BIN="$(swift build --show-bin-path --package-path macos/MarketPulseBar)"
MARKETPULSE_CLI="$PWD/.venv/bin/marketpulse" \
  "$NATIVE_BIN/MarketPulseBar" --demo
```

![Native portfolio window with fictional data](assets/desktop.png)

`swift build --show-bin-path --package-path macos/MarketPulseBar` prints the actual
binary directory if your toolchain uses another layout. The demo disables data
writes and notifications and never opens your real portfolio or fetches quotes.
All demo values and history are fictional.

For integration checks, `marketpulse desktop snapshot --demo` emits the same
versioned JSON used by the app. This bridge includes raw financial amounts even
when privacy mode is enabled, just like the existing `status --json` API.
