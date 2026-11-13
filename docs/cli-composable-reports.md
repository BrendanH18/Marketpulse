# Composable offline reports

[User guide](usage.md) · [Issue #136](https://github.com/BrendanH18/Marketpulse/issues/136)

`marketpulse report SOURCE` gives saved portfolio data, settings and command
metadata a common interface for filtering, selecting columns and exporting.
It reads local data without requesting quotes, recording snapshots or changing
financial calculations. Existing commands keep their existing behavior.

This batch provides **25 datasets × 20 report operations = 500 dataset/operation
capabilities**. These are the same 20 operations available on each distinct
dataset, not 500 unrelated features. Some operations were already available on
individual commands; this interface makes their spelling and composition
consistent across all sources.

An additional [40 shared query and output operations](cli-report-improvements.md)
add 1,000 more dataset/operation combinations, including numeric filters, typed
membership, output transformations and row windows. The inventory below records
the original batch.

[Twenty-five more datasets and 50 derived-field functions](cli-report-derived-datasets.md)
bring the interface to 50 datasets. Every operation described here also works on
the newer datasets; `marketpulse report sources` lists them all.

## Start with the schema

Run `marketpulse report SOURCE --describe` to see the source's ordered field
names before choosing filters or columns. With no options, the report emits a
JSON array. All report formats contain raw, unmasked data for scripts, including
when privacy mode is enabled. Configuration sources always redact API keys.

Use fictional data for examples. Before a command that opens the tracker, point
both environment overrides at a scratch directory as described in the
[data guide](data.md):

```bash
export MARKETPULSE_DATA=/tmp/marketpulse-report-example
export MARKETPULSE_CONFIG=/tmp/marketpulse-report-example/config.toml
marketpulse report accounts --describe
marketpulse report accounts --format jsonl
marketpulse report snapshots --offset 10 --limit 5 --page-info
marketpulse report config-keys --format markdown
```

`--describe` and the shared `--output PATH` file destination are additional
conveniences, excluded from the 500-capability count. Output files are written
atomically and an existing destination is never overwritten. Atomic publication
requires a filesystem supporting hard links (for example, NTFS, APFS or ext4).
Unsupported filesystems return an error instead of exposing a partial file.
On POSIX systems, exported files retain owner-only permissions because they
can contain financial records. A failed temporary-file cleanup does not mask
the report result or an earlier error.

## Twenty operations on every source

Every operation below is supported on each source in the following table.
Field-taking options use names from that source's `--describe` output. Options
may be combined unless a validation error explains an incompatible combination.

| Operation | Option | Behavior |
| --- | --- | --- |
| 1 | `--fields FIELD,FIELD` | Select columns and their output order. |
| 2 | `--omit FIELD,FIELD` | Exclude columns from the output. |
| 3 | `--where FIELD=VALUE` | Keep exact, case-sensitive string matches. Repeat to require every condition. |
| 4 | `--not FIELD=VALUE` | Remove exact, case-sensitive string matches. Repeat for several exclusions. |
| 5 | `--contains FIELD=TEXT` | Keep values containing text, ignoring case. |
| 6 | `--prefix FIELD=TEXT` | Keep values beginning with text, ignoring case. |
| 7 | `--suffix FIELD=TEXT` | Keep values ending with text, ignoring case. |
| 8 | `--present FIELD` | Keep values other than null or an empty string. Zero and false are present. |
| 9 | `--missing FIELD` | Keep null or empty-string values. |
| 10 | `--sort FIELD` | Sort by a field; repeat for ordered sort keys. |
| 11 | `--descending` | Reverse the requested sort direction; requires `--sort`. |
| 12 | `--offset N` | Skip the first N matching, ordered rows. |
| 13 | `--limit N` | Show at most N rows after the offset. |
| 14 | `--unique FIELD` | Keep the first row for each field value; repeat to form a composite key. |
| 15 | `--count` | Print the matching row count before pagination. |
| 16 | `--format jsonl` | Emit one JSON object per line. |
| 17 | `--format csv` | Emit comma-separated columns with a header. |
| 18 | `--format tsv` | Emit tab-separated columns with a header. |
| 19 | `--format markdown` | Emit a Markdown table. |
| 20 | `--page-info` | Wrap default JSON output with pagination metadata. |

The original operation order is filtering, deduplication, sorting, counting or pagination,
column selection, then serialization. When using the added operations, see the
[extended processing order](cli-report-improvements.md#processing-and-composition). Thus `--unique` keeps the first matching
row in source order before sorting. `--count` counts deduplicated matches before
pagination. Missing sort values remain last in either direction. Unknown field
names and invalid option values are rejected before loading source data.

`--fields` and `--omit` are mutually exclusive and must leave at least one column.
`--count` rejects pagination, projection and alternate formats; `--page-info`
requires JSON row output. `--describe` accepts only a source and optional output
path. Empty CSV, TSV and Markdown results retain their headers. JSON Lines
returns empty output for no rows.

Filters compare strings directly; numbers, booleans, arrays and objects use
JSON text (for example `true` or `10`), while null uses an empty string. Sorting
orders numbers numerically before text and nested JSON, with missing values
last. Markdown escapes pipes, newlines and HTML delimiters; CSV and TSV quote
special characters and serialize nested values as JSON. These are raw script
exports, so spreadsheet consumers should treat cells as data.

Filters operate on saved field values; they do not recompute financial values
or convert currencies. Repeated conditions combine with AND. Row counts never
sum monetary amounts across currencies.

## Capability inventory

The source row identifies a contiguous block of 20 capabilities. Within that
block, operation 1 through operation 20 correspond exactly to the numbered
operations above. For example, capability 1 is account column selection,
capability 20 is account pagination metadata, capability 21 is asset column
selection, and capability 500 is compounding pagination metadata.

| Capabilities | Source | Dataset |
| --- | --- | --- |
| 1–20 | `accounts` | Active account metadata. |
| 21–40 | `assets` | Saved asset definitions. |
| 41–60 | `transactions` | Ledger transaction records for active accounts. |
| 61–80 | `positions` | Open ledger positions without market prices. |
| 81–100 | `cash` | Ledger cash balances without currency conversion. |
| 101–120 | `snapshots` | Previously recorded net-worth snapshots. |
| 121–140 | `cached-quotes` | Quotes already saved in the offline cache. |
| 141–160 | `alerts` | Saved alert definitions. |
| 161–180 | `watchlist` | Saved watched symbols. |
| 181–200 | `targets` | Saved allocation targets. |
| 201–220 | `realized` | Ledger-derived realized events. |
| 221–240 | `payouts` | Ledger-derived income events. |
| 241–260 | `backups` | Local backup inventory metadata. |
| 261–280 | `config` | Current settings with secrets redacted. |
| 281–300 | `config-defaults` | Default settings with secrets redacted. |
| 301–320 | `config-diff` | Settings differing from their defaults, with secrets redacted. |
| 321–340 | `config-keys` | Available configuration keys. |
| 341–360 | `themes` | Embedded theme metadata. |
| 361–380 | `commands` | Registered CLI command metadata. |
| 381–400 | `providers` | Provider status without a quote request. |
| 401–420 | `account-types` | Supported account types. |
| 421–440 | `transaction-types` | Supported transaction types. |
| 441–460 | `asset-kinds` | Supported asset kinds. |
| 461–480 | `asset-classes` | Supported asset classes. |
| 481–500 | `compounding` | Supported compounding schedules. |

Portfolio transaction, position, cash, realized and payout sources exclude
archived accounts. Snapshot and backup sources describe stored history and files;
they do not rebuild those records. There is no live quote lookup, telemetry,
provider test, or setting mutation in the query pipeline.

Sources that need saved data use the same tracker startup as existing CLI
commands. Startup may create the database, update metadata, run schema or legacy
migrations, and create or prune automatic backups. These reports are offline
queries, not a filesystem read-only inspection mode; they require the normal
writable data directory. The no-write adapter tests begin after tracker startup.
`--describe` and catalog sources other than `providers` do not open the tracker.
