# Offline inventory exports

These ten additions extend account and configured-asset browsing. Exported JSON
and CSV contain raw, unmasked metadata, even when privacy mode is enabled.
CSV preserves commas, quotes and line breaks through standard CSV quoting.
These commands do not fetch quotes or create valuation snapshots.

1. `marketpulse accounts list --csv` exports account metadata with a header,
   including when the result is empty. Archived accounts remain hidden unless
   `--archived` is supplied.
2. `marketpulse accounts list --count` prints the matching account count before
   pagination. Existing account filters still apply.
3. `marketpulse accounts list --limit 10` limits the page and implies offline
   metadata output.
4. `marketpulse accounts list --offset 10` skips matches after filtering and
   sorting, and implies offline metadata output.
5. `marketpulse accounts list --json --page-info --limit 10` wraps JSON records
   in `items` alongside `total`, `offset`, `limit`, `returned`, and `next_offset`.
6. `marketpulse asset list --csv` exports configured asset metadata, including
   the explicit classification and fixed-income terms.
7. `marketpulse asset list --count --kind manual` counts matching definitions
   before pagination.
8. `marketpulse asset list --json --page-info --limit 10` adds the same JSON
   pagination envelope as account browsing.
9. `marketpulse asset list --symbol ART --json` selects an exact configured
   symbol; surrounding whitespace and letter case are ignored.
10. `marketpulse asset list --unclassified --json` finds definitions without an
    explicit asset class. This inspects metadata, not inferred valuation classes.

Existing JSON output stays an array unless `--page-info` is supplied. For both
inventories, `total` counts all filtered matches, `limit` is null when unlimited,
and `next_offset` is null on the final or empty page. Counts ignore page bounds.
`--json`, `--csv`, and `--count` are mutually exclusive; `--page-info` requires
`--json`. Limits must be positive and offsets nonnegative. Filters compose by
intersection, so `--unclassified --class fixed_income` yields no matches.

For example, to export the second page of active CAD accounts in name order:

```bash
marketpulse accounts list --csv --currency CAD --sort name --offset 10 --limit 10 > accounts.csv
marketpulse asset list --json --unclassified --sort symbol --limit 20 --page-info
```
