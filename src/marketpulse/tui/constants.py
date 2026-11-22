"""Workspace hints, table columns and dashboard choices."""

NW_RANGES = ["1m", "3m", "6m", "ytd", "1y", "all"]
ALLOC_MODES = ["class", "account", "currency"]
MOVERS_MODES = ["day %", "day $", "unrealized"]
HOLDING_FILTER_MODES = ["all", "gainers", "losers", "non-market"]
ACTIVITY_FILTER_MODES = ["all", "trades", "income", "cash"]
ALERT_FILTER_MODES = ["all", "armed", "triggered", "paused"]
# `%` in activity: how far back entries are listed (all, the last 30 / 90 days, this year, the last year).
ACTIVITY_WINDOWS = ["all", "30d", "90d", "ytd", "1y"]
# Holdings table keeps Account, Symbol, Qty, Price, Day, Value, Gain, Gain %, Weight;
# name and average cost live in the position pane.
HOLDING_COLUMNS = (0, 1, 3, 5, 6, 7, 8, 9, 10)
HINTS = {
    "dashboard": "n new txn · / search · g grouping · , range- · . range+ · p privacy · t theme",
    "holdings": "⏎ chart · b buy · s sell · D dividend · f account · A alert · w watch",
    "watchlist": "⏎ chart · a add · x remove · J/K reorder · b buy · A alert",
    "chart": "[/] period · c compare · C clear · ←/→ crosshair · b buy · w watch · A alert",
    "activity": "n new · e edit · x delete · u undo · / filter · i import · E export",
    "income": "D dividend · n new txn · r refresh",
    "tax": "n new account · e edit · x delete · R room · G add GIC/asset · V value asset · ⏎ holdings",
    "alerts": "n new alert · x delete · space pause/resume · ⏎ chart",
}

# ── Keyboard navigation and productivity (#130) ───────────────────────────────
# Tables the navigation keys (j/k, </>, Y, o/O) act on, by workspace.
TABLES = {
    "holdings": "#holdings-table",
    "watchlist": "#watch-table",
    "activity": "#activity-table",
    "tax": "#accounts-table",
    "alerts": "#alerts-table",
}
# Sort columns cycled by `o`: the first is the default order; the flag is the natural "descending".
SORT_MODES: dict[str, list[tuple[str, bool]]] = {
    "holdings": [
        ("account", False),
        ("symbol", False),
        ("value", True),
        ("day %", True),
        ("gain", True),
        ("gain %", True),
    ],
    "activity": [("date", True), ("symbol", False), ("type", False), ("account", False), ("amount", True)],
    # #153: the watchlist, accounts and alerts tables sort too; each default is the order they always had.
    "watchlist": [("list", False), ("symbol", False), ("day %", True)],
    "tax": [("id", False), ("name", False), ("type", False), ("value", True)],
    "alerts": [("symbol", False), ("id", False), ("state", False)],
}
# Every transaction type for the `N` picker, in the command palette's order.
TXN_CHOICES = [
    ("BUY", "Buy", "Record a buy"),
    ("SELL", "Sell", "Record a sell"),
    ("DIVIDEND", "Dividend", "Cash dividend or distribution"),
    ("DRIP", "DRIP", "Reinvested dividend"),
    ("DEPOSIT", "Deposit", "Money into an account"),
    ("WITHDRAWAL", "Withdrawal", "Money out of an account"),
    ("INTEREST", "Interest", "Interest income"),
    ("SPLIT", "Split", "Stock split"),
    ("TRANSFER", "Transfer in-kind", "Move shares between accounts"),
    ("ROC", "Return of capital", "Reduces the ACB"),
    ("ACB_INCREASE", "Increase cost base", "Adjusts the ACB without moving cash or shares"),
    ("FEE", "Fee", "Account or management fee"),
    ("VALUATION", "Valuation", "Mark a manual asset at a price"),
]
_TABLE_KEYS = [
    ("j / k", "next / previous row"),
    ("ctrl+d / ctrl+u", "half-page down / up"),
    ("< / >", "first / last row"),
    ("Y", "copy the row"),
    ("ctrl+y", "copy the whole table (TSV)"),
    ("# / X", "copy table as CSV / Markdown"),
    ('"', "copy table as JSON"),
    (":", "go to row number"),
    ("ctrl+f / ctrl+g", "find a row / find next"),
    ("( / )", "previous / next group"),
    ("P", "details of the selected row"),
]
_SORT_KEYS = [("o / O", "sort column / reverse"), ("0", "reset table sort")]
_SYMBOL_KEYS = [
    ("y", "copy the symbol"),
    ("v", "open its chart"),
    ("T", "show its transactions"),
    ("S", "jump to symbol in holdings"),
    ("W", "add to / remove from the watchlist"),
    ("&", "alerts for the symbol"),
]
# Keys added under #130, #153 and later batches, per workspace; F1 lists them after the workspace's HINTS.
WORKSPACE_KEYS: dict[str, list[tuple[str, str]]] = {
    "dashboard": [
        ("z", "zoom: hide the side column"),
        ("m", "cycle movers metric (day % / day $ / unrealized)"),
        ("Q", "copy portfolio summary"),
        ("ctrl+t", "copy the accounts and returns panes as text"),
    ],
    "holdings": [
        ("F", "filter holdings as you type"),
        ("M", "cycle holdings mode (all / gainers / losers / non-market)"),
        *_SORT_KEYS,
        *_TABLE_KEYS,
        *_SYMBOL_KEYS,
        ("z", "zoom: hide the position pane"),
        ("$", "show / hide cash rows"),
        (";", "show only the selected row's account"),
        ("ctrl+t", "copy the position pane as text"),
    ],
    "watchlist": [
        *_SORT_KEYS,
        *_TABLE_KEYS,
        *_SYMBOL_KEYS,
        ("z", "zoom: hide the quote pane"),
        ("ctrl+s", "save the sorted order as the list order"),
        ("ctrl+t", "copy the quote pane as text"),
    ],
    "chart": [
        ("y", "copy the symbol"),
        ("Y", "copy chart bar or summary"),
        ("T", "show its transactions"),
        ("S", "jump to symbol in holdings"),
        ("W", "add to / remove from the watchlist"),
        ("&", "alerts for the symbol"),
        ("^ / _", "crosshair to the period high / low"),
        ("'", "back to the previous chart"),
        ("ctrl+t", "copy the chart's quote line"),
    ],
    "activity": [
        ("M", "cycle activity mode (all / trades / income / cash)"),
        ("@", "cycle account filter"),
        *_SORT_KEYS,
        *_TABLE_KEYS,
        *_SYMBOL_KEYS,
        ("escape", "clear filters"),
        ("d", "duplicate the entry, dated today"),
        ("%", "cycle date window (all / 30d / 90d / ytd / 1y)"),
        (";", "show only the selected entry's account"),
        (":", "go to a row number or date (2024-03)"),
        ("ctrl+e", "next transaction with a ledger issue"),
    ],
    "income": [
        ("j / k / < / >", "scroll income view"),
        ("- / +", "step income year (or all)"),
        ("ctrl+t", "copy the income report as text"),
    ],
    "tax": [
        *_SORT_KEYS,
        *_TABLE_KEYS,
        ("I", "show / hide archived accounts"),
        ("- / +", "step tax year (or all)"),
        ("ctrl+t", "copy the tax report as text"),
    ],
    "alerts": [
        ("M", "cycle alerts mode (all / armed / triggered / paused)"),
        ("U", "re-arm all triggered alerts"),
        ("&", "only this symbol's alerts (escape clears)"),
        *_SORT_KEYS,
        *_TABLE_KEYS,
        *_SYMBOL_KEYS,
    ],
}
GLOBAL_KEYS = [
    ("backspace", "previous workspace"),
    ("{ / }", "previous / next workspace"),
    ("N", "record any transaction type"),
    ("F1", "keys for this workspace"),
    ("!", "problems: ledger issues, missing prices"),
]
