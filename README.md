# ⚡ MarketPulse

A terminal-based portfolio tracker with live market data, ASCII charts, and multi-portfolio management. Made with Claude Code.

---

## Install & Run

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### Setup

```bash
# Clone / enter project
cd marketpulse

# Create venv and install all deps with uv
uv sync

# Run directly via uv
uv run marketpulse --help

# Or install command globally
uv tool install --editable .
```

---

## Commands

### TUI — Interactive Mode (default)

Run with no arguments to launch the full-screen TUI — one process, no re-running commands:

```bash
uv run marketpulse                 # launches the TUI
uv run marketpulse tui -p rrsp     # TUI on a named portfolio
uv run marketpulse tui -r 15       # refresh quotes every 15s
```

Keys: `1`/`2`/`3` switch between Watchlist, Portfolio, and Chart tabs • `r` refresh now • `a` add/buy • `s` sell • `d` remove • `i` quote details • `h` transaction history • `q` quit.
On the Chart tab, type `TICKER [PERIOD]` (e.g. `SPY 1y`) and press Enter.

### `watch` — Live Watchlist Table

```bash
# Default watchlist (XEQT.TO, SPY, QQQ, NVDA, BTC-USD, etc.)
uv run marketpulse watch

# Custom tickers
uv run marketpulse watch XEQT.TO VFV.TO AAPL MSFT

# Auto-refresh every 30 seconds
uv run marketpulse watch --refresh 30

# Use your portfolio's watchlist
uv run marketpulse watch -p myportfolio
```

### `quote` — Detailed Quote Cards

```bash
uv run marketpulse quote XEQT.TO
uv run marketpulse quote AAPL NVDA MSFT BTC-USD
uv run marketpulse quote VFV.TO ZAG.TO
```

### `chart` — ASCII Price Chart

```bash
uv run marketpulse chart XEQT.TO
uv run marketpulse chart SPY --period 5y
uv run marketpulse chart BTC-USD --period 1y
```

Periods: `1d` `5d` `1mo` `3mo` `6mo` `1y` `2y` `5y`

### `compare` — Normalized Performance Comparison

```bash
# Compare XEQT vs QQQ vs SPY over 1 year
uv run marketpulse compare XEQT.TO QQQ SPY --period 1y

# Canadian ETF shootout
uv run marketpulse compare XEQT.TO VFV.TO QQC.TO --period 2y
```

Includes return %, max drawdown, and sparklines.

### `portfolio` — Manage Holdings

```bash
# Record buys (TICKER SHARES PRICE_PER_SHARE) — fees fold into the cost base
uv run marketpulse portfolio buy XEQT.TO 200 28.50
uv run marketpulse portfolio buy AAPL 15 175.00 --fees 4.95 --note "Core holding"

# Record sells — realized P&L computed with the average-cost method
uv run marketpulse portfolio sell AAPL 5 200.00

# Transaction ledger (optionally for one ticker)
uv run marketpulse portfolio history
uv run marketpulse portfolio history AAPL

# View with live P&L, day change, weights, and a portfolio summary.
# Mixed-currency portfolios convert totals into the portfolio's base
# currency (CAD by default) using live FX rates.
uv run marketpulse portfolio show

# Use a named portfolio
uv run marketpulse portfolio -n rrsp buy VFV.TO 100 105.00
uv run marketpulse portfolio -n rrsp show

# Manage watchlist
uv run marketpulse portfolio watchlist-add NVDA TSM ASML
uv run marketpulse portfolio watchlist-remove NVDA

# Remove a position
uv run marketpulse portfolio remove AAPL

# List all saved portfolios
uv run marketpulse portfolio list

# Delete a portfolio
uv run marketpulse portfolio delete rrsp
```

---

## Ticker Format Notes

| Asset type      | Format example      |
|-----------------|---------------------|
| TSX (Canadian)  | `XEQT.TO`, `VFV.TO` |
| NYSE/NASDAQ     | `AAPL`, `QQQ`, `SPY`|
| Crypto          | `BTC-USD`, `ETH-USD` |

---

## Data Directory

Portfolios are stored as JSON in `~/.marketpulse/`. Override with `MARKETPULSE_DATA` env var.
Files saved before transaction support (schema 1) are migrated automatically: existing positions
get a synthesized "opening balance" BUY so the ledger replays to your current holdings.

---

## Development

```bash
uv sync                  # includes dev group (pytest, ruff)
uv run pytest            # test suite
uv run ruff check .      # lint
uv run ruff format .     # format
```

---

## Dependencies

| Package      | Purpose                         |
|--------------|---------------------------------|
| `yfinance`   | Yahoo Finance market data       |
| `rich`       | Terminal UI, tables, panels     |
| `textual`    | Interactive TUI                 |
| `click`      | CLI framework                   |
| `pandas`     | Time series data manipulation   |
| `httpx`      | HTTP client (used by yfinance)  |
| `python-dotenv` | Env var config               |
