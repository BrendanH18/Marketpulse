# One hundred CLI and terminal app workflow improvements

[User guide](usage.md) · [Data & scratch paths](data.md)

This batch adds 100 distinct, opt-in improvements across five areas of the CLI
and terminal app: tax and allocation inspection, diagnostics and settings,
accounts/watchlist/alerts, positions/snapshots/assets/data exchange, and the
terminal app (TUI). Every addition preserves existing defaults, financial math
(ACB, FX, tax, valuation, contribution room), `status --json`, and the desktop
bridge. No new network endpoints are added, archived accounts remain hidden in
ordinary portfolio views, and API keys remain redacted.

## Tax inspection (`cli/taxes.py`, 1–10)

1. `tax --since DATE` — Filter dispositions on or after `YYYY-MM-DD`.
2. `tax --until DATE` — Filter dispositions on or before `YYYY-MM-DD`.
3. `tax --currency CODE` — Filter dispositions by native currency (repeatable, case-insensitive).
4. `tax --exclude-currency CODE` — Exclude dispositions in native currency (repeatable, case-insensitive).
5. `tax --exclude-symbol TEXT` — Exclude dispositions whose symbol contains `TEXT` (repeatable, case-insensitive).
6. `tax --exact-symbol SYMBOL` — Match exact symbol(s), ignoring case (repeatable).
7. `tax --superficial` — Filter strictly to superficial-loss dispositions.
8. `tax --min-gain AMOUNT` — Filter complete dispositions with allowed gain `>= AMOUNT`.
9. `tax --max-gain AMOUNT` — Filter complete dispositions with allowed gain `<= AMOUNT`.
10. `tax --jsonl` — Emit raw, unmasked dispositions as JSON Lines.

## Allocation and targets (`cli/allocation.py`, 11–20)

11. `allocation --max-weight PCT` — Hide breakdown rows above `PCT%`.
12. `allocation --search TEXT` — Match breakdown or rebalance rows by key or label, ignoring case.
13. `allocation --exclude TEXT` — Exclude breakdown or rebalance rows by key or label (repeatable).
14. `allocation --jsonl` — Emit breakdown or `--drift-only` rebalance rows as JSON Lines.
15. `allocation --limit N` — Show at most `N` breakdown or `--drift-only` rows.
16. `allocation --offset N` — Skip the first `N` breakdown or `--drift-only` rows.
17. `allocation --drift-only --sort [target|drift|abs-drift|delta]` — Sort rebalancing rows by target, drift, absolute drift, or dollar delta.
18. `targets --summary` — Show saved target count, total targeted percentage, and unallocated percentage (supports `--json`).
19. `targets --untargeted` — List valid asset classes without a saved target.
20. `targets --require-100` — Exit with status 1 when saved targets do not sum to 100%.

## Doctor, providers, discovery and settings (`cli/doctor.py`, `cli/provider.py`, `cli/discovery.py`, `cli/settings.py`, 21–40)

21. `doctor -q/--quiet` — Suppress output and report health solely through the exit status.
22. `doctor --exclude-status STATUS` — Hide checks ending in the given status (repeatable).
23. `doctor --sort [check|status]` — Order visible checks by name or status severity (with `--descending`).
24. `doctor --names-only` — Print matching check names one per line for scripting.
25. `doctor --jsonl` — Emit matching checks as JSON Lines.
26. `provider status --supported` — Offline catalog of supported fallback quote providers (`--json`, `--csv`, `--count`, `--search`).
27. `provider status --search TEXT` — Filter provider status rows by name, label, or error text.
28. `provider status --exit-code` — Exit 1 if any shown provider is failing or a configured fallback lacks a key.
29. `provider key NAME --dry-run` (and `--json`) — Validate a fallback API key without saving, with a redacted JSON receipt.
30. `provider clear --dry-run` (and `--json`) — Preview clearing the fallback provider without modifying config.
31. `commands --has-options/--no-options` — Filter commands with or without options.
32. `commands --exclude-option FLAG` — Exclude commands accepting a given option flag (repeatable).
33. `commands --param-type TYPE` — Filter commands having a parameter of the given Click type.
34. `commands --sort [command|depth|params]` — Order commands by path, nesting depth, or parameter count.
35. `commands --jsonl` — Emit matching command catalog entries as JSON Lines.
36. `theme list --json` (and `--page-info`) — Export filtered/paginated embedded themes as JSON.
37. `theme set NAME --dry-run` (and `--json`) — Validate and preview a theme change without saving.
38. `config diff --details` — Show default and effective values side by side (text, JSON, and CSV).
39. `config defaults --value` — Print only the default value(s), one per line, for scripts.
40. `config validate --file PATH` — Validate an arbitrary TOML file offline without modifying active config.

## Accounts, watchlist and alerts (`cli/accounts.py`, `cli/watchlist.py`, 41–60)

41. `accounts list --jsonl` — Emit matching accounts as JSON Lines, offline.
42. `accounts list --names` — Print matching account names, one per line, offline.
43. `accounts list --ids` — Print matching account IDs, one per line, offline.
44. `accounts list --archived-only` — Show only archived accounts, offline.
45. `accounts show REF --archived` — Inspect an archived account by ID or name.
46. `accounts show REF --exists` — Print nothing and exit 0 if the account exists, 1 otherwise.
47. `accounts edit REF --json` — Print a structured JSON receipt with field diffs (supports `--dry-run`).
48. `accounts remove REF --json` — Print a structured JSON receipt with transaction count (supports `--dry-run`).
49. `accounts room --json` — Print contribution room status or update receipt as JSON.
50. `accounts room --dry-run` — Validate and preview a contribution room update without saving.
51. `watch list --prefix TEXT` — Match watchlist symbols starting with `TEXT`, ignoring case.
52. `watch list --jsonl` — Emit saved watchlist positions and symbols as JSON Lines, offline.
53. `watch move SYMBOL --dry-run` (and `--json`) — Preview moving a watchlist symbol without saving.
54. `watch add --from-holdings` — Add all symbols currently held in active accounts offline (supports `--dry-run` and `--json`).
55. `watch rm SYMBOLS... --json` — Print a JSON receipt of removed (or would-remove) symbols.
56. `alerts list --jsonl` — Emit matching alerts as JSON Lines, offline.
57. `alerts list --ids` — Print matching alert IDs one per line for scripting.
58. `alerts list --held/--not-held` — Filter alerts by whether their symbol is held in an active account.
59. `alerts show ALERT_ID --exists` — Print nothing and exit 0 if the alert exists, 1 otherwise.
60. `alerts pause|resume|rearm|rm --dry-run` (and `--json`) — Preview or emit JSON receipts for batch alert mutations.

## Positions, snapshots, assets and data/backup (`cli/positions.py`, `cli/snapshots.py`, `cli/assets.py`, `cli/data.py`, 61–80)

61. `positions --jsonl` — Emit open ledger positions as JSON Lines, offline.
62. `positions --symbols-only` — Print matching distinct symbols, one per line, offline.
63. `positions --symbol-suffix TEXT` — Match positions whose symbol ends with `TEXT`, ignoring case.
64. `positions --totals` — Print per-currency book-cost totals without mixing currencies (`--json`, `--csv`).
65. `cash --totals` — Print per-currency cash totals without mixing currencies (`--json`, `--csv`).
66. `snapshots --quarter-start-only` — Keep only snapshots on Jan 1, Apr 1, Jul 1, or Oct 1.
67. `snapshots --quarter-end-only` — Keep only snapshots on Mar 31, Jun 30, Sep 30, or Dec 31.
68. `snapshots --above-book` — Keep only snapshots where `net_worth > book`.
69. `snapshots --below-book` — Keep only snapshots where `net_worth < book`.
70. `snapshots --stats` — Show the count and date span plus net worth, book value, and daily change ranges by currency. JSON groups ranges under `by_currency`.
71. `asset list --jsonl` — Emit matching configured assets as JSON Lines, offline.
72. `asset list --held/--not-held` — Filter configured assets by open active holdings, offline.
73. `asset classify SYMBOL --clear` — Clear a custom `asset_class` override (supports `--dry-run` and `--json`).
74. `asset remove SYMBOL --dry-run` (and `--json`) — Preview removing asset metadata with active-holding count.
75. `asset value SYMBOL VALUE -a/--account` — Target a specific account for a manual valuation (supports `--dry-run` and `--json`). With `--request-id`, JSON returns the saved transaction ID on the first save and on retries.
76. `import --strict` — Refuse to write any rows if the dry-run preview finds any row issue or the file or ledger changes before import.
77. `export --no-overwrite` — Refuse to overwrite an existing file at `PATH`.
78. `export --dry-run` — Preview how many rows would be exported without writing a file.
79. `backup verify -q/--quiet` (and `--csv`) — Report backup validity solely via exit status, or export CSV.
80. `backup restore --json` — Emit structured JSON for `--dry-run` restore previews and completed restores.

## Terminal app (`tui/`, 81–100)

81. **Reset table sort (`0`)** — Restore the active workspace table to its default sort order.
82. **Half-page jump (`ctrl+d` / `ctrl+u`)** — Jump half a page down/up in active tables or scroll panes.
83. **Scroll `income` with `j`/`k`/`<`/`>`** — Keyboard scrolling on non-table scroll workspaces.
84. **Hide/show archived accounts (`I`)** — Toggle archived rows in the `tax` workspace's accounts table.
85. **Jump to symbol in holdings (`S`)** — Locate the selected symbol from watchlist, activity, alerts, or chart directly in holdings.
86. **Copy table as CSV (`#`)** — Copy the visible table with headers as RFC-4180 CSV (privacy-safe).
87. **Copy table as Markdown (`X`)** — Copy the visible table with headers as GitHub-Flavored Markdown (privacy-safe).
88. **Copy portfolio summary (`Q`)** — Copy net worth, today, unrealized, income YTD, and position count (privacy-safe).
89. **Context filter mode cycler (`M`)** — Cycle quick modes in holdings (`all`/`gainers`/`losers`/`non-market`), activity (`all`/`trades`/`income`/`cash`), and alerts (`all`/`armed`/`triggered`/`paused`).
90. **Activity account filter (`@`)** — Cycle accounts directly inside the activity workspace (plus command palette entries).
91. **Focus workspace input (`F2`)** — Focus `#holdings-filter`, `#activity-filter`, or `#chart-input`.
92. **Smart manual valuation prefill (`V`)** — Prefill the currently selected manual asset symbol instead of always the first.
93. **Smart `Y` on chart workspace** — Copy the active crosshair bar or chart period summary instead of failing.
94. **Dashboard movers metric cycler (`m`)** — Cycle dashboard movers between `day %`, `day $`, and `unrealized`.
95. **Tax year stepper (`-` / `+`)** — Focus a single tax year or return to all years in `#tax-view`.
96. **Income year stepper (`-` / `+`)** — Focus a single calendar year or all-time income by symbol in `#income-view`.
97. **Re-arm all triggered alerts (`U`)** — Re-arm every triggered alert in one keypress.
98. **Bulk pause / resume all alerts** — Command palette actions to pause or resume all alerts at once.
99. **Create local database backup** — Command palette action to save a manual SQLite backup.
100. **Restore Theme: Auto (Omarchy)** — Command palette entry to switch back to automatic Omarchy theme tracking.
