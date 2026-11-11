# Offline report filters

[User guide](usage.md) · [Report browsing](cli-report-browsing.md)

Thirty additive improvements under
[#118](https://github.com/BrendanH18/Marketpulse/issues/118) extend existing
reports without fetching quotes, recording snapshots, or editing ledger rows.

| Improvements | Guide | Purpose |
| --- | --- | --- |
| 1–10 | [Sales and income filters](cli-income-filters.md) | Search, amount bounds, ordering and income page metadata |
| 11–20 | [Snapshot filters](cli-snapshot-filters.md) | Book, contribution and change bounds, change direction and date exclusions |
| 21–30 | [Saved alert filters](cli-alert-filters.md) | Threshold bounds, notes, trigger dates, exclusions and pages |

All examples use fictional symbols and dates. Values remain in their recorded
currencies or alert-condition units; these filters do not perform conversion.
Archived accounts remain excluded from sales and income reports. Snapshot
history retains recorded totals. Human output respects privacy mode, while JSON
and CSV intentionally expose raw values. Existing default output stays unchanged.
