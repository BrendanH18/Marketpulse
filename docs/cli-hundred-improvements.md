# One hundred recording, ledger, lookup, overview and terminal app improvements

[User guide](usage.md) · [Issue #130](https://github.com/BrendanH18/Marketpulse/issues/130)

One hundred additions across five areas that earlier batches mostly left alone:
recording commands, ledger maintenance and data exchange, market lookups, the
status and income overviews, and the terminal app. Each guide numbers ten
capabilities and gives examples using fictional data.

| Improvements | Guide | Area |
| --- | --- | --- |
| 1–10 | [Recording previews, receipts and shortcuts](cli-recording-receipts.md) | `buy`, `sell`, `dividend`, `transfer` and the other recording commands |
| 11–20 | [Recording checks and shortcuts](cli-recording-checks.md) | warnings, `--strict`, `withdraw all`, `--per-unit`, split ratios |
| 21–30 | [Ledger maintenance](cli-ledger-maintenance.md) | `txn` and `undo` |
| 31–40 | [Data exchange](cli-data-exchange.md) | `import`, `export` and `backfill` |
| 41–50 | [Chart and quote lookups](cli-market-lookups.md) | `chart` and `quote` |
| 51–60 | [Comparisons and symbol search](cli-market-comparisons.md) | `compare` and `search` |
| 61–70 | [Status and dashboard overview](cli-overview-status-summary.md) | `status` and `summary` |
| 71–80 | [Income overview](cli-overview-income.md) | `income` |
| 81–90 | [Terminal app navigation](tui-navigation.md) | TUI keys for moving around |
| 91–100 | [Terminal app productivity](tui-productivity.md) | TUI sorting, copying, pickers and command palette |

Every addition is opt-in. The plain commands print and save exactly what they
did before, and golden tests captured from the earlier code check that.
`status --json` and `status --waybar` are stable contracts and are unchanged.
ACB, FX, tax and valuation math are unchanged. No option adds a network
endpoint: market lookups reuse the plain command's request and filter or format
the result locally, and recording checks read only the offline quote cache.

Human output still masks amounts in privacy mode. JSON, CSV and single-value
outputs for scripts are raw and unmasked, as in earlier batches. New totals
leave archived accounts out; `export` options select from the full ledger file,
which has always included them. No existing terminal app key was rebound.
