# Snapshot report refinements

These ten additions under [#124](https://github.com/BrendanH18/Marketpulse/issues/124)
read saved snapshots offline. They never fetch quotes, record snapshots, or
recalculate portfolio values.

1. `snapshots --quarter 2024-Q2` selects a calendar quarter (`YYYY-Q1` through `YYYY-Q4`).
2. `snapshots --weekday mon --weekday fri` selects one or several weekdays. Names ignore case.
3. `snapshots --on 2024-01-01 --on 2024-04-01` selects specific recorded dates. Repeated dates do not duplicate rows.
4. `snapshots --exclude-currency USD --exclude-currency EUR` excludes recorded currencies, ignoring case and surrounding whitespace.
5. `snapshots --known-change-only` keeps snapshots with a comparable prior recorded snapshot, including zero changes.
6. `snapshots --earliest --since 2024-01-01` inspects the earliest matching snapshot. Like `--latest`, JSON returns one object, CSV one data row, and no match exits 1.
7. `snapshots --summary year` counts matching snapshots per calendar year.
8. `snapshots --summary month` counts matching snapshots per calendar month.
9. `snapshots --summary quarter` counts matching snapshots per calendar quarter.
10. `snapshots --summary currency` counts matching snapshots per recorded currency.

Selections intersect with existing filters before counting, sorting, or paging.
All change comparisons retain their previous recorded baseline, even if that
baseline is excluded by a filter. Calendar filters that do not intersect
produce no matches. No currency conversion is performed.

Summaries support human tables, `--json` (`group`/`count` objects), and `--csv`
(`group,count`). Groups sort alphabetically; empty JSON summaries return `[]`
and empty CSV summaries retain the header. Summaries count records, never sum
money. They cannot combine with `--count`, `--latest`, `--earliest`, `--limit`,
`--sort`, `--descending`, `--offset`, or `--page-info`.

`--earliest` cannot combine with `--latest`, counting, ordering, or pagination.
`--known-change-only` cannot combine with `--unknown-change-only`. Invalid dates,
quarters, weekdays, and blank currency exclusions fail with usage errors.
Human monetary output retains privacy masking; JSON and CSV retain the
existing explicit raw-export behavior. Existing defaults are unchanged.
