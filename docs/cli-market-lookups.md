# Chart and quote lookups

[User guide](usage.md) · [One hundred improvements](cli-hundred-improvements.md) · [Issue #130](https://github.com/BrendanH18/Marketpulse/issues/130)

These ten additions export, summarize, trim and resize what `marketpulse chart`
already fetches, and make live `quote` easier to script. Every option works on
the same requests the plain command makes (one `chart` history request per
symbol plus the quote for the card); trimming and statistics happen on the
fetched series, so no option asks Yahoo for anything extra. The examples use
fictional prices.

41. `chart AAPL -p 1mo --json` prints the fetched bars instead of drawing them: `{"symbol": "AAPL", "period": "1mo", "interval": "1h", "currency": "USD", "bars": [{"symbol": "AAPL", "date": "2025-03-03", "time": "2025-03-03T12:00:00+00:00", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100}, …], "vs": {}}`. `date` is the exchange's calendar date and `time` the bar time in the exchange's zone. Each `--vs` symbol's bars are listed under `vs`.
42. `chart AAPL -p 1mo --vs VFV.TO --csv` prints the same bars as CSV (`symbol,date,time,open,high,low,close,volume`), the charted symbol first and then each `--vs` symbol, with `\n` line endings.
43. `chart AAPL -p 1mo --stats` prints one row per symbol instead of a chart: first and last close, change, % change, high, low, max drawdown and annualized volatility, titled with the date range and bar count (`1mo statistics · 2025-03-03 to 2025-03-21 · 15 bars`). The figures come from the same helpers as the chart footer and `compare`. `--stats --json` and `--stats --csv` add `period`, `interval`, `from`, `to`, `bars`, `high_date` and `low_date`: `[{"symbol": "AAPL", "first": 100.0, "last": 109.0, "change": 9.0, "change_pct": 9.0, "high": 110.0, "high_date": "2025-03-20", "low": 97.0, "low_date": "2025-03-11", "max_drawdown_pct": -6.73, "volatility_pct": 95.03, …}]`.
44. `chart AAPL -p 1y --from 2025-03-10 --to 2025-03-14` keeps only the fetched bars between two exchange dates, inclusive, in the chart, JSON, CSV and statistics. Dates take the same forms as elsewhere (`2025-03-10`, `yesterday`, `-30d`). Pick a `--period` that covers the range; trimming never fetches more history. `--from` after `--to` is a usage error, and a range with no bars fails with `No AAPL 1y bars in the selected range.`
45. `chart AAPL -p 1mo --last 5` keeps only the last five fetched bars (at least 2). It applies after `--from`/`--to`, so `--to 2025-03-14 --last 2` is the two sessions ending 14 March.
46. `chart AAPL --normalize` draws the symbol as % change from its first bar, with a `━━ AAPL +9.00%` legend, the way a `--vs` overlay is drawn. With `--vs` the chart is already in % change, so the flag changes nothing.
47. `chart AAPL --width 60` draws the chart 60 columns wide (at least 20) instead of filling the terminal; combine it with `-H` for a compact chart.
48. `chart AAPL --no-card` leaves out the quote card above the chart. The quote is still fetched as before, so a one-day chart keeps its previous-close line.
49. `quote AAPL --field price` prints one bare value, `200.0`, for scripts. Several symbols print `SYMBOL<tab>value` lines (`quote AAPL XEQT.TO --field currency`). Fields are `price`, `prev_close`, `change`, `change_pct`, `currency`, `name`, `exchange` and `volume`; an unknown value prints an empty string. A symbol with no quote is reported on stderr, and the command exits 1 only when no symbol has a quote.
50. `quote AAPL NOPE --strict` prints the usual table but exits 1 when any named symbol has no quote. It also applies to `--json` and `--field`; one missing symbol already fails without it.

## Rules

- `--json` and `--csv` are exclusive. `--normalize`, `--width` and `--no-card` change only the drawn chart, so they can't be combined with `--json`, `--csv` or `--stats`.
- `--field` reads live quotes and can't be combined with `--cached` or `--json`. `--strict` applies to live quotes, not `--cached`.
- A symbol with no history fails exactly as plain `chart` does, in every output format.

## What stays the same

`marketpulse chart AAPL`, `chart AAPL --vs XEQT.TO` and `quote AAPL XEQT.TO`
print exactly what they printed before. The quote card, footer statistics and
`--vs` overlays are unchanged, and the chart still uses the configured
`chart_period` when `--period` is omitted. JSON and CSV carry raw prices as
Yahoo returned them (minor-unit currencies such as GBp already converted).
