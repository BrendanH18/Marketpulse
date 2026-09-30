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
```

Backups use SQLite's online backup API, so the copy is consistent even when
another MarketPulse process has the database open.

| Reason | When | Retention |
| --- | --- | --- |
| `daily` | Startup when the most recent daily backup is over 24 hours old | Latest 14 daily backups |
| `import` | Before a non-preview CSV import | Latest 14 import backups |
| `pre-vN` | Before an existing database is upgraded to schema version N | Until removed manually |
| `manual` | When requested | Until removed manually |

Default backups live in the data directory's `backups/` folder. A backup written
to an explicit path is not included in `backup list`. Local backups do not
protect against losing the disk; copy important backups to another location.
The database backup does not include the TOML configuration file.

## Restore a database

1. Quit the TUI and the menu bar companion, and stop any scheduled MarketPulse jobs.
2. Preserve the current database and any `marketpulse.db-wal` / `marketpulse.db-shm`
   sidecar files in a separate directory.
3. Copy the selected backup to `marketpulse.db` in your data directory. Ensure old
   WAL and SHM files are no longer alongside the restored database.
4. Restart MarketPulse and review accounts, activity, and `marketpulse doctor`.

Use the overridden data directory if `MARKETPULSE_DATA` is set. Restoring an
older backup replaces changes recorded after that backup.

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
