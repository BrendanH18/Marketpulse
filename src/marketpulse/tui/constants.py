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
