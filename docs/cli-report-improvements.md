# One thousand offline report capabilities

[User guide](usage.md) · [Base report interface](cli-composable-reports.md) ·
[Issue #138](https://github.com/BrendanH18/Marketpulse/issues/138)

`marketpulse report SOURCE` now supports **40 additional operations across 25
saved datasets = 1,000 new dataset/operation capabilities**. The count describes
shared operations available on different datasets, not 1,000 unrelated features.
These extend the original 20 operations (500 combinations) from #136.
No new sources, network requests or financial calculations are introduced.
The operations also apply to the [25 datasets and derived fields added
later](cli-report-derived-datasets.md).

## New operations

All field names in filters, sorting, deduplication and cell transformations refer
to the original source schema (`report SOURCE --describe`). Filters repeat with
AND, including across old and new filter options. Cell transformations affect
output only; they never change saved values or the values used to filter/sort.
They can be repeated for multiple fields.

| No. | Option | Behavior |
| --- | --- | --- |
| 1 | `--ieq FIELD=TEXT` | Text equality ignoring case, using Unicode case folding. |
| 2 | `--ine FIELD=TEXT` | Text inequality ignoring case. |
| 3 | `--not-contains FIELD=TEXT` | Exclude substring matches, ignoring case. |
| 4 | `--not-prefix FIELD=TEXT` | Exclude prefix matches, ignoring case. |
| 5 | `--not-suffix FIELD=TEXT` | Exclude suffix matches, ignoring case. |
| 6 | `--gt FIELD=NUMBER` | Keep numeric values strictly above the threshold. |
| 7 | `--ge FIELD=NUMBER` | Keep numeric values at or above the threshold. |
| 8 | `--lt FIELD=NUMBER` | Keep numeric values strictly below the threshold. |
| 9 | `--le FIELD=NUMBER` | Keep numeric values at or below the threshold. |
| 10 | `--between FIELD=LOW,HIGH` | Keep values within inclusive numeric bounds. |
| 11 | `--outside FIELD=LOW,HIGH` | Keep values strictly outside inclusive numeric bounds. |
| 12 | `--in FIELD=JSON_ARRAY` | Keep typed membership matches, including nested JSON values. |
| 13 | `--not-in FIELD=JSON_ARRAY` | Exclude typed membership matches. |
| 14 | `--empty FIELD` | Keep null, empty string, empty array or empty object. |
| 15 | `--nonempty FIELD` | Exclude those empty values; zero and false remain. |
| 16 | `--is-type FIELD=TYPE` | Select `string`, `number`, `boolean`, `array`, `object` or `null`. |
| 17 | `--length FIELD=N` | Select strings, arrays or objects with exactly N elements. |
| 18 | `--min-length FIELD=N` | Select strings, arrays or objects with at least N elements. |
| 19 | `--max-length FIELD=N` | Select strings, arrays or objects with at most N elements. |
| 20 | `--glob FIELD=PATTERN` | Case-sensitive shell wildcards (`*`, `?`, `[abc]`), over report text. |
| 21 | `--lower FIELD` | Lowercase strings for output; other types retain their values. |
| 22 | `--upper FIELD` | Uppercase strings for output. |
| 23 | `--strip FIELD` | Remove whitespace from both ends of strings. |
| 24 | `--lstrip FIELD` | Remove leading string whitespace. |
| 25 | `--rstrip FIELD` | Remove trailing string whitespace. |
| 26 | `--replace FIELD=JSON_PAIR` | Replace substrings; pair is `["old","new"]`, with nonempty old text. |
| 27 | `--fill FIELD=JSON` | Replace null with a JSON value; empty strings, zero and false remain. |
| 28 | `--null-if FIELD=JSON` | Replace typed matches with null. |
| 29 | `--stringify FIELD` | Convert to report text: strings unchanged, null empty, others canonical JSON. |
| 30 | `--encode-json FIELD` | Serialize any value, including strings and null, into a JSON string. |
| 31 | `--decode-json FIELD` | Parse strings as JSON; nonstrings retain their values. Invalid JSON is an error. |
| 32 | `--length-of FIELD` | Output string/array/object length, or null for other types. |
| 33 | `--round FIELD=DIGITS` | Round finite JSON numbers to 0–15 decimal places for output only. |
| 34 | `--rename FIELD=NAME` | Rename output columns simultaneously; swaps are supported. |
| 35 | `--constant NAME=JSON` | Append a constant output column. |
| 36 | `--row-number NAME` | Append a 1-based row position within the result before pagination. |
| 37 | `--sort-ci FIELD` | Case-insensitive ordering; repeat for ordered tie breakers. |
| 38 | `--reverse-rows` | Reverse the ordered rows. |
| 39 | `--tail N` | Retain the last N rows before pagination (N ≥ 1). |
| 40 | `--every N` | Retain every Nth row, starting with the first (N ≥ 1). |

Numeric filters accept finite JSON numbers and numeric strings. Booleans, null
and nonnumeric values never pass a numeric filter, including `--outside`.
Bounds must be finite and LOW ≤ HIGH. Numeric strings compare as decimal
numbers without converting currencies. Membership and `--null-if` compare JSON
types: false differs from zero, strings differ from numbers, and objects compare
independently of key order. Numbers such as 1 and 1.0 compare equal. These rules
also apply inside nested arrays and objects. An empty membership array matches
nothing; an empty exclusion array excludes nothing.

Text filters and globs use the original report text convention: strings are raw,
null is an empty string, and other values are canonical JSON. Glob brackets use
shell patterns, not regular expressions. Length counts Unicode code points for
strings, elements for arrays and keys for objects; length predicates reject
other types. N must be a nonnegative integer. New JSON arguments and decoded
values reject nonfinite numbers, including overflowing exponents.

## Processing and composition

The fixed order is:

1. Old and new filters on original source values.
2. `--unique` in source order.
3. `--sort` or `--sort-ci`, with optional `--descending`.
4. `--reverse-rows`, then `--tail`, then `--every`.
5. Count the remaining rows for `--count` or `--page-info.total`.
6. Apply `--offset` and `--limit`.
7. Cell transforms in table order (21–33). Repeated instances of one option run
   in their argument order, regardless of where other options appear.
8. Simultaneous renames, then constants, then row numbers.
9. `--fields` or `--omit` using the **final output column names**, then export.

`--sort` and `--sort-ci` cannot combine. Both support `--descending` and place
missing values last; numbers remain numerically sorted before text and nested
JSON. Case-insensitive text ties preserve source order unless another key breaks
them. Window operations affect counts; pagination does not. Row numbers start
at offset + 1 in the windowed result, so the second page continues numbering.

Cell transforms reference original column names even when that column is
renamed. Text transforms (21–26) leave nonstrings unchanged. `--fill` and
`--null-if` can insert nested JSON. `--round` uses Python's ties-to-even numeric
rounding; it does not pad zeros, convert numeric strings or round booleans.
It changes only exported values, never financial-engine calculations.
`--encode-json` followed by `--decode-json` round-trips JSON values;
`--stringify` produces raw text instead. Decoding runs only on the selected
page, before projection, and fails without emitting a partial report or file.

New column names must match `[A-Za-z_][A-Za-z0-9_]*`. Duplicate aliases, aliases
that collide with an unchanged column, duplicate constants and conflicting row
number names are rejected. Renames are simultaneous, allowing swaps, and retain
the original column positions. Constants and row numbers append to the schema.
Empty results retain the final headers in CSV, TSV and Markdown.

`--count` rejects output transformations, projection, pagination and alternate
formats; filters, sorting and windows are allowed. `--describe` accepts no query
operations, and always describes the original source. Malformed arguments,
unknown fields and conflicting options fail before loading source data. The
existing raw/unmasked export, secret redaction and atomic no-overwrite file
rules still apply. Tracker startup may migrate data and maintain backups as
explained in the base report guide; these remain offline queries, not a
filesystem read-only mode.

## Examples on fictional data

Use both scratch overrides before running examples, as in the [data guide](data.md).
The commands below are shell examples; single quotes protect JSON and wildcards.

```bash
export MARKETPULSE_DATA=/tmp/marketpulse-report-improvements
export MARKETPULSE_CONFIG=/tmp/marketpulse-report-improvements/config.toml
marketpulse report transactions --between amount=100,500 --not-in 'type=["FEE","WITHDRAWAL"]'
marketpulse report accounts --ieq currency=CAD --glob 'name=Demo*' --rename name=account_name
marketpulse report positions --gt quantity=0 --round quantity=3 --constant 'reviewed=false'
marketpulse report config --is-type value=array --length-of value --rename value=items
marketpulse report commands --not-prefix 'command=desktop' --sort-ci command --tail 10 --row-number row
marketpulse report snapshots --every 7 --limit 20 --page-info
marketpulse report config-defaults --encode-json value --format csv --output defaults.csv
```

## Capability inventory

Each dataset receives all 40 numbered operations above. Each row below is a
block of 40 new combinations: operation 1 is the first number in that block,
operation 40 is the last. These IDs are local to this batch. For example, 1 is
account case-insensitive equality, 40 is account stride selection, 41 is asset
case-insensitive equality and 1,000 is compounding stride selection. A filter
can validly return no rows for a field with incompatible types; this does not
add types or fields to the source schema.

| New capabilities | Source |
| --- | --- |
| 1–40 | `accounts` |
| 41–80 | `assets` |
| 81–120 | `transactions` |
| 121–160 | `positions` |
| 161–200 | `cash` |
| 201–240 | `snapshots` |
| 241–280 | `cached-quotes` |
| 281–320 | `alerts` |
| 321–360 | `watchlist` |
| 361–400 | `targets` |
| 401–440 | `realized` |
| 441–480 | `payouts` |
| 481–520 | `backups` |
| 521–560 | `config` |
| 561–600 | `config-defaults` |
| 601–640 | `config-diff` |
| 641–680 | `config-keys` |
| 681–720 | `themes` |
| 721–760 | `commands` |
| 761–800 | `providers` |
| 801–840 | `account-types` |
| 841–880 | `transaction-types` |
| 881–920 | `asset-kinds` |
| 921–960 | `asset-classes` |
| 961–1,000 | `compounding` |
