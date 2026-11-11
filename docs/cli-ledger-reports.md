# Offline ledger reports and diagnostics

[User guide](usage.md) · [CLI productivity](cli-productivity.md)

This fourth batch of 30 improvements is tracked in
[#111](https://github.com/BrendanH18/Marketpulse/issues/111).
Each guide numbers its ten additions and includes runnable examples using
fictional records:

| Improvements | Guide | Purpose |
| --- | --- | --- |
| 1–10 | [Positions and cash](cli-positions-cash.md) | Open positions at cost and ledger cash balances, with filters, sorting and an overdraft check |
| 11–20 | [Realized gains and payouts](cli-realized-payouts.md) | Sales and dividend, DRIP and interest income in native currency, with grouped totals |
| 21–30 | [Snapshots and diagnostics](cli-snapshots-diagnostics.md) | Snapshot history, cached quotes, quote JSON, and offline, JSON and strict `doctor` runs |

These commands read the ledger replay, the snapshot table and the saved quote
cache. Except for a live `quote --json` and `doctor` without `--offline`, they
make no network requests. Amounts stay in their recorded currency and are never
converted; `realized` is not the tax report. Archived accounts remain excluded.
Human tables respect privacy mode. JSON and CSV output contains unmasked values,
including in privacy mode; protect redirected output like a ledger export.
