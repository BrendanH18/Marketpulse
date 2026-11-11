# Activity selection

[Ledger selection](cli-ledger-selection.md) · [Activity discovery](cli-discovery-exports.md)

Improvements 21–30 under [#120](https://github.com/BrendanH18/Marketpulse/issues/120)
extend `marketpulse activity`. All filters compose with existing date, type,
account, currency, search and output controls. They read existing ledger rows
without fetching prices or recording snapshots. Archived accounts and transfers
to archived accounts stay hidden.

| # | Improvement | Fictional example |
| --- | --- | --- |
| 21 | Filter by calendar month across years, from 1 to 12 | `marketpulse activity --month 1 --year 2024` |
| 22 | Exclude currencies; repeat for several (exact, case-insensitive, trimmed) | `marketpulse activity --exclude-currency USD --exclude-currency EUR` |
| 23 | Exclude dates; repeat for several | `marketpulse activity --exclude-date 2024-01-02 --exclude-date 2024-01-03` |
| 24 | Minimum recorded amount, inclusive | `marketpulse activity --type DEPOSIT --currency CAD --min-amount 100` |
| 25 | Maximum recorded amount, inclusive | `marketpulse activity --type DEPOSIT --currency CAD --max-amount 500` |
| 26 | Minimum recorded fees, inclusive | `marketpulse activity --currency CAD --min-fees 2` |
| 27 | Maximum recorded fees, inclusive | `marketpulse activity --currency CAD --max-fees 5` |
| 28 | Select entries with nonzero or zero fees | `marketpulse activity --has-fees` or `marketpulse activity --no-fees` |
| 29 | Count entries by calendar quarter, with year retained | `marketpulse activity --summary quarter --json` |
| 30 | Count entries by source account type | `marketpulse activity --summary account-type --csv` |

Amount bounds use the stored `Transaction.amount` field. They do **not** use
quantity × price or total trade consideration: an ordinary BUY may record an
amount of zero. Use `--type` and `--currency` when comparing amounts. Fee bounds
also use recorded native-currency fees without conversion. Negative finite bounds
are accepted; NaN, infinity and reversed minimum/maximum pairs are usage errors.
`--has-fees` means exactly nonzero recorded fees, and `--no-fees` means exactly zero.
Date exclusions accept the same date syntax as `--since`, including relative dates.

Quarter groups have names such as `2024-Q1`. Account-type groups use the source
account type (for example `TFSA` or `RRSP`); a transfer is counted once under its
source. Summaries count entries, never monetary values, and use all filtered
entries before pagination. Existing `--summary-sort count`, JSON and CSV controls
also apply. Human activity output respects privacy mode. JSON and CSV contain
raw unmasked values, including when privacy mode is enabled; protect exports
like the ledger itself.
