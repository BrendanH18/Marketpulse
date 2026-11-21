# One thousand offline reporting improvements

Both `marketpulse report SOURCE` and `marketpulse summarize SOURCE` accept five
new datasets. Each supports the 197 shared operations listed by
`marketpulse report report-operations`. That gives 985 new dataset/operation
combinations. The 15 filter presets in the table below bring the total to
**1,000**. A shared operation or preset counts once per dataset.

| Dataset | Rows | Presets |
| --- | --- | --- |
| `automation-runs` | Recorded automation runs, newest first, plus the most recent failure if it has aged out of the rolling history. | `failed` finds failed runs, `stale` finds runs that used stale quotes, and `quote-errors` finds runs with at least one quote error. |
| `transaction-months` | One row for each active account and calendar month with recorded activity, including its date range, transaction count, types and number of distinct symbols. | `deposits`, `withdrawals`, and `transfers` find months with the named transaction type. |
| `account-symbols` | One row for each symbol with recorded activity in an active account, including its date range, transaction count and types. | `buys`, `sales`, and `dividends` find account and symbol pairs with the named entry type. |
| `broker-transaction-codes` | Known Questrade activity and Wealthsimple transaction codes and how the importer handles them. | `supported` finds codes with a transaction type mapping, `skipped` finds explicitly skipped codes, and `trade-actions` finds Questrade trades whose mapping depends on the Action column. |
| `transaction-csv-columns` | Transaction export headers in order, with the aliases and required headers for generic CSV import. | `required` and `optional` distinguish headers required for every generic import, and `account-routing` finds the account and target account headers. |

`SOURCE --describe` lists the available presets and their equivalent filters.
Presets combine with other filters using AND. They filter dataset rows before
grouping, so a summary of `transaction-months --preset deposits` summarizes
months that have deposits and retains each selected month's all-activity count.

```bash
# Show the date and counts for runs with quote errors.
marketpulse report automation-runs --preset quote-errors \
  --fields ran_at,stale_count,quote_error_count

# Count the months with withdrawals for each account.
marketpulse summarize transaction-months --preset withdrawals \
  --group-by account --metric months=count

# Check why the broker importer skips a known code.
marketpulse report broker-transaction-codes --preset skipped \
  --where profile=questrade --fields code,reason

# Look up accepted headings for account routing before preparing a CSV.
marketpulse report transaction-csv-columns --preset account-routing
```

Automation counts are null when a run didn't record the corresponding result.
They are zero when the result was recorded and empty. `retained_failure`
identifies the separately retained failure. A quote error by itself doesn't
mark the run as failed.

The activity reports count recorded entries. A transfer from an active account
appears for each active endpoint, so summing across accounts can count the same
transfer twice. Transactions originating from archived accounts are excluded.
`account-symbols` includes historical activity for symbols even after they are
sold. These reports read saved data through [normal report startup](cli-composable-reports.md#capability-inventory).
They do not fetch quotes or calculate market values. As with other reports,
script output contains raw names and symbols when display privacy mode is on.

The two CSV reference datasets can be queried without opening saved data.
Mapped broker codes still go through normal row validation. Generic CSV imports
can require other values depending on the transaction type or the account
assignment for a row.
