# Allocation and rebalancing targets

[User guide](usage.md) · [Offline tax, allocation and holdings inspection](cli-portfolio-inspection.md)

These options extend `marketpulse allocation`, which shows your portfolio split
by asset class, account or currency and, with asset-class targets saved,
compares it with those targets. They are items 11–20 of the 30-improvement
batch (#128). They choose and present the existing breakdown and rebalancing
results; the valuation and rebalancing math is unchanged.

The examples use a fictional portfolio worth $2,000: Equity $1,000 (50%), ETF
$600 (30%) and Cash $400 (20%), with targets Equity 40, ETF 40 and Cash 20.

11. **Saved targets, offline:** `marketpulse allocation --show-targets` lists
    the saved targets and how much of 100% is left untargeted, read straight
    from the database. It doesn't fetch prices or record a snapshot. Add
    `--json` for
    `{"targets": [{"bucket": "cash", "label": "Cash", "target": 20.0}, …], "total": 100.0, "unallocated": 0.0}`.
    It can't be combined with other options except `--json`.
12. **Remove one target:** `marketpulse allocation -q --remove-target cash`
    drops one class and keeps the rest; repeat it for several. Every
    `--remove-target` and `--target` is checked before anything is saved: an
    unknown class or a class without a saved target is an error and nothing
    changes. It combines with `--target` for other classes, but not with
    `--clear-targets` or with a `--target` for the same class.
13. **Dry run:** `marketpulse allocation --dry-run --target crypto=5 --remove-target cash`
    validates the change and prints what would be saved, for example
    `Would save targets (85% allocated). Nothing saved (dry run).` followed by
    each class. Nothing is written and holdings aren't priced. It needs
    `--target`, `--remove-target` or `--clear-targets`.
14. **JSON:** `marketpulse allocation --json` prints
    `{"by", "base", "total", "rows", "rebalance"}`. `rows` has `key`, `label`,
    `value` and `weight` per group; `rebalance` has `bucket`, `label`, `value`,
    `weight`, `target`, `drift` and `delta` (positive to buy, negative to sell,
    in the base currency) and is empty unless `--by class` with targets saved.
    With `--drift-only` it prints just the `rebalance` list.
15. **CSV:** `marketpulse allocation --by account --csv > allocation.csv` writes
    the breakdown rows (`key,label,value,weight`) to stdout with a header;
    `--csv --drift-only` writes the rebalancing rows instead.
16. **Sorting:** `marketpulse allocation --sort name` orders rows by `value`,
    `weight` or `name` (ties by name); `--descending` reverses the order,
    including the default (largest value first for the breakdown, largest
    amount to rebalance first for the rebalancing table). Sorting applies to
    both tables.
17. **Minimum weight:** `marketpulse allocation --min-weight 25` hides groups
    below 25% of the portfolio (Cash here). Weights stay shares of the whole
    portfolio and `total` is unchanged. It filters the breakdown only.
18. **Drift only:** `marketpulse allocation --drift-only` prints only the
    rebalancing table. Without saved targets it says so (JSON `[]`).
19. **Drift threshold and exit code:**
    `marketpulse allocation --drift-only --threshold 5` keeps classes whose
    weight is more than 5 percentage points from target (Equity +10, ETF −10).
    Add `--exit-code` to exit with status 1 when any class is listed, after
    printing the output:

    ```bash
    marketpulse allocation --drift-only --threshold 5 --exit-code || echo "Fictional portfolio needs rebalancing"
    ```

    `--exit-code` needs `--threshold`.
20. **Counting:** `marketpulse allocation --count` prints the number of
    breakdown rows that would be shown (after `--min-weight`); with
    `--drift-only` it counts the rebalancing rows (after `--threshold`).

## Rules and what stays the same

- `marketpulse allocation` with none of these options prints exactly what it
  printed before, and `--by`, `--target`, `--clear-targets` and `--quiet` keep
  their meaning. Targets still can't add up to more than 100%.
- `--json` and `--csv` are raw and unmasked, as elsewhere in the CLI. The
  human tables still mask amounts in privacy mode. Percentages are never masked.
- `--json`, `--csv` and `--count` are mutually exclusive, and none of them
  combines with a target change; save targets first (`-q`), then read them.
  `--quiet` combines with target changes only. Drift options (`--drift-only`,
  `--threshold`, `--exit-code`) need `--by class`, because targets are per
  asset class. Conflicts are usage errors (exit 2).
- Archived accounts stay out of every breakdown and total.

| Code | Meaning |
| --- | --- |
| 0 | Success; with `--exit-code`, no class drifts beyond `--threshold`. |
| 1 | `--exit-code` found drift beyond the threshold (output is still printed), or an error such as an unknown asset class. |
| 2 | Usage error, such as conflicting options. |
