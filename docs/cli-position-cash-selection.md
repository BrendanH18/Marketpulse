# Position and cash selection

[User guide](usage.md) · [Position browsing](cli-positions-browsing.md)

Improvements 1–20 of [#120](https://github.com/BrendanH18/Marketpulse/issues/120)
add selection controls to existing offline reports. Examples use fictional
accounts and symbols. Filters combine with AND; repeated inclusion symbols
match any listed symbol. Exact symbol/currency matches ignore case and outer
whitespace. Institution matches are exact, ignoring case and outer whitespace.

| # | Improvement | Example |
| --- | --- | --- |
| 1 | Position text search across account name, symbol and currency | `marketpulse positions --search maple` |
| 2 | Repeatable exact position-symbol inclusion | `marketpulse positions --symbols AAA --symbols BBB` |
| 3 | Repeatable exact position-symbol exclusion | `marketpulse positions --exclude-symbol AAA --exclude-symbol BBB` |
| 4 | Position account-type filter | `marketpulse positions --account-type TFSA` |
| 5 | Position institution filter | `marketpulse positions --institution Maple` |
| 6 | Inclusive minimum position quantity | `marketpulse positions --min-quantity 2` |
| 7 | Inclusive maximum position quantity | `marketpulse positions --max-quantity 10` |
| 8 | Inclusive minimum recorded book cost | `marketpulse positions --currency CAD --min-book 100` |
| 9 | Inclusive maximum recorded book cost | `marketpulse positions --currency CAD --max-book 500` |
| 10 | Average-cost ordering, with existing reverse-order support | `marketpulse positions --currency CAD --sort average-cost --descending` |
| 11 | Cash page size | `marketpulse cash --limit 10` |
| 12 | Cash page offset after sorting | `marketpulse cash --sort balance --offset 10 --limit 10` |
| 13 | Cash JSON page envelope | `marketpulse cash --json --page-info --limit 10` |
| 14 | Inclusive minimum recorded cash balance | `marketpulse cash --currency CAD --min-balance 100` |
| 15 | Inclusive maximum recorded cash balance | `marketpulse cash --currency CAD --max-balance 500` |
| 16 | Strictly positive cash balances | `marketpulse cash --positive` |
| 17 | Repeatable cash-currency exclusion | `marketpulse cash --exclude-currency USD --exclude-currency EUR` |
| 18 | Repeatable active-account cash exclusion by name, ID or unique type | `marketpulse cash --exclude-account TFSA --exclude-account 'Fictional Margin'` |
| 19 | Cash account-type filter | `marketpulse cash --account-type TFSA` |
| 20 | Cash institution filter | `marketpulse cash --institution Maple` |

Amounts remain in each row's recorded currency. Neither numeric bounds nor
average-cost ordering convert currencies; filter to a currency when comparing
amounts. Bounds must be finite, and each minimum must be at or below its
maximum. Bounds include equality. Cash values within the ledger's existing
floating-point tolerance of zero are normalized to zero before filtering, so
`--positive` excludes them. `--positive` and `--negative` cannot be combined.

Selection happens before sorting, counting and pagination, consistently for
human, JSON and CSV output. Cash `--page-info` requires `--json` and returns
`{"rows": [...], "total": N, "offset": N, "limit": N}`; total counts filtered
matches before the page is selected, and limit is `null` when omitted. An offset
past the end returns an empty page. `--count` cannot be combined with page
controls or JSON/CSV output. With `--negative`, exit status 1 means an overdrawn
balance matches all filters, even if its row falls outside the requested page;
an empty page does not mean no overdrafts exist.

Archived accounts stay hidden, including when filtering by account type or
institution. Excluded account references must resolve to active accounts;
unknown and archived references fail alike. Commands only read existing ledger
rows: no quote requests, transaction changes or new snapshots. Human reports
respect privacy mode. JSON and CSV exports intentionally contain unmasked
values and should be protected like the ledger.
