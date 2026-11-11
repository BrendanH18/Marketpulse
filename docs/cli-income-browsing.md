# Realized-gain and payout browsing

These ten additions extend the offline reports. They read the local ledger,
exclude archived accounts, and never fetch prices or exchange rates. They do
not change cost calculations or tax reports. Human output respects privacy;
JSON and CSV exports contain unmasked values.

1. `realized --currency CAD` selects one native currency, ignoring case and surrounding spaces.
2. `realized --count` prints the number of matching sales.
3. `realized --newest-first` orders dates newest first, preserving same-day ledger order.
4. `realized --limit 20` shows at most twenty sales after ordering and offset.
5. `realized --offset 20` skips twenty matching sales.
6. `payouts --currency USD` selects one native currency with the same normalization.
7. `payouts --count` counts matching income events; with `--by`, it counts groups instead.
8. `payouts --newest-first` orders event dates newest first with stable same-day order;
   with `--by`, it reverses the normal group order (including the currency tie-break).
9. `payouts --limit 20` limits events, or groups when `--by` is supplied.
10. `payouts --offset 20` skips events, or groups when `--by` is supplied.

Filters run before ordering and paging. Offset runs before limit. Limits must
be positive; offsets must be nonnegative. Counts cannot be combined with JSON,
CSV, ordering, limit or offset. Blank currency filters are rejected.

JSON retains its existing `rows`/`totals` or `by`/`groups`/`totals` shape.
Totals in both JSON and human tables cover **all filtered events**, even when
the visible rows or groups are limited. Currencies are always kept separate.
CSV contains the selected page only. An offset beyond the matches produces
an empty page (JSON still carries the full filtered totals).

```bash
marketpulse realized --currency CAD --newest-first --offset 10 --limit 10 --json
marketpulse payouts --kind dividend --by month --currency USD --limit 12 --csv
marketpulse payouts --year 2024 --by symbol --count
```
