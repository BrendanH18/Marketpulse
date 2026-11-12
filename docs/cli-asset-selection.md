# Offline asset selection

`marketpulse asset list` reads configured metadata without fetching prices or
recording snapshots. These ten controls compose with existing kind, class,
currency, search, count, JSON, CSV and pagination options. Bounds are inclusive.

1. `--exclude-symbol SYMBOL` excludes an exact symbol, ignoring case and surrounding
   whitespace. Repeat for several symbols; blank exclusions are rejected.
2. `--min-rate NUMBER` selects fixed-income assets at or above the annual rate in
   percent. The value must be finite.
3. `--max-rate NUMBER` selects fixed-income assets at or below the annual rate.
   A minimum greater than the maximum is rejected.
4. `--starts-since YYYY-MM-DD` selects fixed-income assets starting on or after
   the date. Assets without a start date are excluded.
5. `--starts-until YYYY-MM-DD` selects fixed-income assets starting on or before
   the date. An inverted start-date range is rejected.
6. `--matures-since YYYY-MM-DD` selects fixed-income assets maturing on or after
   the date. Assets without a maturity date are excluded.
7. `--matures-until YYYY-MM-DD` selects fixed-income assets maturing on or before
   the date. An inverted maturity-date range is rejected.
8. `--compounding annual|semiannual|quarterly|monthly|simple` selects the saved
   fixed-income compounding schedule, ignoring case.
9. `--sort rate` orders fixed-income assets numerically by annual rate. Other
   assets and nonfinite rates remain last even with `--descending`.
10. `--sort maturity-date` orders dated fixed-income assets chronologically.
    Other assets and missing dates remain last even with `--descending`.

These filters inspect saved fields; they do not calculate accrual, change asset
metadata, or infer maturity from today's date. JSON and CSV contain raw values.
Counts and page totals use every matching asset before pagination.

```bash
marketpulse asset list --min-rate 3 --matures-until 2028-12-31 --sort maturity-date
marketpulse asset list --compounding monthly --exclude-symbol FIC-OLD --csv
marketpulse asset list --starts-since 2025-01-01 --json --page-info --limit 20
```
