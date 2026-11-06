"""The capital gains tax report."""

from __future__ import annotations

from pathlib import Path

import click
from rich.text import Text

from .. import render
from .base import App, fail, pass_app
from .root import main


@main.command()
@click.option("-y", "--year", type=int, default=None)
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write the dispositions (the --year's, or every year's) to this CSV file instead of showing the report.",
)
@pass_app
def tax(app: App, year: int | None, csv_path: Path | None) -> None:
    """Capital gains (pooled ACB, trade-date FX), superficial losses and contribution room."""
    tr = app.tracker
    if csv_path is not None:
        from ..desktop import write_tax_csv

        try:
            with app.busy("Building tax report…"):
                result = write_tax_csv(tr, csv_path, year)
        except ValueError as e:
            fail(str(e))
        app.ok(f"Exported {result['exported']} disposition(s) to {csv_path}")
        if result["issues"]:
            # E.g. a transfer into a TFSA with no price: its deemed sale can't be in the file.
            app.warn(f"{len(result['issues'])} issue(s) may leave sales out of this file:")
            for issue in result["issues"]:
                app.warn(f"  {issue['date']} {issue['message']}")
        return
    with app.busy("Building tax report…"):
        years, report = tr.tax_years()
        rooms = tr.room()
    app.title("Tax")
    app.console.print(
        render.tax_group(years, report, rooms, tr.store.account_map(), tr.base, privacy=app.privacy, year=year)
    )
    app.console.print(
        Text(
            "\nEstimates only — confirm figures against your broker slips (T5008/T3/T5) before filing."
            "\nPurchases by a spouse or a corporation you control can also make a loss superficial;"
            " MarketPulse can't see those.",
            style="muted",
        )
    )
