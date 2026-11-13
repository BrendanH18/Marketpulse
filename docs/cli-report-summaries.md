# One thousand offline summary capabilities

[User guide](usage.md) · [Saved report sources](cli-composable-reports.md) ·
[Issue #140](https://github.com/BrendanH18/Marketpulse/issues/140)

`marketpulse summarize SOURCE` adds **40 summary operations on each of 25 saved
datasets = 1,000 new dataset/operation combinations**. These are shared operations
across datasets; the count does not mean 1,000 unrelated features. The existing
`report` command continues to return individual rows. The operations also apply
to the [25 datasets added later](cli-report-derived-datasets.md), and `--derive`
fields can be grouped and summarized like source fields.

Summaries use the same offline source adapters as `report`. They do not request
quotes or historical prices, record snapshots, or change the ledger. Configuration
API keys stay redacted. Archived accounts and their activity remain hidden in
portfolio sources. Like `report`, script output otherwise contains raw values,
including when display privacy mode is enabled.

## Query and export

```bash
# Count saved accounts by account type.
marketpulse summarize accounts --group-by type --metric accounts=count

# Inspect quantities recorded in fictional CAD buy rows by symbol.
marketpulse summarize transactions --where type=BUY --where currency=CAD \
  --group-by symbol --metric rows=count --metric quantity=number-sum:quantity

# Compare quote freshness using only the saved cache.
marketpulse summarize cached-quotes --group-by stale --metric quotes=count

# Find the most frequent currency among saved accounts.
marketpulse summarize accounts --metric currency=mode:currency

# Export the largest groups first, with numeric sorting of the count.
marketpulse summarize transactions --group-by type --metric rows=count \
  --sort rows --descending --limit 5 --format csv --output activity-summary.csv

# Discover source fields and the full operation catalog without opening data.
marketpulse summarize transactions --describe
```

Repeat `--metric NAME=OP:FIELD` to add summary columns in order. `count` uses
`NAME=count` without a field. Other operations require a source or `--derive` field. Names must
be ASCII identifiers (`[A-Za-z_][A-Za-z0-9_]*`), distinct from other metric names
and grouping fields. Repeat `--group-by FIELD` for composite groups. Grouping
columns appear first, followed by metric columns. Ungrouped queries produce one
summary row, including for an empty source; grouped empty sources produce no rows.

`--where FIELD=TEXT` compares the source's report text exactly; repeat it for AND.
All 20 [advanced report filters](cli-report-improvements.md#new-operations), from
`--ieq` through `--glob`, are also available and combine with AND before grouping.
Field names always refer to the original source schema in filters and metrics,
or to a field added earlier with [`--derive`](cli-report-derived-datasets.md#derived-fields).

Groups retain their first-encountered order unless sorted. Repeat `--sort FIELD`
for tie breakers on output columns, with optional `--descending`. Numeric summary
results sort numerically, including the decimal strings described below. Missing
values stay last in both directions. `--offset N` and `--limit N` paginate groups
after sorting. `--page-info` wraps JSON output in source, total group count,
offset, limit and rows; it cannot be combined with other export formats.

`--format` supports `json` (default), `jsonl`, `csv`, `tsv` and `markdown` using
the existing report serializers. An empty CSV/TSV/Markdown result retains its
headers. `--output PATH` publishes a complete UTF-8 file atomically and refuses
to overwrite existing files or symlinks. Invalid fields, operations, aliases and
option combinations fail before loading the source.

## Operations

All operations except `count` take a field. “Missing” means null or the empty
string; “empty” also includes empty arrays and objects. Zero and false are
present and nonempty. `first`, `last`, `mode`, `values` and distinct operations
retain native JSON types. Distinctness is typed recursively: false differs from
0, including inside arrays and objects, while numeric 1 and 1.0 are equal. A
numeric string remains distinct from its numeric equivalent except in
`number-distinct`, which compares parsed numbers. Mode ties choose the value
encountered first.

| No. | Operation | Result |
| --- | --- | --- |
| 1 | `count` | Number of rows. |
| 2 | `present` | Number of nonmissing values. |
| 3 | `missing` | Number of null or empty-string values. |
| 4 | `empty` | Number of null, empty-string, empty-array or empty-object values. |
| 5 | `nonempty` | Number of values that are not empty. |
| 6 | `distinct` | Number of distinct typed values, including missing values. |
| 7 | `duplicates` | Number of values beyond their first occurrence. |
| 8 | `first` | First value, including null. |
| 9 | `last` | Last value, including null. |
| 10 | `first-present` | First nonmissing value. |
| 11 | `last-present` | Last nonmissing value. |
| 12 | `mode` | Most frequent typed value. |
| 13 | `mode-count` | Frequency of the most frequent typed value. |
| 14 | `values` | All field values in source order. |
| 15 | `distinct-values` | Distinct typed values in first-encountered order. |
| 16 | `number-count` | Number of finite numeric values. |
| 17 | `number-distinct` | Number of distinct parsed finite numbers. |
| 18 | `number-sum` | Sum of finite numbers. |
| 19 | `number-min` | Smallest finite number. |
| 20 | `number-max` | Largest finite number. |
| 21 | `number-mean` | Arithmetic mean of finite numbers. |
| 22 | `number-median` | Median of finite numbers; mean of the middle pair for even counts. |
| 23 | `number-range` | Largest minus smallest finite number. |
| 24 | `positive-count` | Number of finite numbers above zero. |
| 25 | `negative-count` | Number of finite numbers below zero. |
| 26 | `zero-count` | Number of finite numbers equal to zero. |
| 27 | `positive-sum` | Sum of finite numbers above zero. |
| 28 | `negative-sum` | Sum of finite numbers below zero. |
| 29 | `absolute-sum` | Sum of the absolute values of finite numbers. |
| 30 | `true-count` | Number of JSON true values; numeric 1 is excluded. |
| 31 | `false-count` | Number of JSON false values; numeric 0 is excluded. |
| 32 | `string-count` | Number of strings, including empty strings. |
| 33 | `array-count` | Number of arrays, including empty arrays. |
| 34 | `object-count` | Number of objects, including empty objects. |
| 35 | `length-sum` | Sum of string lengths, array lengths and object key counts. |
| 36 | `length-min` | Smallest length among strings, arrays and objects. |
| 37 | `length-max` | Largest length among strings, arrays and objects. |
| 38 | `length-mean` | Mean length among strings, arrays and objects. |
| 39 | `text-min` | Smallest string in case-sensitive Unicode order. |
| 40 | `text-max` | Largest string in case-sensitive Unicode order. |

Numeric operations accept finite JSON numbers and finite decimal strings;
booleans, null, arrays, objects, invalid strings and nonfinite strings are skipped.
Numeric value results and `length-mean` are decimal **strings** to avoid losing
precision in JSON consumers; count results and other length results are integers.
Decimal strings omit insignificant fractional zeros, render zero as `"0"`, and
use scientific notation outside adjusted exponents -6 through 20. Means use
28 significant digits with half-even rounding. Sums, ranges and medians use
operand-dependent precision up to 10,000 digits; arithmetic exceeding the
supported precision or exponent range fails with a CLI error. The process's
ambient decimal context is left unchanged.

For empty inputs (or no eligible values), count operations and `length-sum`
return 0; numeric sum operations return `"0"`; list operations return `[]`;
`mode-count` returns 0. Other operations return null. Missing values are still
eligible for `first`, `last`, `mode` and typed distinct/list operations.

These are descriptive summaries of saved rows, not currency conversion or tax
calculations. Group by currency before summing monetary fields; this command
does not prevent combining currencies or detect incomplete valuations. Use the
dedicated tax and portfolio commands for their financial semantics.

## Capability inventory and verification

Every operation above is available on every existing source:

`accounts`, `assets`, `transactions`, `positions`, `cash`, `snapshots`,
`cached-quotes`, `alerts`, `watchlist`, `targets`, `realized`, `payouts`, `backups`,
`config`, `config-defaults`, `config-diff`, `config-keys`, `themes`, `commands`,
`providers`, `account-types`, `transaction-types`, `asset-kinds`, `asset-classes`,
`compounding`.

`tests/test_summary_capabilities.py` exercises all 25 × 40 combinations through
the actual CLI with independently specified expected results. Separate tests
cover real fictional source data, grouping and filtering, output formats,
validation before loading, read-only behavior, archived-account hiding and
configuration-key redaction.
