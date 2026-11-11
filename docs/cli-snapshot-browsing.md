# Snapshot history browsing

`marketpulse snapshots` reads saved snapshots offline without changing them or
fetching quotes. These ten additions compose with existing date and currency
filters. JSON and CSV contain raw values; human output respects privacy mode.

1. `--year 2024` selects a calendar year (1–9999).
2. `--month 2024-02` selects a validated `YYYY-MM` calendar month. When combined
   with `--year`, both must refer to the same year.
3. `--sort date|net-worth|book|contributions|change` orders matching snapshots.
   Dates break ties. Unknown changes sort last in both directions.
4. `--descending` reverses the selected order, defaulting to date order.
5. `--offset N` skips the first N ordered matches (zero is valid).
6. `--page-info --json` returns an object with `rows`, the matching `total`
   before pagination, `offset`, and `limit` (`null` when unlimited).
7. `--min-net-worth N` includes saved net worth at or above a finite number.
8. `--max-net-worth N` includes saved net worth at or below a finite number.
   Minimum must not exceed maximum. Values remain in their recorded currency;
   combine with `--currency` for comparisons within one currency.
9. `--changed-only` includes known, nonzero changes.
10. `--unchanged-only` includes known zero changes. The two change filters are
    mutually exclusive; neither includes an unknown change.

A change always compares with the immediately preceding recorded snapshot in
full history, even when that predecessor is filtered out. It is unknown for the
first snapshot and whenever the recorded currency changes. Nothing is converted.

For compatibility, `--limit N` alone still selects the most recent N matches,
oldest first. Adding **any** of `--sort`, `--descending`, `--offset` (even zero),
or `--page-info` enables forward pagination: order all matches, skip the offset,
then keep the first N if limited. `--latest` cannot combine with ordering or
pagination. `--count` accepts filters, but rejects output, ordering, pagination,
and `--latest` options. Existing JSON array and `--latest` object output remain
unchanged unless `--page-info` is requested.

```bash
marketpulse snapshots --year 2024 --currency CAD --changed-only --count
marketpulse snapshots --month 2024-02 --sort net-worth --descending --limit 5 --json
marketpulse snapshots --sort date --offset 20 --limit 10 --page-info --json
marketpulse snapshots --currency CAD --min-net-worth 1000 --max-net-worth 5000 --csv
```
