# Offline inventory workflows (improvements 26–50)

[Batch inventory](cli-next-hundred-improvements.md) · [Issue #132](https://github.com/BrendanH18/Marketpulse/issues/132)

These options inspect the fictional examples below entirely from the saved
ledger and metadata. They never fetch prices or write a snapshot. Existing
commands retain their defaults; all filters compose with existing selection,
sorting, pagination and output formats.

| # | Capability | Example |
| --- | --- | --- |
| 26 | Exclude recorded position currencies, repeatably | `marketpulse positions --exclude-currency USD` |
| 27 | Exclude active position accounts by ID, name or unique type, repeatably | `marketpulse positions --exclude-account 'Fictional Alpha'` |
| 28 | Set an inclusive minimum position average cost | `marketpulse positions --min-average-cost 10` |
| 29 | Set an inclusive maximum position average cost | `marketpulse positions --max-average-cost 20` |
| 30 | Select positions by account registration status | `marketpulse positions --registered` (or `--nonregistered`) |
| 31 | Select positions by account cash tracking | `marketpulse positions --cash-tracked` (or `--cash-untracked`) |
| 32 | Find positions with or without saved asset metadata | `marketpulse positions --no-metadata` (or `--has-metadata`) |
| 33 | Select position asset kinds offline | `marketpulse positions --asset-kind fixed_income` |
| 34 | Select explicitly classified positions offline | `marketpulse positions --asset-class etf` |
| 35 | Find positions by symbol prefix | `marketpulse positions --symbol-prefix AA` |
| 36 | Count matching positions by account | `marketpulse positions --summary account --json` |
| 37 | Count matching positions by recorded currency | `marketpulse positions --summary currency --csv` |
| 38 | Count matching positions by symbol across accounts | `marketpulse positions --summary symbol` |
| 39 | Find exactly zero cash balances, ignoring floating-point residue | `marketpulse cash --zero` |
| 40 | Select cash balances by account registration status | `marketpulse cash --nonregistered` (or `--registered`) |
| 41 | Count matching cash balances by account | `marketpulse cash --summary account` |
| 42 | Count matching cash balances by recorded currency | `marketpulse cash --summary currency --json` |
| 43 | Count matching cash balances by account type | `marketpulse cash --summary account-type --csv` |
| 44 | Count matching cash balances by institution | `marketpulse cash --summary institution` |
| 45 | Find accounts with or without open positions | `marketpulse accounts list --has-positions` (or `--no-positions`) |
| 46 | Find accounts with or without transaction history | `marketpulse accounts list --has-transactions` (or `--no-transactions`) |
| 47 | Set an inclusive minimum account transaction count | `marketpulse accounts list --min-transactions 2` |
| 48 | Set an inclusive maximum account transaction count | `marketpulse accounts list --max-transactions 5` |
| 49 | Find account names by prefix | `marketpulse accounts list --name-prefix Fictional` |
| 50 | Find account names by suffix | `marketpulse accounts list --name-suffix Alpha` |

Position average cost is the existing ledger average cost in its recorded
currency; bounds do not convert currencies. Select `--currency` when comparing
costs in one currency. A symbol without metadata has kind `market`, but does not
have an *explicit* asset class. No quote-based class inference is performed.
Text matching ignores case. Currency values and symbol prefixes accept surrounding whitespace.

Summaries count rows, never sum money across currencies. They use every matching
row before `--offset` and `--limit`, return `group` and `count` columns in JSON or
CSV, and reject `--count` and `--page-info`. Empty selections produce an empty
JSON array or CSV header. Account groups use the displayed account name, so
accounts sharing the same name share a count group. `cash --negative` retains
exit status 1 when any matching overdrawn balance exists, including summary
output. `--zero` conflicts with `--positive`, `--negative` and `--nonzero`.

Each account transaction count includes incoming and outgoing transfers once
per participating account. An account that sold its last position still has
transaction history. These six new account options automatically use offline
metadata output, including in human-readable mode. They compose with existing
account summaries and exports. Archived accounts remain hidden unless the
account list's existing `--archived` option is explicitly selected; positions
and cash never expose them. Human financial amounts remain masked in privacy
mode; JSON and CSV remain raw, as in the existing commands.
