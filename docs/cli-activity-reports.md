# Offline activity reports

[Offline CLI workflows](cli-workflows.md) · [User guide](usage.md)

These ten additions to `activity` are part of
[#106](https://github.com/BrendanH18/Marketpulse/issues/106). All examples use
fictional records. They read the ledger without fetching quotes, creating an
account, recording a snapshot, or changing financial calculations.

| # | Improvement | Example |
| --- | --- | --- |
| 1 | Filtered activity CSV on stdout | `marketpulse activity --all --csv > activity.csv` |
| 2 | Count matching activity before pagination | `marketpulse activity --count --since 2024-01-01` |
| 3 | Counts by transaction type | `marketpulse activity --summary type` |
| 4 | Counts by source account | `marketpulse activity --summary account --json` |
| 5 | Counts by recorded currency | `marketpulse activity --summary currency` |
| 6 | Counts by calendar month | `marketpulse activity --summary month` |
| 7 | Counts by symbol | `marketpulse activity --summary symbol` |
| 8 | Filter by note presence or absence | `marketpulse activity --has-note` or `marketpulse activity --no-note` |
| 9 | Inclusive minimum transaction ID | `marketpulse activity --min-id 100 --all --json` |
| 10 | Inclusive maximum transaction ID | `marketpulse activity --max-id 200 --all --json` |

All modes use the existing account, symbol, date, type, text, and currency filters
and hide archived accounts and transfers touching an archived account. ID
filters compose and must be positive; reversed ID ranges are refused. Note
presence means the note contains at least one non-whitespace character.

CSV uses the same ordering and pagination as ordinary activity and JSON:
newest first, default limit 40, `--oldest-first`, `--offset`, and `--all`.
Its header contains every transaction field followed by `account`,
`target_account`, and `revision`, matching activity JSON records. Missing
optional values are empty CSV cells; notes are quoted to preserve commas,
quotes, and line breaks. No matches produces the header alone. This is an
activity report; use `marketpulse export` for a ledger CSV intended for import.
CSV is raw and unmasked even in privacy mode, like existing JSON output.

`--count` writes just an integer and newline. `--summary` counts entries in
**all matching rows before pagination**, ignoring limit, offset, and order.
It never sums money or quantities. A transfer counts once under its source
account; currency means the recorded currency; month means `YYYY-MM` from the
recorded date. Symbol-less entries form an empty-string group, shown as
`(no symbol)` in the human table. Summary rows sort lexically by group key.
Account groups use the account ID as the key so distinct accounts stay distinct.

Summary JSON is an array of `{"group": "BUY", "count": 2}` objects. Account
summaries additionally include `account`, with the group containing the source
account ID as a string. Empty summaries return `[]`. Human summaries display a
count table and contain no monetary amounts. Count and summary output do not
run a ledger consistency check; use `marketpulse txn check` for that.

Choose one of CSV, count, or summary. `--json` can accompany summary and cannot
accompany CSV or count. Omitting these report options preserves ordinary
activity behavior and the existing JSON array contract.
