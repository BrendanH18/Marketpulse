# Recording previews, receipts and shortcuts

[User guide](usage.md) · [One hundred improvements](cli-hundred-improvements.md) · [Issue #130](https://github.com/BrendanH18/Marketpulse/issues/130)

These ten additions under [#130](https://github.com/BrendanH18/Marketpulse/issues/130)
let you preview an entry before it is saved, get a machine-readable receipt
afterwards, and enter common trades in fewer steps. They apply to the recording
commands `buy`, `sell`, `drip`, `dividend`, `interest`, `deposit`, `withdraw`,
`fee`, `split`, `roc` and `transfer`. Every option is opt-in: without one, a
command prints and saves exactly what it did before. The examples use fictional
accounts.

1. `--dry-run` runs the real save in a transaction that is then rolled back, so a preview checks the same things a save would: selling more than you hold, a future date, moving shares that weren't there yet, or a DRIP or return of capital in a different currency from the holding. It prints the line the command would print, with the position after it, and saves nothing. A refusal exits with code 1 and the same message as the real save. With no accounts yet, a dry run refuses rather than creating the first one. Looking up a missing price or currency works as it does for a save, so the quote is cached.
   `marketpulse buy XEQT.TO 10 40 -a "Maple Cash" --dry-run` prints `○ Dry run, not saved: Bought 10 XEQT.TO @ 40.00 CAD in Maple Cash · now 20 @ avg 40.00`.
2. `--json` prints one JSON receipt of the saved entry instead of the confirmation line: `recorded`, `dry_run`, `duplicate`, `id`, `type`, `date`, `account_id`, `account`, `symbol`, `quantity`, `price`, `amount`, `fees`, `currency`, `ratio`, `target_account_id`, `target_account`, `note`, the confirmation `message`, any `notes` the command adds (such as a return of capital past the cost base) and `warnings` (see [items 11–17](cli-recording-checks.md)). Other messages, such as the live price a transfer used, go to stderr, so stdout is always one JSON object. With `--dry-run` the receipt has `"id": null` and `"recorded": false`.
3. The receipt's `after` block shows the ledger after the entry: `position` (`quantity`, `book`, `avg_cost`, `currency`, or `null` once the position is closed), `realized_gain` for a sale or a return of capital past the cost base, `cash` by currency for an account that tracks cash (`null` otherwise) and, for a transfer, the destination's `target_position`. The figures are read from the same ledger replay as `positions` and `cash`.
   `marketpulse sell XEQT.TO 4 45 -a "Maple Cash" --json` includes `"after": {"position": {"quantity": 6.0, "book": 240.0, "avg_cost": 40.0, "currency": "CAD"}, "realized_gain": 20.0, "cash": {"CAD": 780.0}}`.
4. `--quiet` prints only the new entry's id, for scripts that edit or tag it next: `id=$(marketpulse deposit 500 -a "Maple Cash" --quiet)`. With `--dry-run` it prints nothing and the exit status says whether the entry is valid. `--quiet` and `--json` are exclusive.
5. `--balance` adds the account's cash balance after the entry, one line per currency, for accounts that track cash; other accounts say they don't track cash. A transfer shows both accounts. Balances are masked in privacy mode.
   `marketpulse withdraw 250 -a "Maple Cash" --balance` adds `  cash in Maple Cash: 350.00 CAD`.
6. `--confirm` shows the dry-run preview and any warnings, then asks `Record it? [y/N]`. Anything but yes exits with code 1 and `Not recorded.`, saving nothing. It can't be combined with `--dry-run`, `--json` or `--quiet`.
7. `--once` skips the entry when an identical one (same account, type, date, symbol, numbers, currency, destination and note) is already in the ledger, printing `✓ Already recorded (#42); nothing saved.` and exiting 0. With `--quiet` it prints the existing id, and with `--json` the existing entry's receipt with `"duplicate": true`. Re-running a script of monthly entries with `--once` doesn't record them twice.
8. `--total GROSS` on `buy`, `sell` and `drip` sets PRICE to GROSS ÷ QUANTITY, for broker confirmations that give units and a gross value. GROSS is the trade value before commission; fees still go in `--fees`. It replaces PRICE, so give one or the other.
   `marketpulse buy XEQT.TO 8 --total 1000 -c CAD -a "Maple Cash"` records 8 units at 125.00.
9. `sell SYMBOL all [PRICE]` sells every unit held in the account at the end of the entry's date (entries dated later don't count). It fails with `Maple Cash holds no XEQT.TO on 2025-01-09.` when there is nothing to sell. Combine it with `--total` to give the gross proceeds instead of a price.
10. `transfer SYMBOL all --from A --to B` moves the whole position held in the source account at the end of the date, e.g. `marketpulse transfer XEQT.TO all --from "Maple Cash" --to "Maple TFSA" -p 41` prints `✓ Transferred 10 XEQT.TO Maple Cash → Maple TFSA`.

## Rules

- The new options can't be combined with `--request-id`, the Mac app's retry identity; its fingerprint of a command is unchanged.
- `--json` and `--quiet` are exclusive; `--confirm` excludes `--dry-run`, `--json` and `--quiet`; `--total` must be a positive amount and can't be given with PRICE.
- Usage errors exit with code 2 and refused entries with code 1, as before.

## What stays the same

A plain recording command prints the same confirmation and saves the same row as
before, and a mistyped number or a missing PRICE gives the same usage error. A
dry run uses the real checks and the real ledger replay, so a preview equals the
save. ACB, FX and tax calculations are unchanged, and no option adds a network
call: a missing price or currency is looked up exactly as before. Archived
accounts still don't appear in portfolio views.
