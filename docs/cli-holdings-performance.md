# Priced holdings and performance

[User guide](usage.md) · [Offline tax, allocation and holdings inspection](cli-portfolio-inspection.md)

These ten additions extend `marketpulse holdings` and `marketpulse perf`. They
price the portfolio exactly as the plain commands do (cached quotes when offline,
no extra requests) and only choose what is printed. Examples use fictional
accounts and symbols.

21. `holdings --json` prints the priced positions as a JSON array: account,
    symbol, name, asset class, kind, currency, quantity, average cost, price,
    book, market value, unrealized gain and %, day change and %, plus the base
    currency, FX rate, base-currency value, book, gain and day change, the weight
    (% of net worth), and `priced` and `stale` flags. Native amounts are in the
    position's currency. A position without a price or FX rate has `null` values
    and `"priced": false`. Like `positions --json`, the numbers are raw and
    unmasked, even in privacy mode.
22. `holdings --csv` prints the same fields as CSV to stdout, with `\n` line
    endings, ready for a spreadsheet: `marketpulse holdings --csv > holdings.csv`.
23. `holdings --sort value|weight|gain|gain-pct|day|day-pct|symbol|account`
    orders positions; `--descending` reverses it. Value, gain and day change
    compare base-currency amounts, so mixed currencies sort correctly. Positions
    without the metric come last in either direction; ties fall back to account,
    then symbol. `--descending` requires `--sort`.
24. `holdings --symbol TEXT` keeps symbols containing TEXT and `--currency CCY`
    keeps positions held in CCY, both ignoring case.
25. `holdings --gainers` keeps positions with an unrealized gain, `--losers`
    those with an unrealized loss. They can't be combined, and unpriced positions
    match neither.
26. `holdings --min-weight PCT` keeps priced positions that are at least PCT% of
    net worth (the account's value with `-a`).
27. `holdings --limit N` and `--offset N` page through the sorted matches, so
    `--sort value --descending --limit 5` lists the five largest holdings.
28. `holdings --count` prints only the number of matching positions, for
    scripts. It can't be combined with `--json`, `--csv`, `--limit` or `--offset`.
29. `holdings --stale` keeps positions priced from a cached quote because the
    network was unavailable. `holdings --excluded` instead lists everything the
    totals leave out and why: positions with no price or FX rate (with the
    provider's message), cash with no FX rate, and archived accounts that still
    hold value. It combines only with `-a` and `--json`.
30. `perf --json` prints the raw performance metrics (`since`, `days`,
    `net_contributions`, `total_gain`, `xirr_pct`, `twr_pct`, `twr_annual_pct`,
    `max_drawdown_pct`, `volatility_pct`), the time-weighted index, and the
    view's `stale` flag and `excluded` items. `perf --metric NAME` prints one of
    them (`since`, `days`, `net-contributions`, `total-gain`, `xirr`, `twr`,
    `twr-annual`, `max-drawdown`, `volatility`) as a bare value, and exits 1 when
    it isn't available yet (for example, time-weighted returns before there are
    two snapshots). Both are unmasked.

```bash
marketpulse holdings --sort value --descending --limit 5
marketpulse holdings --currency USD --losers --json
marketpulse holdings -a "Fictional TFSA" --min-weight 10 --csv > tfsa-holdings.csv
marketpulse holdings --stale --count
marketpulse holdings --excluded
marketpulse perf --metric xirr
```

## What stays the same

`marketpulse holdings`, `marketpulse holdings -a ACCOUNT` and `marketpulse perf`
without these options print exactly what they printed before. Every form runs the
same valuation, so the full-portfolio commands still record today's snapshot under
the existing rules (only when nothing is stale or excluded).

Filters, `--sort`, `--limit` and `--offset` select positions for display only.
The human table then leaves out cash rows and the net worth summary rather than
summing a subset, says how many of the portfolio's positions it shows, and warns
when prices are stale, something is excluded, or an archived account that still
holds value is pausing snapshots. Weights stay a share of the whole
portfolio (or of the account with `-a`). Human output respects privacy mode; JSON,
CSV, `--count` and `--metric` are raw. Conflicting output options are usage errors
(exit 2).

With any of these options, `-a` takes only active accounts: an archived account
fails like an unknown one, by name or id.
