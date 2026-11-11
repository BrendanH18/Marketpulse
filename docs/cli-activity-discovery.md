# Activity discovery

These ten additions (11–20 of the offline discovery batch) read the saved ledger
without fetching prices or recording snapshots. They combine with existing date,
type, note, count, summary, export and pagination options. Archived accounts and
transfers involving them remain hidden. JSON and CSV contain unmasked data.

11. `activity --symbols AAA --symbols BBB` includes either exact symbol. Values
    ignore case and surrounding whitespace. The list intersects with `--symbol`
    and exclusions when those options are also supplied.
12. `activity --exclude-account Birch --exclude-account Maple` excludes entries
    involving either account, including a transfer's source or destination.
13. `activity --account-type tfsa` matches the source account type.
14. `activity --institution 'Fictional North'` matches the source institution
    exactly, ignoring case and surrounding whitespace in the argument.
15. `activity --has-symbol` shows entries with symbols; `--no-symbol` shows entries
    without them, such as cash deposits.
16. `activity --target-account Birch` shows transfers to that destination. Account
    references accept IDs, case-insensitive names or a unique account type.
17. `activity --quarter 2 --year 2024` selects April through June 2024. Without
    `--year`, the quarter matches across all years.
18. `activity --weekday mon` selects Mondays. Accepted values are `mon`, `tue`,
    `wed`, `thu`, `fri`, `sat`, `sun`, ignoring case.
19. `activity --summary weekday --json` counts entries by the same weekday labels.
20. `activity --summary institution --csv` counts entries by the source account's
    saved institution. Empty institutions use an empty group value in JSON/CSV and appear as
    `(no institution)` in text output. Institution
    labels preserve their saved spelling and are grouped exactly as stored.

Summaries count all matching visible entries before pagination. As with existing
summaries, groups sort alphabetically by default; `--summary-sort count` sorts by
descending count, breaking ties by group. `--count` also counts before pagination.
Missing or archived account references fail explicitly. A combination whose
filters do not overlap returns no matches.

For example, on a fictional ledger:

```bash
marketpulse activity --symbols AAA --account-type tfsa --quarter 1 --year 2024 --json
marketpulse activity --target-account Birch --exclude-account Maple --count
marketpulse activity --institution 'Fictional North' --summary weekday --csv
```
