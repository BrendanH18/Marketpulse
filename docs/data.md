# Data, backups, and privacy

[Back to the README](../README.md) · [User guide](usage.md) · [Configuration](configuration.md)

## Local storage

MarketPulse stores its ledger, account settings, asset definitions, watchlist,
alerts, quote cache, contribution-room inputs, and portfolio snapshots in
`~/.marketpulse/marketpulse.db`. Set `MARKETPULSE_DATA` to use a different directory.
Display settings live in a separate TOML file.

The database and backups are not encrypted by MarketPulse. Privacy mode hides
amounts on screen; it does not redact ledger exports, `status --json`, or the
other [CLI JSON reports](cli-workflows.md). Protect these files as you would
other financial records.

There is no application telemetry or brokerage authentication. Yahoo Finance
receives symbol and market-data requests, including normal request metadata.
If you set up a [fallback quote provider](#market-data-and-stale-prices), it
receives the symbols it's asked for, and your key, only while Yahoo can't be reached.
The Mac app also checks GitHub for a newer release at most once a day; see
[update checks](desktop.md#update-checks) for exactly what it sends and how to turn it off.

## Market data and stale prices

Quotes are delayed market data, not a brokerage feed. Check prices with your broker
before you trade. MarketPulse gets each price in this order:

1. **Yahoo Finance.** This is the default and needs no setup. It covers the TSX, US
   listings, exchange rates, indexes and crypto, and it's the only source for charts,
   history, dividends and symbol search.
2. **A fallback provider, if you set one up.** It's used only when Yahoo can't be
   reached, and only for prices that are missing or more than an hour old.
3. **The offline cache.** This is the last price MarketPulse saw for each symbol.

A cached price is **stale**. It shows with ◌ and its age, for example "◌ offline — 2
cached prices, oldest 3 h old" in `marketpulse summary`, or a "Cached price from 3 hours
ago" tooltip in the Mac app's Holdings. A stale price is exactly what it says: a past
price that may be hours or days old. Don't make trading or rebalancing decisions on it.

- Alerts don't fire from a stale price. Alerts on symbols with fresh prices still do.
- While any holding's price or exchange rate is stale, no performance snapshot is recorded for that day, so returns and drawdown aren't
  computed from old prices.
- Positions with no price at all, cached or fresh, are listed as excluded and left out of
  totals rather than counted at zero.

### Fallback provider: Alpha Vantage

[Alpha Vantage](https://www.alphavantage.co/) is the one free service we found whose
free tier covers TSX listings. Get a free key from its
[support page](https://www.alphavantage.co/support/#api-key), then:

```bash
marketpulse provider key alphavantage   # paste the key at the hidden prompt
marketpulse provider test XEQT.TO       # optional: one quote, to check it works
marketpulse provider status             # how each provider did on the last refresh
marketpulse provider clear              # remove the provider and its key
```

In the Mac app, use **Settings › General › Market data**. **Automation › Quote
providers** shows each provider's status.

Know these limits before you rely on it:

- **End-of-day prices.** Its free quote is the latest daily close. A fallback price
  replaces a cached Yahoo price only if it's for a later trading day.
- **25 calls a day.** Each symbol is one call, so MarketPulse asks for at most 5 symbols
  every 15 minutes and 25 a day. It asks first for symbols with no price, then the
  oldest. A large portfolio refreshes over several hours during a long outage.
- **Coverage.** TSX (`.TO`), TSX Venture (`.V`) and US listings, exchange rates such as
  `USDCAD=X`, and crypto such as `BTC-USD`. Indexes (`^GSPTSE`), futures and other
  exchanges stay with Yahoo and the cache.
- **Exchange rates and crypto show no day change**, because that endpoint has no
  previous close.

Prices from the fallback aren't stale. They show the provider's name ("via Alpha
Vantage" in `marketpulse quote`), fire alerts, and count toward snapshots.

**Your key.** It's stored as `quote_api_key` in your config file, which becomes readable
only by you once a key is saved. It's sent only to Alpha Vantage. It never appears in
`marketpulse config`, `doctor`, error messages, exports, backups, the desktop bridge, or
`status --json`. `marketpulse config set` refuses to set it, because the value would
end up in your shell history. Use `provider key`, which reads it from a prompt or
standard input. The free tier is for personal use; check Alpha Vantage's terms.

## Backups

```bash
marketpulse backup
marketpulse backup now /path/to/portfolio-backup.db
marketpulse backup list
marketpulse backup list --json
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
`backup list --json` returns the same newest-first inventory as a JSON array,
including absolute paths, reasons, sizes in bytes, and timestamps parsed from
backup filenames (`null` when unavailable). It does not restore files. As with
other CLI commands, opening the ledger may take an overdue daily backup and
prune older daily backups according to the retention policy above.

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
