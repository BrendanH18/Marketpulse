# Changelog

All notable changes to MarketPulse are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.1] - 2026-10-06

First tagged release after MarketPulse 2.0. Cuts a pin-able build from `main`
after the September 2.0.1-era improvements, Canadian tax engine, data-safety
work, and documentation/CI professionalization.

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
   git checkout v2.0.1
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

[Unreleased]: https://github.com/BrendanH18/Marketpulse/compare/v2.0.1...HEAD
[2.0.1]: https://github.com/BrendanH18/Marketpulse/compare/08b9aff...v2.0.1
[2.0.0]: https://github.com/BrendanH18/Marketpulse/tree/08b9aff
