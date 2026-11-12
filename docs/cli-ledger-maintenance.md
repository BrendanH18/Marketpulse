# Ledger maintenance

[User guide](usage.md) · [One hundred improvements](cli-hundred-improvements.md) · [Issue #130](https://github.com/BrendanH18/Marketpulse/issues/130)

These ten additions under [#130](https://github.com/BrendanH18/Marketpulse/issues/130)
make `marketpulse undo` and the `marketpulse txn` commands safer to use on a
real ledger: preview a change before making it, pick the entry to undo, inspect
several entries and what they did, and narrow the consistency check. Every
check a dry run reports is the one the real command runs (the same ledger
replay and the same refusal message), so a dry run that passes is a change that
will be accepted. The examples use fictional accounts.

21. `undo --dry-run` shows the entry `undo` would delete and whether it can be deleted, and changes nothing. A refusal is reported as the real undo would give it, e.g. `Not deleted: transaction #5 on 2025-02-03 would no longer add up (…)`, and exits 1; otherwise it prints `Dry run: would delete transaction #9. Nothing was changed.`
22. `undo -a "Maple Cash"` undoes the most recently recorded entry in that active account (either end of a transfer), and `undo -s xeqt.to` the most recent entry for that symbol; combine them for both. Archived accounts can't be named, and their entries are never picked by a filter; `No matching transaction to undo.` when nothing matches.
23. `undo --json -y` prints `{"dry_run": false, "ok": true, "deleted": true, "error": null, "transaction": {…}}` with the raw, unmasked entry (the same fields as `txn show --json`) instead of the table, so a script knows exactly what it removed. `--json --dry-run` reports without deleting. A refusal is printed in the same shape with `"ok": false` and the message in `error`, and exits 1. `--json` needs `--yes` or `--dry-run`, since it can't ask for confirmation.
24. `txn show 3 9` inspects several entries, one table each, in the order given (a repeated id is shown once). `--json` prints one object for one id, as before, and a list for several. If any id is missing or in an archived account, nothing is printed and it fails with `No active transaction #99.`
25. `txn show --with-effect 7` adds an `Effect of #7` table: each holding (units and ACB) and tracked cash balance of the entry's account(s) that the entry changed, before and after it, from replaying the ledger up to just before it and up to and including it. `--json --with-effect` adds an `effect` list, e.g. `[{"kind": "holding", "account": "Maple Cash", "symbol": "XEQT.TO", "currency": "CAD", "before": {"quantity": 50.0, "book": 1505.0}, "after": {"quantity": 30.0, "book": 903.0}, …}, {"kind": "cash", …, "before": {"balance": 3520.0}, "after": {"balance": 4160.0}}]`. An entry the ledger couldn't apply shows `#8 changes no holding or tracked cash balance.`
26. `txn check --code sell_exceeds_held` reports only issues with that code, ignoring case; repeat for several. The codes are the `code` values in `txn check --json` (`sell_exceeds_held`, `split_nothing_held`, `transfer_nothing_held`, `transfer_exceeds_held`, `hidden_account_issue`). With a filter, a clean result reads `No matching ledger issues.` and exits 0.
27. `txn check -a "Birch TFSA"` reports only issues on entries in that active account (either end of a transfer). It combines with `--code`. The whole ledger is still replayed; the filters only choose which issues to report, and so whether the command exits 1.
28. `txn edit --dry-run --quantity 25 -- 4` prints a `Transaction #4 (dry run)` table of only the fields that would change (`Field`, `Before`, `After`; account by name; amounts masked in privacy mode), then runs every check the save would: field validation, `--revision`, and the replay that refuses an edit leaving a later sale short. A new symbol without `--currency` has its currency worked out as the save would. It ends with `Dry run: would update #4. Nothing was changed.`, or the refusal and exit 1; `No changes.` when the options change nothing.
29. `txn delete -- 3 7` deletes several entries with a single confirmation (`Delete these 2 transactions?`). They are checked together first, so a purchase can go together with the sale that depends on it, and either all are deleted or none is (`… Nothing was deleted.`). They are then all deleted in one database transaction, newest first, so the result always matches `--dry-run`. `--revision` needs a single id.
30. `txn delete --dry-run -- 3` shows the entries and whether deleting them would be accepted, without asking or deleting: `Dry run: would delete #3, #7. Nothing was changed.`, or the refusal and exit 1. It honours `--revision` for a single id.

## Rules

- `--dry-run` never asks for confirmation and never writes. It exits 1 when the real command would be refused.
- `undo --json` needs `--yes` or `--dry-run`. A blank `undo --symbol` or `txn check --code` is a usage error.
- `undo -a`, `txn check -a` take an active account (name, id or unique type); an archived or unknown one fails with `No active account '…'.`

## What stays the same

`marketpulse undo`, `undo -y`, `txn show ID`, `txn show --json ID`, `txn check`,
`txn check --json`, `txn edit` and `txn delete ID` print exactly what they
printed before and ask the same questions. Plain `undo` still picks the most
recently recorded entry in the whole ledger. Raw JSON is unmasked like other
`--json` output; tables honour `privacy`.
