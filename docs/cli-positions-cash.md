# Offline positions and cash

[User guide](usage.md) · [Ledger reports and diagnostics](cli-ledger-reports.md)

These commands read open positions and cash balances straight from the local
ledger replay. They never look up quotes, convert currencies or record a
snapshot, so they work offline and make no network calls. They are items 1–10
of the 30-improvement batch (#111).

They are **cost-base views, not valuations**: book cost is the adjusted cost
base the ledger has accumulated, in each position's own currency. For market
values, gains and weights, use `marketpulse holdings` or the TUI.

1. **Open positions:** `marketpulse positions` lists every open position
   (quantity above zero) in active accounts: account, symbol, quantity, book
   cost, average cost (book ÷ quantity), currency and the date the position was
   opened. A footer notes that prices aren't fetched. With nothing held it
   prints `No open positions yet.`; with filters that match nothing,
   `No positions match these filters.`
2. **JSON:** `marketpulse positions --json` prints a list of objects with
   `account_id`, `account`, `symbol`, `quantity`, `book`, `average_cost`,
   `currency` and `first_date`.
3. **CSV:** `marketpulse positions --csv > positions.csv` writes the same fields,
   with a header row, to stdout.
4. **One account:** `marketpulse positions -a TFSA` (name, id or unique account
   type, as elsewhere in the CLI).
5. **Symbol search:** `marketpulse positions --symbol .to` matches symbols that
   contain the text, ignoring case.
6. **Currency:** `marketpulse positions --currency usd` keeps positions held in
   that currency, ignoring case.
7. **Sorting:** `marketpulse positions --sort book --descending`. Choices are
   `account` (default: account name, then symbol), `symbol`, `quantity`, `book`
   and `first-date`; ties fall back to account then symbol. `--descending`
   reverses the whole order, including the default.
8. **Counting:** `marketpulse positions --currency usd --count` prints only the
   number of matching positions. As with `activity --count`, it can't be
   combined with `--json` or `--csv` (usage error, exit 2).
9. **Cash balances:** `marketpulse cash` lists the ledger cash balance per
   account and currency for accounts that track cash (`accounts add
   --track-cash`). It supports `-a/--account`, `--currency`, `--json` and
   `--csv`; JSON and CSV rows have `account_id`, `account`, `currency` and
   `balance`. Zero balances are listed. Asking for an account that doesn't track
   cash says so (JSON and CSV print no rows).
10. **Overdrawn balances:** `marketpulse cash --negative` shows only balances
    below zero and exits with status 1 when any are listed, so a script can
    alert on it:

    ```bash
    marketpulse cash --negative --json > overdrawn.json || echo "Fictional TFSA needs a deposit"
    ```

    Float residue smaller than one billionth (for example deposits of 0.10 and
    0.20 followed by a 0.30 withdrawal) counts as zero, never as overdrawn.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success; with `cash --negative`, no overdrawn balance matched. |
| 1 | `cash --negative` listed at least one overdrawn balance (output is still printed), or an error such as an unknown account (`Error: …` on stderr). |
| 2 | Usage error: conflicting output flags or an invalid choice. |

## Privacy and hidden accounts

- With privacy mode on (`marketpulse config set privacy true`), the human
  tables mask quantity, book cost, average cost and cash balances, and don't
  colour overdrawn balances. `--json` and `--csv` stay raw and unmasked, as
  with existing exports such as `activity --json`.
- Archived accounts are left out of both reports. An `-a` reference to an
  archived account fails with the same `No active account '…'` error as an
  unknown one, so it reveals nothing.
- Cash-tracking accounts that have no cash entries in the ledger have no rows.
