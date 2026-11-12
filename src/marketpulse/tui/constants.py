"""Workspace hints, table columns and dashboard choices."""

NW_RANGES = ["1m", "3m", "6m", "ytd", "1y", "all"]
ALLOC_MODES = ["class", "account", "currency"]
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
    ("FEE", "Fee", "Account or management fee"),
    ("VALUATION", "Valuation", "Mark a manual asset at a price"),
]
_TABLE_KEYS = [("j / k", "next / previous row"), ("< / >", "first / last row"), ("Y", "copy the row")]
_SYMBOL_KEYS = [("y", "copy the symbol"), ("v", "open its chart"), ("T", "show its transactions")]
# Keys added under #130, per workspace; F1 lists them after the workspace's HINTS.
WORKSPACE_KEYS: dict[str, list[tuple[str, str]]] = {
    "dashboard": [("z", "zoom: hide the side column")],
    "holdings": [
        ("F", "filter holdings as you type"),
        ("o / O", "sort column / reverse"),
        *_TABLE_KEYS,
        *_SYMBOL_KEYS,
        ("z", "zoom: hide the position pane"),
    ],
    "watchlist": [*_TABLE_KEYS, *_SYMBOL_KEYS, ("z", "zoom: hide the quote pane")],
    "chart": [("y", "copy the symbol"), ("T", "show its transactions")],
    "activity": [("o / O", "sort column / reverse"), *_TABLE_KEYS, *_SYMBOL_KEYS, ("escape", "clear the filter")],
    "income": [],
    "tax": _TABLE_KEYS,
    "alerts": [*_TABLE_KEYS, *_SYMBOL_KEYS],
}
GLOBAL_KEYS = [
    ("backspace", "previous workspace"),
    ("{ / }", "previous / next workspace"),
    ("N", "record any transaction type"),
    ("F1", "keys for this workspace"),
]
