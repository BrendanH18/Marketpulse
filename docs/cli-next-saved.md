# Saved symbols, alerts, themes and configuration workflows

[User guide](usage.md) · [Issue #132](https://github.com/BrendanH18/Marketpulse/issues/132)

These 25 additions read local metadata. Existing plain commands retain their
behavior. Watch filters below imply offline mode, and combine with existing
sorting, paging, JSON, CSV and counts. Examples use fictional symbols.

| # | Capability | Example |
| --- | --- | --- |
| 51 | Select watched symbols currently held in active accounts, or their complement | `marketpulse watch list --held` / `--not-held` |
| 52 | Select watched symbols with a readable local quote, or their complement | `marketpulse watch list --cached` / `--not-cached` |
| 53 | Match watched symbol suffixes, ignoring case | `marketpulse watch list --suffix .TO` |
| 54 | Exclude watched symbols containing text, ignoring case | `marketpulse watch list --exclude-search ALPHA` |
| 55 | Emit one saved symbol per line for shell pipelines | `marketpulse watch list --lines --alphabetical` |
| 56 | Select an exact set of saved alert IDs | `marketpulse alerts list --id 2 --id 7` |
| 57 | Browse alerts starting at an inclusive ID | `marketpulse alerts list --min-id 10` |
| 58 | Browse alerts through an inclusive ID | `marketpulse alerts list --max-id 20` |
| 59 | Exclude one or several alert conditions | `marketpulse alerts list --exclude-condition above --exclude-condition below` |
| 60 | Select alerts whose symbol is watched, or their complement | `marketpulse alerts list --watched` / `--not-watched` |
| 61 | Select alerts with retained trigger history, including paused alerts, or those without it | `marketpulse alerts list --ever-triggered` / `--never-triggered` |
| 62 | Count alerts by retained trigger month, with a `never` bucket | `marketpulse alerts list --summary trigger-month --json` |
| 63 | Browse the embedded theme catalog without changing the active theme | `marketpulse theme list` |
| 64 | Find a theme by slug or display label, ignoring case | `marketpulse theme list --search tokyo` |
| 65 | Select dark or light themes | `marketpulse theme list --mode light` |
| 66 | Export theme slugs, labels and modes as CSV | `marketpulse theme list --csv` |
| 67 | Count matching themes before pagination | `marketpulse theme list --mode dark --count` |
| 68 | Emit theme slugs one per line for scripts | `marketpulse theme list --names` |
| 69 | Page through the alphabetically ordered theme catalog | `marketpulse theme list --offset 2 --limit 5` |
| 70 | Browse the theme catalog in reverse alphabetical order | `marketpulse theme list --descending` |
| 71 | Preview resetting a setting without writing the config file | `marketpulse config reset privacy --dry-run` |
| 72 | Get a machine-readable reset receipt | `marketpulse config reset privacy --json` |
| 73 | Get a normalized machine-readable setting receipt | `marketpulse config set base_currency usd --json --dry-run` |
| 74 | Discover settings by their declared value type | `marketpulse config keys --type bool` |
| 75 | Count matching setting names | `marketpulse config keys --changed --count` |

`--held` uses positive open holdings from the ledger and excludes archived
accounts. `--cached` means that a saved quote can be decoded; it does not claim
that its price is fresh. Neither filter requests prices, records a snapshot or
fires alerts. Membership selection precedes sorting and pagination and never
changes the saved watchlist order. `--lines` is an output format and cannot be
combined with JSON, CSV or count output.

Alert filters run before summaries, counts and paging. Trigger history is
independent of whether an alert is paused. Rearming an alert clears that retained
history, as before. `trigger-month` uses the first seven characters of the saved
trigger timestamp; alerts without one are grouped as `never`. Thresholds remain
masked in human output when privacy mode is enabled; existing machine-readable
alert formats remain raw and unmasked.

`theme list` includes embedded themes, while `theme` and `theme --json` keep their
existing active-theme display and contract. Theme listing and configuration
commands never open the ledger. Theme search and mode filters run before counts
and paging. Output formats (`--csv`, `--count`, `--names`) are mutually exclusive.

Setting and reset receipts contain `key`, normalized `value`, and `saved`.
`--dry-run` produces `saved: false` and does not create or alter the file.
Otherwise the setting is saved before the receipt is printed. API key writes
remain restricted to `provider key` and `provider clear`; reset and set receipts
cannot expose or modify that secret. Type choices are `bool`, `int`, `float`,
`str`, and `list`, based on factory defaults rather than potentially malformed
saved values. `config keys --type` combines with `--search` and `--changed`;
`--count` and `--json` are mutually exclusive.
