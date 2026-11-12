# Command discovery and diagnostic exports (76–100)

[Batch inventory](cli-next-hundred-improvements.md). All examples are offline.
The catalog reads Click metadata without opening the database. Provider status
reads the existing attempt state without fetching quotes. Doctor still runs
its selected checks; use `--offline` to skip network checks.

| # | New capability | Example |
| --- | --- | --- |
| 76 | Browse a command catalog with help text | `marketpulse commands` |
| 77 | Scope discovery to a command group | `marketpulse commands --group 'accounts'` |
| 78 | Search command paths and help, case-insensitively | `marketpulse commands --search offline` |
| 79 | Find commands that accept an option | `marketpulse commands --option=--csv` |
| 80 | List executable leaf commands only | `marketpulse commands --leaves` |
| 81 | List command groups only | `marketpulse commands --groups` |
| 82 | Export the command catalog as JSON | `marketpulse commands --json` |
| 83 | Export the command catalog as CSV | `marketpulse commands --csv` |
| 84 | Count matching commands before pagination | `marketpulse commands --search tax --count` |
| 85 | Limit command catalog results | `marketpulse commands --limit 10` |
| 86 | Skip command catalog results | `marketpulse commands --offset 10` |
| 87 | Reverse alphabetical catalog order | `marketpulse commands --descending` |
| 88 | Include parameter flags, names, types, required status and help | `marketpulse commands --group provider --details --json` |
| 89 | Generate a Markdown command reference | `marketpulse commands --markdown` |
| 90 | Limit discovery to a maximum nesting depth | `marketpulse commands --depth 1` |
| 91 | Export provider status as CSV | `marketpulse provider status --csv` |
| 92 | Select an exact provider name | `marketpulse provider status --name yahoo` |
| 93 | Select providers by role | `marketpulse provider status --role primary` |
| 94 | Select providers by last attempt state | `marketpulse provider status --state untried` |
| 95 | Count matching providers | `marketpulse provider status --role fallback --count` |
| 96 | Export diagnostic checks or their status summary as CSV | `marketpulse doctor --offline --csv` |
| 97 | Filter diagnostic results by repeatable status | `marketpulse doctor --offline --status fail --status skipped` |
| 98 | Search diagnostic names and details | `marketpulse doctor --offline --search ledger` |
| 99 | Count diagnostic matches | `marketpulse doctor --offline --status fail --count` |
| 100 | List diagnostic check names without executing them | `marketpulse doctor --list-checks --json` |

The command tree listing includes every visible registered group and leaf.
Parameter discovery includes explicitly declared parameters; Click’s implicit
help option is omitted.
`doctor --list-checks` supports human, JSON, CSV and count output.

Formats are mutually exclusive. `commands --count` rejects pagination;
`--groups` and `--leaves` are mutually exclusive. An unknown `--group` is an
error; unmatched searches yield an empty result. CSV parameter details are a
JSON array in the `parameters` column. Markdown details appear inside their
command rows. All catalog output is raw command metadata, never financial data.

Provider states are `ok`, `failing`, and `untried`. Provider filters combine,
and a filtered human listing omits the general setup hint. No API keys are
included. Diagnostic `--strict` and JSON's `ok` reflect **all executed checks**,
even if result filters hide a failure; filtering is presentation only.
