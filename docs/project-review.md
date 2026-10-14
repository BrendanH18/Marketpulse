# Project review and next steps

Review of the source checkout, October 2026. This is a code and product review,
not an audit of current Canadian tax legislation or a certification of tax results.

## Overall assessment

MarketPulse has a useful foundation: transactions are the source of truth,
valuation is separated from replay, and interfaces share a Tracker facade.
SQLite migrations, consistent backups, fake market transports, and explicit
missing-FX handling make the core more mature than its terminal-only positioning
suggests. Keep that architecture as the app grows.

The largest opportunity is making that functionality easier to use and trust.
A full native app should help someone understand their portfolio, record an
entry, see what a CSV will do, and know whether prices and backups are current.
It should not create a second ledger or duplicate financial calculations in Swift.

## Implemented in this change

- A SwiftUI portfolio window with overview, holdings, activity, accounts,
  watchlist and alerts, recorded income, and automation workspaces.
- Native charts, searchable tables, account filters, and transaction/account/alert
  sheets. CSV preview/import and export use native file dialogs.
- A versioned desktop JSON bridge independent of the existing menu bar status
  contract. The menu bar and terminal remain available.
- A shared maintenance cycle: quote refresh, eligible daily snapshots, alert-only
  symbol checks, daily backups, and surfaced failures. The desktop timer runs it;
  a CLI runner supports continuous execution or a one-shot external scheduler.
- A read-only fictional demo that never opens the user's database or fetches
  network data, allowing repeatable UI checks.
- Finite-number validation for transactions and positive finite alert thresholds.
  Previously NaN/infinity could evade ordinary numeric comparisons.
- CSV previews can represent accounts they would create, including transfer
  destinations, without changing the ledger. The desktop preview never creates
  an implicit default account.
- The installer preserves the selected configuration path as well as the data
  directory, and removes obsolete overrides when installing for default paths.
- Native CLI calls have a timeout so a stuck subprocess cannot leave the app
  refreshing indefinitely.

## Findings and follow-up priorities

### 1. Make import profiles explicit

`csvio.py` uses header aliases and keyword inference. That is convenient, but
broker exports can contain signed cash amounts, settlement dates, FX legs,
and reinvestments with different semantics. Add named, versioned broker profiles
with representative fixtures and a row-level preview. Keep the generic importer
for known simple CSVs. Do not automatically import a watched folder until profile
validation, idempotency, and failure reporting are well established.

The current importer can create accounts before validating the entire file,
and account creation and transaction insertion are separate commits. A future
refactor should stage a full import plan and apply accounts and entries in one
SQLite transaction. Existing pre-import backups are valuable recovery, but are
not a substitute for atomic writes.

### 2. Strengthen chronological entry validation

`Tracker.add_transaction` checks a sale against current holdings. A backdated
sale can therefore be accepted using shares acquired later, or refused because
shares were sold after the date being entered. Imported entries and direct
updates also bypass this service guard. Replay records issues, and the native
app now displays them, but a shared chronological validation path for add/edit/
import would be a stronger contract. Cover backdated sales, same-day ordering,
transfers, splits, and edits before changing this behavior.

### 3. Measure coverage where mistakes are expensive

There are meaningful ledger, pooled-ACB, migration, and missing-FX tests. CI runs
them across Python versions and macOS, but has no measured coverage gate.
Add branch coverage thresholds for the financial core and migration machinery;
avoid a blanket UI percentage that rewards shallow tests. Expand invariant and
round-trip tests for CSVs and chronological entry changes.

### 4. Keep heavy work away from routine refresh

Snapshot generation and basic quotes belong on the regular timer. Tax reports,
full historical backfills, and dividend forecasts can involve many network
requests and should remain explicit, cancellable tasks with progress. The new
app deliberately uses recorded income and local history for its default screens.
For larger ledgers, add pagination to activity and measure repeated replay cost
before introducing caches that could become incorrect after edits.

### 5. Finish native distribution and lifecycle

The app currently requires an editable source checkout, Python CLI, macOS 14+,
and Swift tools. The next release-quality milestone is a signed/notarized app
bundle with a pinned bundled backend, a proper icon, update strategy, and a
migration/restore flow. Ad-hoc source builds are useful for development but are
not the final end-user installation experience.

Automation stops when the app quits. Launch at login is available, and the
one-shot runner can be used by launchd/cron. A managed scheduler installer,
persistent job history, cross-process locking, and wake-from-sleep policy would
make unattended automation more dependable. Today, run one worker per ledger;
multiple interface processes can race to notify the same alert.

### 6. Consolidate interface glue incrementally

`cli.py` and `tui/app.py` each exceed 1,600 lines. Keep new business rules in
services and small modules, then split command groups and TUI workspace handlers
with behavior-preserving changes. The desktop bridge is isolated in `desktop.py`
and maintenance in `automation.py`. The Swift UI lives in separate models,
workspaces, and forms rather than expanding the popover file.

### 7. Complete app workflow parity

The native app covers the common creation and inspection workflows. Transaction
editing/deletion, manual/fixed-income asset forms, target-allocation editing,
full tax reporting, and historical backfill controls are follow-ups. These remain
available in the CLI/TUI. Account archiving and contribution-room editing deserve
native forms with clear consequences. Add keyboard and VoiceOver checks, chart
inspection, system appearance options, and window-size testing as UI polish.

## Validation

Run the checks in CONTRIBUTING.md, including the native bridge checks. Financial tests
use fake market data; UI inspection should use the fictional demo or a separate
MARKETPULSE_DATA directory. A successful build and tests do not establish live
Yahoo reliability or validate a real investor's records.
