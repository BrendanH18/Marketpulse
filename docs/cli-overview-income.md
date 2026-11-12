# Income overview

[User guide](usage.md) · [One hundred improvements](cli-hundred-improvements.md) · [Issue #130](https://github.com/BrendanH18/Marketpulse/issues/130)

These ten additions under [#130](https://github.com/BrendanH18/Marketpulse/issues/130)
select, regroup and export the `marketpulse income` report: dividends, DRIPs and
interest converted to your base currency at today's rates, exactly as the plain
report converts them. For native-currency payout lists with no conversion, use
`marketpulse payouts`. The examples use fictional accounts.

71. `income --json` prints the report as raw, unmasked JSON: `base_currency`, `window_months`, `year`, `months` (`month`, `amount`), `window_total`, `sources_year`, `sources` (`source`, `amount`), `sources_total`, `forecast` (rows of `symbol`, `name`, `quantity`, `per_share_ttm`, `currency`, `annual`, `base_currency`, `annual_base`, `yield_pct`, `yield_on_cost_pct`; `null` with `--no-forecast`), `forecast_total` and `unconverted`, the payouts left out because no FX rate converts them.
72. `income --csv` prints the monthly totals as `month,amount,base_currency` rows with `\n` line endings (with `--by`, the groups; with `--forecast-only`, the forecast rows). CSV never fetches distribution history.
73. `income --months 36` widens the monthly history to the last 36 months (1–120; 12 by default). The header reads `LAST 36 MONTHS`, and the chart shows as many of the most recent months as fit the terminal; JSON and CSV have them all.
74. `income --year 2024` charts January to December 2024 and lists that year's sources. It can't be combined with `--months`.
75. `income -a "Fictional Income"` keeps one active account's income (name, id or type); the forward estimate covers that account's holdings. Archived accounts fail like unknown ones.
76. `income --symbol xeqt.to` keeps one symbol's income, ignoring case and surrounding spaces, and its forecast row. A blank symbol is a usage error.
77. `income --kind dividend --kind drip` keeps those kinds of income (`dividend`, `drip`, `interest`). When no dividend kind is chosen, the forecast is skipped.
78. `income --by account` replaces the report with base-currency totals and payout counts per `month`, `symbol`, `account` or `kind` over the window (the last 12 months, `--months N` or `--year`), largest first (months in date order). It works offline: `--by` never fetches distribution history.
79. `income --top 5` keeps the five largest sources, groups or forecast rows. Totals (`sources_total`, `forecast_total`, a `--by` table's total) still cover every matching row.
80. `income --forecast-only` prints only the forward 12-month estimate (trailing distributions × shares held). It combines with `-a`, `--symbol`, `--top`, `--json` (`{"base_currency": "CAD", "forecast": […], "total": 64.0}`) and `--csv`.

```bash
marketpulse income --months 24 --kind dividend --kind drip
marketpulse income --year 2025 --by symbol --top 5
marketpulse income -a TFSA --json --no-forecast
marketpulse income --by month --csv > fictional-income.csv
marketpulse income --forecast-only --symbol VFV.TO
```

## Rules

- `--json` and `--csv` are exclusive; `--months` and `--year` are exclusive.
- `--forecast-only` can't be combined with `--no-forecast`, `--by`, `--months`, `--year` or `--kind`.
- With any of these options, payouts in a currency with no FX rate are listed under `unconverted` (and as a warning in the table) instead of being counted as zero.

## What stays the same

Plain `income` and `income --no-forecast` print exactly what they printed
before. Every new option selects from active accounts only, so archived
accounts' income is left out of the selected totals, as in `payouts`. Human
output honours `privacy`; JSON and CSV are raw and unmasked. Conversion,
forecast and yield math are unchanged, and only the forecast fetches
distribution history, as before.
