# Previews, checks and fixes for accounts, alerts, assets, the watchlist and backups

[User guide](usage.md) · [Issue #153](https://github.com/BrendanH18/Marketpulse/issues/153)

Sixteen standalone command line improvements from the 1,000-improvement batch
in [#153](https://github.com/BrendanH18/Marketpulse/issues/153). They fill gaps
in commands that earlier batches left alone: the writes that manage accounts,
alerts, asset metadata, the watchlist and backups. They add previews
(`--dry-run`) and receipts (`--json`), catch obvious bad input before it is
saved, and fix five commands that reported success when nothing happened. The
examples use fictional accounts and symbols.

| # | Command | Improvement | Example |
| --- | --- | --- | --- |
| 1 | `accounts add` | `--dry-run` checks the name (blank, or already taken by any account, archived ones included) and the currency, and previews the account without saving it. | `marketpulse accounts add "Maple RRSP" -t rrsp --dry-run` prints `✓ Would add Maple RRSP (RRSP, CAD); nothing saved.` |
| 2 | `accounts add` | `--json` prints the new account's metadata, including its `id`, and `"saved": true`. With `--dry-run` the `id` is `null` and `saved` is `false`. | `marketpulse accounts add "Maple FHSA" -t fhsa --json` |
| 3 | `accounts add`, `accounts edit` | `-c/--currency` must be a 3-letter code. Spaces are trimmed and the code is upper-cased, so `" usd "` is saved as `USD` rather than with the spaces. `usdollar` or `US` is a usage error (exit code 2) and nothing is saved. | `marketpulse accounts add "Maple Cash" -c usdollar` fails with `'usdollar' is not a 3-letter currency code like CAD.` |
| 4 | `accounts edit` | `--dry-run` lists each field that would change, old and new, and saves nothing. It runs the same name check as a save and honours `--revision`. Nothing to change prints `No changes to …`. | `marketpulse accounts edit "Maple Cash" --name "Maple Savings" --dry-run` prints `  name: Maple Cash → Maple Savings` |
| 5 | `accounts remove` | `--dry-run` shows the account and how many transactions would be deleted with it, without asking or deleting, and suggests archiving instead. | `marketpulse accounts remove "Maple Cash" --dry-run` prints `✓ Would delete Maple Cash (#1) and its 12 transaction(s); nothing deleted. …` |
| 6 | `accounts room` | Refuses a room amount that is not a finite number (`nan`, `inf`; before, `nan` crashed with a database error) and a year outside 1957 to next year, which catches two-digit years. Negative room, which CRA can report after an over-contribution, is still accepted. | In 2026, `marketpulse accounts room TFSA 26 7000` fails with `Year must be between 1957 and 2027; give all four digits, like 2026.` |
| 7 | `alerts add` | `--dry-run` validates the condition, symbol and threshold and shows the alert without saving it. | `marketpulse alerts add ALPHA.TO ">" 50 --dry-run` prints `✓ Would add alert: ALPHA.TO ≥ 50.00 (not saved).` |
| 8 | `alerts add` | `--json` prints the alert as `alerts show --json` does (with its `id` and `state`), plus `saved`. Works with `--dry-run`. | `marketpulse alerts add ALPHA.TO down 5 --json` |
| 9 | `alerts add` | Spaces around the symbol are trimmed. Before, `" alpha.to "` was saved with its spaces and could never match a quote. | `marketpulse alerts add " alpha.to " above 50` saves `ALPHA.TO` |
| 10 | `alerts edit` | `--dry-run` validates the edit and shows the alert as it would be saved; nothing changes. | `marketpulse alerts edit 3 --threshold 45 --dry-run` prints `✓ Would update alert #3: ALPHA.TO ≥ 45.00 (not saved).` |
| 11 | `alerts rm` | An id with no alert is an error (exit code 1). Before, `alerts rm 99` printed `Removed alert #99.` when there was nothing to remove. | `marketpulse alerts rm 99` fails with `No alert #99; nothing changed.` |
| 12 | `alerts pause`, `resume`, `rearm`, `rm` | Take several ids. All of them are checked first, so either every alert changes or, if one id is missing, none does. Repeated ids count once. | `marketpulse alerts pause 3 4 7` prints `✓ Paused alerts #3, #4, #7.` |
| 13 | `asset classify` | The class is accepted in any case (`ETF`, `Real_Estate`) and spaces around the symbol are trimmed. Before, `" alpha.to "` created a separate asset row with the spaces. A blank symbol is a usage error. | `marketpulse asset classify alpha.to ETF` prints `✓ ALPHA.TO → ETF` |
| 14 | `asset remove` | A symbol with no saved metadata is an error (exit code 1) instead of `Removed metadata for …`. Spaces around the symbol are trimmed. Transactions are still kept. | `marketpulse asset remove BETA.TO` fails with `No configured asset 'BETA.TO'; nothing removed. …` |
| 15 | `watch add`, `watch rm` | `--dry-run` shows which symbols would be added (not already watched) or removed (currently watched), and saves nothing. | With ALPHA.TO already watched, `marketpulse watch add ALPHA.TO GAMMA.TO --dry-run` prints `✓ Would watch GAMMA.TO (not saved).` |
| 16 | `backup now` | Refuses a PATH that is the live database itself, however it is spelled (relative, with `..`). Before, SQLite copied the file onto itself and the command reported a backup that did not exist. | With `MARKETPULSE_DATA=/tmp/mp-scratch` (and `MARKETPULSE_CONFIG=/tmp/mp-scratch/config.toml`), `marketpulse backup now /tmp/mp-scratch/marketpulse.db` fails with `… is the live database; choose another file, or omit PATH to use the backups folder.` |

## What stays the same

Without the new options, every command prints and saves what it did before,
except for the five fixes above that now refuse input which used to be saved
wrongly or reported as done when it wasn't (items 6, 9, 11, 13 and 14), and the
currency check in item 3. The native app always sends 3-letter currency codes
and the id of an alert it lists, so it is unaffected. A preview never writes:
`--dry-run` reads the same saved data a real run would and stops before the
write.

Nothing here makes a network call or reads prices, and ACB, FX, tax, valuation
and contribution-room calculations are unchanged: item 6 only refuses input
before it is saved. `status --json` and the desktop bridge are unchanged.
Archived accounts stay hidden; item 1 counts their names as taken because the
database does too.
