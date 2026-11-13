"""Calendar-date recognition for offline report filters and summaries."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .report_derive import _date

_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


def date_of(value: Any) -> date | None:
    """The calendar date of a report cell, or None.

    The same rule as the --derive date functions: ``YYYY-MM-DD`` alone, or followed by ``T``
    or a space and a valid time with an optional offset. Impossible dates and other types are
    not dates.
    """
    return _date(value)


def parse_date_argument(text: str) -> date | None:
    """A complete ``YYYY-MM-DD`` option value, or None when it is not a valid date."""
    if not _DATE_ONLY.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
