# Offline inventory selection

[User guide](usage.md) · [Inventory exports](cli-inventory-exports.md)

Thirty additions under [#122](https://github.com/BrendanH18/Marketpulse/issues/122)
extend saved account, configured-asset, watchlist and alert inventories.

| Improvements | Guide | Purpose |
| --- | --- | --- |
| 1–10 | [Account selection](cli-account-selection.md) | Exclude accounts, select registration and metadata, and count groups |
| 11–20 | [Asset selection](cli-asset-selection.md) | Select fixed-income rates, start/maturity dates and compounding, and order terms |
| 21–30 | [Watchlist and alert selection](cli-saved-selection.md) | Select saved positions and alert membership, filter alerts and count groups |

The detailed guides number ten improvements each. Filters compose with the
existing options before counting, sorting and pagination. Summaries count the
entire matching inventory before pagination; they never sum money or convert
currencies. New account and watchlist selection options imply offline output.
Asset and alert inventories always read saved metadata offline. These options
neither request quotes nor write valuation snapshots.

Account inventories hide archived accounts unless `--archived` is explicit.
Asset inventory describes configured metadata, including definitions without an
active holding. Watchlist alert membership includes paused and triggered saved
alerts. It does not evaluate current prices.

Human output respects existing privacy settings. JSON and CSV export raw
metadata even with privacy enabled. Existing default command behavior is
preserved.
