"""Suggestions for misspelled report names; never execute a guessed command."""

from __future__ import annotations

from collections.abc import Iterable
from difflib import get_close_matches
from typing import Any

import click


def suggestion(value: str, choices: Iterable[str], *, cutoff: float = 0.75, prefer_simple_edits: bool = False) -> str:
    if prefer_simple_edits:
        choices = tuple(choices)
        same_length = {choice for choice in choices if len(choice) == len(value)}
        if same_length:
            swaps = {
                value[:index] + value[index + 1] + value[index] + value[index + 2 :]
                for index in range(len(value) - 1)
                if value[index] != value[index + 1]
            }
            transposed = same_length & swaps
            if transposed:
                return f" Did you mean '{transposed.pop()}'?" if len(transposed) == 1 else ""
        shorter = {choice for choice in choices if len(choice) + 1 == len(value)}
        if shorter:
            deletions = {value[:index] + value[index + 1 :] for index in range(len(value))}
            contracted = shorter & deletions
            if contracted:
                return f" Did you mean '{contracted.pop()}'?" if len(contracted) == 1 else ""
    matches = get_close_matches(value, choices, n=1, cutoff=cutoff)
    return f" Did you mean '{matches[0]}'?" if matches else ""


class SourceChoice(click.Choice):
    """Retain Click's validation and completion, adding a close source spelling."""

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> str:
        try:
            return super().convert(value, param, ctx)
        except click.BadParameter as exc:
            raise click.BadParameter(exc.message + suggestion(str(value), self.choices), ctx=ctx, param=param) from None
