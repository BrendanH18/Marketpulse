# Status and dashboard overview

[User guide](usage.md) · [One hundred improvements](cli-hundred-improvements.md) · [Issue #130](https://github.com/BrendanH18/Marketpulse/issues/130)

These ten additions under [#130](https://github.com/BrendanH18/Marketpulse/issues/130)
let scripts and status bars read single figures from `marketpulse status`, and
let you trim or export the `marketpulse summary` dashboard. Every option reuses
the valuation the plain commands already compute: the same quotes, offline
quote cache, FX rates and snapshot. The examples use fictional accounts.

61. `status --field net-worth` prints one raw, unmasked value for scripts: `net-worth`, `day-change`, `day-change-pct`, `unrealized`, `unrealized-pct`, `invested`, `cash`, `realized`, `income-ytd`, `base`, `market-state` (empty when no exchange-traded holding reports one) or `stale` (`true`/`false`). Money is rounded to cents and percentages to four places, as in `status --json`; `status --field net-worth` prints `13700.0`.
62. `status --format '{arrow} {day_change_pct} · {net_worth_compact}'` prints one line from a template, e.g. `▲ +0.62% · $13.7K`. Placeholders: `{net_worth}`, `{net_worth_compact}`, `{day_change}`, `{day_change_pct}`, `{arrow}`, `{unrealized}`, `{unrealized_pct}`, `{invested}`, `{cash}`, `{realized}`, `{income_ytd}`, `{base}`, `{market_state}` and `{stale}` (`◌` when prices come from the offline cache, otherwise empty). Amounts are masked in privacy mode; an unknown placeholder or unbalanced brace is a usage error.
63. `status --exit-code` exits 1 when prices are stale (served from the offline cache) or the totals leave something out (no price or FX rate, or an archived account that still holds value). The output is unchanged, so it combines with every mode, including `--json` and `--waybar`: `marketpulse status --short --exit-code || echo "check prices"`.
64. `status --accounts` follows the plain summary with a table of each active account's value, day change, day change % and weight. Archived accounts are not listed.
65. `status -a "Fictional Income"` shows one active account (name, id or type) with the plain summary, `--short`, `--field`, `--format` or `--accounts`. A one-account view is never recorded as a net-worth snapshot. Archived accounts fail like unknown ones, and `-a` can't be combined with the stable `--json` and `--waybar` contracts.
66. `summary --json` prints the dashboard's figures as raw, unmasked JSON: `base_currency`, `stale`, `market_state`, `markets` (each strip symbol's `label`, `price`, `change`, `change_pct`, `currency`, `stale`; `null` when no quote), the totals (`net_worth`, `day_change`, `day_change_pct`, `invested`, `unrealized`, `unrealized_pct`, `realized`, `income_ytd`, `cash`), `returns` (`since`, `xirr_pct`, `twr_pct`), `history` (the chart's snapshots), `allocation` (`by` and `rows` of `key`, `label`, `value`, `weight`), `movers`, `excluded` and `archived_with_value`.
67. `summary --section totals --section movers` shows only the chosen sections, always in dashboard order: `markets`, `totals`, `chart`, `allocation`, `movers`. The market strip's quotes are fetched only when `markets` is shown. With `--json`, only the chosen sections' keys appear (plus `base_currency`, `stale`, `excluded` and `archived_with_value`).
68. `summary --top 3` shows up to three of today's movers (six by default), in the table and in JSON.
69. `summary --months 6` sets the net-worth history window (1–120 months, 12 by default). The chart title follows it: `Net worth · 6m`, `Net worth · 2y`.
70. `summary --allocation-by account` (or `currency`) groups the allocation by account or currency instead of asset class; the title becomes `Allocation by account`.

```bash
marketpulse status --field day-change-pct
marketpulse status --format '{arrow} {day_change} ({day_change_pct}){stale}' --exit-code
marketpulse status -a TFSA --accounts
marketpulse summary --section totals --section allocation --allocation-by currency
marketpulse summary --json --section movers --top 3
```

## Rules

- `status` takes one of `--json`, `--waybar`, `--short`, `--field` and `--format`. `--accounts` only adds to the plain status.
- `--top` must be at least 1; `--months` is 1–120. Unknown `--field`, `--section` and `--allocation-by` values are usage errors.

## What stays the same

Plain `status`, `status --short`, `status --json`, `status --waybar` and plain
`summary` print exactly what they printed before; `--json` and `--waybar` remain
stable contracts. Human output honours `privacy`; `--field` and `summary --json`
are raw and unmasked, like `positions --json`. Archived accounts stay out of the
totals, the allocation and the account table. Valuation, FX and return math are
unchanged, and no option adds a network call.
