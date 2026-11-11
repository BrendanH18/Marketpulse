# Offline account selection

These ten improvements extend `marketpulse accounts list`. New selection flags
and summaries read saved metadata without fetching quotes or recording snapshots.
Existing list defaults are unchanged. Archived accounts remain hidden unless
`--archived` is supplied. JSON and CSV contain raw metadata.

1. Repeat `--exclude-account REF` to exclude IDs, names (ignoring case), or unique
   active account types. Unknown or ambiguous references fail; archived references
   require `--archived`. Type resolution follows the existing active-account resolver.
2. `--registered` / `--nonregistered` selects the account type's registration status.
3. `--has-institution` / `--no-institution` selects nonblank or blank institutions;
   whitespace-only institutions count as blank.
4. `--min-id N` selects account IDs at or above N.
5. `--max-id N` selects account IDs at or below N. Bounds must be positive and
   the minimum cannot exceed the maximum.
6. `--summary type` counts matching accounts by their saved account type.
7. `--summary currency` counts matching accounts by configured currency.
8. `--summary institution` counts matching accounts by trimmed institution text.
   Blank institutions use an empty group in exports and `(no institution)` in
   human output; nonblank spelling and case are preserved.
9. `--summary cash` counts matching accounts as `tracked` or `untracked`.
10. `--summary-sort group|count` orders summary groups alphabetically (the default)
    or by descending count, with group text breaking ties.

All filters compose. Summaries include all matches before `--limit` and `--offset`
and support human output, `--json`, or `--csv`. Summary rows have `group` and
`count` fields. Empty summaries export `[]` in JSON or just the CSV header.
`--summary` cannot combine with `--count` or `--page-info`; choosing count order
requires a summary. Row ordering flags do not reorder summary groups.

```sh
marketpulse accounts list --registered --has-institution --exclude-account "Example TFSA" --json
marketpulse accounts list --min-id 2 --max-id 10 --limit 3 --json --page-info
marketpulse accounts list --nonregistered --summary currency --csv
marketpulse accounts list --summary institution --summary-sort count --json
```
