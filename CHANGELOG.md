# Changelog

All notable changes to MarketPulse are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
