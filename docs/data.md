# Data, backups, and privacy

[Back to the README](../README.md) · [User guide](usage.md) · [Configuration](configuration.md)

## Local storage

MarketPulse stores its ledger, account settings, asset definitions, watchlist,
alerts, quote cache, contribution-room inputs, and portfolio snapshots in
`~/.marketpulse/marketpulse.db`. Set `MARKETPULSE_DATA` to use a different directory.
Display settings live in a separate TOML file.

The database and backups are not encrypted by MarketPulse. Privacy mode hides
amounts on screen; it does not redact ledger exports or the `status --json`
payload. Protect these files as you would other financial records.

There is no application telemetry or brokerage authentication. Yahoo Finance
receives symbol and market-data requests, including normal request metadata.
Missing network data may fall back to cached prices marked as stale; this is
not a guarantee that every feature works offline.

## Backups

```bash
marketpulse backup
marketpulse backup now /path/to/portfolio-backup.db
marketpulse backup list
marketpulse backup restore marketpulse-20261019-091500-daily.db
```

Backups use SQLite's online backup API, so the copy is consistent even when
another MarketPulse process has the database open.

| Reason | When | Retention |
| --- | --- | --- |
| `daily` | Startup or maintenance when the most recent backup of any kind is at least 24 hours old | Latest 14 daily backups |
| `import` | Before a non-preview CSV import | Latest 14 import backups |
| `pre-vN` | Before an existing database is upgraded to schema version N | Until removed manually |
| `manual` | When requested | Until removed manually |
| `pre-restore` | Right before a restore replaces the ledger | Until removed manually |

Default backups live in the data directory's `backups/` folder. A backup written
to an explicit path is not included in `backup list`. Local backups do not
protect against losing the disk; copy important backups to another location.
The database backup does not include the TOML configuration file.

## Restore a database

In the Mac app, open **Automation › Backups**, choose **Restore…** next to a backup,
and confirm. From the command line:

```bash
marketpulse backup restore marketpulse-20261019-091500-daily.db   # a name from `backup list`
marketpulse backup restore /path/to/portfolio-backup.db           # or any backup file
marketpulse backup restore --latest                               # the newest backup
```

A restore:

1. Checks the backup first. It must pass SQLite's integrity check, be a MarketPulse
   database, and use a schema version this build understands. A damaged file, an
   unrelated database, or a backup from a newer MarketPulse is refused, and nothing
   changes. An older backup is upgraded on a scratch copy; the backup file itself
   is never modified.
2. Saves the current ledger as a `pre-restore` backup, so you can undo the restore by
   restoring that file.
3. Replaces the ledger with the backup in one transaction, holding the ledger's write
   lock from the `pre-restore` backup to the end, so nothing written in between is lost.
   A backup whose tables don't match (a missing column, an entry whose account is gone)
   fails here and is rolled back. You don't need to quit the TUI, the app, or scheduled
   jobs: they see the restored ledger on their next read, and a refresh that was already
   running when the restore landed saves no snapshot from the ledger it replaced.

Restoring an older backup replaces everything recorded after it was taken. The
configuration file isn't part of a backup and doesn't change. `--latest` skips
`pre-restore` backups and the daily backup taken as the command started, both of which
are copies of the ledger you're replacing. The CLI asks for confirmation; `--yes` skips
it. Use the overridden data directory if `MARKETPULSE_DATA` is set.

## Upgrades and legacy portfolios

Database migrations are versioned and transactional, with a backup before a
schema upgrade. A database from a newer schema version is refused by an older
application; use a compatible version or restore a backup made before the upgrade.

Legacy MarketPulse 0.1 JSON portfolios in the data directory are imported
automatically when eligible on first startup. The original JSON files are
left untouched. Keep a copy of the original data and review the imported ledger.

## Sharing diagnostics

Use fictional or redacted records in issues. Remove account names, transaction
notes, personal paths, amounts, and identifying information from screenshots,
logs, CSVs, and JSON. Do not upload a real portfolio database to a public issue.
