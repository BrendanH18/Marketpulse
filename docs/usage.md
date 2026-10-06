# User guide

[Back to the README](../README.md) · [Configuration](configuration.md) · [Data and backups](data.md)

## Accounts and transactions

Create accounts before recording transactions. Names, IDs, and account types
can be used with `--account`; a type must resolve to a single account.
If you have one account, you can omit the option. With several accounts, set a
default or select an account explicitly:

```bash
marketpulse accounts add "My TFSA" --type TFSA --track-cash
marketpulse config set default_account "My TFSA"
marketpulse deposit 7000 --account "My TFSA"
marketpulse buy XEQT.TO 20 30.00 --account "My TFSA" --date 2024-01-02
marketpulse sell XEQT.TO 5 35.00 --account "My TFSA" --date 2024-06-03
marketpulse dividend XEQT.TO 22.00 --account "My TFSA"
marketpulse activity
```

Prices and amounts are in the transaction's currency. Use Yahoo symbols such
as `XEQT.TO` for a Toronto listing and `BTC-USD` for Bitcoin. Omit a buy or
sell price to use the current quote; for historical records, provide the actual
execution price and date. `--fees` records commissions. `marketpulse undo`
deletes the latest transaction after confirmation.

With cash tracking, purchases debit cash and sales, deposits, and income credit
it. Without cash tracking, valuation includes holdings without a cash balance.
Cash tracking can be changed with `accounts edit --track-cash`.

## Contribution room and tax estimates

Record a known room balance and the year it applies to:

```bash
marketpulse accounts room TFSA 2026 21500
marketpulse tax --year 2025
```

The balance above is fictional; enter your own verified amount. MarketPulse
derives later room from recorded activity and its implemented annual limits.
It cannot discover unrecorded contributions or verify your eligibility.

The tax report implements:

- A pooled adjusted cost base (ACB) across taxable accounts holding an identical symbol.
- Purchase costs and sale proceeds converted using each transaction date's FX rate.
- Proportional superficial-loss estimates using recorded purchases and holdings
  around the sale date, including registered accounts.
- Deemed dispositions for supported in-kind transfers across taxable and
  registered accounts. Registered replacement purchases can permanently deny a loss.

Account holdings still show their own cost basis, which can differ from the
pooled basis used by the tax report. Rows missing historical FX or required
transfer prices are flagged and excluded from report totals.

For an in-kind transfer, provide the market price explicitly:

```bash
marketpulse transfer XEQT.TO 10 --from "Taxable" --to "My TFSA" --price 40.00 --date 2024-07-02
```

This requires an existing source account and enough shares. An omitted transfer
price can use the live quote for today's date; it cannot supply a historical
value for a backdated transfer. The report cannot see transactions by a spouse
or controlled corporation. These outputs describe recorded activity and are
not a complete tax filing calculation.

## Fixed income and manual assets

```bash
marketpulse asset fixed EQB-GIC-27 10000 --rate 4.1 --start 2025-03-01 --maturity 2027-03-01 --account "My TFSA"
marketpulse accounts add Property --type OTHER
marketpulse asset manual COTTAGE 450000 --class real_estate --account Property
marketpulse asset value COTTAGE 480000
marketpulse asset classify XEQT.TO equity
```

Fixed-income assets are valued using their configured accrual model rather
than a live bond quote. Manual assets use their latest recorded valuation.
Run `marketpulse asset fixed --help` for compounding and currency options.

## Import and export

```bash
marketpulse import activities.csv --account "My TFSA" --dry-run
marketpulse import activities.csv --account "My TFSA"
marketpulse export ledger.csv
```

The importer recognizes common broker header and transaction-type aliases.
`date` and `type` are required; other fields depend on the transaction type.
See [the sample CSV](../examples/transactions.csv) for the canonical columns.
Unsupported or invalid rows are skipped with reasons, and matching transactions
are counted as duplicates. Always review the summary and skipped rows.

An account column takes precedence over the fallback account. Named accounts
can be created during a real import unless `--no-create-accounts` is supplied.
Create accounts before a dry run: a preview does not create unknown accounts
and will skip their rows. Create them explicitly to control account type,
currency, and cash tracking instead of relying on the importer's guesses.

CSV export contains the transaction ledger. It is **not a complete database
backup**: it does not include all account settings, asset definitions, alerts,
watchlist entries, or snapshots. Use `marketpulse backup` for that.

## Performance and history

```bash
marketpulse perf
marketpulse income
marketpulse allocation --target etf=80 --target fixed_income=15 --target cash=5
marketpulse chart NVDA --period 1y --vs QQQ
marketpulse compare XEQT.TO VEQT.TO VFV.TO --period 5y
marketpulse backfill
```

Portfolio views record net-worth snapshots. `backfill` reconstructs daily history
from the ledger and historical prices; it makes network requests and may take
time for long histories. Missing records or prices affect performance estimates.

## Keyboard reference

| Context | Keys |
| --- | --- |
| Everywhere | `1`–`8` workspaces; `ctrl+p` command palette; `?` help; `q` quit |
| Display | `r` refresh; `p` privacy; `t` theme |
| Transactions | `b` buy; `s` sell; `D` dividend; `n` new; `e` edit; `x` delete; `u` undo |
| Symbols | `/` search; `w` add to watchlist; `A` add alert |
| Dashboard | `,` / `.` history range; `g` allocation grouping |
| Holdings | `f` account filter |
| Watchlist | `a` add; `x` remove; `J` / `K` reorder |
| Chart | `[` / `]` period; `←` / `→` crosshair; `c` compare; `C` clear comparisons |
| Activity | `i` import; `E` export |
| Accounts | `R` contribution room; `G` new asset; `V` manual valuation |
| Alerts | `space` pause or resume |
| Forms | `ctrl+s` save; `escape` cancel |

Actions depend on the active workspace and focused widget. The in-app help
shows the available actions.

## Integrations

### macOS menu bar

`marketpulse menubar install` builds and launches
`~/Applications/MarketPulse Bar.app`. It needs macOS 14+, a Swift toolchain, and
an **editable source checkout**: a git-tag or wheel install does not bundle the
Swift project. See [CONTRIBUTING.md](../CONTRIBUTING.md) for the editable setup.
`marketpulse menubar uninstall` removes the application.

The installer records the CLI's absolute path and, when set, `MARKETPULSE_DATA`.
Reinstall after moving the checkout or changing the installed CLI environment.
The companion runs CLI status commands to read the same portfolio.

### Waybar

Add a custom module to your Waybar configuration, then include
`custom/marketpulse` in a module list:

```jsonc
"custom/marketpulse": {
  "exec": "marketpulse status --waybar",
  "return-type": "json",
  "interval": 60,
  "on-click": "xdg-terminal-exec marketpulse"
}
```

### Scripts and other status bars

`marketpulse status --short` prints a compact line for tmux, SketchyBar, or a
shell prompt. `marketpulse status --json` returns the structured payload used
by the menu bar. JSON contains portfolio amounts even when privacy mode is on.

### Alerts

```bash
marketpulse alerts add NVDA above 200
marketpulse alerts check
```

The TUI and menu bar evaluate alerts during refresh. For scheduled CLI checks,
run `marketpulse alerts check --quiet` from your own cron or launchd setup.
Notifications require the platform's notification tools; no scheduler is installed
automatically.
