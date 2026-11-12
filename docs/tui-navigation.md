# Terminal app navigation

[User guide](usage.md) · [One hundred improvements](cli-hundred-improvements.md) · [Issue #130](https://github.com/BrendanH18/Marketpulse/issues/130)

These ten additions to the terminal app (`marketpulse` with no subcommand) move
between workspaces, tables and filters without the mouse. Every key was unbound
before, so the existing keys in the [keyboard reference](usage.md#keyboard-reference)
do exactly what they did. Each one also has a command-palette entry (`ctrl+p`),
named in brackets. The examples use fictional accounts.

81. `backspace` returns to the workspace you were on before the current one; press it again to go back the other way, so it flips between two workspaces (say holdings and activity). It does nothing until you have changed workspace once. (Palette: *Previous workspace*.)
82. `}` and `{` step to the next and previous workspace in the top bar's order, wrapping from alerts back to the dashboard and the other way. `1`–`8` still jump straight to one. (Palette: *Next workspace*, *Workspace to the left*.)
83. `j` and `k` move the cursor one row down or up in the current workspace's table (holdings, watchlist, activity, accounts or alerts), stopping at the ends, alongside the arrow keys. They are ignored while you type in a filter or the chart's symbol box. Watchlist reordering keeps `J` / `K`.
84. `<` and `>` jump to the first and last row of the current table. (`home` / `end` in a table scroll sideways; `ctrl+home` / `ctrl+end` aren't sent by every terminal.) (Palette: *First row*, *Last row*.)
85. `T` shows the selected symbol's transactions: from holdings, the watchlist, the chart, activity or alerts it opens Activity with the filter set to that symbol, so only its buys, sells, dividends and other entries are listed. (Palette: *Show selected symbol's transactions*.)
86. `F` opens a filter line above the holdings table and filters as you type. It keeps holdings whose symbol, name, account or asset class contains the text (ignoring case), and cash rows whose account or currency matches (or that match `cash`). It works with the `f` account filter. The pane footer shows `2 of 3 positions` and the filter text (`F ▸ “birch”`); the total is the value of the rows shown. `enter` returns to the table and keeps the filter; `enter` on an empty filter closes it. (Palette: *Filter holdings*.)
87. `escape` clears a filter: in holdings it empties and hides the `F` filter; in activity it empties the `/` filter. Either way the cursor goes back to the table. Elsewhere `escape` does what it did before (closing forms, clearing the chart crosshair). (Palette: *Clear filter*.)
88. The bottom hints line shows the cursor's place in the current table, such as `row 3/12`, and updates as you move. Workspaces without a table don't show it.
89. The bottom hints line also shows how long ago prices were last refreshed: `updated 12s ago`, `updated 4m ago` or `updated 2h ago`. It is updated every second and resets after each automatic refresh or `r`. Like the other parts of the hints line, both are left out when the terminal is too narrow.
90. `F1` lists the keys for the current workspace: its usual hints, the additions from this guide and [the productivity guide](tui-productivity.md) that apply there, and the keys that work everywhere. `F1`, `escape` or `q` closes it. `?` still shows the full key list, which now has a *Navigation and productivity* section. (Palette: *Workspace keys*.)

## What stays the same

No existing key was rebound and no default changed: `backspace`, `{`, `}`,
`j`, `k`, `<`, `>`, `F`, `T` and `F1` had no binding before, and `escape` at the
app level only acts when a holdings or activity filter is open or has text.
Forms, pickers and the help screen keep their own `escape`. While a text box has
focus, letters go into the box rather than triggering these keys. Nothing here
fetches data or changes the ledger.
