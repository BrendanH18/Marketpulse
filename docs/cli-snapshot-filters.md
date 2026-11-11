# Snapshot value and change filters

[User guide](usage.md) · [Snapshot browsing](cli-snapshot-browsing.md)

These improvements extend offline snapshot inspection under issue #118:

11. `snapshots --min-book VALUE`: inclusive recorded book-value minimum.
12. `snapshots --max-book VALUE`: inclusive recorded book-value maximum.
13. `snapshots --min-contributions VALUE`: inclusive recorded contribution minimum.
14. `snapshots --max-contributions VALUE`: inclusive recorded contribution maximum.
15. `snapshots --min-change VALUE`: inclusive known recorded-change minimum.
16. `snapshots --max-change VALUE`: inclusive known recorded-change maximum.
17. `snapshots --increases-only`: positive changes only.
18. `snapshots --decreases-only`: negative changes only.
19. `snapshots --unknown-change-only`: first snapshot or currency-switch comparisons.
20. `snapshots --exclude-date YYYY-MM-DD`: skip a date; repeat to skip several.

For example:

```bash
marketpulse snapshots --currency CAD --min-book 1000 --max-book 5000 --json
marketpulse snapshots --min-contributions 2000 --max-contributions 4000 --count
marketpulse snapshots --min-change -100 --max-change 100 --csv
marketpulse snapshots --increases-only --exclude-date 2024-01-02 --latest --json
marketpulse snapshots --unknown-change-only --json
```

Filters run before counts, ordering and pagination. Change always compares with
its previous recorded snapshot in the complete history, even when that previous
date is filtered out. Unknown changes do not match numeric change bounds.
Direction and unknown-change flags are mutually exclusive with each other and
with `--unchanged-only`. `--unknown-change-only` also rejects `--changed-only`
and numeric change bounds.

Bounds must be finite and minimums cannot exceed maximums. Amounts retain their
recorded currency; filter `--currency` to compare one currency. These commands
read saved snapshots without fetching prices or recording data. Human output
respects privacy mode; JSON and CSV contain unmasked values.
