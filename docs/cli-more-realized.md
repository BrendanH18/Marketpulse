# More realized-sale and payout inspection (1–25)

[Batch inventory](cli-more-hundred-improvements.md) · [Issue #134](https://github.com/BrendanH18/Marketpulse/issues/134)

These 25 additions inspect the local ledger offline. Examples use fictional
symbols and accounts. Items 1–10 work with both `realized` and `payouts`.

| # | Capability | Example |
| --- | --- | --- |
| 1 | Include several exact symbols | `marketpulse realized --symbols MAPL --symbols GULL` |
| 2 | Select account type | `marketpulse payouts --account-type tfsa` |
| 3 | Select exact account institution | `marketpulse realized --institution 'Fictional Bank'` |
| 4 | Select account registration status | `marketpulse payouts --registered` (or `--nonregistered`) |
| 5 | Select account cash-tracking status | `marketpulse realized --cash-tracked` (or `--cash-untracked`) |
| 6 | Exclude several native currencies | `marketpulse payouts --exclude-currency USD --exclude-currency EUR` |
| 7 | Include several exact dates | `marketpulse realized --on 2024-04-01 --on 2024-04-02` |
| 8 | Exclude several exact dates | `marketpulse payouts --exclude-date 2024-04-01` |
| 9 | Select several weekdays | `marketpulse realized --weekday mon --weekday tue` |
| 10 | Select a symbol prefix | `marketpulse payouts --symbol-prefix MA` |
| 11 | Set an inclusive sale cost minimum | `marketpulse realized --min-cost 20` |
| 12 | Set an inclusive sale cost maximum | `marketpulse realized --max-cost 200` |
| 13 | Set an inclusive sale transaction ID minimum | `marketpulse realized --min-txn-id 3` |
| 14 | Set an inclusive sale transaction ID maximum | `marketpulse realized --max-txn-id 7` |
| 15 | Select sales breaking even to the cent | `marketpulse realized --breakeven-only` |
| 16 | Count matching sales by year | `marketpulse realized --summary year --json` |
| 17 | Count matching sales by calendar month | `marketpulse realized --summary month --csv` |
| 18 | Count matching sales by account name | `marketpulse realized --summary account` |
| 19 | Count matching sales by symbol | `marketpulse realized --summary symbol` |
| 20 | Sort individual payout rows | `marketpulse payouts --sort amount` |
| 21 | Reverse selected payout row order | `marketpulse payouts --sort amount --descending` |
| 22 | Exclude several payout kinds | `marketpulse payouts --exclude-kind interest --exclude-kind drip` |
| 23 | Group payouts by calendar quarter and native currency | `marketpulse payouts --by quarter --json` |
| 24 | Group payouts by income kind and native currency | `marketpulse payouts --by kind --csv` |
| 25 | Group payouts by native currency | `marketpulse payouts --by currency` |

Repeated values within an inclusion option form a union; different options
intersect. Exclusions remove matches even when an inclusion selected them.
Symbols, currencies, institution and prefix values ignore case and surrounding
whitespace; blank values are errors. Dates use the existing date parser.
Weekdays, account types and income kinds ignore case. Archived accounts remain
hidden, including from count summaries and grouped totals.

Cost is the existing ledger cost in each sale's native currency. Select
`--currency CAD` when comparing one currency. Cost bounds must be finite and
ordered; transaction IDs must be positive and ordered. `--breakeven-only` uses
the same cent rounding as the existing gain/loss selectors, and conflicts with
either of them. These reports do not apply tax FX or superficial-loss rules.

Sale summaries return `group,count` rows as JSON or CSV, or a human table.
They describe the complete matching selection and contain no monetary totals.
Accounts with the same displayed name share an account summary group.
Summaries reject `--count`, ordering and pagination options. Empty summaries
return `[]` in JSON and a header in CSV.

Payout sorts accept `date`, `account`, `symbol`, `kind`, `amount`, or `currency`.
They sort before offset and limit, preserve ledger order on ties, and leave
full-selection totals unchanged. `--descending` alone reverses date order.
These individual-row options conflict with `--by`, `--count` and
`--newest-first`. Grouped payouts retain existing group ordering, pagination,
formats and `--newest-first` behavior. Every group keeps currencies separate.

Human financial amounts remain masked in privacy mode. Explicit JSON and CSV
remain raw. No addition fetches quotes or FX, records a snapshot, or mutates the
ledger. Existing invocations retain their output and defaults.
