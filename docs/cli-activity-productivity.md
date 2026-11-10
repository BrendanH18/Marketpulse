# Activity productivity tools

These ten additions to `marketpulse activity` run offline against the saved ledger.
Filters intersect, reports omit entries involving archived accounts, and summaries
count matching transactions before pagination. Nothing here changes financial
calculations. JSON and CSV exports contain raw values, including in privacy mode.

1. **Exclude transaction types.** Repeat `--exclude-type` to omit categories:
   `marketpulse activity --exclude-type BUY --exclude-type SELL`.
2. **Exclude symbols.** Repeat `--exclude-symbol` to omit tickers, ignoring case:
   `marketpulse activity --exclude-symbol AAPL --exclude-symbol XEQT.TO`.
3. **Search notes only.** `marketpulse activity --note winter` matches notes
   case-insensitively without matching the same text in an account name or symbol.
4. **Filter a calendar year.** `marketpulse activity --year 2024 --count` counts
   that year's visible entries. Years must be between 1 and 9999.
5. **Filter one date.** `marketpulse activity --on 2024-01-02` selects that day.
   It intersects with `--since`, `--until` and `--year`; incompatible filters
   produce no matches.
6. **Summarize by year.** `marketpulse activity --summary year --json` returns
   calendar-year counts, with years ordered ascending by default.
7. **Summarize by day.** `marketpulse activity --summary day` shows daily counts.
8. **Export grouped counts as CSV.**
   `marketpulse activity --summary account --csv > activity-accounts.csv` uses
   `group,count,account` columns for account groups; other groups use `group,count`.
   Empty reports retain headers. Account groups use saved account IDs, so equal
   account names remain distinct. Standard CSV quoting preserves commas and quotes.
9. **Rank groups by frequency.**
   `marketpulse activity --summary symbol --summary-sort count --json` sorts by
   descending count, then ascending group for ties. `--summary-sort group` is the
   default. Summary sorting applies to terminal, JSON and CSV reports.
10. **Read pagination metadata.**
    `marketpulse activity --year 2024 --limit 20 --json --page-info` returns an
    object with `total`, `offset`, `limit`, `returned`, `next_offset` and `items`.
    `total` counts all filtered visible entries; `items` contains the current page.
    Pass the non-null `next_offset` back as `--offset` to continue. `--all` uses
    `limit: null`; the last page uses `next_offset: null`. Without `--page-info`,
    existing `--json` output remains an array. The envelope requires transaction
    JSON and cannot be combined with a summary or count.

Examples use fictional dates and symbols. For manual experiments, set both
`MARKETPULSE_DATA` and `MARKETPULSE_CONFIG` to scratch paths before invoking a command.
