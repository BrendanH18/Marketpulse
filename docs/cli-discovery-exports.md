# Offline CLI discovery and exports

This fourth batch adds 30 improvements under
[#110](https://github.com/BrendanH18/Marketpulse/issues/110).

| Improvements | Guide | Purpose |
| --- | --- | --- |
| 1–10 | [Inventory exports](cli-inventory-exports.md) | Export, count and page account and asset metadata |
| 11–20 | [Activity discovery](cli-activity-discovery.md) | Filter entries by accounts, symbols and calendar fields; summarize institutions and weekdays |
| 21–30 | [Watchlist and alert exports](cli-watch-exports.md) | Export saved metadata and narrow, order and page local results |

All new reports use local data without fetching quotes or recording valuation
snapshots. Account and transaction browsing excludes archived accounts by default;
`accounts list --archived` explicitly includes archived account metadata.
CSV and JSON exports contain unmasked values even in privacy mode. Protect
redirected reports like a ledger export. Grouped activity reports count recorded
entries and do not calculate investment performance.

Use fictional scratch data for experimentation:

```bash
export MARKETPULSE_DATA="$(mktemp -d)"
export MARKETPULSE_CONFIG="$MARKETPULSE_DATA/config.toml"
marketpulse accounts add "Example TFSA" -t TFSA -i "Example Bank"
marketpulse accounts list --csv
marketpulse accounts list --json --limit 10 --page-info
marketpulse activity --institution "Example Bank" --summary weekday --json
marketpulse watch add ALPHA.TO BETA.TO
marketpulse watch list --csv
```
