# Saved alert filtering

[User guide](usage.md) · [All 30 improvements](cli-report-filters.md)

`marketpulse alerts list` inspects saved metadata offline. It never evaluates
prices or sends notifications. The ten improvements in this batch are:

21. `--min-threshold N`: inclusive threshold minimum.
22. `--max-threshold N`: inclusive threshold maximum.
23. `--with-note`: require a nonblank note.
24. `--without-note`: require an empty or whitespace-only note.
25. `--triggered-since YYYY-MM-DD`: inclusive trigger-date minimum.
26. `--triggered-until YYYY-MM-DD`: inclusive trigger-date maximum.
27. `--exclude-symbol SYMBOL`: omit exact symbols, case-insensitively; repeat it.
28. `--page-info --json`: wrap the usual items in a pagination envelope.
29. `--sort threshold`: numeric threshold order.
30. `--sort triggered-at`: timestamp order.

```bash
marketpulse alerts list --with-note --exclude-symbol FICTION --json
marketpulse alerts list --condition above --min-threshold 50 --max-threshold 100 --csv
marketpulse alerts list --triggered-since 2024-01-01 --triggered-until 2024-12-31
marketpulse alerts list --sort threshold --descending --limit 10 --json --page-info
```

Thresholds keep each alert condition's units: price thresholds and percentage
thresholds are not directly comparable. Select `--condition` and a symbol when
that distinction matters. Bounds must be finite and ordered. Legacy nonfinite
thresholds do not match numeric bounds and sort after known thresholds in either
direction. Missing trigger timestamps also sort last. Equal sort values use
alert ID as a tie breaker; `--descending` reverses that order as well.

Trigger-date filters compare the calendar date saved in `triggered_at`, without
timezone conversion. They omit alerts with no trigger timestamp and include
paused alerts with matching retained history. Trigger history is the saved
current marker, not an event log; rearming can clear it.

Filters combine before sorting and pagination. `--count` counts all matches
before paging. Page metadata contains `items`, `total`, `offset`, `limit`,
`returned`, and `next_offset` (null at the end). Ordinary JSON remains an array.
Human output masks thresholds in privacy mode; JSON and CSV export raw values.
`--with-note` conflicts with `--without-note`; `--page-info` requires JSON.
