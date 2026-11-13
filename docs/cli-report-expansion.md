# Offline report filters, selections, summaries and formats

[User guide](usage.md) · [Base report interface](cli-composable-reports.md) ·
[Report operations](cli-report-improvements.md) · [Summaries](cli-report-summaries.md) ·
[Derived fields and datasets](cli-report-derived-datasets.md) ·
[Issue #143](https://github.com/BrendanH18/Marketpulse/issues/143)

`marketpulse report SOURCE` and `marketpulse summarize SOURCE` gain 7 datasets and
30 operations. Before this batch there were 50 datasets and 150 shared operations:
the 20 operations of [#136](cli-composable-reports.md), the 40 of
[#138](cli-report-improvements.md), the 40 summary operations of
[#140](cli-report-summaries.md) and the 50 derived-field functions of
[#142](cli-report-derived-datasets.md). Now:

- each of the 7 new datasets supports the 150 earlier operations: 7 × 150 = 1,050;
- each of the 30 new operations works on all 57 datasets: 30 × 57 = 1,710.

That makes **7 × 150 + 30 × 57 = 2,760 new dataset/operation combinations**. They
are combinations of shared operations and datasets, not 2,760 unrelated features.

What stays the same:

- Both commands are offline, read-only queries. They never request quotes or
  historical prices, record snapshots or change the ledger, and nothing in this
  batch changes a financial calculation (ACB, FX, tax, valuation or contribution
  room).
- Configuration API keys stay redacted.
- Archived accounts and their entries are never listed. (`contribution-room` still
  counts their deposits against the room, as `marketpulse accounts room` does.)
- Script output is raw and unmasked, including when privacy mode is enabled.
- Saved-data sources open the tracker with the startup described in the
  [base report guide](cli-composable-reports.md#capability-inventory): it may create
  the database, run migrations and create or prune automatic backups. Of the new
  datasets, `contribution-room` and `snapshot-classes` open it; the five catalogs,
  and `--describe`, do not.
- The earlier datasets and options behave as before, apart from the
  [fixes](#fixes-and-known-limitations) listed at the end. The catalogs that
  describe the interface grow with it: `report sources` lists 57 datasets, and
  `report summary-operations` and `summarize SOURCE --describe` list 50 summary
  operations.

## Seven new datasets

Run `marketpulse report sources` to list every dataset, or
`marketpulse report SOURCE --describe` for one dataset's fields. Each new dataset
supports the [20 operations of #136](cli-composable-reports.md#twenty-operations-on-every-source),
the [40 operations of #138](cli-report-improvements.md#new-operations), the
[40 summary operations of #140](cli-report-summaries.md#operations), the
[50 derived-field functions of #142](cli-report-derived-datasets.md#functions) and
the 30 new operations below.

| No. | Source | Fields | Dataset |
| --- | --- | --- | --- |
| 1 | `contribution-room` | account_type, as_of_year, starting_room, contributions, withdrawals_added_back, new_limits, remaining, forfeited, accounts | Remaining contribution room the engine derives from saved baselines and recorded flows. |
| 2 | `snapshot-classes` | date, asset_class, value, currency | Asset-class breakdown saved with each net-worth snapshot. |
| 3 | `alert-conditions` | value, description, percent | Alert conditions and whether their threshold is a percent. |
| 4 | `chart-periods` | period, interval, bars_per_year | Chart periods, their bar interval and bars per year. |
| 5 | `tui-keys` | workspace, key, action | Terminal app keys by workspace. |
| 6 | `workspaces` | name, hint, table, sort_modes | Terminal app workspaces with their hint, table and sort columns. |
| 7 | `report-operations` | number, family, operation, commands, syntax, summary, issue | Every shared report and summary operation, with its syntax and the commands that accept it. |

### Saved data (1–2)

These are in the `ledger` group of `report sources` and open the tracker.

- `contribution-room` has one row per account type with a saved baseline: the
  same figures `marketpulse accounts room` shows, from the existing engine. It
  depends on the current year, because annual limits and TFSA withdrawals are
  added back up to it.
  `accounts` lists the names of the active accounts of that type. Deposits to
  archived accounts of the type still count against the room, as they do in the
  engine; their names are not listed. The saved baselines alone are in
  [`rooms`](cli-report-derived-datasets.md#new-datasets).
- `snapshot-classes` has one row per asset class of each net-worth snapshot that
  was saved with a breakdown, classes in alphabetical order within a date. `value`
  is in the snapshot's `currency`. Backfilled and older snapshots have no breakdown
  and contribute no rows.

### Reference catalogs (3–7)

These are in the `reference` group, describe MarketPulse itself and never open the
tracker.

- `alert-conditions` lists the four conditions `marketpulse alerts` accepts, what
  each compares and whether its threshold is a percent.
- `chart-periods` lists each chart period with the bar interval it requests and
  the number of such bars in a year.
- `tui-keys` lists the global keys first, then each workspace's own keys, in
  workspace order.
- `workspaces` lists the eight terminal app workspaces in order, with their key
  hint, the id of their main table (null when there is none) and the columns that
  table can be sorted by (`[]` when it has no sort modes).
- `report-operations` lists all 180 shared operations in catalog order. Numbers
  1–20 come from #136, 21–60 from #138, 61–100 from #140, 101–150 are the derive
  functions of #142, and 151–180 are operations 1–30 of this guide. `commands` is
  an array of the commands that accept the operation (`report`, `summarize` or
  both) and `issue` is the issue number that added it.

## Thirty new operations

The operations are numbered 1 to 30 across the tables below, and the
[capability inventory](#capability-inventory) uses these numbers. Every operation
works on all 57 datasets. An option works on both `report` and `summarize` unless
its section says otherwise.

### Terms

The tables rely on these definitions:

- **Report text** of a cell: a string is itself, null is the empty string, and any
  other value is its canonical JSON,
  `json.dumps(value, ensure_ascii=False, sort_keys=True)`, for example `true`, `10`,
  `1.5`, `[1, 2]` or `{"a": 1}`. The older text filters use the same convention.
- **Date-like value**: the ISO date text the [`--derive` date functions](cli-report-derived-datasets.md)
  read: `YYYY-MM-DD` alone, or followed by `T` or one space and a time (`HH:MM` or
  `HH:MM:SS`, optionally with fractional seconds, then optionally `Z` or a `±HH:MM`
  offset). The date must exist and the time must be valid. `2024-02-30`, `2024-3-5`,
  `20240305`, `2024-03-05x`, `2024-03-05 lunch`, `2024-03-05T99:99`, numbers and null
  are not date-like.
- **JSON number**: an int or float that is not a boolean. A numeric string such as
  `"12.5"` is not a JSON number.
- **Finite number**: a JSON number, or a string that parses as a finite decimal.
  Booleans, null, arrays, objects, invalid strings and non-finite strings are skipped.
  The summary operations and the numeric filters of #138 (`--gt`, `--between` and the
  others) read finite numbers.
- **Typed equality and distinctness**: `false` differs from `0`, strings differ from
  numbers, and `1` equals `1.0`. The rule applies recursively inside arrays and
  objects, and objects compare without regard to key order.

### Row filters (1–10)

| No. | Option | Behavior |
| --- | --- | --- |
| 1 | `--regex FIELD=PATTERN` | Keep rows whose report text contains a match of the Python regular expression. It searches anywhere in the text and is case-sensitive unless the pattern says otherwise, for example with `(?i)`. |
| 2 | `--not-regex FIELD=PATTERN` | Exclude those rows. |
| 3 | `--iglob FIELD=PATTERN` | Keep rows whose whole report text matches the shell wildcard pattern (`*`, `?`, `[abc]`), ignoring case. |
| 4 | `--not-glob FIELD=PATTERN` | Exclude rows whose whole report text matches the wildcard pattern, case-sensitively. |
| 5 | `--contains-any FIELD=JSON_ARRAY` | The value is a JSON array of strings. Keep rows whose report text contains at least one of them, ignoring case. An empty array matches nothing. |
| 6 | `--contains-all FIELD=JSON_ARRAY` | Keep rows whose report text contains every listed string, ignoring case. An empty array matches every row. |
| 7 | `--date-from FIELD=YYYY-MM-DD` | Keep rows whose value is date-like with a date on or after the given day. |
| 8 | `--date-to FIELD=YYYY-MM-DD` | Keep rows whose value is date-like with a date on or before the given day. |
| 9 | `--has-item FIELD=JSON` | Keep rows whose value is an array containing an element typed-equal to the JSON value. |
| 10 | `--has-key FIELD=KEY` | Keep rows whose value is an object that has exactly that key. |

Rules:

- All ten take `FIELD=VALUE`, can be repeated, and combine with AND with each other
  and with every older filter. FIELD can be a source field or a
  [derived field](cli-report-derived-datasets.md#derived-fields). In `summarize` they
  filter source rows before grouping; [`--having`](#grouped-summary-steps-2425-summarize-only)
  applies them to summary rows.
- Pattern and text matching reads report text, so a number matches as its JSON text
  and null as the empty string. Put patterns and JSON in single quotes in the shell.
- `--iglob` ignores case one character at a time, as `--regex` does with `(?i)`: `?`
  matches exactly one character, and `[ß]` matches `ß` or `ẞ` but not `ss`.
  `--contains-any` and `--contains-all` compare fully case-folded text, so
  `'["strasse"]'` also finds `Straße`.
- `--regex` runs Python's regular expressions without a time limit. A pattern with
  nested repeats, such as `(a+)+$`, can take a very long time on long text.
- Values that are not date-like never match `--date-from` or `--date-to`; a
  timestamp compares by its date. Use both options for an inclusive range.
- Non-arrays never match `--has-item`, and non-objects never match `--has-key`. For
  example, `marketpulse report report-operations --has-item 'commands="summarize"'`
  lists the operations `summarize` accepts, and
  `marketpulse report ledger-issues --has-key details=symbol` lists the ledger
  warnings that name a symbol.

These are usage errors (exit code 2), raised before the source is loaded: an invalid
regular expression; a `--contains-any` or `--contains-all` value that is not a JSON
array of strings; a `--date-from` or `--date-to` value that is not a valid
`YYYY-MM-DD` date; a `--has-item` value that is not valid finite JSON; a missing `=`;
an unknown field.

### Keyed row selection (11–13), `report` only

| No. | Option | Behavior |
| --- | --- | --- |
| 11 | `--duplicates FIELD` | Keep every row whose key occurs more than once among the filtered rows. Order is preserved. |
| 12 | `--singletons FIELD` | Keep every row whose key occurs exactly once. |
| 13 | `--unique-last FIELD` | Keep the last row for each key; the kept rows stay in source order. (`--unique` keeps the first.) |

Rules:

- Repeat an option to build a composite key, for example
  `--duplicates date --duplicates symbol`.
- Keys compare the canonical JSON of each cell, exactly like the existing `--unique`:
  `1` and `1.0` are different keys, and `true` differs from `1`.
- They run after all filters and before sorting, row windows and pagination.
  `--duplicates` and `--singletons` run before `--unique` and `--unique-last`.
- `--duplicates` cannot be combined with `--singletons` ("Choose --duplicates or
  --singletons."), nor `--unique` with `--unique-last` ("Choose --unique or
  --unique-last."). Both are usage errors (exit code 2).
- All three change what `--count` and the `--page-info` total report.

### Summary operations (14–23), `summarize` only

Use them as `marketpulse summarize SOURCE --metric NAME=OPERATION:FIELD`.

| No. | OPERATION | Result |
| --- | --- | --- |
| 14 | `date-min` | Earliest date among the date-like values, as `YYYY-MM-DD` text; null when there are none. |
| 15 | `date-max` | Latest date, as `YYYY-MM-DD` text; null when there are none. |
| 16 | `date-count` | Number of date-like values, an integer; 0 when there are none. |
| 17 | `date-span` | Whole days between the earliest and latest date, an integer (0 for a single date); null when there are none. |
| 18 | `number-variance` | Population variance of the finite numbers: the mean squared deviation from the mean, dividing by the count. A decimal string; `"0"` for a single number; null when there are none. |
| 19 | `number-stdev` | Population standard deviation, the square root of that variance, as a decimal string; `"0"` for a single number; null when there are none. |
| 20 | `number-q1` | First quartile of the finite numbers by linear interpolation between closest ranks (the inclusive method, as spreadsheet QUARTILE.INC): sort ascending, take position (n - 1) × 0.25 counting from 0, and interpolate between the two neighbours. A decimal string; null when there are none. |
| 21 | `number-q3` | Third quartile, the same way at position (n - 1) × 0.75. |
| 22 | `value-counts` | Array of `[value, count]` pairs, one per distinct typed value (null included), most frequent first; equally frequent values keep first-encountered order. `[]` for no rows. |
| 23 | `repeated-values` | Array of the distinct typed values that occur more than once, in first-encountered order. `[]` when there are none. |

Rules:

- Date operations read date-like values and skip everything else; a timestamp counts
  as its date.
- Variance and standard deviation are the exact values rounded once to 28 significant
  digits, half to even, so they are exact when they terminate within 28 digits.
  Quartiles are always exact.
- Decimal strings follow the convention of the older numeric summaries: no
  insignificant zeros, zero is `"0"`, ordinary notation for adjusted exponents -6
  through 20 and scientific notation outside that range.
- Example: the values 2, 4, 4, 4, 5, 5, 7, 9 have variance `"4"`, standard deviation
  `"2"`, first quartile `"4"` and third quartile `"5.5"`.
- As with the older numeric summaries, operands spanning more than 10,000 digits, and
  results whose exponent is beyond plus or minus 999,999, fail with a clean CLI error
  (exit code 1).
- When sorting summary rows, `date-min`, `date-max`, `value-counts` and
  `repeated-values` sort as text and the other six numerically.
- `value-counts` and `repeated-values` use typed distinctness, so `false`, `0` and
  `"0"` are three values while `1` and `1.0` are one; each value is shown as it was
  first encountered.
- These are descriptive summaries and do not convert currencies. Group by currency
  before measuring the spread of a monetary field.
- `marketpulse summarize SOURCE --describe` lists the source's fields and all 50
  summary operations.

### Grouped-summary steps (24–25), `summarize` only

| No. | Option | Behavior |
| --- | --- | --- |
| 24 | `--having FILTER:NAME=VALUE` | After grouping, keep only the summary rows that pass the filter. |
| 25 | `--totals` | Append one final row computed over every filtered source row. |

Rules for `--having`:

- FILTER is the dashed name of any `FIELD=VALUE` row filter shared by both commands:
  `ieq`, `ine`, `not-contains`, `not-prefix`, `not-suffix`, `gt`, `ge`, `lt`, `le`,
  `between`, `outside`, `in`, `not-in`, `empty`, `nonempty`, `is-type`, `length`,
  `min-length`, `max-length`, `glob`, `regex`, `not-regex`, `iglob`, `not-glob`,
  `contains-any`, `contains-all`, `date-from`, `date-to`, `has-item` or `has-key`.
- NAME is a `--group-by` field or a metric name. `empty` and `nonempty` take only
  `FILTER:NAME`, for example `--having nonempty:symbol`.
- Numeric filters read decimal-string metric results as numbers, so
  `--having gt:total=1000` works on a `number-sum` result.
- Repeat `--having` for AND. It runs before `--sort`, `--offset` and `--limit`, and
  the `--page-info` total counts the remaining groups.
- Malformed conditions are usage errors (exit code 2), raised before the source is
  loaded. A missing colon or an unknown filter gives "--having requires
  FILTER:NAME=VALUE with a filter from: ...". A bad condition gives "--having VALUE:"
  followed by the filter's own message, for example "--having gt:rows=x: --gt
  requires FIELD=NUMBER with finite numbers."

Rules for `--totals`:

- In the totals row the grouping columns are null and the metric columns hold the
  same metrics over all the filtered source rows.
- The row is added after `--having`, sorting and pagination, so it is always last, is
  not counted in the `--page-info` total, and still covers rows of groups that
  `--having` or pagination removed.
- `--totals` requires `--group-by` ("--totals requires --group-by.").

For example, this keeps the symbols with more than one entry and then adds a totals
row over every entry that has a symbol, including the groups `--having` removed:

```bash
marketpulse summarize transactions --nonempty symbol --group-by symbol --metric rows=count \
  --metric last=date-max:date --having gt:rows=1 --totals --format text
```

```text
symbol   rows  last
-------  ----  ----------
FIC.TO      4  2024-09-30
DEMO.TO     2  2024-07-20
            7  2024-09-30
```

### Export formats (26–30)

`--format` now offers the same ten choices on `report` and `summarize`: `json`
(default), `jsonl`, `csv`, `tsv`, `markdown`, `html`, `text`, `records`, `lines` and
`json-columns`.

| No. | Option | Output |
| --- | --- | --- |
| 26 | `--format html` | An HTML table fragment. |
| 27 | `--format text` | An aligned plain-text table. |
| 28 | `--format records` | One block of `name: value` lines per row. |
| 29 | `--format lines` | One value per line from a single column, with no header. |
| 30 | `--format json-columns` | One JSON object mapping each column to an array of its values. |

**`html`** writes one element per line, and every line ends with a newline. Each cell
is the report text, HTML-escaped (`&` becomes `&amp;`, `<` becomes `&lt;`, `>`
becomes `&gt;`, `"` becomes `&quot;` and `'` becomes `&#x27;`); after escaping, a
carriage return becomes `&#13;` and a line feed becomes `<br>`. Header cells are the
column names, escaped the same way. With no rows the `<tbody>` is empty. For
`marketpulse report cash-flows --fields date,account,amount --limit 2 --format html`:

```html
<table>
<thead>
<tr><th>date</th><th>account</th><th>amount</th></tr>
</thead>
<tbody>
<tr><td>2024-01-02</td><td>Fictional TFSA</td><td>5000.0</td></tr>
<tr><td>2024-03-01</td><td>Fictional Margin</td><td>2000.0</td></tr>
</tbody>
</table>
```

**`text`** prints one header line, one rule line, then one line per row. Columns are
separated by two spaces, and each column is as wide as the longest of its name and
its cells, counted in characters. The rule is `-` repeated to each column's width.
Cells holding JSON numbers are right-aligned; names and all other cells, including
the decimal strings summaries return, are left-aligned. A cell is its report text on
one line: a backslash becomes `\\`, a line feed `\n`, a carriage return `\r` and a
tab `\t`. Trailing spaces are removed from every line. With no rows there is only the
header and the rule.

**`records`** prints each row as a block of `name: value` lines in column order. The
value is the one-line report text, as in `text`; an empty value gives `name:` with
nothing after the colon, and trailing spaces inside a value are kept. Blocks are
separated by one blank line, with no blank line at the end. With no rows the output
is empty.

**`lines`** needs exactly one output column: choose it with `--fields` on `report`,
or use a single grouping field or metric on `summarize`. Otherwise it is a usage error
before loading: "--format lines requires exactly one output column." Each row's
report text is printed on its own line, with no header and without escapes. A value
containing a line feed or carriage return fails with "Cannot write a value
containing a line break with --format lines." (exit code 1) and writes nothing. With
no rows the output is empty.

**`json-columns`** prints one JSON object that maps each column name to the array of
its values in row order, with native types, followed by a newline. With no rows every
column maps to `[]`.

The same two `cash-flows` rows in `text`, `records` and `json-columns`:

```text
date        account           amount
----------  ----------------  ------
2024-01-02  Fictional TFSA    5000.0
2024-03-01  Fictional Margin  2000.0

date: 2024-01-02
account: Fictional TFSA
amount: 5000.0

date: 2024-03-01
account: Fictional Margin
amount: 2000.0

{"date": ["2024-01-02", "2024-03-01"], "account": ["Fictional TFSA", "Fictional Margin"], "amount": [5000.0, 2000.0]}
```

`--page-info` and `--count` still require the default `json` format. `--output PATH`
works with every format, with the same rule as before: the file is written
atomically and an existing file is never overwritten.

## Processing order

As in the [derived-field guide](cli-report-derived-datasets.md#processing-order),
derived columns come first, so every later step can use them. `report` runs its
steps in this order:

1. Load the source and compute `--derive` columns.
2. Apply all filters, old and new, on source and derived values.
3. `--duplicates` or `--singletons`.
4. `--unique` or `--unique-last`.
5. `--sort` or `--sort-ci`, with `--descending`.
6. `--reverse-rows`, `--tail`, `--every`.
7. Count the rows for `--count` and the `--page-info` total.
8. `--offset` and `--limit`.
9. Cell transforms, renames, constants, row numbers.
10. `--fields` or `--omit`, on the final column names.
11. Export in the chosen format.

`summarize` runs its steps in this order:

1. Load the source and compute `--derive` columns.
2. `--where` and all filters.
3. Group and compute metrics.
4. `--having`.
5. `--sort` with `--descending`.
6. Count the groups for `--page-info`.
7. `--offset` and `--limit`.
8. Add the `--totals` row.
9. Export.

Every option is validated before the source is loaded, so a malformed value, an
unknown field or a conflicting combination fails without reading any data. Problems
that depend on the data fail later: a line break with `--format lines`, summary
arithmetic beyond the limits above, or invalid JSON for the older `--decode-json`.
`--describe` accepts none of the new options.

## Examples on fictional data

Use both scratch overrides before running examples, as in the [data guide](data.md).
Single quotes protect JSON, wildcards and regular expressions from the shell.

```bash
export MARKETPULSE_DATA=/tmp/marketpulse-report-expansion
export MARKETPULSE_CONFIG=/tmp/marketpulse-report-expansion/config.toml

# Count transactions per calendar month, with how often each type occurs.
marketpulse summarize transactions --derive month=year-month:date --group-by month \
  --metric entries=count --metric types=value-counts:type --format text

# Group deposits and withdrawals into 1,000-wide amount bands, per currency.
marketpulse summarize cash-flows --derive band=bin:amount:1000 --group-by currency --group-by band \
  --metric flows=count --metric total=number-sum:amount --sort band --format text

# Entries for symbols listed with .TO or .V between March and June 2024.
marketpulse report transactions --date-from date=2024-03-01 --date-to date=2024-06-30 \
  --regex 'symbol=\.(TO|V)$' --fields date,account,type,symbol --format text

# Find possible duplicate entries: the same account, date, symbol, quantity and price.
marketpulse report transactions --duplicates account_id --duplicates date --duplicates symbol \
  --duplicates quantity --duplicates price --fields id,date,account,symbol,quantity,price --format text

# Show the latest entry for each symbol; cash entries have no symbol.
marketpulse report transactions --nonempty symbol --unique-last symbol \
  --fields symbol,date,type,account --format text

# First and last activity per account, and the days between them.
marketpulse summarize transactions --group-by account --metric first=date-min:date \
  --metric last=date-max:date --metric days=date-span:date --format text

# Spread of the prices paid for each symbol.
marketpulse summarize transactions --where type=BUY --group-by symbol --metric q1=number-q1:price \
  --metric median=number-median:price --metric q3=number-q3:price --metric stdev=number-stdev:price

# Years with at least 10 of income, per currency.
marketpulse summarize payouts --derive year=year:date --group-by year --group-by currency \
  --metric total=number-sum:amount --having ge:total=10 --format text

# Run one command per symbol held in some account.
marketpulse report symbols --where held=true --fields symbol --format lines |
  while IFS= read -r symbol; do marketpulse report positions --where "symbol=$symbol" --format jsonl; done

# Export cash flows with the month name as an HTML table to a new file.
marketpulse report cash-flows --derive month=month-name:date --fields date,month,account,amount \
  --format html --output cash-flows.html

# Remaining contribution room, one block per account type.
marketpulse report contribution-room --format records

# Holdings-workspace keys that copy or open a chart.
marketpulse report tui-keys --iglob 'workspace=h*' --contains-any 'action=["copy","chart"]' --format text

# Workspaces whose table can be sorted by symbol.
marketpulse report workspaces --has-item 'sort_modes="symbol"' --fields name,table --format text

# Chart periods that use daily bars, as one array per column.
marketpulse report chart-periods --where interval=1d --fields period,bars_per_year --format json-columns

# The syntax of every operation this guide adds.
marketpulse report report-operations --where issue=143 --fields number,syntax --format text

# Shared operations per issue, with a total of 180.
marketpulse summarize report-operations --group-by issue --metric operations=count --totals --format text
```

## Fixes and known limitations

- Printed reports keep escape sequences and other control characters from saved
  text when the output is piped. Click used to strip them when standard output was
  not a terminal, so piped output could differ from a terminal or an `--output`
  file. Review untrusted text before printing it to a terminal.
- `--output` with text that UTF-8 cannot encode, such as a lone surrogate from a
  JSON `\ud800` escape, now fails with "Cannot write report: ..." (exit code 1) and
  creates no file.
- A missing value for `--in`, as in `--in name`, now gives "--in requires
  FIELD=VALUE." instead of naming another option.
- Known limitation: a NaN or infinity in report data, such as `nan` for a numeric
  setting in `config.toml`, still stops `report` and `summarize` with a traceback
  instead of a clean error. This predates these changes and is tracked in
  [#145](https://github.com/BrendanH18/Marketpulse/issues/145).

## Capability inventory

### New datasets × earlier operations (1–1,050)

Each row is a block of 150, in the order of the dataset table. Inside a block,
positions 1–20 are the #136 operations in the order of the
[base guide's table](cli-composable-reports.md#twenty-operations-on-every-source),
21–60 are the #138 operations 1–40 in the order of
[their table](cli-report-improvements.md#new-operations), 61–100 are the #140
summary operations 1–40 in the order of
[their table](cli-report-summaries.md#operations), and 101–150 are the #142
derived-field functions 1–50 in the order of
[their table](cli-report-derived-datasets.md#functions). For example, capability 1
is `contribution-room` column selection (`--fields`), 21 is `contribution-room`
case-insensitive equality (`--ieq`), 61 is the `contribution-room` `count` metric,
101 is the `contribution-room` `year` function and 1,050 is the
`report-operations` `key` function.

| Capabilities | Source | #136 operations | #138 operations | #140 summaries | #142 derive functions |
| --- | --- | --- | --- | --- | --- |
| 1–150 | `contribution-room` | 1–20 | 21–60 | 61–100 | 101–150 |
| 151–300 | `snapshot-classes` | 151–170 | 171–210 | 211–250 | 251–300 |
| 301–450 | `alert-conditions` | 301–320 | 321–360 | 361–400 | 401–450 |
| 451–600 | `chart-periods` | 451–470 | 471–510 | 511–550 | 551–600 |
| 601–750 | `tui-keys` | 601–620 | 621–660 | 661–700 | 701–750 |
| 751–900 | `workspaces` | 751–770 | 771–810 | 811–850 | 851–900 |
| 901–1,050 | `report-operations` | 901–920 | 921–960 | 961–1,000 | 1,001–1,050 |

### New operations × all datasets (1,051–2,760)

Sources are in alphabetical order, as the CLI lists them. Each row is a block of 30,
and the position inside a block is the operation number from this guide. For
example, 1,051 is `--regex` on `account-activity`, 1,080 is `--format json-columns`
on `account-activity`, and 2,760 is `--format json-columns` on `workspaces`.

| Capabilities | Source | Added in |
| --- | --- | --- |
| 1,051–1,080 | `account-activity` | #142 |
| 1,081–1,110 | `account-types` | #136 |
| 1,111–1,140 | `accounts` | #136 |
| 1,141–1,170 | `alert-conditions` | #143 |
| 1,171–1,200 | `alerts` | #136 |
| 1,201–1,230 | `asset-classes` | #136 |
| 1,231–1,260 | `asset-kinds` | #136 |
| 1,261–1,290 | `assets` | #136 |
| 1,291–1,320 | `backups` | #136 |
| 1,321–1,350 | `broker-profiles` | #142 |
| 1,351–1,380 | `cached-quotes` | #136 |
| 1,381–1,410 | `cash` | #136 |
| 1,411–1,440 | `cash-flows` | #142 |
| 1,441–1,470 | `chart-periods` | #143 |
| 1,471–1,500 | `closed-positions` | #142 |
| 1,501–1,530 | `commands` | #136 |
| 1,531–1,560 | `compounding` | #136 |
| 1,561–1,590 | `config` | #136 |
| 1,591–1,620 | `config-defaults` | #136 |
| 1,621–1,650 | `config-diff` | #136 |
| 1,651–1,680 | `config-keys` | #136 |
| 1,681–1,710 | `contribution-room` | #143 |
| 1,711–1,740 | `currencies` | #142 |
| 1,741–1,770 | `data-files` | #142 |
| 1,771–1,800 | `derive-functions` | #142 |
| 1,801–1,830 | `environment` | #142 |
| 1,831–1,860 | `exchange-suffixes` | #142 |
| 1,861–1,890 | `fees` | #142 |
| 1,891–1,920 | `holdings` | #142 |
| 1,921–1,950 | `import-aliases` | #142 |
| 1,951–1,980 | `import-type-keywords` | #142 |
| 1,981–2,010 | `instrument-classes` | #142 |
| 2,011–2,040 | `ledger-issues` | #142 |
| 2,041–2,070 | `market-strip` | #142 |
| 2,071–2,100 | `paths` | #142 |
| 2,101–2,130 | `payouts` | #136 |
| 2,131–2,160 | `positions` | #136 |
| 2,161–2,190 | `providers` | #136 |
| 2,191–2,220 | `realized` | #136 |
| 2,221–2,250 | `report-operations` | #143 |
| 2,251–2,280 | `rooms` | #142 |
| 2,281–2,310 | `runtime` | #142 |
| 2,311–2,340 | `schema` | #142 |
| 2,341–2,370 | `snapshot-classes` | #143 |
| 2,371–2,400 | `snapshots` | #136 |
| 2,401–2,430 | `sources` | #142 |
| 2,431–2,460 | `summary-operations` | #142 |
| 2,461–2,490 | `symbols` | #142 |
| 2,491–2,520 | `targets` | #136 |
| 2,521–2,550 | `tfsa-limits` | #142 |
| 2,551–2,580 | `theme-colors` | #142 |
| 2,581–2,610 | `themes` | #136 |
| 2,611–2,640 | `transaction-types` | #136 |
| 2,641–2,670 | `transactions` | #136 |
| 2,671–2,700 | `tui-keys` | #143 |
| 2,701–2,730 | `watchlist` | #136 |
| 2,731–2,760 | `workspaces` | #143 |

`marketpulse report report-operations` lists all 180 shared operations offline, in
catalog order: numbers 151–180 are operations 1–30 of this guide.

## Verification

- `tests/test_report_expansion.py` runs the 30 new operations on all 57 sources
  through the real CLI, against results worked out by hand, and checks the
  2,760 count.
- `tests/test_reports.py`, `tests/test_report_improvements.py`,
  `tests/test_summary_capabilities.py` and `tests/test_derive_capabilities.py` run
  the earlier operations on every source, including the 7 new ones.
- Focused tests cover edge cases: `tests/test_report_expansion_filters.py` (row
  filters), `tests/test_report_selection.py` (keyed selection),
  `tests/test_report_expansion_metrics.py` (summary operations),
  `tests/test_summary_expansion.py` (`--having` and `--totals`) and
  `tests/test_report_formats.py` (formats and output).
- `tests/test_report_history.py` checks `contribution-room` and `snapshot-classes`
  on fictional saved data: exact rows, the engine's room figures, no network
  access, no writes and hidden archived accounts. `tests/test_report_interface.py`
  checks the five catalogs: exact rows, typed values and that they open neither
  the tracker nor the network.
- `tests/test_report_operations.py` checks the operation catalog against the real
  command options.
