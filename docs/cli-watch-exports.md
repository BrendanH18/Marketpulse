# Offline watchlist and alert exports

These ten additions extend saved metadata browsing without fetching quotes,
evaluating alerts, sending notifications, recording snapshots, or changing saved
order. Examples use fictional symbols. All filters run before sorting and paging;
counts describe all matching rows before paging.

21. `marketpulse watch list --csv` exports `position,symbol` with a header even
    for an empty list. Position always refers to the original, one-based saved
    position, including when output is filtered, sorted, or paged.
22. `marketpulse watch list --descending` reverses offline output before paging.
    Combine with `--alphabetical` for reverse alphabetical output.
23. `marketpulse watch list --exclude-symbol ALPHA --exclude-symbol BETA.TO`
    omits exact symbols, ignoring case and surrounding whitespace. Other saved
    symbols keep their order. This filter implies offline output.
24. `marketpulse watch list --json --page-info --offset 1 --limit 2` wraps the
    symbol array in `items` and reports `total`, `offset`, `limit`, `returned`,
    and `next_offset`. `total` counts filtered symbols before paging; `limit`
    is null when omitted and `next_offset` is null when there are no more items.
    `--page-info` requires `--json`; the existing bare JSON array stays the default.
25. `marketpulse alerts list --csv` exports every alert metadata field plus
    computed `state`, in stable column order. Notes with commas, newlines, and
    Unicode are CSV-quoted. JSON and CSV are raw, **unmasked** exports even in
    privacy mode. Legacy nonfinite thresholds export as JSON null or an empty
    CSV field, matching existing JSON inspection behavior.
26. `marketpulse alerts list --search fiction` finds text in either symbol or
    note, ignoring case, and combines with existing symbol/state/condition filters.
27. `marketpulse alerts list --sort symbol` sorts by `id`, `symbol`, `state`, or
    `condition`, breaking ties by alert ID. With no sort, existing saved query
    order is preserved.
28. `marketpulse alerts list --descending` reverses the selected order before
    pagination; it also works with the existing default order.
29. `marketpulse alerts list --limit 5` returns at most five matching alerts.
    The limit must be positive and applies to table, JSON, or CSV output.
30. `marketpulse alerts list --offset 5` skips the first five matching alerts.
    The offset must be nonnegative. A page beyond the end returns an empty JSON
    array or a CSV header, as appropriate.

For either list command, select only one of `--json`, `--csv`, and `--count`.
For example, `marketpulse alerts list --search fiction --count --limit 1`
prints the full matching count rather than a paginated count.
