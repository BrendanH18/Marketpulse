# Data exchange

[User guide](usage.md) · [One hundred improvements](cli-hundred-improvements.md) · [Issue #130](https://github.com/BrendanH18/Marketpulse/issues/130)

These ten additions under [#130](https://github.com/BrendanH18/Marketpulse/issues/130)
select what `marketpulse export` writes, summarise and gate `marketpulse
import`, and let `marketpulse backfill` be previewed and reported as JSON. The
examples use fictional accounts.

31. `export -a "Maple Cash"` writes only the rows recorded in that account (name, id or unique type); repeat `-a` for several. Archived accounts can be named, since the full export has always included them. A transfer is the row of the account it left; an unknown account fails with `No account '…'.`
32. `export -s xeqt.to` keeps rows for that exact symbol, ignoring case and spaces, and `--type BUY` keeps one transaction type (any case); repeat either for several, e.g. `export --type buy --type sell`.
33. `export --since 2025-01-01 --until 2025-06-30` keeps rows dated inside the window (inclusive; dates accept the same forms as elsewhere, such as `yesterday` or `-30d`).
34. `export --columns symbol,date,amount` writes only those columns, in that order, with the header. The columns are `date`, `account`, `type`, `symbol`, `quantity`, `price`, `amount`, `fees`, `currency`, `note`, `ratio` and `target_account`; an unknown or repeated one is a usage error. A file missing some columns may not re-import.
35. `export --count` prints only the number of matching rows, e.g. `export --count -a "Maple Cash" --since 2025-02-01` prints `3`. It takes no PATH, `--jsonl` or `--columns`.
36. `export --jsonl` writes one JSON object per row (JSON Lines) instead of CSV, with raw values: numbers as numbers (`"quantity": 10.0`, `0.0` when unset) and `"target_account": null` for rows that aren't transfers, e.g. `{"date": "2025-01-03", "account": "Maple Cash", "type": "BUY", "symbol": "XEQT.TO", "quantity": 50.0, …}`. It combines with the filters, `--columns` and a PATH.
37. `import --summary account` adds a table counting the rows imported by account (or `type`, `symbol` or `month`). With `--dry-run` it counts the rows that would be imported (`Would import`), read back from the same real import against a temporary copy of the ledger that every preview runs, so the preview's counts are the import's. With `--json`, the report gains `"summary": [{"group": "Maple Cash", "count": 2}, {"group": "Pine RRSP", "count": 1}]`; without `--summary` the JSON is unchanged.
38. `import --exit-code` exits 1 when any row was skipped, after reporting as usual (table or `--json`), so a script can stop on a file that didn't read cleanly. With `--dry-run` nothing is written either way; without it, the rows that did read are still imported.
39. `backfill --dry-run` rebuilds the daily history against a temporary copy of the ledger with the same price and FX history, writes no snapshots, and reports `Would rebuild 312 daily snapshots (2025-01-02 to 2025-11-10): 4 new, 308 replacing existing ones. Nothing was written.` It refuses exactly when a real backfill would (for example while an archived account still holds something).
40. `backfill --json` reports the snapshots written as `{"dry_run": false, "snapshots": 312, "new": 4, "replaced": 308, "first": "2025-01-02", "last": "2025-11-10", "currency": "CAD"}`; with `--dry-run`, those that would be. `new` counts days with no snapshot before; `replaced` counts days whose snapshot is rewritten.

## Rules

- Export filters combine (all must match) and keep the full export's order. Without any of the new options, `export` and `export PATH` call the same code as before.
- `--since` must be on or before `--until`; a blank `--symbol` is a usage error.
- `import --summary` and `--exit-code` combine with `--dry-run`, `--json`, `-a`, `--profile` and `--no-create-accounts`.
- `backfill --dry-run` and `--json` fetch the same historical closes as a real backfill, through the same endpoint; nothing else goes over the network.

## What stays the same

`marketpulse export`, `export PATH`, `import FILE`, `import --dry-run FILE`,
`import --json FILE` and `backfill` print exactly what they printed before. An
import preview still runs the real import against a temporary copy of the
ledger, so preview equals import, and a real import still takes its
`import` backup first. A filtered CSV export re-imports like the full one: rows
already in the ledger are recognised as duplicates.
