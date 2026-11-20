# One hundred more CLI and terminal app improvements

[User guide](usage.md) · [Data & scratch paths](data.md) · [Previous batch](cli-tui-hundred-improvements.md)

This batch adds 100 distinct, opt-in improvements across five areas: recording
and realized gains, the portfolio overview commands, quotes, charts and the
ledger, automation and foreign property reporting, and the terminal app (TUI).
Every addition keeps existing defaults. ACB, FX, tax, valuation and
contribution-room calculations, `status --json` and the desktop bridge are
unchanged. No new network endpoints are added, archived accounts stay hidden in
ordinary portfolio views, and stale quotes never fire alerts or record snapshots.

## Recording, realized gains and payouts (`cli/recording.py`, `cli/realized.py`, 1–20)

1. `buy SYMBOL max PRICE` — Buy the most whole units the account's cash covers at `PRICE`, fees included (cash-tracking accounts only).
2. `sell SYMBOL N%` (and `transfer SYMBOL N%`) — Sell or move a percentage of the units held at the end of the date.
3. `sell SYMBOL all --keep UNITS` — Sell everything except `UNITS`.
4. `buy`/`sell --fee-pct PCT` — Record the commission as a percentage of quantity × price, rounded to the cent.
5. `buy`/`sell --net AMOUNT` — Enter the net amount from the trade confirmation; the fees are worked out from quantity × price.
6. `buy`/`sell --max-value AMOUNT` — Fat-finger guard: refuse (exit 1, nothing saved) when quantity × price is above `AMOUNT`.
7. `dividend --withholding PCT` — Treat `AMOUNT` as gross and record what's left after foreign withholding tax (e.g. 15% on US dividends), showing the amount withheld.
8. `dividend --require-holding` — Refuse the dividend unless the account holds `SYMBOL` at the end of the date.
9. `withdraw all --leave AMOUNT` — Withdraw the whole cash balance except `AMOUNT`.
10. `split SYMBOL RATIO --reverse` — Read `RATIO` as a consolidation (`10` or `10:1` records ×0.1).
11. `--receipt-file PATH` (every recording command) — Also write the JSON receipt of the saved, dry-run or duplicate entry to `PATH`, keeping the usual output.
12. `realized --by [year|quarter|month|account|symbol|currency]` — Proceeds, ACB and gain per group and native currency (text, `--json`, `--csv`, `--count`, paging).
13. `realized --gross` — Split each currency's total gain into gross gains and gross losses (text and `--json` totals).
14. `realized --return` — Add each sale's gain as a percentage of its ACB (`Return` column, `return_pct` field).
15. `realized --totals-only` — Print only the per-currency totals (text, `--json`, `--csv`, `--jsonl`, `--markdown`).
16. `realized`/`payouts --jsonl` — Emit raw rows, `--by` groups or `--summary` counts as JSON Lines.
17. `realized`/`payouts --fields LIST` — Choose and order the row fields for `--json`, `--csv`, `--jsonl` or `--markdown`.
18. `realized`/`payouts --last-days N` — Only rows dated today or in the N−1 days before it.
19. `payouts --by GROUP --group-sort [group|amount|count]` — Order payout groups by name, or by amount or count, largest first.
20. `realized`/`payouts --markdown` — Print rows or groups as a Markdown table, masking amounts in privacy mode.

## Portfolio overview (`cli/overview.py`, 21–40)

21. `holdings --asset-class CLASS` — Keep positions of one asset class (`equity`, `etf`, `fund`, `crypto`, `fixed_income`, `cash`, `real_estate`, `commodity`, `alternative`, `other`), ignoring case; repeat for several.
22. `holdings --kind KIND` — Keep positions priced a given way (`market`, `fixed_income`, `manual`, `cash`), ignoring case; repeat for several.
23. `holdings --min-value AMOUNT` — Keep priced positions worth at least AMOUNT in the base currency, so mixed CAD/USD holdings compare fairly.
24. `holdings --day-move PCT` — Keep positions up or down at least PCT% today; positions with no day change are left out.
25. `holdings --opened-since DATE` — Keep positions first bought on or after a `YYYY-MM-DD` date.
26. `holdings --fields LIST` — Choose and order the `--json` or `--csv` columns with a comma-separated list of holding fields; unknown names are a usage error.
27. `holdings --markdown` — Print the matching positions as a Markdown table (account, symbol, quantity, price, base value, unrealized, gain %, weight) that honours privacy mode.
28. `holdings --symbols-only` — Print each matching symbol once per line, ready to pipe into other commands.
29. `holdings --subtotal` — Follow a selection table with the shown priced positions' base-currency value, book and unrealized gain, and a count of unpriced rows left out.
30. `holdings --concentration-limit PCT` — Name each priced position weighing more than PCT% of net worth and exit 1 when there are any; output is otherwise unchanged, and machine output keeps the warnings on stderr.
31. `status --env` — Print every `--field` value as shell-quoted `MARKETPULSE_*=` assignments for `eval "$(marketpulse status --env)"`; works with `-a`.
32. `status --change-since DATE` — Add the net worth change (amount and %) since the last base-currency snapshot on or before DATE to the plain, whole-portfolio status.
33. `status --fail-on-move PCT` — Exit 1 when today's portfolio move is at least PCT% either way, with any output mode including `--json`; cached (stale) prices never trip it.
34. `summary --exclude-section SECTION` — Show every dashboard section except the ones named (repeatable); it can't be combined with `--section` or exclude all five.
35. `summary --min-move PCT` — Keep only movers up or down at least PCT% today, before `--top` is applied, in the table and in `--json`.
36. `perf --csv` — Print the raw, unmasked performance metrics as `metric,value,base_currency` rows with `\n` line endings.
37. `perf --index-csv` — Print the time-weighted performance index as `date,level` CSV rows for charting elsewhere.
38. `income --forecast-sort annual|yield|yield-on-cost|symbol` — Order the forward-estimate rows by estimated annual income, yield or yield on cost (largest first, missing figures last) or by symbol, before `--top`.
39. `income --min-yield PCT` — Keep forward-estimate rows yielding at least PCT% at today's price; the forecast total covers only the rows kept.
40. `income --stats` — Add the window's monthly average, best month and how many months paid to the report (and a `stats` object to `--json`); not with `--csv`, `--by` or `--forecast-only`.

## Quotes, charts and the ledger (`cli/quotes.py`, `cli/history.py`, 41–60)

41. `quote --jsonl` — Print live or `--cached` quotes as JSON Lines, one object per symbol with the same fields as `--json`.
42. `quote --min-move PCT` — Keep only live quotes whose day change is at least `PCT%` either way; symbols without a quote stay listed with their error.
43. `quote --direction up|down` — Keep only rising or falling live quotes (works with the table, `--json`, `--jsonl` and `--field`).
44. `quote --summary` — Add a breadth line under the live table or card: how many shown quotes are up, down and unchanged, and their average % change.
45. `quote --check-above PRICE` — Exit 1 (naming each failure) unless every named symbol has a fresh quote at or above `PRICE`; a stale or missing quote never passes.
46. `quote --check-below PRICE` — Exit 1 unless every named symbol has a fresh quote at or below `PRICE`; combine with `--check-above` for a price band.
47. `quote --fail-on-stale` — Exit 1 when any live quote was served from the offline cache instead of the network.
48. `quote --cached --count` — Print how many cached quotes match the `--cached` filters (`--all`, `--currency`, `--search`, age), without the table.
49. `chart --jsonl` — Print the fetched bars (and `--vs` bars), or the `--stats` rows, as JSON Lines instead of drawing the chart.
50. `chart --resample week|month` — With `--json`, `--csv` or `--jsonl`, keep each ISO week's or calendar month's last bar, after `--from`/`--to`/`--last`.
51. `compare --since DATE` — Measure every return, drawdown and volatility from `DATE` by dropping earlier fetched bars (no extra requests).
52. `compare --min-return PCT` — Keep only symbols whose period return is at least `PCT%` (applied before `--top`); exit 1 when none qualify.
53. `compare --strict` — Exit 1, naming each one, when any compared symbol had no history, after printing the rows that did.
54. `compare --correlation` — Print a matrix of bar-to-bar return correlations between every pair of symbols over their common dates (table, `--json` or `--csv`).
55. `search --canadian` — Keep only Canadian listings: TSX (`.TO`), TSX Venture (`.V`), CSE (`.CN`) and Cboe Canada (`.NE`) symbols.
56. `activity --jsonl` — Print the matching page of raw, unmasked transaction records as JSON Lines.
57. `activity --ids` — Print only the matching transaction IDs, one per line, for piping into `txn show` or `txn delete`.
58. `activity --totals` — Sum recorded amounts and fees of every matching entry per native currency, before pagination (table, `--json` or `--csv`; masked in privacy mode).
59. `activity --last-days N` — Include only entries dated within the last `N` days; with `--since`, the later date wins.
60. `txn check --summary` — Count the reported ledger issues by code instead of listing them (works with `--json`, `--code` and `-a`; still exits 1 when issues exist).

## Automation and foreign property (`cli/native.py`, `cli/taxes.py`, 61–80)

61. `automation history --since DATE` — Keep runs on or after `YYYY-MM-DD` (also `today`, `yesterday` or `-7d`); `--limit` applies after the filter.
62. `automation history --until DATE` — Keep runs on or before `YYYY-MM-DD`.
63. `automation history --successes` — Keep only runs that recorded no errors (the counterpart of `--failures`).
64. `automation history --with-alerts` — Keep only runs that fired at least one price alert.
65. `automation history --jsonl` — Emit the matching runs as JSON Lines, newest first, each with its full report.
66. `automation history --csv` — Print the matching runs as CSV on stdout (`id`, `ran_at`, `failed`, `errors`, `quote_error_count`, `stale_count`, `fired`).
67. `automation history --count` — Print only the number of matching runs.
68. `automation history --summary` — Show totals over the matching runs (runs, succeeded, failed, quote errors, alerts fired, first/last run, last failure); `--json` for raw figures.
69. `automation history --exit-code` — Exit with status 1 when any matching run failed, e.g. `--since today --exit-code` in a health check.
70. `automation run --cycles N` — Run `N` cycles `--interval` seconds apart, then exit with status 1 if any cycle failed.
71. `automation run --strict` — With `--once` or `--cycles`, also exit with status 1 when a symbol or FX rate couldn't be quoted.
72. `tax foreign-property --since-year YEAR` — Keep only this year and later ones in the every-year report.
73. `tax foreign-property --until-year YEAR` — Keep only this year and earlier ones in the every-year report.
74. `tax foreign-property --status STATUS` — Keep years with this assessment: `not_required`, `simplified`, `detailed` or `undetermined` (repeatable, case-insensitive).
75. `tax foreign-property --jsonl` — Emit raw, unmasked years (or `--holdings` rows) as JSON Lines.
76. `tax foreign-property --csv PATH|-` — Write the years (or `--holdings` rows) to a CSV file, or to stdout with `-`.
77. `tax foreign-property --holdings` — Show one row per foreign property per year (table, `--json`, `--jsonl`, `--csv`) instead of one per year.
78. `tax foreign-property --count` — Print only the number of matching years (or `--holdings` rows).
79. `tax foreign-property --exit-code` — Exit with status 1 when T1135 may be required (simplified, detailed or undetermined) in any year shown.
80. `tax foreign-property --headroom` — Add how far each year's highest cost stayed under the $100,000 threshold (negative when it went over) to the table, the one-year detail, `--json`/`--jsonl` (`headroom`) and `--csv`; masked under privacy.

## Terminal app (`tui/`, 81–100)

81. **Row details (`P`)** — Open a details overlay for the selected holding, cash row, watch quote, transaction (with its full note and any ledger issue), account or alert; amounts and quantities are masked in privacy mode, and `P`, `escape` or `q` closes it.
82. **Toggle watchlist (`W`)** — Add the selected symbol from holdings, chart, activity or alerts to the watchlist, or remove it if it is already watched.
83. **Show only this account (`;`)** — Limit holdings or activity to the selected row's account; press again to show every account.
84. **Go to row or date (`:`)** — Jump to a row number in any table, or in activity to the first listed entry dated with a prefix such as `2024-03-15`, `2024-03` or `2024` (a four-digit year wins over a row number there).
85. **Activity date window (`%`)** — Cycle activity between all dates, the last 30 or 90 days, this year and the last year; the footer shows `% ▸ 90d` and `escape` clears it.
86. **Chart high / low crosshair (`^` / `_`)** — Move the chart crosshair to the period's highest high or lowest low and say the price.
87. **Next / previous group (`)` / `(`)** — Jump to the first row of the next or previous group: holdings by account, activity by month, alerts by symbol and accounts by type.
88. **Find a row (`ctrl+f`, `ctrl+g`)** — Find the next row in the current table whose cells, as shown, contain some text (ignoring case); `ctrl+g` finds the next match and wraps.
89. **Copy pane as text (`ctrl+t`)** — Copy the position or quote pane, the income or tax report, the chart's quote line, or the dashboard's accounts and returns as plain text, with privacy masks.
90. **Pause automatic refresh (`ctrl+r`)** — Pause or resume the timed price refresh for this session; the hints line shows `auto-refresh paused`, and `r` still refreshes.
91. **Alerts for this symbol (`&`)** — Open alerts showing only the selected symbol's alerts (`& ▸ AAPL` in the footer); `&` again or `escape` shows them all, and `A` on an empty list prefills that symbol.
92. **Next ledger issue (`ctrl+e`)** — Select the next transaction a ledger issue names in activity, clearing filters that would hide it, and show the issue (masked in privacy mode).
93. **Previous chart (`'`)** — Reopen the symbol charted before the current one; press again to flip back.
94. **Copy table as JSON (`"`)** — Copy the visible table as a JSON array of objects keyed by column header, with privacy masks.
95. **Save watchlist sort (`ctrl+s`)** — Save the watchlist's current sort (for example by symbol) as its list order, so `J` / `K` reorder from there.
96. **Watch every held symbol** — Command palette action that adds every market-priced holding missing from the watchlist.
97. **Copy chart history as CSV** — Command palette action that copies the open chart's bars (date or time, open, high, low, close, volume) as CSV.
98. **Tax and income year choices** — Command palette entries *Tax year: 2024* and *Income year: 2024* for each year with data; `-` / `+` can only step through them.
99. **Direct mode choices** — Command palette entries such as *Holdings mode: losers*, *Activity mode: income*, *Alerts mode: paused*, *Movers: unrealized* and *Activity window: ytd*, which `M`, `m` and `%` can only cycle through.
100. **Today's change in the holdings footer** — The holdings pane footer adds today's change in the base currency for the positions listed, for example `· today -$50` (masked in privacy mode).
