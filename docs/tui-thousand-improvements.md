# Terminal app: fifteen more improvements

[User guide](usage.md) · [Terminal app navigation](tui-navigation.md) · [Terminal app productivity](tui-productivity.md) · [Issue #153](https://github.com/BrendanH18/Marketpulse/issues/153)

These fifteen additions to the terminal app (`marketpulse` with no subcommand)
are the terminal app's share of the thousand improvements in issue #153. They
sort the tables that couldn't be sorted, add a few keys, make the pane footers
say more, and fix one filter bug. Each is tested headlessly in
`tests/test_tui_improvements.py`. The examples use fictional accounts.

| # | Workspace | Key or place | Improvement |
| --- | --- | --- | --- |
| 1 | Watchlist (3) | `o` / `O` | Sorts the watchlist by symbol or by today's % change (biggest gain first), or puts it back in your saved list order. Symbols without a quote stay at the bottom. The footer shows the sort, for example `sort day % ↓`. `J` / `K` still reorder the saved list, so while the watchlist is sorted they say so and do nothing; press `o` until the sort clears. |
| 2 | Accounts (7) | `o` / `O` | Sorts accounts by name, by type or by value (largest first), or back by id, which is the usual order. An account with no value stays last. The cursor stays on the account it was on, and `enter` still opens that account's holdings. |
| 3 | Alerts (8) | `o` / `O` | Sorts alerts by id or by state (triggered, then armed, then paused), or back by symbol, which is the usual order. |
| 4 | Activity (5) | `d` | Duplicates the selected transaction: it opens a new-transaction form with the same type, account, symbol, quantity, price, amount, fees, currency and note, dated today. Nothing is saved until you save the form, and the original entry is not changed. Entries in archived accounts can't be duplicated; the app says so. Anywhere else, `d` tells you to select a transaction in activity. |
| 5 | Everywhere | `!` | Opens a *Problems* list: ledger issues with their date and transaction number (for example `2024-05-01  #6  Sell of 50.0000 XEQT.TO exceeds 5.0000 held`), positions left out of net worth because they have no price or FX rate, archived accounts that still hold value, and quotes that couldn't be loaded. With none, it says *No problems*. `!`, `escape` or `q` closes it. The activity and holdings footers now end their warnings with `(! lists them)`. |
| 6 | Activity (5) | `b`, `s`, `D`, `N` | The transaction form now starts in the selected entry's account, as it already did in holdings. Before, activity always started in the first account (or the `f` account filter). |
| 7 | Holdings (2), Activity (5) | pane footer | When a filter matches nothing, the footer says `no match — escape clears`. |
| 8 | Activity (5) | `/` filter | Bug fix: typing `=` on its way to `=SYMBOL` hid every entry with a symbol and left only deposits and other cash entries. A lone `=` now filters nothing until you type a symbol after it. |
| 9 | Watchlist (3) | pane footer | Counts how many symbols are up and down today and how many have no quote, for example `3 symbols · 1 up · 1 down · 1 unavailable`. A single symbol now reads `1 symbol`, not `1 symbols`. |
| 10 | Alerts (8) | pane footer | Adds how many alerts are triggered right now, for example `2 armed of 3 · 1 triggered`. |
| 11 | Activity (5) | pane footer | Shows the dates the listed entries span, for example `2 of 5 transactions · 2024-02-01 → 2024-04-01`, so a filtered list says how far back it goes. |
| 12 | Any table | `ctrl+y` | Copies the whole table to the clipboard as tab-separated text, with the column headers first: every row the filters leave, in the order shown, with privacy masks (`••••`) if privacy mode is on. `Y` still copies one row. |
| 13 | Holdings (2) | `$` | Hides or shows the cash rows. It works from any workspace and switches to holdings. While cash is hidden the footer ends with `cash hidden ($)`. This lasts for this session only. |
| 14 | Command palette | `ctrl+p` | *Sort holdings by value*, *Sort accounts by name*, *Sort alerts by state* and so on choose a sort column and direction directly, for every table that sorts (21 entries); `o` and `O` can only cycle and reverse. The palette also has *Copy table*, *Show or hide cash rows*, *Duplicate selected transaction* and *Show problems*. |
| 15 | Chart (4) | `[`, `]`, `c`, `C` | These keys used to do nothing, silently, in the wrong place. Now they explain: outside the chart workspace they say they work on the chart (4); on the chart with no symbol open, `Open a chart first: / searches for a symbol, v charts the selected row`; and `C` with nothing to clear says so. |

`F1` lists each workspace's new keys, and `?` lists them all under *Navigation
and productivity*. The offline `report tui-keys` and `report workspaces`
datasets include them too.

## What stays the same

`d`, `$`, `!` and `ctrl+y` had no binding before. No existing key was rebound:
`o` / `O` work in three more tables, and `[`, `]`, `c` and `C` only add a
message where they used to do nothing. Every table opens in its usual order,
and sorting and hiding cash last for this session only. No figure is calculated
differently: sorting reorders the rows, the footers count rows that are already
on screen, and *Problems* lists what the ledger replay and the last refresh
already found. Nothing here fetches data or writes the ledger, except saving a
duplicated transaction, which you confirm in the form.
