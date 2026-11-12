# Terminal app productivity

[User guide](usage.md) · [One hundred improvements](cli-hundred-improvements.md) · [Issue #130](https://github.com/BrendanH18/Marketpulse/issues/130)

These ten additions to the terminal app sort and copy what's on screen, record
any transaction type from the keyboard, and put every key-only action in the
command palette (`ctrl+p`). See [Terminal app navigation](tui-navigation.md) for
items 81–90. Sorting and copying only change how existing rows are ordered or
copied; no figure is calculated differently. The examples use fictional accounts.

91. `o` cycles the sort column in holdings (account, which is the default, then symbol, value, day %, gain and gain %) and in activity (date, which is the default and newest first, then symbol, type, account and amount). Each column starts in its natural direction: names A–Z and amounts largest first. When sorting by an amount or percentage, holdings without one (no price or FX rate) stay at the bottom, and cash rows always come after positions. The pane footer shows the order (`sort value ↓`) whenever it isn't the default. Value and gain sort by the base-currency amounts shown in the Value column and the position pane; activity's amount sorts by each entry's native amount, ignoring sign. (Palette: *Sort by next column*.)
92. `O` reverses the current sort, for example smallest holdings first or oldest activity first (`sort date ↑`). Cycling `o` back to the default column restores the original order. (Palette: *Reverse sort*.)
93. `y` copies the selected symbol to the clipboard (holdings, watchlist, activity, alerts, or the chart's symbol) and confirms with `Copied XEQT.TO`. It uses the terminal's clipboard escape (OSC 52), which most terminals support; macOS Terminal.app doesn't. (Palette: *Copy selected symbol*.)
94. `Y` copies the selected table row as tab-separated text exactly as shown, ready to paste into a spreadsheet. In privacy mode the copy has the same masked amounts (`••••`) as the screen. (Palette: *Copy selected row*.)
95. `z` zooms: it hides the position and quote panes and the dashboard's side column so tables and the net-worth chart get the full width. Press it again to bring them back. It lasts for this session only. (Palette: *Toggle zoom*.)
96. `N` opens a picker with every transaction type (buy, sell, dividend, DRIP, deposit, withdrawal, interest, split, transfer in kind, return of capital, fee and valuation). `↑` / `↓` and `enter` open the usual transaction form for that type, prefilled with the selected symbol and account like `b` and `s`; `escape` closes it. (Palette: *Record any transaction type…*.)
97. `v` charts the selected row's symbol in any workspace that has one, including Activity, where `enter` opens the edit form instead. (Palette: *Chart selected symbol*.)
98. The command palette has view actions that only had keys: *Cycle allocation grouping* (`g`), *Cycle account filter* (`f`), *Next theme* (`t`), plus direct choices the keys can only cycle through: *Net worth range: 1m* … *Net worth range: all* (`,` / `.`), *Holdings: Birch TFSA* for each active account, and *Holdings: all accounts*.
99. The command palette also has actions on the selection: *Edit selected* (`e`), *Delete selected* (`x`, still confirmed), *Pause or resume selected alert* (`space`), *Compare chart with…* (`c`), *Clear chart comparisons* (`C`), *Move watch symbol up/down* (`K` / `J`), *Quit* (`q`), and *Chart period: 1d* … *Chart period: max*, which reopens the current chart at that period or sets the period for the next one.
100. The accounts pane (workspace 7) footer counts your accounts, for example `2 accounts · 1 archived`, or says `No accounts — n to add one`. Archived accounts still appear in the list, labelled `(archived)`, as before.

## What stays the same

`o`, `O`, `y`, `Y`, `z`, `v` and `N` had no binding before; every existing key
and palette entry works as it did. Holdings and activity open in their usual
order, and sorting choices last for this session only. Nothing here fetches
data, writes the ledger or changes a setting.
