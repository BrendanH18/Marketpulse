# Offline report refinements

[User guide](usage.md) · [Issue #124](https://github.com/BrendanH18/Marketpulse/issues/124)

Thirty additions extend offline account inventories, native-currency income and
sale reports, and recorded snapshot history. Each guide numbers ten capabilities
and gives examples using fictional data.

| Improvements | Guide | Area |
| --- | --- | --- |
| 1–10 | [Account refinements](cli-account-refinements.md) | Saved account inventory |
| 11–20 | [Income refinements](cli-income-refinements.md) | Realized sales and income payouts |
| 21–30 | [Snapshot refinements](cli-snapshot-refinements.md) | Recorded daily history |

These commands select saved records without fetching prices or recording new
valuation snapshots. Filters compose with existing selection controls. Defaults
remain unchanged. Ordinary account and ledger reports hide archived accounts;
account inventories require an explicit option to include them.

Sales and payouts retain their native currencies and existing calculations.
They are ledger reports, not substitutes for `marketpulse tax`. Snapshot changes
retain the existing comparison with the previous recorded snapshot, even when
that previous record is filtered out.

Human monetary output respects privacy mode. JSON and CSV remain raw exports,
including when privacy mode is enabled.
