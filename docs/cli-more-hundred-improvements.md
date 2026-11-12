# One hundred more offline CLI improvements

[User guide](usage.md) · [Issue #134](https://github.com/BrendanH18/Marketpulse/issues/134)

This batch adds 100 opt-in capabilities beyond the previous
[100 offline workflow improvements](cli-next-hundred-improvements.md).
Each numbered guide provides concrete commands and describes selection and
output behavior.

| Improvements | Guide | Area |
| --- | --- | --- |
| 1–25 | [Realized gains and payouts](cli-more-realized.md) | Ledger event selection, ordering and summaries |
| 26–50 | [Asset metadata](cli-more-assets.md) | Metadata filters, ordering, summaries and exports |
| 51–75 | [Snapshots and backups](cli-more-snapshots-backups.md) | Recorded history and backup inventory inspection |
| 76–100 | [Saved targets and discovery](cli-more-discovery-targets.md) | Saved target inspection and command selection |

All additions work offline. They preserve existing command defaults, financial
calculations, desktop bridge payloads and `status --json`. They add no network
endpoints. Ordinary portfolio event reports exclude archived accounts. Count
summaries never combine monetary amounts across currencies; existing payout
amount groups retain currency boundaries. Human financial output respects
privacy mode; explicitly selected script formats remain raw and unmasked.

Tests and examples use fictional data. Before manual runs that open the tracker,
set both `MARKETPULSE_DATA` and `MARKETPULSE_CONFIG` to scratch paths as described
in the [data guide](data.md).
