# Account inventory refinements

[User guide](usage.md) · [Reporting refinements](cli-report-refinements.md)

These ten additions to `marketpulse accounts list` select saved metadata without
fetching prices or writing valuation snapshots:

1. Repeat `--type` to include several account types: `--type TFSA --type RRSP`.
2. Repeat `--currency` to include several configured currencies: `--currency CAD --currency USD`.
3. Repeat `--institution` to include several exact institution names:
   `--institution "Example North" --institution "Example South"`.
4. Repeat `--account` to include specific account IDs, names or unique active types:
   `--account 1 --account "Fictional Retirement"`. Invalid or ambiguous references
   fail rather than broadening the selection.
5. Repeat `--exclude-type` to omit account types: `--exclude-type CASH`.
6. Repeat `--exclude-currency` to omit configured currencies: `--exclude-currency USD`.
7. Repeat `--exclude-institution` to omit exact institution names:
   `--exclude-institution "Sample Bank"`.
8. Repeat `--exclude-search` to omit names containing any of the given texts:
   `--exclude-search retired --exclude-search temporary`.
9. Use `--institution-search` for an institution substring: `--institution-search example`.
10. Use `--summary registered` to count registered and nonregistered accounts:
    `--summary registered --json`.

Repeated values within one inclusion option match any value. Different filters
intersect, and exclusions win over inclusions. Type matching ignores case;
currency and institution comparisons ignore case and trim option whitespace.
Name and institution substring searches ignore case. Account references follow
the existing ID/name/type resolution rules.

All new flags, registration summaries, and multiple values for the existing
`--type`, `--currency`, or `--institution` options imply offline output, including
human tables. A single value for an existing option keeps its original behavior;
use `--offline` when you also want that older selection to skip pricing.

Filtering happens before counts, sorting, and pagination. Summaries count all
matching accounts before pagination, as existing summaries do. JSON and CSV keep
existing raw metadata shapes; human output displays saved metadata. Archived
accounts remain hidden unless `--archived` is explicit, including when using
`--account`. No financial calculations change.

```bash
marketpulse accounts list --type TFSA --type RRSP --exclude-institution "Sample Bank" --json
marketpulse accounts list --account 1 --account 2 --currency CAD --count
marketpulse accounts list --institution-search example --summary registered --csv
```
