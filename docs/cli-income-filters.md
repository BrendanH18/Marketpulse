# Sales and payout filters

These improvements extend offline report browsing under
[#118](https://github.com/BrendanH18/Marketpulse/issues/118).

1. `realized --search TEXT` finds a symbol or account name by case-insensitive substring.
2. `realized --sort FIELD` orders by `date`, `account`, `symbol`, `quantity`,
   `proceeds`, `cost`, `gain`, or `currency`. Account names sort ignoring case.
3. `realized --descending` reverses the selected order (date by default).
4. `realized --min-gain VALUE` includes sales at or above a native-currency gain.
5. `realized --max-gain VALUE` includes sales at or below a native-currency gain.
6. `payouts --search TEXT` finds a symbol or account name by case-insensitive substring.
7. `payouts --min-amount VALUE` includes individual payouts at or above the amount.
8. `payouts --max-amount VALUE` includes individual payouts at or below the amount.
9. `payouts --exclude-symbol SYMBOL` excludes an exact symbol ignoring case;
   repeat the option to exclude several symbols.
10. `payouts --json --page-info` adds `total`, `offset`, `limit`, `returned`,
    and `next_offset` to the existing JSON object. With `--by`, these describe
    groups; otherwise they describe payout rows. `next_offset` is null on the
    final or an empty page.

```bash
marketpulse realized --currency CAD --min-gain -100 --max-gain 0 --sort gain --json
marketpulse realized --search fictional --sort proceeds --descending --limit 10 --csv
marketpulse payouts --currency CAD --min-amount 25 --exclude-symbol MAPL --count
marketpulse payouts --search fictional --by month --json --page-info --limit 12
```

Amount boundaries are inclusive and must be finite; a minimum cannot exceed its
maximum. Payout amount filters apply to individual rows before grouping.
Filters combine with existing account, symbol, currency, date and year filters.
Archived accounts stay hidden. Counts and per-currency totals describe all
matching rows before pagination. Sorting precedes pagination and keeps the
ledger order for equal values.

`realized --newest-first` cannot be combined with `--sort` or `--descending`;
`--count` cannot be combined with these ordering options. Payout `--page-info`
requires `--json`, which is incompatible with `--count` or `--csv`.

All operations read existing ledger data without requesting prices or FX or
writing snapshots. Numeric filters and ordering compare recorded native amounts
without conversion; select a currency when comparing amounts. Realized gains
remain an average-cost ledger report, not a tax report. Human output respects
privacy mode; JSON and CSV intentionally export raw values.
