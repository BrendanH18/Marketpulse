# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies and create venv
uv sync

# Run the CLI
uv run marketpulse --help
uv run marketpulse              # no args launches the Textual TUI
uv run marketpulse watch
uv run marketpulse quote AAPL
uv run marketpulse chart SPY --period 1y
uv run marketpulse compare XEQT.TO QQQ SPY --period 1y
uv run marketpulse portfolio show
```

There are no tests or linter configs in this project.

## Architecture

Six modules with strict separation of concerns:

- **`models.py`** — Pure dataclasses (`Quote`, `Position`, `Portfolio`). No I/O. Computed properties for change/P&L math live here.
- **`fetcher.py`** — All yfinance calls. `fetch_quotes()` parallelizes via `ThreadPoolExecutor`. Uses `fast_info` first, falls back to the slower `t.info` dict if price is missing.
- **`storage.py`** — JSON read/write to `~/.marketpulse/<name>.json`. Override location with `MARKETPULSE_DATA` env var.
- **`display.py`** — All `rich` rendering. Receives model objects, returns `Panel`/`Table`/`Text`. The ASCII chart in `history_panel()` and sparklines in `_sparkline()` use Unicode block characters.
- **`main.py`** — `click` CLI wiring only. Calls fetcher → passes results to display. `portfolio add` blends shares/avg cost when a position already exists. Running with no subcommand launches the TUI.
- **`tui.py`** — Textual app (`MarketPulseApp`), a second UI entry point alongside `main`. Three tabs (Watchlist / Portfolio / Chart) that reuse `display` renderables inside `Static` widgets. Fetches run in `@work(thread=True)` workers; UI updates go through `call_from_thread`.

Data flows strictly: `main`/`tui` → `fetcher` → `models` → `display`. Storage is only touched by the entry points (`main`, `tui`).
