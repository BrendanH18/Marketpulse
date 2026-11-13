# Changelog

All notable changes to MarketPulse are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Offline grouped summaries through `marketpulse summarize SOURCE`: 40 summary
  operations across 25 saved datasets (1,000 dataset/operation combinations),
  typed grouping, filtering, sorting, pagination and atomic file exports.
  See the [capability inventory](docs/cli-report-summaries.md)
  ([#140](https://github.com/BrendanH18/Marketpulse/issues/140)).

- Forty additional operations across 25 offline report datasets: 1,000 new
  dataset/operation combinations, including numeric and typed filters, text/JSON
  output transformations, column aliases, constants, row numbering, case-insensitive
  sorting and row windows. See the [capability inventory](docs/cli-report-improvements.md)
  ([#138](https://github.com/BrendanH18/Marketpulse/issues/138)).

- Composable offline reports through `marketpulse report SOURCE`: 25 saved datasets
  with 20 shared query and export operations each (500 dataset/operation
  capabilities), schema discovery, and atomic file output without overwriting.
  See the [capability inventory](docs/cli-composable-reports.md) ([#136](https://github.com/BrendanH18/Marketpulse/issues/136)).

- One hundred more offline CLI inspection improvements ([#134](https://github.com/BrendanH18/Marketpulse/issues/134)):
  realized gains and payout selection, asset metadata filters and exports,
  snapshot and backup inventory tools, saved allocation target inspection,
  and command discovery selectors. See the
  [numbered inventory](docs/cli-more-hundred-improvements.md) for all 100.

- One hundred offline CLI workflow improvements ([#132](https://github.com/BrendanH18/Marketpulse/issues/132)):
  ledger selection and exports, position/cash/account inspection, watchlist and
  alert filters, theme discovery, configuration receipts and previews, a
  searchable command catalog, and provider/doctor exports and filters. See the
  [numbered inventory](docs/cli-next-hundred-improvements.md) for all 100.

- One hundred recording, ledger, lookup, overview and terminal app improvements ([#130](https://github.com/BrendanH18/Marketpulse/issues/130)).
  See [One hundred improvements](docs/cli-hundred-improvements.md) for the numbered guides.
  - Recording commands gain `--dry-run`, `--json` receipts with the position and
    cash afterwards, `--quiet`, `--balance`, `--confirm`, `--once`, and
    `--check`/`--strict` warnings (archived account, same-day duplicate, weekend
    trade, negative cash, price far from the cached quote), plus `--total`,
    `sell`/`transfer`/`withdraw … all`, `dividend`/`roc --per-unit` and split
    ratios such as `3:1`.
  - `undo` gains `--dry-run`, `-a`/`--symbol` and `--json`; `txn show` takes
    several ids and `--with-effect` (holdings and cash before and after);
    `txn check` gains `--code` and `-a`; `txn edit --dry-run` shows a field
    diff; `txn delete` takes several ids with one confirmation, plus
    `--dry-run`.
  - `export` gains `-a`, `--symbol`, `--type`, `--since`/`--until`,
    `--columns`, `--count` and `--jsonl`; `import` gains `--summary` and
    `--exit-code`; `backfill` gains `--dry-run` and `--json`.
  - `chart` gains `--json`, `--csv`, `--stats`, `--from`/`--to`, `--last`,
    `--normalize`, `--width` and `--no-card`; `compare` gains `--json`, `--csv`,
    `--sort`/`--reverse`, `--base`, `--top` and `--no-chart`; `search` gains
    `--json`/`--csv`, `--type`/`--exchange`, `--limit` and `--first`; `quote`
    gains `--field` and `--strict`. Each reuses the plain command's request.
  - `status` gains `--field`, `--format`, `--exit-code`, `--accounts` and `-a`;
    `summary` gains `--json`, `--section`, `--top`, `--months` and
    `--allocation-by`; `income` gains `--json`, `--csv`, `--months`, `--year`,
    `-a`, `--symbol`, `--kind`, `--by`, `--top` and `--forecast-only`.
    `status --json` and `--waybar` are unchanged.
  - The terminal app adds `backspace` for the previous workspace, `{`/`}`,
    `j`/`k` and `<`/`>` to move around, `F` to filter holdings and `escape` to
    clear filters, `o`/`O` to sort, `y`/`Y` to copy, `v` to chart, `T` for a
    symbol's transactions, `N` to pick any transaction type, `z` to zoom and
    `F1` for the current workspace's keys. The footer shows the row position
    and refresh age, and the command palette lists every key-only action.

- Thirty offline tax, allocation and holdings inspection improvements ([#128](https://github.com/BrendanH18/Marketpulse/issues/128)):
  capital gains report filters, sorting, paging, summaries, issue and room views,
  and JSON/CSV output; allocation target listing, removal, dry runs, drift
  thresholds with exit codes, and JSON/CSV output; and priced holdings filters,
  sorting, JSON/CSV, stale and excluded listings, plus `perf --json` and
  `perf --metric`. `tax --csv -` now prints to stdout instead of writing a file
  named `-`, and allocation targets must be from 0 to 100. See
  [Offline tax, allocation and holdings inspection](docs/cli-portfolio-inspection.md).

- Thirty offline maintenance and diagnostics improvements ([#126](https://github.com/BrendanH18/Marketpulse/issues/126))
  for backup inventories, configuration and theme inspection, the offline quote
  cache, and selective `doctor` checks. See
  [Offline maintenance and diagnostics](docs/cli-maintenance-diagnostics.md).

- Thirty offline reporting refinements ([#124](https://github.com/BrendanH18/Marketpulse/issues/124))
  extend saved account inventories, native-currency realized and payout reports,
  and snapshot history. See [Offline report refinements](docs/cli-report-refinements.md)
  for the numbered feature guides and examples.

- Thirty offline inventory selection improvements ([#122](https://github.com/BrendanH18/Marketpulse/issues/122)):
  account exclusions, registration and metadata filters with grouped counts;
  configured-asset rate, term and compounding selection; and saved watchlist
  position/alert filters with alert summaries. See
  [Offline inventory selection](docs/cli-inventory-selection.md).

- Thirty offline ledger selection improvements ([#120](https://github.com/BrendanH18/Marketpulse/issues/120)):
  position metadata and quantity/book filters, average-cost ordering, cash pages
  and balance/account filters, and activity month, amount, fee and exclusion
  filters with quarterly and account-type counts. See
  [Offline ledger selection](docs/cli-ledger-selection.md).

- Thirty offline report filtering improvements ([#118](https://github.com/BrendanH18/Marketpulse/issues/118)):
  search and amount bounds for sales and income, snapshot book/contribution/change
  filters, and saved-alert threshold, note, trigger-date and paging controls.
  Alert list thresholds now respect privacy mode in human output. See
  [Offline report filters](docs/cli-report-filters.md).

- Thirty offline report browsing improvements ([#116](https://github.com/BrendanH18/Marketpulse/issues/116)):
  position pages and holding-date filters, searchable and sortable cash balances,
  currency filters and pages for realized gains and payouts, and calendar,
  value, change and ordering controls for snapshot history. See
  [Offline report browsing](docs/cli-report-browsing.md).

- Windows watchlist ordering and alert management ([#114](https://github.com/BrendanH18/Marketpulse/issues/114)):
  edit thresholds and notes, pause/resume without losing trigger history, explicitly
  rearm, and filter alerts by state. Unpriced watched symbols remain visible and
  movable through the additive version-1 `watchlist_symbols` snapshot field.

- Thirty offline ledger report and diagnostics improvements ([#111](https://github.com/BrendanH18/Marketpulse/issues/111)):
  `positions` and `cash` cost-base views with filters, sorting and an overdraft exit code,
  native-currency `realized` gain and `payouts` income logs with grouped totals, `snapshots`
  history, `quote --cached` and `--json`, and `doctor --offline`, `--json` and `--strict`.
  See [Ledger reports and diagnostics](docs/cli-ledger-reports.md).

- Thirty offline CLI discovery and export improvements ([#110](https://github.com/BrendanH18/Marketpulse/issues/110)):
  account and asset CSV exports, counts and page metadata; account, symbol and
  calendar activity filters and grouped counts; watchlist exports and page
  metadata; and alert exports, text search, ordering and pagination.
  See [CLI discovery and exports](docs/cli-discovery-exports.md).

- Thirty offline CLI productivity improvements ([#108](https://github.com/BrendanH18/Marketpulse/issues/108)):
  activity exclusions and date filters, grouped CSV reports and page metadata,
  saved-watchlist browsing and alert editing, and redacted configuration inspection,
  defaults, individual resets and validation. See [CLI productivity](docs/cli-productivity.md).

- Thirty more offline CLI improvements ([#106](https://github.com/BrendanH18/Marketpulse/issues/106)):
  activity CSV exports, counts and grouped summaries, note and ID filters,
  detailed account/asset inspection, inventory sorting and paging, and backup
  discovery, inspection, read-only verification and JSON creation receipts.
  See [Offline reporting and backup tools](docs/cli-reporting-tools.md).

- Thirty local-first CLI improvements ([#104](https://github.com/BrendanH18/Marketpulse/issues/104)):
  activity date/type/text/currency filters, ordering and pagination, transaction
  inspection with edit revisions, offline ledger checks, offline account and asset
  inventories with composable filters, watchlist reordering, alert pause/resume/rearm
  and filtering, and full JSON reports for these workflows, backups, and CSV imports.
  See [Offline CLI workflows](docs/cli-workflows.md) for the numbered list and examples.
  JSON reports contain unmasked values even in privacy mode.

- A Windows Tax workspace ([#97](https://github.com/BrendanH18/Marketpulse/issues/97))
  with year selection, capital gains, superficial-loss
  details, and CSV export for your accountant. Reports use the existing Python
  engine, load on demand, and respect privacy mode; the fictional demo is read-only.

- Windows custom-asset forms for GICs, bonds and manually valued holdings, with
  valuation updates and asset-class overrides. The Allocation workspace shows
  current weights, targets, drift and engine-provided suggestions; targets can
  be edited or cleared without a terminal. Asset creation checks for symbol
  collisions in the complete ledger, including archived accounts.

- Windows **Automation** can list and create ledger backups, and restore one after
  a clear confirmation. The existing engine validates the file and saves a
  pre-restore copy first; privacy hides backup details and the demo stays read-only.
  See [Windows backups and restore](docs/windows.md#backups-and-restore).
  The version-1 snapshot adds `storage.restore_revision` for saved asset,
  watchlist, alert and allocation-target changes, complementing `ledger_revision`.

- On-demand macOS and Windows desktop benchmarks in the CI workflow, with raw
  samples, source commit, runtime metadata and a run link retained in the reports.
  See [desktop refresh measurements](docs/performance.md) for how to run them.

- An offline desktop latency benchmark using a fictional 5,000-transaction ledger.
  [Desktop refresh measurements](docs/performance.md) explains the startup, refresh,
  and edit-plus-refresh boundaries and the evidence for the next performance decision.

- Windows releases ([#53](https://github.com/BrendanH18/Marketpulse/issues/53)): a per-user
  installer that needs no administrator rights, a portable zip, and a one-line PowerShell
  install (`irm …/install.ps1 | iex`) that runs the installer only if it matches the release's
  `SHA256SUMS`. The installer and app aren't code-signed; [Install on Windows](docs/install.md#windows)
  covers the SmartScreen prompt, checking a download with `Get-FileHash`, updating, and uninstalling,
  which keeps your portfolio. Each GitHub Release now has the macOS and Windows files with one `SHA256SUMS`.

- A Windows portfolio workspace with holdings, signed activity, accounts, watchlists and
  alerts, income, automation, transaction entry, CSV preview/import, privacy mode, and
  system-tray controls ([#52](https://github.com/BrendanH18/Marketpulse/issues/52)).
  The standalone CI artifact includes the Python backend; installer packaging remains
  separate. An explicit read-only demo and isolated scratch-ledger QA are available.

- An Avalonia Windows demo showing fictional net worth in a window with a system-tray
  menu, plus a self-contained CI build and desktop bridge checks
  ([#50](https://github.com/BrendanH18/Marketpulse/issues/50)). Avalonia with C#/XAML is
  the chosen Windows UI stack; the full Windows workspace and installer remain separate work.
- A self-contained Windows x64 backend build, with pinned Python and locked dependencies,
  plus Windows CI tests and a relocated-bundle smoke test
  ([#51](https://github.com/BrendanH18/Marketpulse/issues/51)). See
  [Windows backend builds](docs/windows.md). Windows keeps the existing data/config paths;
  desktop notifications are currently a no-op. The native Windows interface and installer
  remain separate work.
- The Mac app is available in French (Canada)
  ([#46](https://github.com/BrendanH18/Marketpulse/issues/46)). The desktop bridge adds
  stable codes for the engine's messages so the app can word them in French: `warning_items`
  next to the snapshot's `warnings`, and `code` and `args` on tax report and import preview
  `issues`. These are additive; the bridge stays at version 1, `status --json` is unchanged,
  and the CLI and the English text in the bridge read exactly as before.
- An optional fallback quote provider for when Yahoo can't be reached
  ([#49](https://github.com/BrendanH18/Marketpulse/issues/49)): Alpha Vantage, whose free
  tier covers the TSX, with a key you get yourself. Set it with `marketpulse provider key
  alphavantage` (the key is read from a prompt or standard input) or in the Mac app's
  **Settings › General › Market data**. Check it with `provider test` and `provider status`,
  and remove it with `provider clear`. It's used only for prices that are missing or more than
  an hour old, within its free limits (5 symbols per 15 minutes, 25 a day). Its free prices
  are end-of-day closes and never replace a newer cached price. The key never appears in
  `config`, `doctor`, errors, exports or the desktop bridge, and the config file becomes
  owner-only once it holds one.
- Clearer stale prices ([#23](https://github.com/BrendanH18/Marketpulse/issues/23)):
  `summary` and the TUI say how many prices are cached and how old the oldest is, and
  `quote` shows a cached price's age or the provider that supplied it. The Mac app's
  **Automation › Quote providers** panel shows each provider's status and the stale count,
  and a stale Holdings price's tooltip gives its age.
  [Market data and stale prices](docs/data.md#market-data-and-stale-prices) explains
  what stale means and the fallback order.
- Desktop bridge (still version 1, fields added): `providers`, `automation.stale_count` and
  `stale_since`, each position's `quote_source` and `quote_age_seconds`, and the provider
  fields in `settings`.

### Changed

- Desktop refreshes reuse transaction rows and revision hashes within each snapshot,
  reducing repeated ledger reads and serialization. The desktop JSON payload and edit
  revision values stay the same. See [refresh measurements](docs/performance.md).

### Fixed

- Backup filenames without recognized timestamps no longer interrupt startup
  or prevent offline backup inspection on a populated ledger.

- `summary` no longer crashes on 29 February when working out the start of its
  one-year history window.
- Ordinary CLI activity and transaction inspection hide archived accounts, including
  transfers touching archived accounts. CSV previews no longer create a default
  account in the live ledger when a file omits account names; create an account first.
- An alert check already fetching prices no longer overwrites an alert paused or
  edited during that fetch, or fires the paused alert from its stale state.

- Configuration and CSV file exports use UTF-8 explicitly, preserving non-ASCII
  account names on Windows. Saving a provider key no longer calls Unix-only
  permission APIs on Windows.
- `marketpulse doctor` said "Yahoo reachable" even when Yahoo couldn't be reached and
  prices came from the offline cache. It now reports the failure, and the fallback
  provider's status.

## [2.2.0] - 2026-11-03

The first release with the standalone Mac app (App 1.0 for macOS): `MarketPulse.app`
for Apple silicon and Intel, with its own copy of the engine, installed with one command
or from a DMG. The app now covers everyday work without a terminal: onboarding, editing
transactions and accounts, every transaction type, broker CSV imports, the tax workspace,
GICs and manually valued assets, allocation targets, backups and restore, settings, an
update check, and keyboard and VoiceOver support. Minor bump: the CLI, `status --json`, and
the database stay backward compatible (see **Changed** for stricter checks).

### Added

- Keyboard and VoiceOver support in the Mac app. A new **Workspace** menu opens each
  workspace with ⌘1 to ⌘9, and ⇧⌘H hides or shows amounts. VoiceOver names every
  icon-only button (in the window and the menu bar popover), summarizes each chart in
  words (start, end, change, range; allocation shares; income total and best month), and
  reads Overview's accounts and recent activity and each tax row as one line, with gains and
  losses spoken rather than shown only in colour. Light-mode mint is slightly darker so banner
  text meets WCAG AA contrast, and a selected Holdings row no longer draws green or red
  text on the selection colour. See [keyboard and accessibility](docs/desktop.md#keyboard-and-accessibility).

- GICs, bonds, and assets you value yourself, and allocation targets, in the Mac app.
  In **Holdings**, **Add asset** adds a GIC or bond (principal, rate, start, maturity,
  compounding; valued by the interest it earns) or a property or other asset with its
  value and asset class. Right-click a row to **Record a valuation…** of an asset you
  value yourself, or **Change asset class…** of any symbol. A new **Allocation**
  workspace shows each asset class against your targets, with the amount to add or
  reduce to reach them (suggestions only; MarketPulse never trades), and **Set
  targets…** edits them. `asset fixed`, `asset manual`, and `asset value` accept
  `--request-id`, so the app can retry a save without recording it twice. `allocation`
  gains `--quiet` (save targets without pricing holdings), and `--clear-targets` with
  `--target` now replaces the targets in one step, keeping the old ones if a new one is
  rejected. `desktop snapshot` gains `targets`, `rebalance`, and `assets`. The demo
  portfolio gains a fictional GIC and targets.

- Broker CSV profiles for **Questrade** account activity exports and **Wealthsimple**
  monthly statements, detected from the header row. `marketpulse import` and
  `desktop import` accept `--profile auto|questrade|wealthsimple|generic`. Broker codes
  are translated through a table; transfers, currency conversions, corporate actions,
  withholding tax, and amounts with the wrong sign for their type are skipped with a
  reason rather than guessed. A Wealthsimple dividend goes to the listing the account
  holds (a converted US stock keeps its US symbol). See [usage](docs/usage.md#import-and-export).
- Clearer import reports: each skipped row names its line, field, value, and what was
  expected, and duplicates are listed with a one-line summary. `desktop import` results
  gain `profile`, `profile_label`, `issues` (`line`, `field`, `value`, `reason`) and
  `duplicate_rows` (`line`, `summary`); existing fields are unchanged.
- The Mac app's import sheet has a **Broker format** menu (Auto-detect, Questrade,
  Wealthsimple, Generic CSV), names the format the preview used, lists skipped lines in
  a table of line, field, value, and reason, and lists duplicates under a disclosure.

- Record transfers, DRIPs, splits, and returns of capital in the Mac app. The transaction
  form gains **Transfer in kind** (from and to accounts; a market price is required, with
  the reason, between a registered and a non-registered account), **Reinvested dividend
  (DRIP)**, **Stock split** (entered as new shares for old, such as 2 for 1), and
  **Return of capital**, and says how much of the symbol the account holds now. Activity
  labels them DRIP and ROC, and shows a transfer without a price as the units moved. They
  can be deleted, not edited. New `marketpulse roc SYMBOL AMOUNT` records a return of
  capital and says the new cost base, and any part that counts as a capital gain under
  the pooled cost base `marketpulse tax` uses (never in a registered account).
  `drip` and `transfer` accept `--currency`, and `transfer` accepts `--request-id`, so
  the app can retry a save without recording it twice. `desktop snapshot` accounts gain
  `registered`.

- A **Tax** workspace in the Mac app: capital gains for each year with a sale in a
  taxable account, with the same figures as `marketpulse tax` (pooled cost base,
  trade-date exchange rates). It shows net and taxable capital gain, denied losses with
  the reason (superficial losses show what was bought back and held), gains by security
  with each sale (including exact fractional quantities), sales missing an exchange
  rate, contribution room with its working, and a "not tax advice" note. Amounts
  follow privacy mode. **Export CSV…** saves a
  year's sales for an accountant. New `marketpulse desktop tax` (versioned JSON, with
  `--demo`) feeds it, and `marketpulse tax --csv FILE` writes the CSV (and warns about
  ledger issues that may leave sales out; `desktop tax-csv` does the same for the app, in
  JSON). `desktop snapshot` gains `ledger_revision`, so the app recalculates when something
  the report reads has changed, or a new day has started. The demo
  portfolio gains three NVDA trades in its taxable account (a superficial loss, then a
  gain), so the demo's Tax workspace has something to show.

- Manage accounts in the Mac app: in **Accounts**, **Edit account…** renames an account or
  changes its type, currency, institution, or cash tracking, and **Archive…** hides it
  after a confirmation that explains the consequences. **Settings › Data** lists archived
  accounts so they can be unarchived. **Set…** / **Update…** enters TFSA, RRSP, and FHSA
  contribution room without the terminal, even before you open an account of that type.
  `desktop snapshot` gains `archived_accounts` (id, name, type, and revision only), and
  each account gains a `revision`. `accounts edit --revision` refuses the change if the
  account was changed elsewhere, or the portfolio restored, since it was loaded; the app
  always sends it.

- Edit and delete transactions in the Mac app: in **Activity**, right-click an entry for
  **Edit…** (or double-click it) and **Delete…** (or press Delete). Edit opens the
  transaction form filled in, with the type fixed; delete asks first and names the entry.
  Buys, sells, deposits, withdrawals, dividends, interest, and fees can be edited;
  every type can be deleted. Errors show in the form or the window.

- A Settings window in the Mac app (**MarketPulse › Settings…**, ⌘,), with General
  (refresh interval, launch at login, menu bar display, terminal), Appearance (System,
  Light, or Dark), Portfolio (currency for totals, default account, privacy), and Data
  (where the portfolio and settings live, backups) tabs. The portfolio window now has a
  light palette and follows the system appearance instead of always being dark. The
  default account is preselected when recording a transaction. The popover's settings
  panel and the Automation workspace's preferences moved into the window.
  `desktop snapshot` gains a `settings` object.

- Update checks in the Mac app: at most once a day, the release app asks GitHub for its
  latest release. A newer version shows a banner, an **Update Available** menu item and a
  popover line, each offering the release notes and the one-line install command to
  paste into Terminal. Nothing is installed automatically. Turn it off in **Settings ›
  General**; the demo and checkout builds never check. The request and what it sends are
  documented in `docs/desktop.md`.

- Restore from a backup: `marketpulse backup restore PATH` (or a name from `backup list`,
  or `--latest`), and **Automation › Backups** in the Mac app with Restore and Show in
  Finder. The backup is checked first (integrity, a MarketPulse database, a schema this
  version reads), the current ledger is saved as a `pre-restore` backup, and the swap
  happens in one step without quitting other MarketPulse windows. `desktop snapshot`'s
  `storage` object gains `backup_dir` and `backups`.

- First-run onboarding in the Mac app: a new ledger opens with a welcome sheet that
  offers to create an account, import a CSV, or explore the demo, sets the currency
  for totals, and says where data is stored. **Help › Welcome to MarketPulse** brings
  it back. The fictional demo can now be entered and left inside the app.
  `desktop snapshot` gains a `storage` object (`data_dir`, `empty`), and
  `scripts/qa_app.py --empty` builds the QA app on an empty ledger.

- A one-line install for the Mac app: `scripts/install.sh`, attached to each release,
  downloads the app with `curl`, checks it against `SHA256SUMS`, its bundle ID, version,
  and signature, and installs it to `~/Applications` without a Gatekeeper prompt.
  A new [install guide](docs/install.md) covers the DMG route with Open Anyway, verifying
  downloads, why the app is unsigned, and uninstalling; `SECURITY.md` explains how
  releases are produced and verified.

- A native macOS portfolio window with charts, holdings/activity search,
  account/transaction/alert forms, CSV preview/import, export, income, and
  automation status. Install from an editable checkout with `marketpulse desktop install`.
- Versioned `desktop snapshot` JSON bridge and a fictional read-only `--demo`.
- Shared maintenance cycle and `automation run` worker (continuous or `--once`)
  for refresh, daily snapshots, alert checks, and daily safety backups.
- Native checks that decode the real Python demo payload and CI coverage for them.
- A CI coverage gate for the financial core: `scripts/check_coverage.py` fails when branch
  coverage of the ledger, tax, database and migration, valuation, analytics, or import modules
  drops below its floor in `pyproject.toml`. New tests cover selling or transferring more
  than is held and legacy JSON files with unreadable files or bad rows.
- An app icon for the Dock, Finder, and Login Items.
- `scripts/build_app.py` builds a standalone `MarketPulse.app` (arm64 and x86_64) that
  carries its own pinned Python and locked dependencies, so it runs without Python, uv,
  or Xcode tools. It is ad-hoc signed and smoke-tested in a clean environment.
  `scripts/qa_app.py --bundled` builds the QA app the same way.
- The app prefers its bundled backend after `MARKETPULSE_CLI`, and **Automation › About
  MarketPulse** shows the app and backend versions and which backend is running.
- `python -m marketpulse` runs the CLI, and `desktop snapshot` reports a `backend`
  object (engine and Python versions).
- Version tags build the release: a workflow checks that the tag matches the package
  version, builds the wheel and `MarketPulse.app` for Apple silicon and Intel as zips and
  DMGs with `SHA256SUMS`, verifies and runs every app, and opens a draft GitHub Release
  with that version's changelog section. A manual run is a dry run with no release.

### Fixed

- `allocation --clear-targets --target …` no longer clears the saved targets when one of
  the new ones is rejected.
- CSV import no longer reads an unreadable number (such as `2x` in a price or fees
  column) as zero; the row is skipped and reported with the column and value.
- Contribution room still counts deposits to archived accounts. Archiving a TFSA, RRSP
  or FHSA used to drop its contributions, overstating the room left. Archived accounts
  stay out of the room table's account list.
- `accounts edit` reports a clear error instead of a traceback when the new name is
  taken, and refuses a blank name (the TUI's account form too).
- Native transaction saves use durable request receipts: a confirmation failure or timeout
  can be recovered or retried without recording the transaction twice.
- The native window reopens from the Dock and shows its toolbar on macOS 14.
- Opening the TUI in Terminal or iTerm from the app works when the CLI's path contains spaces.
- Transaction validation rejects NaN/infinity; alerts require a finite positive threshold.
- CSV previews (`--dry-run`) run the real import against a temporary copy of the
  ledger, so they always match the import exactly. Imports are all-or-nothing, and
  the app's import refuses to run if the file or ledger changed since its preview.
- macOS installation preserves configuration overrides and clears obsolete paths.
- Native CLI subprocesses time out instead of leaving refresh stuck indefinitely.

### Changed

- Recording a transfer or a split (in the CLI, TUI, or app) is checked against what the
  account held on its date, and refused with the reason if it moves more shares than
  were held, moves shares a later sale needs, or splits a position the account didn't
  hold. A split with nothing held, already in a ledger, is now listed as a ledger issue
  instead of being ignored silently, so deleting the purchase it relies on is refused.
  A DRIP or return of capital in a currency other than the holding's is refused, since
  both change a cost base kept in the holding's currency.

- `marketpulse txn edit`, `txn delete`, and `undo` (and edits and deletes in the TUI)
  now check the ledger the way it's replayed, each entry at its own date, and refuse a
  change that leaves a sale of more than was held then: for example, an edit that
  oversells, a purchase moved after the sale that needs it, or deleting that purchase.
  A transfer that would move more shares than were held counts too.
  Change or delete the sale first. Problems already in the ledger don't block other
  changes. Edits are also validated like new entries (positive quantities, no future
  dates), and an edit or delete that a backup restore overtook is refused.
- A transfer of more shares than were held moves what was held, as before, and is now
  listed with the ledger's other warnings instead of passing silently.
- `txn edit --symbol` without `--currency` works the currency out again for a different
  symbol, and `--currency ""` uses the listing currency.
- `txn edit` and `txn delete` accept `--revision`, and each `desktop snapshot` activity
  row gains a `revision`: the app sends it back, so an entry changed or replaced since the
  window loaded it (in another window, by a restore, or a reused id) is refused, not overwritten.
  Without `--revision`, `txn edit`, `txn delete`, and `undo` (and the TUI) check against the
  entry as they read it, so a change made elsewhere before they write is refused too.

- Archived accounts are now left out of every total (net worth, allocation,
  account lists and movers, including `status --json`), as the TUI's archive
  setting always described. Their history, income, realized gains, room, tax
  reports, and returns (total gain, XIRR) still include them. If an archived account still holds something, you're
  warned, and daily snapshots and history rebuilds (`backfill`) wait until it's resolved.
- CSV imports skip rows that name an archived account, with that reason.

### Upgrade notes

1. **Back up before upgrading.** Quit the TUI and menu bar companion, then run
   `marketpulse backup` (or copy `~/.marketpulse/` to another disk).
2. **No database migration.** The schema is unchanged from 2.1.0, so 2.1.0 can
   still open the ledger if you roll back.
3. **Mac app.** Install it with the one-line command or the DMG in the
   [install guide](docs/install.md). It shares `~/.marketpulse` with the CLI and TUI.
   A companion installed from a checkout (`MarketPulse Bar.app`) is a separate app; if you
   switch, quit it and [remove it](docs/install.md#uninstall) so two apps don't refresh one ledger.
4. **Update the CLI from a release tag:**

   ```bash
   marketpulse backup
   uv tool install --python 3.11 --reinstall git+https://github.com/BrendanH18/Marketpulse.git@v2.2.0
   marketpulse --version
   ```

5. Archived accounts no longer count in totals or `status --json` (see **Changed**), and
   tax figures remain **estimates**: check them against your slips before filing.

## [2.1.0] - 2026-10-06

First tagged release after MarketPulse 2.0. Minor bump (not a patch): this cut
ships new backward-compatible public functionality from the September post-2.0
work — Canadian tax engine, schema/backup workflows, CLI/TUI hardening, and
documentation/CI professionalization — so SemVer calls for `2.1.0`.

### Added

- Schema versioning via SQLite `PRAGMA user_version`, sequential migrations,
  and automatic pre-upgrade database backups (retained until removed manually
  for `pre-vN` copies).
- Canadian capital-gains tax engine with pooled ACB across taxable accounts,
  trade-date FX on both legs, CRA-style superficial-loss handling, and deemed
  dispositions for in-kind transfers into registered accounts.
- `marketpulse tax` reporting (CLI and Accounts workspace estimates).
- Daily and pre-import backup retention, plus clearer `marketpulse backup`
  workflow documentation.
- Project docs and contributor materials: user/config/data guides, security and
  third-party notices, issue/PR templates, Dependabot, and expanded CI
  (multi-Python, macOS, package smoke checks, mypy).

### Changed

- FHSA contribution-room tracking now caps carry-forward at $8,000 and applies
  the $40,000 lifetime limit.
- Contribution FX, stale FX handling, and analytics time bucketing.
- Ledger backfill replays once for consistent holdings.
- Runtime and tooling dependency bumps (Click, curl-cffi, Textual, Ruff,
  pytest, GitHub Actions).

### Fixed

- CLI input validation and CSV import hardening (safer parsing and clearer
  rejection of bad rows).
- TUI refresh, privacy-mode gaps, form validation, and empty-state presentation.

### Upgrade notes

1. **Back up before upgrading.** Quit the TUI and menu bar companion, then run
   `marketpulse backup` (or copy `~/.marketpulse/` to another disk).
2. **Schema migrations.** Opening this build adopts an unversioned MarketPulse
   2.0 database as schema v1. Later schema steps run transactionally with a
   `pre-vN` backup first. A newer-schema database is refused by older builds —
   restore a pre-upgrade backup if you need to roll back the application.
3. **Update from a source checkout** (PyPI publish is out of scope for this
   release):

   ```bash
   marketpulse backup
   git fetch --tags
   git checkout v2.1.0
   uv tool install --python 3.11 --editable --reinstall .
   marketpulse --version
   ```

4. Tax figures are **estimates** for planning; review them against your own
   records before filing. See [docs/data.md](docs/data.md) for backup and
   restore details.

## [2.0.0] - 2026-09-15

Initial 2.0 overhaul: transaction ledger engine, SQLite store, Yahoo market
client, Omarchy-styled Textual TUI, and native macOS menu bar companion.
See PR [#3](https://github.com/BrendanH18/Marketpulse/pull/3).

[Unreleased]: https://github.com/BrendanH18/Marketpulse/compare/v2.2.0...HEAD
[2.2.0]: https://github.com/BrendanH18/Marketpulse/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/BrendanH18/Marketpulse/compare/08b9aff...v2.1.0
[2.0.0]: https://github.com/BrendanH18/Marketpulse/tree/08b9aff
