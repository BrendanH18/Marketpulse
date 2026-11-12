# Offline ledger selection and export controls

[User guide](usage.md) · [Issue #132](https://github.com/BrendanH18/Marketpulse/issues/132)

These 25 additions inspect recorded values and select existing rows locally.
They do not fetch prices, calculate trade consideration, change financial math,
or write the ledger. Examples refer to fictional symbols and accounts.

## Activity: fifteen additions

1. `activity --min-quantity 10`: keep recorded quantities at least 10.
2. `activity --max-quantity 20`: keep recorded quantities at most 20.
3. `activity --min-price 25`: keep recorded unit prices at least 25.
4. `activity --max-price 50`: keep recorded unit prices at most 50.
5. `activity --exclude-note review`: omit notes containing “review”, ignoring case.
6. `activity --symbol-prefix AL`: keep symbols starting with AL, ignoring case.
7. `activity --account-search maple`: search only source account names, ignoring case.
8. `activity --id 12 --id 15`: select exact transaction IDs; repeated IDs do not duplicate rows.
9. `activity --exclude-id 12 --exclude-id 15`: omit exact IDs, including when also selected by `--id`.
10. `activity --has-target`: select entries with a transfer destination; `--no-target` selects the rest.
11. `activity --weekend`: select Saturday/Sunday dates; `--no-weekend` selects Monday–Friday dates.
12. `activity --has-price`: select nonzero recorded unit prices; `--no-price` selects zero prices.
13. `activity --has-quantity`: select nonzero recorded quantities; `--no-quantity` selects zero quantities.
14. `activity --sort amount`: put the largest recorded amounts first, with newest date then largest ID breaking ties.
15. `activity --sort fees`: put the largest recorded fees first, using the same deterministic tie breaks.

Quantity and price bounds are inclusive, finite, and combinable. Zero-valued
fields remain eligible, including types where that field is unused; use
`--has-price` or `--has-quantity` to leave them out. Values remain in their
recorded units/currencies. When sorting amounts or fees across currencies,
restrict with `--currency` if you need a like-for-like comparison.

`--sort date` is the default, preserving the existing newest-first output.
`--oldest-first` reverses the selected order, including its tie breaks, so
`activity --sort fees --oldest-first` shows the smallest fees first. Sorting
applies to detailed rows, while `--summary-sort` continues to control summaries.
All new selectors run before `--count`, `--summary`, and pagination. They work
with ordinary human output, `--json`, `--csv`, and JSON `--page-info`:

```bash
marketpulse activity --min-quantity 10 --max-quantity 20 --currency CAD --json
marketpulse activity --has-price --sort fees --limit 10 --offset 10 --json --page-info
marketpulse activity --weekend --summary type --json
```

Activity still hides archived source accounts and transfers whose destination
is archived. Human output keeps its existing privacy masking; script outputs
remain raw and unmasked.

## Export: ten additions

16. `export --currency CAD`: select recorded currency, ignoring surrounding spaces and case.
17. `export --note winter`: select notes containing “winter”, ignoring case.
18. `export --has-note`: select nonblank notes; `--no-note` includes empty and whitespace-only notes.
19. `export --exclude-type BUY --exclude-type SELL`: omit repeated transaction types, ignoring case.
20. `export --exclude-symbol ALFA --exclude-symbol BETA`: omit repeated exact symbols, ignoring spaces and case.
21. `export --exclude-account 'Fictional Maple'`: omit rows recorded in this source account; repeat for several.
22. `export --year 2025`: select one calendar year (1–9999).
23. `export --month 1`: select a calendar month (1–12) in every year, or combine with `--year`.
24. `export --limit 100`: write at most 100 matching rows in the original ledger order.
25. `export --offset 100`: skip 100 matching rows before writing, optionally followed by `--limit`.

Export remains a full-ledger data exchange operation, including archived
accounts. Account exclusions accept IDs, names, or unique account types, just
like account inclusion. They apply to the source account; a transfer recorded
in another account can still name the excluded destination. Use `--exclude-type
TRANSFER` if you want to omit transfers as well.

Filters intersect; exclusions win over inclusions. Pagination follows filtering
and preserves the original ledger order. `--count` reports all matching rows
and rejects nonzero `--offset` or any `--limit`, avoiding ambiguous page counts.
Empty CSV exports still contain their column header; empty JSON Lines exports
contain no lines. Both stdout and file exports support the new controls, along
with `--columns` and `--jsonl`. Full-column CSVs retain the re-import format:

```bash
marketpulse export fictional-2025.csv --year 2025 --currency CAD --has-note
marketpulse export --exclude-type BUY --exclude-symbol ALFA --count
marketpulse export --year 2025 --month 1 --offset 100 --limit 100 --jsonl
```

Plain `activity` and `export` output is unchanged. Existing golden-output tests
continue to cover those defaults; `tests/test_cli_next_ledger.py` covers every
new selector, sorting, boundaries, combinations, archived accounts, privacy,
CSV/JSON Lines, file exports, duplicate-safe re-import, and absence of requests.
