"""Suggestions for misspelled report names; never execute a guessed command."""

from __future__ import annotations

from collections.abc import Iterable
from difflib import get_close_matches
from typing import Any

import click


def suggestion(value: str, choices: Iterable[str]) -> str:
    matches = get_close_matches(value, choices, n=1, cutoff=0.75)
    return f" Did you mean '{matches[0]}'?" if matches else ""


class SourceChoice(click.Choice):
    """Retain Click's validation and completion, adding a close source spelling."""

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> str:
        try:
            return super().convert(value, param, ctx)
        except click.BadParameter as exc:
            raise click.BadParameter(exc.message + suggestion(str(value), self.choices), ctx=ctx, param=param) from None
