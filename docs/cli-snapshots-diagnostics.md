# Offline snapshots, cached quotes and scriptable diagnostics

[User guide](usage.md) · [Ledger reports and diagnostics](cli-ledger-reports.md)

These improvements read saved local data and make diagnostics scriptable. They
are items 21–30 of the 30-improvement batch (#111). Examples use fictional
symbols; point `MARKETPULSE_DATA` and `MARKETPULSE_CONFIG` at a scratch
directory to try them without touching your own data.

21. **Snapshot history:** `marketpulse snapshots` lists the daily net-worth
    snapshots already recorded (by `marketpulse status`, the app, or
    `marketpulse backfill`), oldest first: date, net worth, book value, change
    and currency. It never fetches prices. Change is the stored net worth minus
    the previous recorded snapshot's, so filtering doesn't blank the first row.
    It is left blank for the first snapshot and whenever the previous snapshot
    was recorded in a different currency (for example after changing
    `base_currency`); no conversion is done. Filter with
    `marketpulse snapshots --since 2024-01-01 --until 2024-03-31` (inclusive;
    `yesterday` and `-30d` work too).
22. **Recent snapshots and currency:** `marketpulse snapshots --limit 5` shows
    the five most recent matches, still oldest first;
    `marketpulse snapshots --currency CAD` keeps one currency's snapshots.
    Filters apply before the limit.
23. **JSON:** `marketpulse snapshots --json` prints a list of
    `{"date", "net_worth", "book", "contributions", "change", "currency"}`
    records; `change` is `null` where the table leaves it blank.
24. **CSV:** `marketpulse snapshots --csv > networth.csv` writes the same
    fields with a header row; a blank `change` is an empty cell.
25. **Count and latest:** `marketpulse snapshots --currency CAD --count` prints
    the number of matching snapshots. `marketpulse snapshots --latest --json`
    prints just the most recent matching snapshot as one object (`--latest`
    also works with the table and `--csv`). `--latest` exits 1 when nothing
    matches.
26. **Cached quotes:** `marketpulse quote --cached XEQT.TO FICT.TO` shows the
    last saved price for each symbol from the offline quote cache, with the
    time it was fetched and its age, without any network request. Symbols not
    in the cache are listed as warnings; the command exits 1 only when none of
    them were found.
27. **Quote JSON:** `marketpulse quote --json AAPL FICT.TO` prints one record
    per requested symbol, in order: `symbol`, `name`, `price`, `prev_close`,
    `change`, `change_pct`, `currency`, `stale`, `fetched_at` (local ISO time
    with offset), `source` and `error`. A symbol with no quote has `null` values
    and an `error` message. Live lookups make the same single batch request as
    `marketpulse quote`; add `--cached` (`marketpulse quote --cached --json FICT.TO`)
    to read the cache instead. Exits 1 when no symbol had a quote.
28. **Offline doctor:** `marketpulse doctor --offline` reports the market data
    check, and a configured fallback provider, as skipped instead of contacting
    them, so it works with no connection. A fallback that is selected but has
    no key is still reported as a failure, since that is a local setting.
29. **Doctor JSON:** `marketpulse doctor --json` prints
    `{"ok": true, "checks": [{"check": "database", "status": "ok", "detail": "…"}, …]}`.
    Status is `ok`, `fail`, `info` (informational, never a failure) or
    `skipped`; `ok` is false when any check failed. Composes with `--offline`.
    The human output lists the same checks in the same order as before.
30. **Strict doctor:** `marketpulse doctor --strict` exits with status 1 when
    any check failed, with or without `--json`, so scripts and CI can gate on
    it: `marketpulse doctor --offline --strict --json > doctor.json`.

## Privacy and exit codes

With privacy mode on (`marketpulse config set privacy true`), the
`snapshots` table masks net worth, book value and change. `--json` and
`--csv` stay unmasked, like the other machine-readable exports, so redirect
them to files you keep private. Quote prices are public market data and are
never masked.

| Command | Exit 0 | Exit 1 | Exit 2 |
| --- | --- | --- | --- |
| `snapshots` | Printed (an empty list is still 0) | `--latest` with no match | Usage error: conflicting output flags, `--count` with `--latest`/`--limit`/`--json`/`--csv`, `--latest` with `--limit`, `--since` after `--until`, an invalid date, a blank `--currency`, `--limit` below 1 |
| `quote --cached`, `quote --json` | At least one symbol found | No symbol found | No symbols given |
| `doctor` | Always, unless `--strict` | `--strict` and a check failed | Unknown option |
