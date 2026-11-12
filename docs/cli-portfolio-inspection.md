# Offline tax, allocation and holdings inspection

[User guide](usage.md) · [Issue #128](https://github.com/BrendanH18/Marketpulse/issues/128)

Thirty additions let you select, sort and export what the capital gains report,
the allocation view and the priced holdings and performance views already
calculate. Each guide numbers ten capabilities and gives examples using
fictional data.

| Improvements | Guide | Area |
| --- | --- | --- |
| 1–10 | [Capital gains report inspection](cli-tax-inspection.md) | `tax` |
| 11–20 | [Allocation and rebalancing targets](cli-allocation-targets.md) | `allocation` |
| 21–30 | [Priced holdings and performance](cli-holdings-performance.md) | `holdings` and `perf` |

Every option works on results that are already calculated. The tax report is
always computed in full before rows are chosen, so a filter never changes a
disposition's ACB or gain. Allocation weights and holdings weights still refer
to the whole portfolio. ACB, FX, tax, valuation and rebalancing math are
unchanged, and no option adds a network call: pricing uses the same quotes and
offline cache as the plain commands, and `allocation --show-targets`,
`allocation --dry-run` and `tax --room` price nothing.

Human output still masks amounts in privacy mode. JSON, CSV and counts are raw
and unmasked, like `positions --json`. Archived accounts stay hidden from
selection and are named only as archived where pooled tax rows need them. The
plain `tax`, `allocation`, `holdings` and `perf` commands print exactly what
they printed before.
