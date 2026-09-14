# ⚡ MarketPulse

A fast, keyboard-first investment tracker for the terminal — with Omarchy themes, braille charts, Canadian account and tax smarts, and a native macOS menu bar companion.

- **Everything you own, in one ledger** — stocks, ETFs, crypto, cash, GICs and bonds, and manually valued assets (property, private shares, pensions) across TFSA, RRSP, FHSA, RESP, non-registered and crypto accounts.
- **Real performance** — money-weighted (XIRR) and time-weighted returns, drawdown, volatility, and a daily net-worth history you can rebuild from your ledger in seconds.
- **Canadian-aware** — average-cost ACB, capital gains per tax year at trade-date FX, superficial-loss warnings, TFSA/FHSA room that rolls forward on its own.
- **Lightweight** — four dependencies, a local SQLite file, no pandas, no account, no telemetry.

---

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/BrendanH18/marketpulse && cd marketpulse
uv tool install --editable .     # puts `marketpulse` (and the short alias `mp`) on your PATH
marketpulse                      # open the TUI
```

Existing MarketPulse 0.1 portfolios in `~/.marketpulse/*.json` are imported automatically on first run (the JSON files are left untouched).

## The TUI

`marketpulse` opens a tiling, Omarchy-style workspace UI: a Waybar-like top bar, panes that light up with your theme's accent when focused, and live quotes that flash as they change.

| Key | Workspace | What's there |
|-----|-----------|--------------|
| `1` | **dash** | Big-digit net worth, today/unrealized/income/returns tiles, net-worth chart (`,` `.` change range), allocation (`g` cycles class/account/currency), movers, market strip |
| `2` | **holdings** | Every position with day change, gain and weight; position detail with a 3-month chart and recent activity (`f` filters by account) |
| `3` | **watch** | Watchlist with intraday sparklines and 52-week ranges (`a` add, `x` remove, `J`/`K` reorder) |
| `4` | **chart** | Braille price chart with crosshair (`←`/`→`), periods (`[`/`]`), comparisons (`c`, or type `NVDA 1y vs QQQ SPY`) |
| `5` | **activity** | The full ledger — `n` new, `e` edit, `x` delete, `u` undo, `/` filter, `i` import CSV, `E` export |
| `6` | **income** | Dividends and interest by month and source, plus a forward 12-month estimate with yield on cost |
| `7` | **accounts** | Accounts, capital gains by year, superficial-loss checks, contribution room (`R`), GICs and manual assets (`G`, `V`) |
| `8` | **alerts** | Price and %-move alerts that notify once and re-arm (`space` pauses) |

Everywhere: `b` buy · `s` sell · `D` dividend · `A` alert · `w` watch · `/` search any symbol · `p` privacy mode · `t` next theme · `r` refresh · `ctrl+p` command palette · `?` help.

Buying with the price left blank uses the live quote, and the form shows the current price and what you already hold as you type.

## The CLI

Every feature is scriptable. A few highlights:

```bash
marketpulse buy XEQT.TO 20                 # buy at the live price (one account? no -a needed)
marketpulse buy AAPL 10 229.50 -a TFSA -f 4.95 -d 2026-03-02
marketpulse sell VFV.TO 5 -a "Non-reg"     # realized gain is printed using average cost
marketpulse dividend XEQT.TO 38.12 -a TFSA
marketpulse deposit 7000 -a TFSA
marketpulse transfer XEQT.TO 50 --from Main --to TFSA
marketpulse undo                           # oops

marketpulse summary                        # dashboard in your scrollback
marketpulse holdings -a TFSA
marketpulse chart NVDA -p 1y --vs QQQ
marketpulse compare XEQT.TO VEQT.TO VFV.TO -p 5y
marketpulse perf                           # XIRR, time-weighted, drawdown, volatility
marketpulse income                         # history + forward estimate
marketpulse tax --year 2025                # capital gains, superficial losses, room
marketpulse allocation --target etf=80 --target fixed_income=15 --target cash=5
```

Run `marketpulse --help` or `marketpulse <command> --help` for everything, including `accounts`, `asset`, `watch`, `alerts`, `import`/`export`, `backfill`, `theme`, `config` and `doctor`.

### Accounts, cash and contribution room

```bash
marketpulse accounts add "Wealthsimple TFSA" -t TFSA --track-cash
marketpulse accounts room TFSA 2026 21500     # room CRA reported for Jan 1, 2026
marketpulse accounts                          # values, day change, weights
```

With `--track-cash`, buys debit the account's cash and sells, dividends and deposits credit it. Without it, an account is treated as fully invested — perfect if you only want to track holdings.

### GICs, bonds and everything else

```bash
marketpulse asset fixed EQB-GIC-27 10000 --rate 4.1 --start 2025-03-01 --maturity 2027-03-01 -a TFSA
marketpulse asset manual COTTAGE 450000 --class real_estate -a Property
marketpulse asset value COTTAGE 480000        # new valuation whenever you like
marketpulse asset classify XEQT.TO equity     # override any symbol's asset class
```

Fixed income accrues daily at its rate; manual assets use their latest valuation.

### Import and export

`marketpulse import activities.csv -a TFSA` understands the common broker column names (date/trade date, action/type, symbol, quantity, price, amount, commission, currency, account) and skips duplicates and anything it can't interpret — with the reason. `--dry-run` previews. `marketpulse export` writes the whole ledger.

### History

Net worth is snapshotted whenever you look. To rebuild years of daily history from your ledger and historical prices:

```bash
marketpulse backfill
```

## macOS menu bar

```bash
marketpulse menubar install
```

Builds a tiny native SwiftUI app into `~/Applications/MarketPulse Bar.app` and launches it. It shows your day change (or net worth, or any symbol) in the menu bar; the popover has a net-worth chart, accounts, movers, watchlist sparklines and alerts, all in your MarketPulse theme. **⌥⌘M** opens the full TUI in Ghostty, iTerm, kitty, WezTerm or Terminal. Settings include refresh interval, terminal, and launch at login.

Requires the Xcode Command Line Tools (`xcode-select --install`). `marketpulse menubar uninstall` removes it.

## Omarchy

MarketPulse ships every built-in [Omarchy](https://omarchy.org) theme — Tokyo Night, Catppuccin, Everforest, Gruvbox, Kanagawa, Nord, Osaka Jade, Ristretto, Rose Pine, Matte Black, Hackerman, Lumon, Retro 82 and the rest — and with `theme = "auto"` it follows whatever theme Omarchy has active. Themes whose red and green are too similar to tell gains from losses get a legible substitute pair.

```bash
marketpulse theme                 # preview every palette
marketpulse theme set kanagawa
```

Waybar module:

```jsonc
"custom/marketpulse": {
  "exec": "marketpulse status --waybar",
  "return-type": "json",
  "interval": 60,
  "on-click": "xdg-terminal-exec marketpulse"
}
```

`status --short` prints a one-liner for tmux, sketchybar or your prompt, and `status --json` is the full machine-readable payload.

## Configuration

`~/.config/marketpulse/config.toml` (or `$MARKETPULSE_CONFIG`) — edit with `marketpulse config edit` or set keys directly:

| Key | Default | |
|-----|---------|-|
| `theme` | `"auto"` | Omarchy theme slug, or `auto` |
| `base_currency` | `"CAD"` | Totals and reports are converted into this |
| `refresh_seconds` | `30` | TUI quote refresh |
| `privacy` | `false` | Mask amounts everywhere (`p` in the TUI) |
| `default_account` | `""` | Used when `-a` is omitted and you have several accounts |
| `chart_period` | `"3mo"` | Default chart range |
| `market_strip` | S&P, Nasdaq, TSX, USD/CAD, BTC, gold, 10Y | Dashboard ticker strip |
| `capital_gains_inclusion` | `0.5` | Used by the tax report |
| `menubar_display` | `"day_pct"` | `day_pct`, `day_change`, `net_worth` or `symbol` |
| `menubar_symbol` | `""` | Symbol shown when `menubar_display = "symbol"` |

Data lives in `~/.marketpulse/marketpulse.db` (override with `MARKETPULSE_DATA`). `marketpulse doctor` checks your setup.

## Market data

Quotes, history, dividends and search come from Yahoo Finance's public endpoints via `curl_cffi`. Quotes are fetched in batches, cached briefly, and the last known prices are shown (marked offline) when the network is unavailable. Data may be delayed; this is a personal tracker, not a trading tool, and tax figures are estimates to check against your slips.

## Development

```bash
uv sync
uv run pytest          # 100+ tests, no network (a fake Yahoo transport is used)
uv run ruff check . && uv run ruff format .
swift build --package-path macos/MarketPulseBar
```

```
src/marketpulse/
  models.py      accounts, transactions, assets, quotes
  ledger.py      replay engine: holdings, ACB, income, cash, room, superficial losses
  analytics.py   XIRR, time-weighted returns, drawdown, rebalancing, income, capital gains
  valuation.py   prices the ledger into a portfolio view
  market.py      Yahoo client (batch quotes, history, dividends, search, FX)
  db.py          SQLite store + legacy JSON migration
  services.py    Tracker facade used by the CLI, TUI and menu bar
  themes.py      Omarchy palettes → Textual + Rich themes
  charts.py      braille charts, sparklines, bars
  render.py      shared Rich renderables
  cli.py         Click commands
  tui/           Textual app, widgets and forms
macos/MarketPulseBar/   SwiftUI menu bar companion
```
