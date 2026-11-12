# Income report refinements

[Reporting refinements](cli-report-refinements.md) · [Ledger reports](cli-ledger-reports.md)

Ten additive capabilities for `realized` and `payouts` under
[#124](https://github.com/BrendanH18/Marketpulse/issues/124):

1. `realized --exclude-symbol MAPL --exclude-symbol GULL` excludes exact symbols,
   ignoring case and surrounding whitespace. Repeat for multiple exclusions.
2. `realized --exclude-account "Fictional Maple"` and
   `payouts --exclude-account TFSA` omit active accounts by ID, name or unique
   type. Repeat for several accounts. Unknown and archived references fail.
3. `realized --min-proceeds 60` selects sales with at least 60 in native proceeds.
4. `realized --max-proceeds 100` sets an inclusive native proceeds ceiling.
5. `realized --min-quantity 4` selects sales of at least four units.
6. `realized --max-quantity 10` sets an inclusive sold-quantity ceiling.
7. `realized --json --page-info --limit 10` adds `total`, `offset`, `limit`,
   `returned` and `next_offset` to the JSON object. Counts describe matching
   sales before pagination; totals continue to cover all matching rows.
8. `realized --month 6` and `payouts --month 6` select June across years.
   Combine with `--year 2024` to select one June.
9. `realized --quarter 2` and `payouts --quarter 2` select April through June
   across years. Month, quarter, year and date bounds intersect.
10. `payouts --has-symbol` selects symbol-associated income; `--no-symbol`
    selects income without a recorded symbol, such as account interest.
    Symbol presence is based on the recorded text, independently of income kind.

Every new selection runs before counts, grouped payout totals, sorting and
pagination. Existing JSON and CSV formats remain unchanged unless `--page-info`
is requested. Native amounts are never converted or summed across currencies;
for comparable proceeds bounds, combine with `--currency CAD` or another native
currency. These are ledger reports, not tax reports.

Proceeds bounds must be finite; quantity bounds must also be nonnegative.
Inverted bounds, invalid calendar numbers and blank symbol exclusions are usage
errors. `--page-info` requires `--json`.

All options read the fictional or configured local ledger without quote, FX or
history requests and without recording snapshots. Archived accounts remain
hidden. Human amounts and quantities respect privacy mode, while explicit JSON
and CSV exports retain raw values.
