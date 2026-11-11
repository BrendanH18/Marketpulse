# Offline report browsing

[User guide](usage.md) · [Original ledger reports](cli-ledger-reports.md)

These 30 improvements extend the existing offline reports under
[#116](https://github.com/BrendanH18/Marketpulse/issues/116).
The linked guides number each batch of ten and show examples:

| Improvements | Guide | Purpose |
| --- | --- | --- |
| 1–10 | [Positions and cash browsing](cli-positions-browsing.md) | Position pages and holding-date filters; searchable, sortable cash balances |
| 11–20 | [Sales and income browsing](cli-income-browsing.md) | Currency filters, counts, ordering and pages for realized gains and payouts |
| 21–30 | [Snapshot browsing](cli-snapshot-browsing.md) | Calendar and value filters, ordering, pages and change filters |

All commands remain offline. They read existing ledger or snapshot data without
requesting prices, recording snapshots, or changing transactions. Archived
accounts remain hidden from position, cash, realized and payout reports.
Snapshot history retains its original recorded portfolio totals.

Amounts stay in their recorded currencies. Sorting or filtering numeric amounts
does not convert them; use a currency filter when comparing amounts in one
currency. Realized gains remain an average-cost ledger report, not a tax report.
Human output respects privacy mode; JSON and CSV intentionally export unmasked
values. Protect exported files like the ledger itself.
