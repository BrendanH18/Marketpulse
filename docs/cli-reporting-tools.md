# Offline reporting and backup tools

[User guide](usage.md) · [Earlier CLI improvements](cli-workflows.md)

The second batch of 30 local-first CLI improvements is tracked in
[#106](https://github.com/BrendanH18/Marketpulse/issues/106). The numbered guides
cover each addition and its command syntax:

| Improvements | Guide | Purpose |
| --- | --- | --- |
| 1–10 | [Activity reports](cli-activity-reports.md) | Export activity, count matches, group counts, and filter notes or IDs |
| 11–20 | [Inventory details](cli-inventory-details.md) | Inspect accounts/assets and sort or page metadata |
| 21–30 | [Backup tools](cli-backup-tools.md) | Find, inspect and verify backups; capture creation receipts |

These commands use recorded data without fetching prices. The existing priced
`accounts list` default still applies unless `--offline` or `--json` is used.
Activity summaries count records; they do not calculate investment returns or
combine monetary values. Financial calculations and desktop JSON contracts
are unchanged.

Examples use fictional data. CSV exports and JSON reports contain unmasked
values even in privacy mode. Protect redirected output as you would a ledger
export. Backup verification reads the selected file without restoring it.
