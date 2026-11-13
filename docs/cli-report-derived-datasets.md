# Five thousand offline dataset and derived-field capabilities

[User guide](usage.md) · [Base report interface](cli-composable-reports.md) ·
[Report operations](cli-report-improvements.md) · [Summaries](cli-report-summaries.md) ·
[Issue #142](https://github.com/BrendanH18/Marketpulse/issues/142)

`marketpulse report` and `marketpulse summarize` gain **5,000 new
dataset/operation combinations** in two parts:

1. **25 new datasets**, for 50 in total. Each new dataset supports the 100
   existing shared operations (20 base report operations, 40 added report
   operations and 40 summary operations): 25 × 100 = 2,500.
2. **50 derived-field functions** through `--derive`, on all 50 datasets:
   50 × 50 = 2,500.

As in the earlier batches, the count describes shared operations available on
distinct datasets, not 5,000 unrelated features. Everything here reads saved
data offline: no quotes or historical prices are requested, no snapshot is
recorded, and the datasets never change the ledger, settings or files.
Datasets that read saved data start the tracker like any other command, and
that startup can create, migrate or back up the database
([details](cli-composable-reports.md#capability-inventory)). Engine
calculations (ACB, FX, tax, valuation, contribution room) are unchanged, and
reports without `--derive` produce the same output as before.

Issue #143 later added 7 more datasets and 30 more operations; see
[Offline report filters, selections, summaries and formats](cli-report-expansion.md).

## New datasets

Run `marketpulse report sources` to list every dataset, or
`marketpulse report SOURCE --describe` for one dataset's fields.

| No. | Source | Fields | Dataset |
| --- | --- | --- | --- |
| 1 | `holdings` | symbol, currency, accounts, quantity, book, first_date | Open ledger positions pooled by symbol and currency across active accounts. |
| 2 | `closed-positions` | account_id, account, symbol, currency, first_date, last_date, transactions | Positions in active accounts whose ledger quantity has returned to zero. |
| 3 | `cash-flows` | date, account_id, account, amount, currency | Recorded deposits and withdrawals as signed external cash flows. |
| 4 | `fees` | transaction_id, date, account_id, account, type, symbol, fee, currency | Fees recorded on saved transactions in active accounts. |
| 5 | `ledger-issues` | transaction_id, date, account_id, account, code, message, details | Ledger replay warnings for transactions in active accounts. |
| 6 | `symbols` | symbol, transactions, first_date, last_date, held, watched, alerts, asset_kind, cached_quote | Every symbol in visible saved data and where it is used. |
| 7 | `currencies` | currency, base, accounts, transactions, positions, cash_balances, cached_quotes | Every currency in visible saved data and where it is used. |
| 8 | `account-activity` | account_id, account, type, currency, transactions, first_date, last_date, open_positions, symbols | Transaction counts, date ranges and open positions for each active account. |
| 9 | `rooms` | account_type, as_of_year, amount | Saved contribution-room baselines by account type. |
| 10 | `schema` | table, position, column, type, required, default, primary_key | Tables and columns of the local database, without reading rows. |
| 11 | `paths` | name, path, exists, kind | Data, database, backup and configuration locations in use. |
| 12 | `data-files` | name, kind, size_bytes, modified_at | Entries directly inside the data directory. |
| 13 | `environment` | name, set, value, purpose | Environment overrides MarketPulse reads and whether they are set. |
| 14 | `runtime` | component, version | Versions of MarketPulse, Python, SQLite and installed dependencies. |
| 15 | `sources` | source, group, fields, field_count, description | Every report dataset with its group, fields and description. |
| 16 | `summary-operations` | position, operation, takes_field, result | Summary operations accepted by `summarize --metric`. |
| 17 | `derive-functions` | position, function, family, argument, result, description | Derived-field functions accepted by `--derive`. |
| 18 | `broker-profiles` | name, label, required_headers, has_accounts, limits | CSV import profiles and the headers that identify them. |
| 19 | `import-aliases` | field, position, alias | CSV header names accepted for each import field. |
| 20 | `import-type-keywords` | position, keyword, type | Words that map generic CSV rows to transaction types, in matching order. |
| 21 | `exchange-suffixes` | suffix, currency | Symbol suffixes and the trading currency assumed for each. |
| 22 | `instrument-classes` | instrument_type, asset_class, label | Quote instrument types and the asset class assigned to each. |
| 23 | `tfsa-limits` | year, limit | Annual TFSA dollar limits used for contribution room. |
| 24 | `theme-colors` | theme, role, color | Palette colors of every embedded theme. |
| 25 | `market-strip` | position, symbol, label, default | Configured market strip symbols and their labels. |

### Ledger rollups (1–9)

These replay the saved ledger exactly as the existing `positions`, `cash`,
`realized` and `payouts` datasets do. Archived accounts are hidden: their
transactions, positions, cash and warnings appear in no row, count or sum.
Amounts stay in their native currency and are never converted, so group by
`currency` before adding monetary fields.

- `holdings` adds quantity and book value across the active accounts holding a
  symbol in one currency; `accounts` is how many hold it and `first_date` is
  the earliest opening date. It has no average-cost column: a cross-account
  average is not a tax ACB. Use `marketpulse tax` for tax cost base.
- `closed-positions` lists account and symbol pairs that were held and are now
  at zero. `first_date` is when the most recent holding period began;
  `last_date` and `transactions` cover saved transactions for the symbol where
  the account is the transaction's account or its transfer destination.
- `cash-flows` lists deposits as positive and withdrawals as negative amounts,
  in ledger order. Purchases in accounts that do not track cash are not listed.
- `fees` lists the amount of each `FEE` transaction and the fee recorded on
  each `BUY`, `DRIP` and `SELL`, omitting zero fees. A sale's fee is in the
  currency of the position sold.
- `ledger-issues` lists replay warnings such as a sale exceeding the quantity
  held, with the stable `code` and the values behind the message in `details`.
- `symbols` has one row per symbol found in active-account transactions or
  positions (including positions received by transfer), saved assets, the
  watchlist, alerts or the offline quote cache. `asset_kind` is null when no
  asset is saved for the symbol.
- `currencies` has one row per currency found in active accounts, their
  transactions, open positions, cash balances or cached quotes, and always
  lists the base currency.
- `account-activity` has one row per active account, including accounts with
  no transactions. An in-kind transfer between active accounts counts for both
  accounts, as it does in `marketpulse activity -a`.
- `rooms` lists the saved baselines only. `marketpulse accounts room` shows the
  remaining contribution room.

### Local system (10–14)

- `schema` opens the database file read-only and reads table definitions, never
  rows. `required` is the column's NOT NULL declaration, `default` is its SQL
  default expression as written (text keeps its quotes) and `primary_key`
  marks key columns.
- `paths` reports the data directory, database, backup directory and
  configuration file in use, following symbolic links, with `kind` as
  `directory`, `file`, `other` or `missing`.
- `data-files` lists the entries directly inside the data directory without
  following symbolic links. `size_bytes` is null except for regular files, and
  `modified_at` is a UTC timestamp, or null for a time outside the years 1 to
  9999. SQLite's temporary companion files can appear and disappear between runs.
- `environment` lists `MARKETPULSE_DATA`, `MARKETPULSE_CONFIG` and
  `XDG_CONFIG_HOME`. An empty variable counts as unset, as it does when
  MarketPulse starts. These hold paths; no secret is read from the environment.
- `runtime` lists the versions of MarketPulse, Python, SQLite and the installed
  dependencies, for bug reports, plus two rows whose `version` holds the Python
  implementation (such as `CPython`) and the platform (such as `linux`). A
  dependency that is not installed has a null version.

`environment` and `runtime` do not open the tracker. `schema`, `paths` and
`data-files` use the same tracker startup as the other saved-data datasets
(see the [base report guide](cli-composable-reports.md#capability-inventory)).
Paths and file names describe your own machine; review them before sharing an
export.

### Reference catalogs (15–25)

These describe MarketPulse itself and never open the tracker. `market-strip`
reads the current configuration; the others are fixed tables. `sources`,
`summary-operations` and `derive-functions` document this interface, so scripts
can discover datasets, summary operations and derived-field functions without
parsing help text.
In `broker-profiles`, `has_accounts` is null for the generic profile, which
decides per file by whether an account column is present. `tfsa-limits` lists
the published limits; contribution room assumes the latest one for later years
until MarketPulse is updated.

## Derived fields

`--derive NAME=FUNCTION:FIELD[:ARGUMENT]` adds a computed column to `report`
and `summarize`. Repeat it to add several.

```bash
# Income per calendar quarter, in each native currency.
marketpulse summarize payouts --derive quarter=year-quarter:date \
  --group-by quarter --group-by currency --metric amount=number-sum:amount

# Unit cost of pooled holdings, to four decimal places.
marketpulse report holdings --derive unit_cost=divide-field:book:quantity --round unit_cost=4

# Purchases in buckets of 1,000.
marketpulse summarize transactions --where type=BUY \
  --derive cost=multiply-field:quantity:price --derive bucket=bin:cost:1000 \
  --group-by bucket --metric purchases=count --sort bucket

# Count purchases beside all rows: a derived boolean makes a conditional count.
marketpulse summarize transactions --derive 'is_buy=equals:type:"BUY"' \
  --metric buys=true-count:is_buy --metric rows=count

# Open positions by exchange suffix.
marketpulse summarize positions --derive exchange=after-last:symbol:. \
  --group-by exchange --metric positions=count
```

Rules:

- `NAME` is an ASCII identifier (`[A-Za-z_][A-Za-z0-9_]*`) that is not already
  a field. `FIELD` is a source field or a derived field defined earlier on the
  command line, so derivations can be chained.
- Derived columns are computed for every loaded row before any filter runs, and
  are appended to the source's fields in argument order. Every other option can
  then name them like source fields: filters, `--sort`, `--unique`, `--fields`,
  `--omit`, output transformations and `--rename` in `report`; `--where`,
  filters, `--group-by` and `--metric` in `summarize`.
- A function returns null for a value it does not apply to (for example a date
  function on a number). It never removes a row or stops the report.
- The text after the second colon is the argument, taken literally: it may
  contain colons, commas, spaces and `=`. Functions marked `—` take no argument.
- Unknown functions and fields, invalid names and missing, unexpected or
  invalid arguments are rejected before the source is loaded.
- `--describe` describes the source only and cannot be combined with `--derive`.
- Derived values exist only in the output. Saved data is never changed.

### Functions

| No. | Function | Argument | Result |
| --- | --- | --- | --- |
| 1 | `year` | — | Calendar year, as an integer. |
| 2 | `quarter` | — | Calendar quarter, 1 to 4. |
| 3 | `month` | — | Month number, 1 to 12. |
| 4 | `day` | — | Day of the month, 1 to 31. |
| 5 | `weekday` | — | ISO weekday number: 1 for Monday to 7 for Sunday. |
| 6 | `day-of-year` | — | Day of the year, 1 to 366. |
| 7 | `iso-week` | — | ISO 8601 week number, 1 to 53. |
| 8 | `year-month` | — | Year and month, such as `2024-03`. |
| 9 | `year-quarter` | — | Year and quarter, such as `2024-Q1`. |
| 10 | `year-week` | — | ISO week-numbering year and week, such as `2025-W01` for 2024-12-30. |
| 11 | `month-name` | — | English month name, such as `March`. |
| 12 | `weekday-name` | — | English weekday name, such as `Monday`. |
| 13 | `date` | — | The calendar date as `YYYY-MM-DD`, dropping any time. |
| 14 | `month-start` | — | First day of the month. |
| 15 | `month-end` | — | Last day of the month. |
| 16 | `quarter-start` | — | First day of the calendar quarter. |
| 17 | `quarter-end` | — | Last day of the calendar quarter. |
| 18 | `year-start` | — | January 1 of the year. |
| 19 | `year-end` | — | December 31 of the year. |
| 20 | `week-start` | — | The Monday that starts the ISO week. |
| 21 | `is-weekend` | — | True on Saturday and Sunday, otherwise false. |
| 22 | `days-from` | `DATE` | Days from `DATE` (`YYYY-MM-DD`) to the field's date; negative when the field is earlier. |
| 23 | `number` | — | The numeric value as a JSON number, parsing numeric text. |
| 24 | `abs` | — | Absolute value. |
| 25 | `negate` | — | The value with its sign reversed. |
| 26 | `sign` | — | -1, 0 or 1. |
| 27 | `floor` | — | Largest whole number at or below the value. |
| 28 | `ceil` | — | Smallest whole number at or above the value. |
| 29 | `round` | `DIGITS` | The value rounded half to even at `DIGITS` (0 to 15) decimal places. |
| 30 | `bin` | `WIDTH` | Lower edge of the value's bucket: the largest multiple of `WIDTH` (above zero) at or below it. |
| 31 | `add` | `NUMBER` | The value plus `NUMBER`. |
| 32 | `multiply` | `NUMBER` | The value times `NUMBER`. |
| 33 | `add-field` | `FIELD` | The value plus another field's value. |
| 34 | `subtract-field` | `FIELD` | The value minus another field's value. |
| 35 | `multiply-field` | `FIELD` | The value times another field's value. |
| 36 | `divide-field` | `FIELD` | The value divided by another field's value; null when that value is zero. |
| 37 | `lower` | — | Lowercase text. |
| 38 | `upper` | — | Uppercase text. |
| 39 | `trim` | — | Text without leading or trailing whitespace. |
| 40 | `left` | `N` | The first `N` characters (`N` from 1 to 999,999,999). |
| 41 | `before` | `TEXT` | Text before the first `TEXT`; the whole text when `TEXT` is absent. |
| 42 | `after-last` | `TEXT` | Text after the last `TEXT`; empty when `TEXT` is absent. |
| 43 | `length` | — | Characters in text, elements in an array or keys in an object. |
| 44 | `text` | — | Report text: text unchanged, null as empty text, other values as canonical JSON. |
| 45 | `type` | — | `string`, `number`, `boolean`, `array`, `object` or `null`. |
| 46 | `is-missing` | — | True for null or empty text, otherwise false. |
| 47 | `coalesce` | `JSON` | The value, or the `JSON` argument when the value is null. |
| 48 | `equals` | `JSON` | True when the value equals the `JSON` argument, comparing JSON types. |
| 49 | `item` | `N` | Element `N` of an array, counting from 0; negative `N` counts from the end. `N` has at most nine digits. |
| 50 | `key` | `NAME` | Member `NAME` of an object. |

**Dates (1–22)** read ISO date text: `YYYY-MM-DD`, alone or followed by `T`
or one space and a time (`HH:MM` or `HH:MM:SS`, optionally with fractional
seconds, then optionally `Z` or a `±HH:MM` offset). The date must exist in the
calendar, and the result uses the date as written; an offset never moves it to
another day. Anything else, including numbers, gives null. Weeks follow ISO 8601: they
start on Monday, and the first week of a year is the one containing its first
Thursday, so `year-week` can name the previous or next year near January 1.
Month and weekday names are English regardless of locale.

**Numbers (23–36)** accept finite JSON numbers and numeric text, as the report
filters do; booleans, null and other values give null. Arithmetic is decimal,
with 28 significant digits and half-even rounding, so `add` on 0.2 with 0.1
gives 0.3. Results are JSON numbers: whole results below 10^15 in magnitude are
integers, and other results are the nearest double. A result too large for a
double is null. `round` rounds the number's decimal text, so 2.675 at 2 places
gives 2.68; the `--round` output transformation rounds the binary value
instead. The two-field functions give null when either value is not a number.
These are arithmetic on exported values, not currency conversion: both fields
must already be in the same currency for a sum or difference to mean anything.

**Text (37–42)** apply to text and give null for other values. `left` counts
Unicode code points.

**Values (43–50)** accept any JSON value. `length` gives null for numbers,
booleans and null. `equals` and `coalesce` take a finite JSON argument, so text
needs JSON quotes: `equals:type:"BUY"`. Equality is typed as in the
[membership filters](cli-report-improvements.md#new-operations): false differs
from 0, 1 equals 1.0, and objects compare without regard to key order. `item`
gives null for an index outside the array and for values that are not arrays;
`key` gives null for a missing member and for values that are not objects.

### Processing order

`report` computes derived columns immediately after loading the source, before
step 1 of the [existing order](cli-report-improvements.md#processing-and-composition).
Output transformations such as `--round` or `--upper` on a derived column
therefore change only its exported value, after filtering and sorting used the
derived value. `summarize` computes derived fields first, then filters, groups,
summarizes, sorts and paginates as before.

## Examples on fictional data

Use both scratch overrides before running examples, as in the [data guide](data.md).

```bash
export MARKETPULSE_DATA=/tmp/marketpulse-derived-example
export MARKETPULSE_CONFIG=/tmp/marketpulse-derived-example/config.toml
marketpulse report sources --fields source,group,description --format markdown
marketpulse report derive-functions --where family=date --fields function,argument,description
marketpulse report holdings --sort book --descending --limit 10
marketpulse report fees --derive year=year:date --where year=2024 --format csv --output fees-2024.csv
marketpulse summarize cash-flows --derive year=year:date --group-by year --group-by currency \
  --metric deposits=positive-sum:amount --metric withdrawals=negative-sum:amount
marketpulse report symbols --where held=false --where watched=true --fields symbol,alerts
marketpulse report ledger-issues --derive symbol=key:details:symbol --fields date,account,code,symbol
marketpulse report closed-positions --derive closed_after=days-from:last_date:2024-01-01 --gt closed_after=0
marketpulse summarize transactions --derive weekday=weekday-name:date --group-by weekday --metric rows=count
marketpulse report schema --where table=transactions --fields position,column,type
marketpulse report tfsa-limits --ge year=2020 --format tsv
```

## Capability inventory

### New datasets × existing operations (1–2,500)

Each row is a block of 100 combinations. Within a block, 1–20 are the
[base report operations](cli-composable-reports.md#twenty-operations-on-every-source),
21–60 are the [40 added report operations](cli-report-improvements.md#new-operations)
and 61–100 are the [40 summary operations](cli-report-summaries.md#operations),
each in its documented order. For example, 1 is holdings column selection, 100
is the holdings `text-max` summary and 2,500 is the market strip `text-max`
summary.

| New capabilities | Source |
| --- | --- |
| 1–100 | `holdings` |
| 101–200 | `closed-positions` |
| 201–300 | `cash-flows` |
| 301–400 | `fees` |
| 401–500 | `ledger-issues` |
| 501–600 | `symbols` |
| 601–700 | `currencies` |
| 701–800 | `account-activity` |
| 801–900 | `rooms` |
| 901–1,000 | `schema` |
| 1,001–1,100 | `paths` |
| 1,101–1,200 | `data-files` |
| 1,201–1,300 | `environment` |
| 1,301–1,400 | `runtime` |
| 1,401–1,500 | `sources` |
| 1,501–1,600 | `summary-operations` |
| 1,601–1,700 | `derive-functions` |
| 1,701–1,800 | `broker-profiles` |
| 1,801–1,900 | `import-aliases` |
| 1,901–2,000 | `import-type-keywords` |
| 2,001–2,100 | `exchange-suffixes` |
| 2,101–2,200 | `instrument-classes` |
| 2,201–2,300 | `tfsa-limits` |
| 2,301–2,400 | `theme-colors` |
| 2,401–2,500 | `market-strip` |

### Derived-field functions × all datasets (2,501–5,000)

Each row is a block of 50 combinations, one per function in the numbered order
above. For example, 2,501 is the account `year` function, 2,550 is the account
`key` function and 5,000 is the market strip `key` function. A function that
does not apply to a field's values gives null, as described above; this does
not add types or fields to a dataset.

| New capabilities | Source | New capabilities | Source |
| --- | --- | --- | --- |
| 2,501–2,550 | `accounts` | 3,751–3,800 | `holdings` |
| 2,551–2,600 | `assets` | 3,801–3,850 | `closed-positions` |
| 2,601–2,650 | `transactions` | 3,851–3,900 | `cash-flows` |
| 2,651–2,700 | `positions` | 3,901–3,950 | `fees` |
| 2,701–2,750 | `cash` | 3,951–4,000 | `ledger-issues` |
| 2,751–2,800 | `snapshots` | 4,001–4,050 | `symbols` |
| 2,801–2,850 | `cached-quotes` | 4,051–4,100 | `currencies` |
| 2,851–2,900 | `alerts` | 4,101–4,150 | `account-activity` |
| 2,901–2,950 | `watchlist` | 4,151–4,200 | `rooms` |
| 2,951–3,000 | `targets` | 4,201–4,250 | `schema` |
| 3,001–3,050 | `realized` | 4,251–4,300 | `paths` |
| 3,051–3,100 | `payouts` | 4,301–4,350 | `data-files` |
| 3,101–3,150 | `backups` | 4,351–4,400 | `environment` |
| 3,151–3,200 | `config` | 4,401–4,450 | `runtime` |
| 3,201–3,250 | `config-defaults` | 4,451–4,500 | `sources` |
| 3,251–3,300 | `config-diff` | 4,501–4,550 | `summary-operations` |
| 3,301–3,350 | `config-keys` | 4,551–4,600 | `derive-functions` |
| 3,351–3,400 | `themes` | 4,601–4,650 | `broker-profiles` |
| 3,401–3,450 | `commands` | 4,651–4,700 | `import-aliases` |
| 3,451–3,500 | `providers` | 4,701–4,750 | `import-type-keywords` |
| 3,501–3,550 | `account-types` | 4,751–4,800 | `exchange-suffixes` |
| 3,551–3,600 | `transaction-types` | 4,801–4,850 | `instrument-classes` |
| 3,601–3,650 | `asset-kinds` | 4,851–4,900 | `tfsa-limits` |
| 3,651–3,700 | `asset-classes` | 4,901–4,950 | `theme-colors` |
| 3,701–3,750 | `compounding` | 4,951–5,000 | `market-strip` |

## Verification

- The three existing matrices (`tests/test_reports.py`,
  `tests/test_report_improvements.py`, `tests/test_summary_capabilities.py`)
  run every existing operation on every dataset through the actual CLI, so the
  25 new datasets add 2,500 cases.
- `tests/test_derive_capabilities.py` runs all 50 functions on all 50 datasets
  through the actual CLI against independently specified results (2,500
  cases), and each function again through `summarize`.
- `tests/test_report_ledger.py`, `tests/test_report_system.py` and
  `tests/test_report_reference.py` load every new dataset from fictional saved
  data and check exact rows, archived-account hiding, offline and read-only
  behavior.
- `tests/test_report_derive.py` covers composition with filters, sorting,
  grouping and exports, validation before loading, calendar and decimal edge
  cases, and a fictional ledger end to end.
