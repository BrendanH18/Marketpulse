# Offline backup tools

These ten additions complete items 21–30 of [issue #106](https://github.com/BrendanH18/Marketpulse/issues/106).
Examples use fictional backup dates and scratch paths.

| # | Improvement | Example |
| --- | --- | --- |
| 21 | Filter backup reason, ignoring case | `marketpulse backup list --reason manual` |
| 22 | Inclusive earliest backup date | `marketpulse backup list --since 2024-01-01` |
| 23 | Inclusive latest backup date | `marketpulse backup list --until 2024-12-31` |
| 24 | Limit matching backups | `marketpulse backup list --limit 5` |
| 25 | Skip matching backups | `marketpulse backup list --offset 5` |
| 26 | List oldest backups first | `marketpulse backup list --oldest-first` |
| 27 | Search filenames, ignoring case | `marketpulse backup list --search import` |
| 28 | Inspect one backup's file metadata | `marketpulse backup show /tmp/fictional-backup.db --json` |
| 29 | Verify integrity and schema compatibility without restoring | `marketpulse backup verify /tmp/fictional-backup.db --json` |
| 30 | Create a backup with machine-readable metadata | `marketpulse backup now /tmp/fictional-backup.db --json` |

List filters compose with `--json`, apply before pagination, and retain the
existing newest-first filename ordering by default. Dates refer to the local
backup timestamp in its filename, rather than file modification time. Files
without a recognized timestamp do not match date filters. Dates accept the
same relative values as transaction entry; reversed ranges are refused.
Limits must be positive and offsets nonnegative. Filters never delete backups.

`show` reads file metadata only; it does not establish that the file is a valid
backup. `verify` uses the restore integrity/schema preflight, opening the source
read-only and making a disposable temporary copy. It checks SQLite integrity,
core MarketPulse tables, and that the schema version is supported. It never
replaces the ledger, migrates the source, or establishes financial correctness.
Verification JSON is `{"ok": true, "path": "/absolute/path", "error": null}`;
invalid databases return `ok: false`, an error message and exit status 1.
Missing files also exit 1, with the ordinary CLI error on stderr.

Both commands accept a bare filename from `backup list` or an explicit path.
As with restore, a bare name prefers the backups directory when a file exists
there; use `./name.db` to explicitly select a local file. Opening the configured
ledger to resolve a bare name or list backups may take its usual daily backup.
Explicit paths for `show` and `verify` do not open the current ledger.

`show --json` and `now --json` return the same fields as `list --json`: `file`,
`path`, `reason`, `size_bytes`, and `taken_at`. Timestamps and reasons are derived
from the standard filename convention; timestamps are null for arbitrary names.
JSON is unmasked even in privacy mode. File paths and names can contain personal
information, so protect saved output. No command fetches prices or sends notifications.
