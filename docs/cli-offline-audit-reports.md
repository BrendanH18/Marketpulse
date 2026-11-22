# Offline audit reports

Use `marketpulse report SOURCE` to inspect saved records and `marketpulse
summarize SOURCE` to group them. These five datasets each support the 197
shared operations cataloged by `marketpulse report report-operations`. The
985 new dataset and operation combinations plus the 15 named filters below
give **1,000 new reporting capabilities**. The two commands share this count.

| Dataset | What each row shows | `--preset` choices |
| --- | --- | --- |
| `transaction-currency-audit` | One transaction in an active account, with the recorded currency, the resolved input currency, and how it was chosen. | `explicit` for recorded currencies, `inferred` for currencies from the symbol or account, and `cross-currency` for resolved input currencies different from the account currency. |
| `transfer-routes` | One directed route between two active accounts, with the date range, number of transfers, transferred symbols, and effective transaction currencies. | `same-currency` and `cross-currency` compare the two accounts' currencies. `repeat` keeps routes with at least two transfers. |
| `watchlist-quote-coverage` | One watched symbol in watchlist order, with any saved quote's provider, currency, and fetch time. | `cached`, `uncached`, and `missing-fetch-time`. The last preset requires a saved quote with an unknown fetch time. |
| `alert-quote-coverage` | One saved alert with its active state, recorded trigger time, and any saved quote's provider, currency, and fetch time. | `active` keeps alerts eligible for evaluation, `uncached` keeps alerts whose symbols lack a saved quote, and `triggered` keeps alerts with a recorded trigger time. |
| `snapshot-month-coverage` | One calendar month within the saved snapshot history, with observed dates, expected and missing days, currencies, and the number of backfilled days. | `gaps` keeps months missing at least one expected day, `backfilled` keeps months with backfilled snapshots, and `mixed-currency` keeps months saved in more than one currency. |

`SOURCE --describe` lists the fields, preset names, and their equivalent CLI
filters. Presets combine with other filters using AND and select rows before
`summarize` groups them.

```bash
# Show entries whose resolved input currency differs from the account's.
marketpulse report transaction-currency-audit --preset cross-currency \
  --fields transaction_id,date,account,symbol,account_currency,effective_currency

# Find routes with repeated transfers and see the most-used routes first.
marketpulse report transfer-routes --preset repeat --sort transactions --descending

# Count watched symbols missing from the local quote cache.
marketpulse report watchlist-quote-coverage --preset uncached --count

# Count missing snapshot days by month.
marketpulse summarize snapshot-month-coverage --preset gaps \
  --group-by month --metric missing=number-sum:missing_days
```

Currency audit rows use `explicit`, `symbol`, or `account` for `currency_source`.
The recorded currency is null when the transaction left it blank.
`effective_currency` is the resolved input currency, independent of ledger
replay. In particular, replay records sale proceeds in the holding's currency.
The transfer route direction follows the recorded source and destination.
Routes with an archived or missing endpoint are omitted. The currency audit
shows the originating account only.

Quote coverage uses the local cache and can include old quotes. A fetch time
is expressed in UTC, or null if unavailable. Trigger times come from saved
alert state. The `active` field and preset follow the same validation as
`alerts list`, which treats legacy alerts with blank symbols or invalid
thresholds as inactive. These queries make no provider calls.

Snapshot coverage counts calendar days from the earliest through the latest
saved snapshot with a valid `YYYY-MM-DD` date, inclusive. The first and last
months count only days inside that range. Rows with invalid dates are skipped.
An empty month within the range has null observed dates, an empty currency
list, and every calendar day counted as missing. Backfilled days count only
snapshots explicitly marked as backfilled.

The datasets follow [normal report startup](cli-composable-reports.md#capability-inventory).
As with other script output, reports show raw names and symbols when display
privacy mode is on.
