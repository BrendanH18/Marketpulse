# Quote cache and diagnostics refinements

These ten additions under [#126](https://github.com/BrendanH18/Marketpulse/issues/126)
browse the saved offline quote cache and narrow `marketpulse doctor`. The cache
options read only the `quote_cache` table and never contact a quote provider.

1. `quote --cached --all` lists every cached symbol, A–Z, without naming any symbols.
2. `quote --cached --all --currency CAD --currency USD` keeps quotes in one or several currencies. Codes ignore case and surrounding whitespace.
3. `quote --cached --all --search maple` keeps quotes whose symbol or name contains the text, ignoring case.
4. `quote --cached --all --older-than 1d` and `--newer-than 30m` filter by cache age. Durations are a positive number and a unit: `s`, `m`, `h`, `d` or `w` (`90s`, `30m`, `2.5h`, `3d`, `1w`). `--older-than` keeps quotes cached at least that long ago; `--newer-than` keeps quotes cached less than that long ago.
5. `quote --cached --all --sort age` orders by `symbol`, `age` (newest first) or `change` (percent change, smallest first); add `--descending` to reverse.
6. `quote --cached --all --csv` prints the same fields as `--json` (`symbol,name,price,prev_close,change,change_pct,currency,stale,fetched_at,source,error`) as CSV.
7. `doctor --only ledger-checks --only backups` runs only the named checks (repeatable).
8. `doctor --exclude market-data` runs every check except the named ones (repeatable).
9. `doctor --failed-only` shows only failed checks, or "No failed checks."; JSON keeps the `ok` flag with the filtered `checks` list.
10. `doctor --summary` prints counts by status (`2 ok · 0 fail · 6 info · 1 skipped`); with `--json` it prints `{"ok": …, "summary": {"ok": n, "fail": n, "info": n, "skipped": n}}`.

## Quote cache rules

`--all`, `--currency`, `--search`, `--older-than`, `--newer-than`, `--sort`,
`--descending` and `--csv` require `--cached`, so live `quote` output is
unchanged. Symbols remain required unless `--all` is given, and `--all` cannot
be combined with symbols. Cached quotes are always marked stale.

The filters also apply to named symbols. Named symbols keep their given order
unless `--sort` is set; symbols missing from the cache are still reported (a
warning in the table, an `error` row in JSON and CSV) and are listed after
sorted rows. Quotes with an unknown cache time never match an age filter and
sort last by age. Filters intersect.

When nothing matches, the command exits 1: the table form prints an error,
JSON prints `[]` (or only error rows), and CSV keeps its header. `--descending`
requires `--sort`; `--json` and `--csv` are exclusive; blank `--search` or
`--currency` values, malformed or zero durations, and `--older-than` not
shorter than `--newer-than` fail with usage errors.

## Doctor rules

Check names are `version`, `config`, `database`, `backups`, `ledger`,
`ledger checks`, `market data`, `fallback quotes`, `theme`, `cli path`,
`swift` and `menu bar app` (the last two on macOS only). Names ignore case,
and `-` or `_` can stand for spaces. An unknown name fails with a usage error
listing the valid names.

A check that isn't selected doesn't run, so excluding `market data` makes no
network request. `--offline` still skips the network checks when they are
selected. `--only` and `--exclude` cannot be combined, and `--failed-only`
cannot be combined with `--summary`. The `ok` flag and `--strict` exit status
reflect the selected checks. Existing defaults are unchanged.
