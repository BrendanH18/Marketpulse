# One hundred offline CLI workflow improvements

[User guide](usage.md) · [Issue #132](https://github.com/BrendanH18/Marketpulse/issues/132)

This batch adds 100 capabilities beyond the earlier
[recording, ledger, lookup, overview and TUI batch](cli-hundred-improvements.md).
The numbered guides give each addition a concrete command example:

| Improvements | Guide | Area |
| --- | --- | --- |
| 1–25 | [Ledger selection and exports](cli-next-ledger.md) | Activity selection, ordering and ledger exports |
| 26–50 | [Inventory inspection](cli-next-inventory.md) | Positions, cash and account selection and summaries |
| 51–75 | [Saved items and configuration](cli-next-saved.md) | Watchlists, alerts, themes and settings |
| 76–100 | [Command discovery and diagnostics](cli-next-discovery.md) | Searchable command catalog, provider status and doctor |

All additions are opt-in and offline. Existing defaults, financial calculations,
`status --json`, the desktop bridge and existing network endpoints are unchanged.
Human financial output respects privacy mode; JSON and CSV remain raw, unmasked
script outputs. Count summaries describe matching rows and never sum monetary
amounts across currencies. Ordinary portfolio inspection excludes archived
accounts; ledger export retains its existing full-ledger semantics.

Examples and tests use fictional data. For manual commands that open the tracker,
set both `MARKETPULSE_DATA` and `MARKETPULSE_CONFIG` to scratch paths as described
in the [data guide](data.md).
