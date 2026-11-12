# Comparisons and symbol search

[User guide](usage.md) · [One hundred improvements](cli-hundred-improvements.md) · [Issue #130](https://github.com/BrendanH18/Marketpulse/issues/130)

These ten additions export, reorder and annotate `marketpulse compare`, and
narrow or script `marketpulse search`. `compare` still makes one `chart` history
request per symbol and `search` one search request for up to twelve matches;
every option sorts, filters or formats those results, so none adds a request.
The examples use fictional symbols and prices.

51. `compare AAPL XEQT.TO VFV.TO -p 1mo --json` prints the comparison rows instead of a chart and table, in the table's order: `[{"symbol": "AAPL", "period": "1mo", "interval": "1h", "from": "2025-03-03", "to": "2025-03-21", "bars": 15, "start": 100.0, "end": 109.0, "return_pct": 9.0, "max_drawdown_pct": -6.73, "volatility_pct": 95.03, "vs_base_pp": null}, …]`. A symbol that can't be fetched is reported on stderr and left out; when none can, the command fails as before.
52. `compare AAPL XEQT.TO VFV.TO --csv` prints the same rows as CSV with those columns as the header and `\n` line endings; an unknown value is an empty cell.
53. `compare AAPL XEQT.TO VFV.TO --sort drawdown` orders rows by `return` (best first, the default order), `drawdown` (shallowest first), `volatility` (calmest first) or `symbol` (A–Z). `--reverse` flips the order, so `compare … --reverse` lists the worst return first. Symbols with too few bars to measure volatility stay last when sorting by volatility.
54. `compare AAPL XEQT.TO VFV.TO --base XEQT.TO` adds a `vs XEQT.TO` column: each return minus XEQT.TO's return over the same period, in percentage points (`+5.33 pp`, `-12.00 pp`; the base row reads `base`). JSON and CSV carry it as `vs_base_pp`. The base must be one of the compared symbols, so nothing extra is fetched.
55. `compare AAPL XEQT.TO VFV.TO --top 2` keeps only the first two rows after ordering, in the chart, table, JSON and CSV; `--sort drawdown --top 1` names the symbol that fell least.
56. `compare AAPL XEQT.TO VFV.TO --no-chart` prints only the comparison table, exactly as it appears under the chart.
57. `search maple --json` prints `[{"symbol": "MAPL.TO", "name": "Maple Leaf Growth ETF", "exchange": "Toronto", "type": "ETF"}, …]`, and `search maple --csv` the same as `symbol,name,exchange,type` CSV. With no matches JSON prints `[]`, CSV prints only the header, and both exit 1, as plain `search` does.
58. `search maple --type etf` keeps one result type (`ETF`, `Equity`, `Mutual fund`, `Index`, `Cryptocurrency`…), ignoring case, spaces and dashes, so `mutual fund` matches `MUTUALFUND`; repeat for several. `--exchange tor` keeps results whose exchange contains the text, ignoring case (`Toronto`); repeat for several. Filters intersect, and when they remove everything the command fails with `No matches for --type/--exchange.`
59. `search maple --limit 3` shows at most three matches (1–12), after any filters. The request still asks for twelve, so a filter can reach past the first few.
60. `search maple --first` prints only the top matching symbol, `MAPL.TO`, for scripts such as `marketpulse chart "$(marketpulse search maple --type etf --first)"`. With no match it exits 1 with `No matches.` on stderr.

## Rules

- `--json` and `--csv` are exclusive on both commands. `compare --no-chart` can't be combined with them, since they never draw a chart.
- `--base` takes one symbol that is also compared; if its history can't be fetched the command fails.
- `search --first` can't be combined with `--json` or `--csv`. Blank `--type` or `--exchange` values are usage errors.

## What stays the same

`marketpulse compare XEQT.TO VEQT.TO VFV.TO` and `marketpulse search maple`
print exactly what they printed before: the same overlay chart, the table
ordered by return, and up to twelve search matches. Returns, drawdown and
volatility use the same calculations as before; `--base` only subtracts two
returns that are already shown.
