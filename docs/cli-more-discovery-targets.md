# Saved targets and command discovery (76–100)

[Batch inventory](cli-more-hundred-improvements.md) · [Issue #134](https://github.com/BrendanH18/Marketpulse/issues/134)

`targets` is a read-only inspector for saved allocation target percentages.
It never prices holdings or records a snapshot. Continue setting targets with
`allocation --target CLASS=PCT -q`; the existing `allocation --show-targets`
output is unchanged. JSON and CSV target rows contain `bucket`, `label`, and
`target` (percent). Plain output shows the same saved rows as a table.

| # | New capability | Example |
| --- | --- | --- |
| 76 | Export saved target rows as CSV | `marketpulse targets --csv` |
| 77 | Count matching saved targets | `marketpulse targets --positive --count` |
| 78 | Include several saved target classes | `marketpulse targets --class etf --class equity` |
| 79 | Exclude several saved target classes | `marketpulse targets --exclude-class other` |
| 80 | Search saved class keys and labels | `marketpulse targets --search income` |
| 81 | Select an inclusive target minimum | `marketpulse targets --min-target 10` |
| 82 | Select an inclusive target maximum | `marketpulse targets --max-target 50` |
| 83 | Inspect positive saved targets | `marketpulse targets --positive` |
| 84 | Inspect explicitly saved zero targets | `marketpulse targets --zero` |
| 85 | Sort saved targets by class, label or percentage | `marketpulse targets --sort target` |
| 86 | Reverse saved target ordering | `marketpulse targets --sort target --descending` |
| 87 | Limit saved target matches | `marketpulse targets --limit 2` |
| 88 | Skip saved target matches | `marketpulse targets --offset 2` |
| 89 | Include target pagination metadata | `marketpulse targets --json --page-info --limit 2` |
| 90 | Print only matching target class keys | `marketpulse targets --buckets-only` |
| 91 | Project saved target fields in a chosen order | `marketpulse targets --csv --fields target,bucket` |
| 92 | Find one exact command path | `marketpulse commands --exact 'provider status'` |
| 93 | Find command path prefixes | `marketpulse commands --prefix 'provider s'` |
| 94 | Exclude groups and all descendants, repeatably | `marketpulse commands --exclude-group provider --exclude-group menubar` |
| 95 | Select a minimum nesting depth | `marketpulse commands --min-depth 2` |
| 96 | Find commands with or without positional arguments | `marketpulse commands --has-arguments` (or `--no-arguments`) |
| 97 | Find commands with or without required parameters | `marketpulse commands --has-required` (or `--no-required`) |
| 98 | Search parameter names, flags, types and help | `marketpulse commands --parameter-search=--csv` |
| 99 | Include command pagination metadata | `marketpulse commands --json --page-info --limit 10` |
| 100 | Print only command paths for scripts | `marketpulse commands --group provider --paths` |

Selections combine before sorting and pagination; `--count` counts all matches
and rejects pagination. `--page-info` requires JSON and returns `rows`, `total`,
`offset`, and `limit`. Empty selections produce empty arrays or CSV headers.
Target fields must be unique known names; projection requires JSON or CSV.
Target percentages must be finite and within 0–100; zero targets must have
actually been saved, rather than being inferred for unsaved classes. Sorting
by percentage breaks ties by class key; label sorting ignores case. These are configured percentages, not
financial valuations or advice; no contributions, ACB, tax or FX are computed.

Command discovery does not open the ledger. Exact and prefix matching ignore
case and normalize whitespace. Excluded group names must be valid group paths;
excluding the selected group yields no rows. Presence filters refer to explicitly
declared parameters on each command, rather than inherited root options. `--paths`
rejects other formats and `--details`; parameter search does not require details.
