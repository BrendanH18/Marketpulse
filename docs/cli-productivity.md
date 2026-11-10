# Offline CLI productivity

[User guide](usage.md) · [Reporting and backup tools](cli-reporting-tools.md)

This third batch of 30 improvements is tracked in
[#108](https://github.com/BrendanH18/Marketpulse/issues/108).
Each guide numbers its ten additions and includes runnable examples using
fictional records:

| Improvements | Guide | Purpose |
| --- | --- | --- |
| 1–10 | [Activity productivity](cli-activity-productivity.md) | Narrow activity, export grouped counts, and inspect page metadata |
| 11–20 | [Watchlists and alerts](cli-watch-productivity.md) | Browse saved symbols and inspect or maintain alerts offline |
| 21–30 | [Configuration productivity](cli-config-productivity.md) | Inspect defaults, reset individual settings, and validate configuration |

These additions use local data without fetching quotes. Activity reports
count recorded entries; they do not calculate investment performance.
Archived accounts remain excluded from activity browsing. CSV and JSON
activity and alert reports contain unmasked values, including in privacy
mode; protect redirected output like a ledger export. Configuration reports
always redact the provider API key.
