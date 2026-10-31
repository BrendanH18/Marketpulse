# Changelog

All notable changes to MarketPulse are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

No database migration is required.

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

[Unreleased]: https://github.com/BrendanH18/Marketpulse/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/BrendanH18/Marketpulse/compare/08b9aff...v2.1.0
[2.0.0]: https://github.com/BrendanH18/Marketpulse/tree/08b9aff
