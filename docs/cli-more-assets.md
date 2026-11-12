# Asset metadata inspection (improvements 26–50)

[Issue #134](https://github.com/BrendanH18/Marketpulse/issues/134) · [User guide](usage.md)

These additions read saved asset definitions entirely offline. They do not price
holdings, replay financial calculations, create asset definitions, write ledger
rows, or record snapshots. Examples use fictional symbols. Set both
`MARKETPULSE_DATA` and `MARKETPULSE_CONFIG` to scratch paths before trying commands
against a fictional ledger, as described in the [data guide](data.md).

| # | New capability | Example |
| --- | --- | --- |
| 26 | Include any of several configured symbols | `marketpulse asset list --symbols FIC-A --symbols ART-A` |
| 27 | Exclude configured currencies, repeatably | `marketpulse asset list --exclude-currency USD` |
| 28 | Exclude asset kinds, repeatably | `marketpulse asset list --exclude-kind market` |
| 29 | Exclude explicit asset classes, repeatably | `marketpulse asset list --exclude-class etf` |
| 30 | Search only the configured asset name | `marketpulse asset list --name deposit` |
| 31 | Select symbol prefixes | `marketpulse asset list --symbol-prefix FIC-` |
| 32 | Select symbol suffixes | `marketpulse asset list --symbol-suffix -A` |
| 33 | Find metadata with or without a nonblank name | `marketpulse asset list --no-name` (or `--has-name`) |
| 34 | Find metadata with or without a configured currency | `marketpulse asset list --no-currency` (or `--has-currency`) |
| 35 | Select explicitly classified asset definitions | `marketpulse asset list --classified` |
| 36 | Find metadata with or without a saved start date | `marketpulse asset list --has-start-date` (or `--no-start-date`) |
| 37 | Find metadata with or without a saved maturity date | `marketpulse asset list --no-maturity-date` (or `--has-maturity-date`) |
| 38 | Sort fixed-income definitions by their start date | `marketpulse asset list --sort start-date` |
| 39 | Sort definitions by explicit asset class | `marketpulse asset list --sort class` |
| 40 | Sort fixed-income definitions by compounding schedule | `marketpulse asset list --sort compounding` |
| 41 | Count matching definitions by asset kind | `marketpulse asset list --summary kind --json` |
| 42 | Count matching definitions by configured currency | `marketpulse asset list --summary currency --csv` |
| 43 | Count matching definitions by explicit asset class | `marketpulse asset list --summary class` |
| 44 | Count matching definitions by compounding schedule | `marketpulse asset list --summary compounding --json` |
| 45 | Print matching symbols one per line for scripts | `marketpulse asset list --symbols-only --symbol-prefix FIC-` |
| 46 | Select fields for list JSON and CSV exports | `marketpulse asset list --fields symbol --fields maturity_date --csv` |
| 47 | Export one configured definition as CSV | `marketpulse asset show FIC-A --csv` |
| 48 | Select fields when inspecting a definition | `marketpulse asset show FIC-A --fields symbol --fields rate --json` |
| 49 | Read one raw metadata value for a script | `marketpulse asset show FIC-A --value rate` |
| 50 | Check whether a symbol has a saved definition using only exit status | `marketpulse asset show FIC-A --exists` |

Filters combine with the existing selectors and use all matching definitions
before counts or pagination. Text matching ignores case. The new `--symbols`,
`--exclude-currency`, `--name`, `--symbol-prefix` and `--symbol-suffix` selectors
trim surrounding whitespace; the existing `--search` keeps query whitespace.
Repeatable inclusion matches any included symbol; exclusions remove
any excluded value. Excluding classes retains unclassified definitions. Blank
symbol inclusions, currency exclusions, names, prefixes, and suffixes are usage
errors. `--classified` conflicts with `--unclassified`.

Date-presence selectors inspect saved fields on every asset kind. Sorting by
`start-date` or `compounding` applies to fixed-income definitions; other kinds
remain at the end. Sorting by `class` puts unclassified definitions last. Missing
sort values stay last even with `--descending`; symbol breaks ties. Compounding
sorts alphabetically by the stored schedule name. No elapsed time, accrual, or
market class inference is calculated.

Summaries return `group` and `count` columns in human, JSON, or CSV output.
Unspecified currencies use `(unspecified)`, missing classes use `(unclassified)`,
and non-fixed-income compounding uses `(not applicable)`. Summary counts never
sum money. Summaries accept selectors, but reject separate counting, symbol
output, projection, sorting, and pagination. Empty JSON summaries are `[]`; empty
CSV summaries still include their header.

`--symbols-only` uses the same selection, order, offset, and limit as other list
output. It conflicts with JSON, CSV, and count output. Empty symbol output is
empty stdout. List `--fields` requires JSON or CSV; show `--fields` also supports
human output. Repeat the option to preserve a chosen column order; duplicates
are removed. Accepted fields are `symbol`, `kind`, `name`, `asset_class`,
`currency`, `rate`, `compounding`, `start_date`, and `maturity_date`. Existing JSON
page metadata remains available around projected list rows.

Human `asset show` masks the rate in privacy mode, including projected output.
JSON, CSV, and `--value` remain raw, unmasked outputs for scripts. An unset field
prints an empty line under `--value`. A missing symbol still exits 1 with a
friendly error, except under `--exists`, which always prints nothing and exits
0 for a configured symbol or 1 for a missing one. `--exists` and `--value` reject
other output selectors or field projection.
