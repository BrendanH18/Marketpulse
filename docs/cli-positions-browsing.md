# Position and cash browsing

These ten additions extend the existing offline `positions` and `cash` reports.
They replay only the local ledger, hide archived accounts, and fetch no prices or
FX. Book costs and cash balances retain their existing native-currency meaning.

1. `positions --limit N` caps the sorted matching positions at a positive N.
2. `positions --offset N` skips a nonnegative number of sorted matches.
3. `positions --json --page-info` returns `{rows, total, offset, limit}` instead
   of the usual JSON array. `total` counts all filtered visible positions before
   pagination, and `limit` is `null` when omitted. An offset beyond the end yields
   an empty `rows` array with the original matching total.
4. `positions --held-since DATE` includes holdings whose first ledger date is
   on or after DATE.
5. `positions --held-until DATE` includes holdings whose first ledger date is
   on or before DATE. Both bounds are inclusive, accept the CLI's usual date
   syntax, and describe the opening date rather than a historical portfolio view.
6. `cash --count` prints the number of matching balance rows, after filters.
7. `cash --sort account|currency|balance` orders rows with deterministic account,
   account-ID and currency tie breakers. The default remains account order.
8. `cash --descending` reverses the selected sort order.
9. `cash --nonzero` omits zero balances after the existing EPSILON float-residue
   normalization; overdrafts remain included.
10. `cash --search TEXT` filters by account-name substring, ignoring case and
    surrounding whitespace, and combines with account and currency filters.

```bash
marketpulse positions --held-since 2024-01-01 --held-until 2024-12-31 --sort book --descending --limit 10
marketpulse positions --currency CAD --offset 10 --limit 10 --json --page-info
marketpulse cash --search 'fictional' --nonzero --sort balance --descending --csv
marketpulse cash --negative --count
```

Position filters run before sorting and pagination. JSON, CSV, and human tables
use the same selected rows. `positions --count` reports the complete filtered
count and cannot be combined with pagination, JSON or CSV. `--page-info` requires
JSON. Invalid dates, reversed date bounds and invalid numeric bounds are usage
errors (exit 2).

Cash counts cannot be combined with JSON or CSV. `cash --negative` retains its
exit status: 1 when at least one matching overdrawn balance exists, otherwise 0,
including when combined with `--count`. Numeric balance sorting compares native
amounts; it does not convert or aggregate currencies. Human amounts respect
privacy mode; JSON and CSV contain raw unmasked amounts as before.
