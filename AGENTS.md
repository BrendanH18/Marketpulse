# Agent guide

Instructions for AI coding agents (Claude Code, Codex, Cursor, and others) and
the people directing them. Keep durable project context in this file and the
repository docs so it is available to every agent and fresh clone.

## What this project is

MarketPulse is a local-first investment tracker for Canadian investors: a Python
engine (ledger, pooled ACB, FX, tax, CSV import, quotes) with a CLI and TUI, plus
a native SwiftUI app for macOS that talks to the engine through a versioned JSON
bridge. The Mac app shipped in v3.0.0 (epic [#32](https://github.com/BrendanH18/Marketpulse/issues/32),
closed); current status and next steps are in [docs/roadmap.md](docs/roadmap.md), and
the app's decisions in [docs/app-plan.md](docs/app-plan.md).

| Path | What's there |
| --- | --- |
| `src/marketpulse/` | Engine and CLI. `models.py`, `ledger.py`, `valuation.py`, `services.py` (core); `csvio.py` (import/export); `market.py` (quotes); `db.py` (SQLite, backups, migrations); `cli/`; `tui/` |
| `src/marketpulse/desktop.py`, `automation.py` | Desktop JSON bridge and the shared refresh/backup/alert cycle |
| `macos/MarketPulseBar/` | SwiftUI app (menu bar + portfolio window), `AppIcon.icns` |
| `scripts/` | Bridge, coverage and localization checks; QA and standalone app builders; release, benchmark, installer, icon and README-preview scripts |
| `tests/` | pytest with isolated data, fake Yahoo transport, mocked notifications |
| `docs/` | User guides, plan, QA checklist, roadmap |

## Start of every session

1. Read this file, then the issue you're working on **including its latest comments**.
   A `Handoff` comment means another agent started; continue from it.
2. If the issue is unclaimed, claim it with a comment:
   `Claiming for <agent/model>. Branch: <branch>.`
3. Prefer issues labelled `agent-ready`. Skip `needs-decision` issues; ask the maintainer instead.

## Cloud sandboxes (Boat)

Use a Boat sandbox for builds, tests, untrusted code, Docker, and long jobs. Never run them on this computer.
Docs: https://docs.boat.dev/llms.txt. Prices and limits: run `boat limits`; never quote prices from memory.

- Create: `id=$(boat new --json | jq -r 'select(.event=="ready") | .id')`
- One-shot job: `boat run --push . -- npm test` (new sandbox, run, cost, delete; exits with the test exit code)
- Run: `boat exec "$id" --cwd my-app "npm test"` (30 s timeout; `--timeout 0` = no limit)
- Server: `boat exec "$id" --detach "npm run dev"`, then `boat exec "$id" --status <pid>`
- Copy files: `boat push "$id" ./my-app` (git-tracked files, to /home/user/my-app) or clone the repo inside the sandbox
- Public URL for a port: `boat ssh "$id" "host 3000 --private"`
- Always pass the sandbox id. `current` does not work in a non-interactive shell.
- When done: `boat stop "$id"` (keeps the disk for at least 14 days) or `boat delete "$id" --yes` (erases it)
- Boat is x86_64 Linux. Run the Python checks (`uv sync`, Ruff, mypy, pytest with coverage) in Boat. These need macOS, so they run on this Mac: `swift format`, `swift build`, `scripts/check_native_bridge.py`, `scripts/build_app.py`, `scripts/qa_app.py` (both download a pinned CPython and packages, so ask before the first run on this Mac) and the [docs/qa.md](docs/qa.md) checklist, `menubar install` / `desktop install`, `scripts/benchmark_desktop.py`, `scripts/release.py package` and `verify` (they use `ditto`, `hdiutil` and `codesign`), and the darwin-only tests (for example `tests/test_update_check.py`), which pytest skips on Linux.

## Checks

```bash
uv sync --locked --dev
uv run --locked ruff check . && uv run --locked ruff format --check . && uv run --locked mypy
uv run --locked pytest -q --cov && uv run --locked python scripts/check_coverage.py
# macOS, for app or bridge changes:
swift format lint --strict -r macos/MarketPulseBar scripts/*.swift
swift build -c release --package-path macos/MarketPulseBar
uv run --locked python scripts/check_native_bridge.py
uv run --locked python scripts/build_app.py --out "$TMPDIR/mp-app"
```

All must pass before you hand work back. Paste the results, not a summary of them.

## Verifying app changes

Build the throwaway QA app on a fictional ledger and follow [docs/qa.md](docs/qa.md):

```bash
uv run --locked python scripts/qa_app.py --fresh && "$TMPDIR/marketpulse-qa/launch.sh"
```

Run the checklist with computer use and report the PASS / FAIL / UNVERIFIED
table. If you couldn't run it, say which items you couldn't verify. Never report a
UI item as passing that you didn't see.

## Commands

```bash
uv sync                                        # install (includes dev group: mypy, pytest, pytest-cov, ruff)
uv run marketpulse                             # TUI (no subcommand = TUI); `mp` is an alias
uv run pytest                                  # full suite, offline
uv run pytest tests/test_ledger.py::test_split_keeps_cost_base   # single test
uv run pytest --cov && uv run python scripts/check_coverage.py   # financial-core coverage floors (CI gate)
uv run ruff check . && uv run ruff format --check .   # lint; `ruff format .` applies fixes; line length 120
swift format -i -r macos/MarketPulseBar scripts/*.swift          # format Swift (.swift-format: 2 spaces, 120 columns)
swift build -c release --package-path macos/MarketPulseBar       # menu bar app
```

The main ruleset requires the `CI passed` job in `.github/workflows/ci.yml`, which fails when any other CI job failed or was cancelled: add any new CI job to its `needs`.

Run the CLI against throwaway data with `MARKETPULSE_DATA=/tmp/x MARKETPULSE_CONFIG=/tmp/x/config.toml uv run marketpulse ...` — otherwise it reads/writes `~/.marketpulse/marketpulse.db` and `~/.config/marketpulse/config.toml`.

TUI changes can be checked headlessly, with `MARKETPULSE_DATA`/`MARKETPULSE_CONFIG` pointed at scratch paths as above (the test fixtures do this for you): `async with MarketPulseApp(Config.load()).run_test(size=(180, 52)) as pilot:`, then `pilot.press(...)` and `app.save_screenshot(...)` (see `tests/test_tui.py`).

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
- **TUI (`tui/`):** one `App` with a `ContentSwitcher` of 8 workspaces (not Screens); modals live in `screens.py`. `app.py` owns layout, state, lifecycle, and Textual `@on`/`@work` entry points. Typed helpers in `workspaces.py` render views, `chart.py` handles chart interaction, `records.py` handles transaction/account/asset edits, `actions.py` handles watchlists, alerts, CSV, and app actions, `navigation.py` handles keyboard navigation, table sorting and filtering, clipboard copies and the footer status, and `extras.py` holds row details, find, go-to, grouping and other per-workspace extras. `commands.py` owns command-palette discovery; `constants.py` holds workspace hints and display choices. Helpers receive the app; entry points forward to them so Textual dispatch and worker ownership stay on the app. Network/DB work runs in `@work(thread=True)` workers that hand results back via `call_from_thread`. `Canvas` widgets take a `(width, height) -> renderable` builder so charts reflow on resize. `MarketPulseApp` sets `config`/`palette` *before* `super().__init__()` because Textual requests theme variables during construction; avoid attribute names that shadow `App` internals (e.g. `_ready`).
- **CLI (`cli/`):** one Click group, `main` in `cli/root.py`; each module (`accounts.py`, `recording.py`, `native.py`…) adds one area's commands, and `cli/__init__.py` imports them all. `App` (in `cli/base.py`, with `fail` and the shared options) is the context object; it lazily opens the `Tracker`. Account resolution for `-a` is `Store.get_account` (id, case-insensitive name, or unique account type). Table renderers take `width` and drop low-priority columns under 110 columns.
- **Offline reports (`cli/reports.py`, `cli/summaries.py`):** `report SOURCE` and `summarize SOURCE` share the dataset adapters registered in `reports.SOURCE_MODULES`; each `report_*` adapter module exposes `GROUP`, `SOURCES` (ordered field schemas), `DESCRIPTIONS` and `load_source`. Adapters are read-only, offline and hide archived accounts. `report_derive.py` computes `--derive` columns after loading and before filters. The dataset × operation matrices in `tests/` parametrize over `reports.SOURCES`, so a new dataset or operation extends them; `docs/cli-report-derived-datasets.md` is checked against the code.
- **Report discovery:** `report report-fields` catalogs source names, groups and ordered field positions directly from `reports.SOURCE_MODULES`, including its own schema, without opening the tracker. The 200-improvement inventory for #162 is in `docs/cli-discovery-improvements.md` (197 dataset/operation combinations and three CLI typo-suggestion improvements).
- **Native app (`macos/MarketPulseBar`, `menubar.py`, `desktop.py`):** the Swift app (menu bar + portfolio window) refreshes with `marketpulse desktop snapshot`, the versioned desktop JSON bridge built in `desktop.py` (decoded with `convertFromSnakeCase` in `DesktopModels.swift`). If that fails, the menu bar falls back to `marketpulse status --json` (`Tracker.status_payload`, `Models.swift`), a separate stable contract. Writes shell out to ordinary CLI commands with user text after `--`. Changing either payload requires updating the Swift models and `scripts/check_native_bridge.*`. `menubar install` builds with SwiftPM, assembles `~/Applications/MarketPulse Bar.app`, and stores the CLI path in `defaults` (`dev.marketpulse.bar cliPath`). Don't use SwiftUI `@State` — the Command Line Tools toolchain lacks the macro plugin; use `ObservableObject` state instead.
- **Tax in the app:** tax loads on demand through `desktop tax`, invalidates on the snapshot's `ledger_revision`, and exports through `desktop tax-csv`. Tax includes anonymized archived taxable entries as the engine requires; ordinary portfolio views still hide archived accounts.
- **Platforms:** macOS (app, CLI, TUI) and Linux (CLI, TUI). There is no Windows build ([ADR 0002](docs/adr/0002-no-windows-build.md)); the engine keeps its portability code (explicit UTF-8, `tzdata` on Windows), but nothing is built or tested there.
- **Legacy migration:** `db.migrate_legacy_json` imports 0.1 `~/.marketpulse/*.json` portfolios once (guarded by a `meta` key), reconciling positions removed without a sell via a zero-gain SELL.

Tests are isolated by autouse fixtures that point `MARKETPULSE_DATA`/`MARKETPULSE_CONFIG` at tmp dirs, disable Omarchy detection, and stub desktop notifications.

## Rules

- **No Windows build.** The maintainer dropped Windows on 2026-11-14
  ([ADR 0002](docs/adr/0002-no-windows-build.md)). Don't add a Windows app,
  installer, script or CI job, or Windows-only work to an issue, unless the
  maintainer reverses that decision.
- **Never touch real financial data.** Use fictional data in tests, docs, fixtures,
  and screenshots. For manual runs set `MARKETPULSE_DATA` and `MARKETPULSE_CONFIG`
  to a scratch directory; never read or write `~/.marketpulse`.
- **Financial math** (ACB, FX, tax, valuation, contribution room) changes only under
  an issue that calls for it, with tests on fictional fixtures that show the before and after.
- **Desktop bridge:** adding fields is fine; removing or changing one requires bumping
  `version` and updating the Swift models and `scripts/check_native_bridge.*`.
  `status --json` is a separate stable contract; note any change in the changelog.
- **Invariants that tests protect; keep them:** archived accounts are hidden everywhere
  and left out of totals; a CSV preview runs the real import against a temporary copy, so
  preview equals import; text typed in the app reaches the CLI after `--`; stale quotes
  never fire alerts or record snapshots.
- No new network calls, telemetry, or accounts beyond what an issue specifies. No secrets in the repo.
- Keep changes focused on one issue. Refactors stay behavior-preserving.
- Add a line to `CHANGELOG.md` under **Unreleased** for user-visible changes, and update the docs you affect.

## Handoff protocol

Hand off whenever you might not finish: usage limits, a long-running task, a
blocker, or the end of a session. It takes two minutes and saves the next agent an hour.

Post this comment **on the issue**. If you cannot access GitHub, return the
handoff block in your response for the maintainer to post:

```markdown
### Handoff — <agent/model>, <YYYY-MM-DD>
**Status:** in progress | blocked | ready for review
**Branch / PR:** `<branch>` / #<pr>
**Done:**
- …
**Next steps (in order):**
1. …
**Verified:** <commands run and results; QA items checked>
**Not verified / known issues:** …
**Gotchas:** <anything surprising: environment quirks, failed approaches, decisions made>
**Open questions for the maintainer:** …
```

The next agent starts from the latest handoff comment, not from scratch.

## Agent-specific notes

- **Claude Code** reads `CLAUDE.md`, which only imports this file.
- **Codex** and **Cursor** read `AGENTS.md` directly.
- Agents without GitHub access can't read issues: the maintainer should paste the
  issue and its latest handoff comment into the session.

## Context maintenance

- Keep project rules and durable project knowledge in tracked `AGENTS.md` and
  repository docs; do not store them in agent auto-memory or machine-local notes.
- `CLAUDE.md` contains only `@AGENTS.md`. Shared hooks, scripts and settings
  belong in tracked files. Do not ignore instruction files or shared settings;
  ignore only machine-local settings and agent worktrees.
