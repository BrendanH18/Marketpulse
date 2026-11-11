# Offline realized gains and payouts

[User guide](usage.md) · [Ledger reports and diagnostics](cli-ledger-reports.md)

`marketpulse realized` and `marketpulse payouts` list what the ledger already
records: sales with their average-cost result, and dividend, DRIP and interest
income. They are items 11–20 of the 30-improvement batch (#111).

Both commands work entirely offline. They replay the local ledger and never look
up quotes, FX rates or price history. Every amount stays in the currency the
trade or payout was recorded in, and totals are only added up within one
currency: CAD and USD amounts are never converted or mixed.

> **This is not the tax report.** `marketpulse tax` converts each trade to CAD at
> its trade-date FX rate and applies the superficial-loss rules, which can deny or
> defer a loss. `realized` shows the raw average-cost result from the ledger in
> each native currency, with neither adjustment. Use `marketpulse tax` for
> anything you file.

Archived accounts never appear: their sales and payouts are left out of the rows
and of every total, and `-a` refuses an archived account.

## Realized gains

11. **Realized-gains log:** `marketpulse realized` prints every sale, oldest
    first: date, account, symbol, quantity, proceeds (net of fees), ACB of the
    shares sold, gain and currency. A second table totals proceeds, ACB and gain
    per currency. A return of capital beyond the ACB, which the ledger treats as a
    deemed gain, appears as a row with quantity 0.
12. **Date filters:** `marketpulse realized --year 2024`, `--since 2024-01-01`
    and `--until 2024-06-30` combine; a row must match all of them. Dates accept
    the same forms as `activity` (`2024-01-31`, `yesterday`, `-30d`); an invalid
    date, or `--since` after `--until`, is a usage error.
13. **Account and symbol filters:** `marketpulse realized -a "Maple Fictional"`
    takes an account name, id or type as everywhere else.
    `marketpulse realized --symbol mapl` matches the symbol **exactly**, ignoring
    case: `--symbol MAP` does not match `MAPL`.
14. **JSON:** `marketpulse realized --json` prints
    `{"rows": [...], "totals": {...}}`. Each row has `date`, `account_id`,
    `account`, `symbol`, `quantity`, `proceeds`, `cost`, `gain`, `currency` and
    `txn_id` (the sale's transaction id, as shown by `activity`). `totals` is keyed
    by currency, for example
    `{"CAD": {"count": 2, "proceeds": 70.0, "cost": 60.0, "gain": 10.0}}`.
15. **CSV:** `marketpulse realized --csv > realized.csv` writes the same row
    fields as CSV to standard output, with a header even when nothing matches.
    Totals are not included; add them up per `currency` column.
16. **Gains or losses only:** `marketpulse realized --gains-only` keeps sales
    whose gain rounds to more than zero cents; `--losses-only` keeps those that
    round to less than zero. Break-even sales match neither. The two flags cannot
    be combined.

## Payouts

17. **Payout log:** `marketpulse payouts` lists recorded dividends, DRIPs and
    interest, oldest first: date, account, symbol (`—` for account-level interest),
    kind, amount and currency, with totals per currency. A DRIP counts its
    reinvested value (quantity × price). The command supports the same `--year`,
    `--since`, `--until`, `-a/--account` and exact `--symbol` filters as
    `realized`; interest without a symbol never matches `--symbol`.
18. **Kind filter:** `marketpulse payouts --kind dividend --kind drip` keeps the
    chosen kinds: `dividend`, `drip` or `interest`, case-insensitive. Repeat it for
    several.
19. **Grouped totals:** `marketpulse payouts --by month` (or `year`, `symbol`,
    `account`) replaces the row list with one total per group and currency, so a
    month with CAD and USD dividends has two lines. Groups sort by name, then
    currency. `--by account` groups by account id, so identically named accounts
    stay separate, and shows the account name.
20. **JSON and CSV:** `marketpulse payouts --json` prints
    `{"rows": [...], "totals": {"CAD": {"count": 2, "amount": 15.5}}}` with rows of
    `date`, `account_id`, `account`, `symbol`, `kind`, `amount` and `currency`.
    With `--by`, JSON is `{"by": "month", "groups": [...], "totals": {...}}`, each
    group being `{"group", "currency", "count", "amount"}` plus `account` for
    `--by account`. `--csv` prints the rows, or with `--by` the groups, to standard
    output.

## Examples

```bash
marketpulse realized --year 2024
marketpulse realized -a "Maple Fictional" --symbol MAPL --losses-only
marketpulse realized --since 2024-01-01 --json
marketpulse payouts --kind dividend --year 2024
marketpulse payouts --by month --since 2024-01-01 --csv > payouts-by-month.csv
marketpulse payouts --by account --json
```

## Privacy and exports

With privacy mode on (`marketpulse config set privacy true`), the tables mask
every amount and quantity, and gains are not coloured, so the sign stays hidden
too. `--json` and `--csv` output is always raw and unmasked, like the existing
`activity` and CSV exports: it is meant for scripts and files you choose to
write. Choose one of `--json` or `--csv`; asking for both is a usage error.
