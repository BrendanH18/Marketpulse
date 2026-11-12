# Capital gains report inspection

[User guide](usage.md) · [Offline tax, allocation and holdings inspection](cli-portfolio-inspection.md)

These ten additions under [#128](https://github.com/BrendanH18/Marketpulse/issues/128)
select, sort and export rows of the `marketpulse tax` capital gains report. The
report is always computed in full first (pooled ACB across every taxable
account, trade-date FX, superficial losses), and only then are rows chosen, so
a filter never changes a disposition's ACB, proceeds or gain. The examples use
fictional accounts.

1. `tax --json` prints every disposition as raw, unmasked JSON, oldest first, with its tax `year` and the same fields as the app's Tax workspace: `date`, `account_id`, `account`, `account_type`, `archived`, `symbol`, `quantity`, `currency`, `fx`, `kind`, `complete`, `proceeds`, `acb`, `gain`, `denied`, `allowed_gain`, `denied_reason`, `superficial`, `acquired_in_window`, `held_after_window`, `window_open`, `note` and `transaction_id`. A row missing an FX rate has `null` amounts. `--year 2025` keeps one year's rows.
2. `tax --csv -` prints the accountant CSV (the same columns as `tax --csv gains.csv`) to stdout with `\n` line endings; ledger issues go to stderr. Every filter below also applies to `--csv -` and to `--csv PATH`, e.g. `tax -a "Birch Margin" --csv birch.csv`.
3. `tax --symbol vfv` keeps dispositions whose symbol contains the text, ignoring case; repeat for any of several (`--symbol aapl --symbol sap`).
4. `tax -a "Birch Margin"` keeps dispositions in one active account (name, id or type). Archived accounts can't be selected and fail like unknown ones.
5. `tax --kind roc` keeps one kind of disposition: `sale`, `roc` (return of capital above ACB) or `deemed` (transfer in kind to a registered account); repeat for several.
6. `tax --gains-only`, `--losses-only` and `--denied` keep rows with a capital gain, a capital loss (denied or not), or a denied loss (superficial or moved into a registered plan). `--incomplete` keeps the rows missing an FX rate, which every total leaves out.
7. `tax --sort gain --descending` orders by `date` (the default), `symbol`, `account`, `proceeds`, `acb`, `gain` (the reported gain, after any denial) or `denied`. Rows missing an FX rate stay last when sorting by an amount; archived accounts sort after named ones.
8. `tax --count` prints only the number of matching dispositions; `--limit 2 --offset 3` pages the matching rows in the table, JSON and CSV, and `--json --page-info` wraps them as `{"rows": […], "total": 8, "offset": 3, "limit": 2}`.
9. `tax --summary` prints per-year totals (rows, proceeds, ACB, denied, net gain, taxable, missing FX) of the matching dispositions; `--summary --json` prints `[{"year": 2025, "dispositions": 4, "proceeds": 2160.0, "acb": 1940.0, "denied": 0.0, "net_gain": 220.0, "taxable": 110.0, "inclusion_rate": 0.5, "missing_fx": 1, "superficial": 0}, …]`. Totals are summed exactly as the report's own yearly totals, so without filters they match `marketpulse tax`; with filters they cover only the selected rows (an inspection aid, not a figure to file).
10. `tax --issues` lists only the ledger issues that can leave sales out of the report (`--json` for raw rows with `code` and `args`, `--year` to narrow them, `--exit-code` to exit 1 when any exist). `tax --room` prints only the contribution room table, or `--room --json` for raw room rows with the active `accounts` of each type; it fetches no FX history.

## Rules

- `--json` and `--csv` are exclusive; `--count` can't be combined with `--json`, `--csv` or paging; `--page-info` requires `--json`.
- `--summary`, `--issues` and `--room` are exclusive, and can't be combined with `--count`, `--csv`, `--sort`, `--descending` or paging. `--issues` and `--room` take no disposition filters, and `--room` takes no `--year`. `--exit-code` requires `--issues`.
- `--gains-only` and `--losses-only` are exclusive, and `--incomplete` can't be combined with them or `--denied` (those rows have no known gain).
- A blank `--symbol` is a usage error. When nothing matches, the table says so and JSON prints `[]`; the exit status stays 0.

## What stays the same

`marketpulse tax` and `marketpulse tax --year 2024` print exactly the report
they printed before, and `--csv PATH` without filters writes the same
accountant file with the same messages. Raw JSON and CSV are unmasked like other
`--json`/`--csv` outputs; the tables honour `privacy`. JSON and the tables name
an archived account's dispositions only as archived, as the app does, while the
accountant CSV names every account as it always has. Archived accounts'
dispositions still count in every total and in pooled ACB. Tax figures are
estimates; check them against your T5008, T3 and T5 slips.
