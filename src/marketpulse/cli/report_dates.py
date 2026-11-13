"""Calendar-date recognition shared by offline report filters, derived columns and summaries."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

_DATE_TEXT = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ].*)?", re.ASCII | re.DOTALL)
_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


def date_of(value: Any) -> date | None:
    """The calendar date a report cell starts with, or None.

    Only strings count: ``YYYY-MM-DD`` alone, or followed by ``T`` or a space
    and a time, the way saved dates and timestamps are written. Impossible
    dates such as ``2024-02-30`` and every other type are not dates.
    """
    if not isinstance(value, str) or not _DATE_TEXT.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_date_argument(text: str) -> date | None:
    """A complete ``YYYY-MM-DD`` option value, or None when it is not a valid date."""
    if not _DATE_ONLY.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
