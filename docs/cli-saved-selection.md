# Saved watchlist and alert selection

These ten additions inspect local saved metadata. They never fetch prices,
record snapshots, or change watchlist order or alert state. JSON and CSV remain
unmasked exports, including in privacy mode.

1. `watch list --symbol ZETA --symbol BETA` includes any exact symbol, ignoring
   case and surrounding whitespace. Blank symbols are rejected.
2. `watch list --min-position 2` selects saved positions starting at 2, inclusive.
3. `watch list --max-position 4` selects saved positions through 4, inclusive.
   Positions are positive, one-based and evaluated before ordering or pagination.
   An inverted position range is rejected.
4. `watch list --with-alert` includes symbols with any saved alert;
   `--without-alert` includes those with none. Paused and triggered alerts count.
5. `alerts list --symbols ZETA --symbols BETA` selects any exact symbol, ignoring
   case and surrounding whitespace. Blank values are rejected. Combining this
   with the existing `--symbol` option intersects both selections.
6. `alerts list --exclude-state paused --exclude-state triggered` excludes any
   listed state. Choices are `armed`, `paused`, and `triggered` (case-insensitive).
7. `alerts list --note entry` searches only note text, ignoring case.
8. `alerts list --summary symbol` counts selected alerts by exact symbol.
9. `alerts list --summary state` counts selected alerts by their displayed state.
10. `alerts list --summary condition` counts selected alerts by condition.

All four watch filters imply offline output. Existing search, exclusions,
ordering, counts and exports compose with the selection. CSV positions always
refer to the saved order, even with alphabetical or descending display.

Alert summaries count all filtered matches before `--offset` or `--limit` and
sort groups alphabetically. `--json` returns `[{"group": "ZETA", "count": 2}]`;
`--csv` returns `group,count` columns. Empty selections produce `[]` or a CSV
header. Human summaries show the same counts. `--count` and `--page-info` cannot
be combined with a summary. Summaries do not total or compare thresholds.

```bash
marketpulse watch list --min-position 2 --max-position 10 --without-alert --csv
marketpulse alerts list --symbols ZETA --exclude-state paused --note entry --json
marketpulse alerts list --summary state --csv
```
