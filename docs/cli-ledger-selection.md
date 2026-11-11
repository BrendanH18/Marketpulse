# Offline ledger selection

[User guide](usage.md) · [Report filters](cli-report-filters.md)

Thirty additions under [#120](https://github.com/BrendanH18/Marketpulse/issues/120)
extend the existing position, cash and activity commands. Each numbered guide
describes the exact flags and includes fictional examples.

| Improvements | Guide | Purpose |
| --- | --- | --- |
| 1–10 | [Position selection](cli-position-cash-selection.md) | Search account metadata, select exact symbols, bound quantities and book costs, and order by average cost |
| 11–20 | [Cash selection](cli-position-cash-selection.md) | Page balances, filter positive balances and amount ranges, and exclude currencies or accounts |
| 21–30 | [Activity selection](cli-activity-selection.md) | Filter calendar months, excluded dates/currencies, recorded amounts and fees; count by quarter or account type |

All filters compose with existing options before sorting, counting and paging.
These commands read the local ledger without requesting quotes or recording
snapshots. Archived accounts remain hidden. Numeric amounts retain their
recorded currencies; filters and sorting do not convert currencies or calculate
investment returns. Use a currency filter when comparing monetary values.

Human output respects privacy mode. JSON and CSV contain raw values, including
when privacy mode is enabled; protect exported files like the ledger itself.
Existing default output is unchanged.
