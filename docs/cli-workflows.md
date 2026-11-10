# Offline CLI workflows

[User guide](usage.md) · [Data and backups](data.md)

Find recorded activity, inspect metadata, and prepare scripts without fetching
market prices. These 30 additions are tracked in
[#104](https://github.com/BrendanH18/Marketpulse/issues/104).
Examples use fictional account names and symbols; transaction and alert IDs come
from your own listings.

## Find and check transactions

| # | Improvement | Example |
| --- | --- | --- |
| 1 | Inclusive start date | `marketpulse activity --since 2024-01-01` |
| 2 | Inclusive end date | `marketpulse activity --until 2024-12-31` |
| 3 | One or more transaction types | `marketpulse activity --type BUY --type SELL` |
| 4 | Search symbols, notes, and account names, ignoring case | `marketpulse activity --search winter` |
| 5 | Recorded currency filter | `marketpulse activity --currency CAD` |
| 6 | Oldest entries first | `marketpulse activity --oldest-first` |
| 7 | Skip matching entries and choose a page size | `marketpulse activity --offset 40 --limit 20` |
| 8 | Raw transaction JSON, including account names and revisions | `marketpulse activity --all --json` |
| 9 | Inspect one complete transaction, including its note and edit revision | `marketpulse txn show 12 --json` |
| 10 | Check existing ledger consistency offline, with exit status | `marketpulse txn check --json` |

Filters compose with `--account` and `--symbol` and run before ordering and
paging. `--since` and `--until` accept the same relative dates as transaction
entry, such as `yesterday`; reversed date ranges are refused. Type values ignore
case and repeated types match any of those types. Currency matching ignores case
but uses the recorded currency; no conversion is performed. Newest first remains
the default, with transaction ID breaking same-date ties. `--limit` must be
positive, `--offset` nonnegative. `--all` removes the limit but still applies the
offset. Pages reflect the ledger at the time each command runs.

Activity and `txn show` hide archived accounts and transfers touching an
archived account. They never create a missing account. `txn show ID` without
`--json` shows a field/value table; its amounts and quantities follow privacy
mode. The JSON `revision` can be passed to `txn edit ID --revision REVISION`
or `txn delete ID --revision REVISION` to refuse an edit if the record has
changed or the ledger has been restored since you read it.

`txn check` runs the existing ledger replay without repairing or repricing
anything. Exit 0 means no ledger issues; exit 1 means issues were found. JSON is
`{"ok": true, "issues": []}` or an issues array containing `txn_id`, `date`,
`message`, `code`, and `args`. Issues involving hidden accounts are anonymized
but still cause exit 1. This checks ledger consistency, not the completeness of
your records or a tax filing.

## Browse account and asset metadata

| # | Improvement | Example |
| --- | --- | --- |
| 11 | Account inventory without quotes or a valuation snapshot | `marketpulse accounts list --offline` |
| 12 | Offline account metadata JSON | `marketpulse accounts list --json` |
| 13 | Account type filter | `marketpulse accounts list --offline --type TFSA` |
| 14 | Exact institution match, ignoring case | `marketpulse accounts list --offline --institution "Example Credit"` |
| 15 | Account name search, ignoring case | `marketpulse accounts list --offline --search maple` |
| 16 | Asset metadata JSON | `marketpulse asset list --json` |
| 17 | Asset kind filter | `marketpulse asset list --kind fixed_income` |
| 18 | Configured asset class filter | `marketpulse asset list --class real_estate` |
| 19 | Configured asset currency filter | `marketpulse asset list --currency CAD` |
| 20 | Asset symbol/name search, ignoring case | `marketpulse asset list --search cottage` |

All inventory filters compose. `accounts list` still prices accounts by default;
`--offline` shows only metadata columns and `--json` always reads metadata
without pricing, even if `--offline` is omitted. Archived accounts appear only
with the existing explicit `--archived` option. Account JSON contains `id`,
`name`, `type`, `currency`, `institution`, `track_cash`, `archived`, and
`created_at`.

Asset listings read configured definitions, including market-symbol overrides;
they do not fetch quotes or infer missing classifications. `--class` matches an
explicit class, and `--currency` matches the configured currency. Asset JSON
contains `symbol`, `kind`, `name`, `asset_class`, `currency`, `rate`,
`compounding`, `start_date`, and `maturity_date`. Kind and class choices ignore
case; `--help` lists the accepted values. Empty JSON inventories return `[]`.

## Watchlists, alerts, and reports

| # | Improvement | Example |
| --- | --- | --- |
| 21 | Saved watchlist order without fetching prices, optionally as a JSON symbol array | `marketpulse watch list --offline` or `marketpulse watch list --json` |
| 22 | Move a watched symbol to a one-based position | `marketpulse watch move XEQT.TO --to 1` |
| 23 | Alert symbol filter | `marketpulse alerts list --symbol AAPL` |
| 24 | Alert state filter | `marketpulse alerts list --state paused` |
| 25 | Pause an alert | `marketpulse alerts pause 3` |
| 26 | Resume without clearing trigger history | `marketpulse alerts resume 3` |
| 27 | Activate and explicitly clear trigger history | `marketpulse alerts rearm 3` |
| 28 | Offline alert metadata JSON | `marketpulse alerts list --json` |
| 29 | Backup inventory JSON with absolute paths, reasons, byte sizes, and timestamps | `marketpulse backup list --json` |
| 30 | Complete CSV preview/import reports as JSON | `marketpulse import fictional.csv --dry-run --json` |

`watch move` requires an existing symbol and a position from 1 to the watchlist's
length; it never adds or removes symbols. `watch list` keeps its priced default.
Offline listings and alert controls do not fetch prices or send notifications.

Alert state filters compose with the symbol filter. States are `paused` when
inactive, `triggered` when active with trigger history, and `armed` otherwise.
Pausing preserves history. Resuming preserves it too, so a condition that is
still true does not immediately notify again. Rearming clears it deliberately:
the next matching fresh price can notify again. Invalid legacy alerts can be
inspected or paused, but cannot be resumed or rearmed until replaced with a
valid alert. Alert JSON includes stored fields plus `state`; a non-finite legacy
threshold is represented as `null`.

Import JSON contains the full existing import result: counts (`added`,
`duplicates`), `accounts_created`, `backup` (path or `null`), `profile`,
`profile_label`, `fingerprint`, `issues`, `duplicate_rows`, `skipped`, and
`dry_run`. Neither issues nor duplicates are truncated. The same engine handles
preview and import; `--dry-run` changes no accounts or ledger entries. Files
without account names need an existing account for preview or JSON reporting;
create one first and use `--account` when needed. Fatal errors still use stderr
and a nonzero exit status; valid reports may contain skipped rows and exit 0,
as human import reports do.

Backup JSON is a newest-first array of `file`, `path`, `reason`, `size_bytes`,
and `taken_at` (ISO local timestamp, or `null` when not in the filename).
Listing backups does not restore them.

All new JSON commands write plain JSON to stdout and contain **unmasked data**,
even with privacy mode enabled. Notes, account names, amounts and paths can be
personal. Protect redirected output like a CSV export. These commands do not
change `status --json` or the native desktop bridge.
