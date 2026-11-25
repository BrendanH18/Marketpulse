# Ledger history reports

Use `marketpulse report SOURCE` to list these records and `marketpulse
summarize SOURCE` to group them. Each of the five datasets supports the 197
shared operations cataloged by `marketpulse report report-operations`. The
985 new dataset and operation combinations plus the 15 named filters below
give **1,000 new reporting capabilities**. The two commands share this count.

| Dataset | What each row shows | `--preset` choices |
| --- | --- | --- |
| `duplicate-transactions` | A group of two or more transactions in one active account with the same date, type, symbol, quantity, price, amount, fees, input currency, split ratio and transfer target. | `same-note` keeps groups whose notes also match, `trades` keeps buys and sells, and `repeated` keeps groups of three or more. |
| `asset-usage` | A symbol with a saved asset entry, a transaction in an active account, a current holding, a watchlist entry or an alert, with where it is used. | `held`, `watch-only` for symbols that are only watched or alerted, and `unused` for asset entries nothing else refers to. |
| `income-calendar` | Dividend, reinvested dividend and interest payments for one year, account, symbol and currency, with the months paid. | `monthly` keeps rows paid in all 12 months, `reinvested` keeps rows with a reinvested dividend, and `single-payment` keeps rows with one payment. |
| `holding-periods` | One period an active account held a symbol, from the first shares to the last, with the days held. | `open`, `closed`, and `under-a-year` for periods closed in fewer than 365 days. |
| `snapshot-changes` | A saved net-worth snapshot compared with the previous one: days between them and the change in net worth and contributions. | `gains`, `losses`, and `gaps` for snapshots more than one day after the previous one. |

`SOURCE --describe` lists the fields, preset names, and their equivalent CLI
filters. Presets combine with other filters using AND and select rows before
`summarize` groups them.

```bash
# Find transactions that were probably recorded twice.
marketpulse report duplicate-transactions --fields transactions,transaction_ids,date,type,symbol

# List saved assets that nothing else uses.
marketpulse report asset-usage --preset unused --fields symbol,kind,name

# Total income by year and currency for holdings that paid in every month.
marketpulse summarize income-calendar --preset monthly --group-by year --group-by currency --metric paid=number-sum:amount

# Show positions closed within a year, longest first.
marketpulse report holding-periods --preset under-a-year --sort days_held --descending

# Find the days with the largest drops in net worth.
marketpulse report snapshot-changes --preset losses --sort change --limit 5
```

## How rows are built

**Duplicate transactions.** The note doesn't count toward a match, and
`notes_differ` says whether the notes, ignoring surrounding spaces, differ. An
explicit currency matches the same currency inferred from the symbol or account.
`transaction_ids` lists the saved ids in ascending order. `target_account_id`
and `target_account` are null unless the transfer target is an active account. Rows are ordered by date,
account and the first transaction id. A match isn't necessarily a mistake: two
identical purchases on the same day are possible.

**Asset usage.** `usage` is `held` when an active account holds the symbol,
`traded` when it has transactions but no holding, `watched` when it is only on
the watchlist or in an alert, and `unused` otherwise. `quantity` is the total
held across active accounts, from the same ledger replay as the `holdings`
dataset. `accounts` lists active accounts with a transaction in the symbol, a
transfer of it in, or a current holding. `alerts` counts saved alerts in every
state.

**Income calendar.** Rows are grouped by year, account, symbol and the
transaction's input currency, and only include payments with a complete
`YYYY-MM-DD` date. Interest without a symbol has a blank symbol. `amount` is
the income the ledger records: the amount of a dividend or interest payment,
and quantity × price for a reinvested dividend. `months` lists the month
numbers paid, from 1 to 12.

**Holding periods.** Periods follow the ledger's own replay, so buys, sells,
reinvested dividends, splits and transfers change quantities exactly as they do
in `holdings`. A period opens when the quantity rises above zero and closes
when it returns to zero. `increases` counts buys, reinvested dividends and
incoming transfers in the period; `decreases` counts sells and outgoing
transfers. Splits count as neither. `days_held` is null for an open period, so
results don't depend on today's date. A transfer in from an archived account
opens a period on the transfer date.

**Snapshot changes.** Each saved snapshot with a valid date is compared with
the previous one. When the two were saved in different currencies,
`same_currency` is false and every change is null. `change_pct` is a percentage
of the previous net worth, and null when that was zero. `market_change` is the
change in net worth less the change in contributions. `backfilled` is true for
snapshots marked as backfilled.

The datasets follow [normal report startup](cli-composable-reports.md#capability-inventory).
They read saved data only, never call a quote provider, and leave out archived
accounts. As with other script output, reports show raw names and symbols when
display privacy mode is on.
