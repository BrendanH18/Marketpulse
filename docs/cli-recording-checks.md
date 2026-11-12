# Recording checks and shortcuts

[User guide](usage.md) · [One hundred improvements](cli-hundred-improvements.md) · [Issue #130](https://github.com/BrendanH18/Marketpulse/issues/130)

These ten additions under [#130](https://github.com/BrendanH18/Marketpulse/issues/130)
catch likely typos when you record an entry and add three input shortcuts. The
checks never block a save on their own: a warning is shown with `--dry-run` or
`--check`, listed in the `--json` receipt, and refuses the entry only with
`--strict`. Entries that are invalid (selling more than you hold, a future date)
are still refused as before. Without the new options, every command prints and
saves exactly what it did before. The examples use fictional accounts.

11. `--check` prints any warnings after the confirmation line of a real save. `--dry-run` always prints them, and `--quiet --check` sends them to stderr.
    `marketpulse buy XEQT.TO 1 40 -a "Maple Cash" -d 2025-01-12 --check` adds `! 2025-01-12 is a Sunday, when markets are closed`.
12. `--strict` refuses an entry when any warning applies, with exit code 1 and nothing saved: `Error: Not recorded (--strict): 2025-01-11 is a Saturday, when markets are closed.` Use `--dry-run --strict` to validate a line of a script without saving it.
13. Archived account (`archived_account`): recording into an account that is archived, which you can still name with `-a`, warns `Old Cedar is archived, so this entry stays out of sight`. For a transfer, either account counts. Archived accounts stay hidden in portfolio views, and their entries still count for tax.
14. Same-day duplicate (`possible_duplicate`): an entry of the same type, account, date, symbol and destination with the same quantity, amount and split ratio already exists, whatever its price or note: `a matching BUY on 2025-01-06 is already recorded (#2)`. To skip exact repeats instead, use `--once` ([item 7](cli-recording-receipts.md)).
15. Weekend trade date (`weekend`): a `buy` or `sell` dated on a Saturday or Sunday warns `2025-01-11 is a Saturday, when markets are closed`, which usually means a settlement date or a typo. Cash events can be dated any day.
16. Negative cash (`negative_cash`): in an account that tracks cash, an entry that takes cash out (a buy, withdrawal or fee) and leaves the balance in its currency below zero warns `cash in Maple Cash is now -100.00 CAD`. The balance is the ledger's own cash balance after the entry.
17. Price far from the last quote (`price_far_from_quote`): a `buy`, `sell` or `drip` dated in the last seven days whose price is more than 50% away from the last quote saved in the offline quote cache, in the same currency, warns `price 400.00 CAD is far from the last known quote 40.00 CAD`. It reads only the cache and makes no network call; with no cached quote there is no check.
18. `withdraw all` withdraws the account's whole cash balance at the end of the date, in the account currency or `-c`'s, e.g. `marketpulse withdraw all -a "Maple Cash" --balance` prints `✓ Withdrawal 600.00 CAD → Maple Cash on 2025-01-08` and `  cash in Maple Cash: 0.00 CAD`. It works only for accounts that track cash and fails when there is no balance to withdraw.
19. `--per-unit` on `dividend` and `roc` treats AMOUNT as a per-unit rate, as distribution notices and box 42 of the T3 slip give it, and records the rate times the units held in the account at the end of the date, rounded to the cent. The confirmation shows the working:
    `marketpulse dividend VFV.TO 0.125 --per-unit -a "Birch TFSA" -d 2025-03-31` prints `✓ Dividend 2.50 CAD from VFV.TO → Birch TFSA on 2025-03-31 (0.1250 × 20 units)`. It fails when no units are held on the date.
20. `split` takes RATIO as new:old shares as well as a number: `3:1`, `2-for-1`, `1 for 4`, `3/2` or `1:10` (a 1-for-10 consolidation, saved as 0.1). `marketpulse split XEQT.TO 3:1 -a "Maple Cash"` prints `✓ Split XEQT.TO ×3 in Maple Cash`. Zero shares on either side is a usage error.

## Warning codes

`--json` lists each warning as `{"code": …, "message": …}` with one of the codes
above: `archived_account`, `possible_duplicate`, `weekend`, `negative_cash` and
`price_far_from_quote`. Return-of-capital notes, such as a cost base reaching zero,
are in `notes`, and they print after the confirmation line as before.

## What stays the same

A plain command never prints these warnings and saves the same row as before.
The checks only read the ledger and the quote cache; ACB, FX, tax and cash
calculations are unchanged. `withdraw all`, `--per-unit` and the ratio forms only
fill in the number you would otherwise type, from the same ledger replay as
`positions` and `cash`.
