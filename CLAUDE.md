# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
The shared rules for every agent (claiming issues, checks, QA, and the handoff protocol) are in AGENTS.md:

@AGENTS.md

## Commands

```bash
uv sync                                        # install (includes dev group: pytest, ruff)
uv run marketpulse                             # TUI (no subcommand = TUI); `mp` is an alias
uv run pytest                                  # full suite, offline (~2s)
uv run pytest tests/test_ledger.py::test_split_keeps_cost_base   # single test
uv run pytest --cov && uv run python scripts/check_coverage.py   # financial-core coverage floors (CI gate)
uv run ruff check . && uv run ruff format --check .   # what CI runs; `ruff format .` applies fixes; line length 120
swift build -c release --package-path macos/MarketPulseBar       # menu bar app
```

Run the CLI against throwaway data with `MARKETPULSE_DATA=/tmp/x MARKETPULSE_CONFIG=/tmp/x/config.toml uv run marketpulse ...` — otherwise it reads/writes `~/.marketpulse/marketpulse.db` and `~/.config/marketpulse/config.toml`.

TUI changes can be checked headlessly: `MarketPulseApp(Config.load()).run_test(size=(180, 52))` with `pilot.press(...)` and `app.save_screenshot(...)` (see `tests/test_tui.py`).

## Architecture

Python package in `src/marketpulse/` (Python ≥3.11, deps: click, rich, textual, curl_cffi) plus a SwiftUI menu bar app in `macos/MarketPulseBar/`.

**Data flow:** `db.Store` (SQLite) → `ledger.replay()` → `valuation.build_view()` (+ quotes/FX from `market.MarketData`) → `PortfolioView` → rendered by `render.py` (CLI) or `tui/app.py` (TUI). `services.Tracker` is the single facade that wires store + market + config; the CLI, TUI and menu bar all go through it.

- **The ledger is the only source of truth.** There is no stored "positions" table. Holdings, average-cost ACB, cash, income, realized gains and contribution flows are always derived by `ledger.replay()`, which sorts by `(date, same-day type order, id)` and applies each row via `ledger._apply()`; `ledger.replay_by_day()` walks one state forward a day at a time (used by backfill, so history is one pass rather than one replay per day). Any new transaction type must be handled in `_apply`, in `models.TxnType` (`needs_symbol`/`uses_quantity`/`uses_amount`), in `analytics.external_flows`, and in the TUI `TransactionForm` field visibility.
- **Pricing depends on `Asset.kind`:** `MARKET` symbols need no asset row and are priced from Yahoo; `FIXED_INCOME` accrues via `Asset.accrual_factor`; `MANUAL` uses the latest `VALUATION` transaction. If a ledger currency disagrees with a listing currency, `valuation._price_holding` converts the price rather than trusting either blindly.
- **Cash** is only tracked for accounts with `track_cash=True`. Otherwise an account is "fully invested" and `external_flows` treats buys as contributions and sells/dividends as withdrawals (used by XIRR, TWR and snapshots).
- **Multi-currency:** everything is stored in native currency; conversion to `config.base_currency` (default CAD) happens only in `valuation`/`analytics`. Positions without a price or FX rate are listed in `view.excluded` and never silently summed; incomplete valuations are not written as snapshots.
- **Market data (`market.py`):** Yahoo blocks plain httpx/curl (HTTP 429), so requests go through `curl_cffi` with Chrome impersonation. Quotes use the batch `spark` endpoint (max 20 symbols per call); history/dividends use `chart`; `search` uses query2. Quotes are cached 15s in memory and persisted to `quote_cache` as an offline fallback (`Quote.stale`). Minor-unit currencies (GBp etc.) are normalized. Tests never hit the network: `tests/conftest.py::FakeTransport` fakes all three endpoints.
- **Snapshots:** `Tracker.valuation()` upserts today's net-worth snapshot; `Tracker.backfill()` rebuilds daily history by replaying the ledger per day against historical closes/FX. Performance (TWR, drawdown) is computed from snapshots.
- **Themes (`themes.py`, `themes_data.py`):** Omarchy `colors.toml` palettes are embedded (`themes_data.py` is generated — don't hand-edit, excluded from ruff). `theme = "auto"` reads the active Omarchy theme from `~/.local/state/omarchy/current/theme/colors.toml`. `Palette` maps to a Textual `Theme` (with `$mp-*` CSS variables) and to semantic Rich styles (`up`, `down`, `muted`, `accent`, `warn`, `info`, `title`…). `render.py` uses these style names, so the TUI must push the Rich theme onto `app.console` (done in `MarketPulseApp._push_rich_theme`). Palettes whose red/green hues are too close get a fallback gain/loss pair.
- **TUI (`tui/`):** one `App` with a `ContentSwitcher` of 8 workspaces (not Screens); modals live in `screens.py`. Network/DB work runs in `@work(thread=True)` workers that hand results back via `call_from_thread`. `Canvas` widgets take a `(width, height) -> renderable` builder so charts reflow on resize. `MarketPulseApp` sets `config`/`palette` *before* `super().__init__()` because Textual requests theme variables during construction; avoid attribute names that shadow `App` internals (e.g. `_ready`).
- **CLI (`cli.py`):** Click group; `App` context object lazily opens the `Tracker`. Account resolution for `-a` is `Store.get_account` (id, case-insensitive name, or unique account type). Table renderers take `width` and drop low-priority columns under 110 columns.
- **Native app (`macos/MarketPulseBar`, `menubar.py`, `desktop.py`):** the Swift app (menu bar + portfolio window) refreshes with `marketpulse desktop snapshot`, the versioned desktop JSON bridge built in `desktop.py` (decoded with `convertFromSnakeCase` in `DesktopModels.swift`). If that fails, the menu bar falls back to `marketpulse status --json` (`Tracker.status_payload`, `Models.swift`), a separate stable contract. Writes shell out to ordinary CLI commands with user text after `--`. Changing either payload requires updating the Swift models and `scripts/check_native_bridge.*`. `menubar install` builds with SwiftPM, assembles `~/Applications/MarketPulse Bar.app`, and stores the CLI path in `defaults` (`dev.marketpulse.bar cliPath`). Don't use SwiftUI `@State` — the Command Line Tools toolchain lacks the macro plugin; use `ObservableObject` state instead.
- **Legacy migration:** `db.migrate_legacy_json` imports 0.1 `~/.marketpulse/*.json` portfolios once (guarded by a `meta` key), reconciling positions removed without a sell via a zero-gain SELL.

Tests are isolated by autouse fixtures that point `MARKETPULSE_DATA`/`MARKETPULSE_CONFIG` at tmp dirs, disable Omarchy detection, and stub desktop notifications.
