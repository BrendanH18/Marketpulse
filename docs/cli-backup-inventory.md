# Backup inventory

These ten additions under [#126](https://github.com/BrendanH18/Marketpulse/issues/126)
browse and check backups offline. Listing reads file names and sizes only; it
never opens, changes, or deletes a backup. Examples use fictional dates and paths.

1. `backup list --count --reason manual` prints the number of matching backups.
2. `backup list --csv --since 2024-01-01` prints matching backups as CSV to stdout
   (`file,path,reason,size_bytes,taken_at`). Empty results keep the header.
3. `backup list --json --page-info --limit 10 --offset 10` wraps the JSON rows in
   `{"total", "offset", "limit", "returned", "next_offset", "items"}`; `next_offset`
   is null on the last page.
4. `backup list --reason manual --reason import --exclude-reason daily` repeats `--reason`
   to include several reasons and `--exclude-reason` to leave reasons out, ignoring case
   and surrounding whitespace. A single `--reason` works as before.
5. `backup list --min-size 512 --max-size 2048` keeps backups whose file size is within
   the inclusive bounds, in KB (1 KB = 1024 bytes, the unit the table shows). Fractions
   such as `--min-size 1.5` are allowed.
6. `backup list --sort size --descending` orders matching backups by `date`, `size`,
   `name`, or `reason`, ascending unless `--descending` is given. `--descending` alone
   orders by date, newest first (the default order).
7. `backup list --year 2024 --month 2024-01` and `backup list --on 2024-01-02 --on 2024-03-01`
   select calendar years, months (`YYYY-MM`) and specific dates. Repeated dates do not
   duplicate rows.
8. `backup list --latest --reason manual --json` and `backup list --earliest --json`
   inspect the newest or oldest matching backup. JSON returns one object, CSV one data
   row, and no match exits 1.
9. `backup list --summary reason`, `--summary year` and `--summary month` count matching
   backups per group.
10. `backup verify fictional-a.db fictional-b.db` verifies several files in one run, and
    `backup verify --latest` verifies the backup `backup restore --latest` would restore.

Filters (reasons, search, dates, sizes, calendar selections) intersect and apply
before summaries, counting, sorting, single-record selection, and paging. Dates
come from the timestamp in the backup's filename, not the file modification
time. Backups without a recognized timestamp never match date or calendar filters;
in year and month summaries they count under `unknown`. Sorting ties break on
the filename.

Summaries support human tables, `--json` (`group`/`count` objects) and `--csv`
(`group,count`). Groups sort alphabetically; empty JSON summaries return `[]` and
empty CSV summaries keep the header. They cannot combine with `--count`,
`--latest`, `--earliest`, `--limit`, `--offset`, `--sort`, `--descending`,
`--oldest-first`, or `--page-info`.

`--count` cannot combine with `--json`, `--csv`, ordering, or pagination options.
`--latest` and `--earliest` exclude each other and cannot combine with counting,
ordering, or pagination options. `--oldest-first` cannot combine with `--sort` or
`--descending`. `--page-info` requires `--json`, and `--json` and `--csv` exclude
each other. Blank reasons, negative or non-finite sizes, a minimum size above the
maximum, invalid months or dates, and a `--year` that disagrees with `--month` all
fail with usage errors.

`backup verify` with one path or `--latest` keeps the existing JSON object. With
several paths it prints a JSON array in the order given, and human output names
each failing file. The command exits 1 if any file fails verification. A missing
file stops before anything is verified. `--latest` skips `pre-restore` backups and
any daily backup taken while the command opened the ledger, exactly as
`backup restore --latest` does, and exits 1 when there is none. Give paths or
`--latest`, not both. Verification never replaces the ledger or modifies a
source. Existing defaults are unchanged, and no command fetches prices or sends
notifications.
