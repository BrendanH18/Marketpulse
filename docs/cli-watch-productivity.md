# Offline watchlist and alert productivity

These improvements use saved local data without looking up prices. They are
items 11–20 of the 30-improvement productivity batch (#108).

11. **Watchlist search:** `marketpulse watch list --search .TO --json` matches
    symbol substrings without case sensitivity.
12. **Watchlist pages:** `marketpulse watch list --offset 10 --limit 5 --json`
    skips matches and limits results. Both options imply offline output. Human
    output retains each symbol's saved position, including when filtered.
13. **Watchlist counts:** `marketpulse watch list --search .TO --count` prints
    the match count before pagination. `--count` takes precedence over `--json`.
14. **Alphabetical watchlists:** `marketpulse watch list --alphabetical --json`
    sorts the displayed results without changing saved order. Sorting comes
    before pagination. This option also implies offline output.
15. **Full alert inspection:** `marketpulse alerts show 1 --json` includes the
    complete note, threshold, state and trigger history. Without `--json`, the
    field table masks the threshold when privacy mode is enabled. JSON is
    unmasked, as with existing alert exports. Invalid legacy thresholds are null.
16. **Edit alert thresholds:** `marketpulse alerts edit 1 --threshold 120`
    requires a finite, positive value.
17. **Edit alert conditions:** `marketpulse alerts edit 1 --condition below`
    accepts `above`, `below`, `up_pct`, and `down_pct` (case insensitive).
18. **Replace or clear alert notes:** `marketpulse alerts edit 1 --note 'Review later'`
    replaces the note; `--note ''` clears it. Notes render as plain text.
19. **Count saved alerts:** `marketpulse alerts list --state armed --count`
    prints the filtered count. Count takes precedence over `--json`.
20. **Filter by alert condition:** `marketpulse alerts list --condition below --json`
    composes with `--symbol`, `--state`, and `--count`.

Alert edits can combine threshold, condition and note changes in one atomic
operation. Missing IDs, invalid criteria and empty edits fail without changing
saved alerts. Edits preserve paused/armed state and trigger history. Use
`marketpulse alerts rearm 1` explicitly to clear that history and allow another
notification from a matching fresh quote; editing alone does not rearm an alert.
No edit evaluates quotes or sends notifications.
