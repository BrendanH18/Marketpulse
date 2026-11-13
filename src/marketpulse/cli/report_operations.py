"""The catalog of shared report and summary operations, for discovery and documentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import report_derive


@dataclass(frozen=True)
class Operation:
    family: str
    operation: str
    commands: tuple[str, ...]
    syntax: str
    summary: str
    issue: int


# The commands that accept an operation, always in this order.
_REPORT = ("report",)
_SUMMARIZE = ("summarize",)
_BOTH = ("report", "summarize")


def _options(issue: int, family: str, commands: tuple[str, ...], *rows: tuple[str, str]) -> tuple[Operation, ...]:
    """Operations that each have an option of their own: a row is the syntax and the summary.

    The operation is named after its option, without the dashes.
    """
    return tuple(
        Operation(family, syntax.split()[0].removeprefix("--"), commands, syntax, summary, issue)
        for syntax, summary in rows
    )


def _choices(
    issue: int, family: str, commands: tuple[str, ...], syntax: str, *rows: tuple[str, str]
) -> tuple[Operation, ...]:
    """Operations that share an option and are chosen by name in its value: a row is the name and the summary.

    The name fills the ``{}`` in ``syntax``.
    """
    return tuple(Operation(family, name, commands, syntax.format(name), summary, issue) for name, summary in rows)


# The catalog order is part of the interface: batches as they shipped and, within each, the order of
# its documentation. `commands` names only the commands that really have the option, and a summary
# is one plain sentence. The first hundred summaries come from docs/cli-composable-reports.md (#136),
# docs/cli-report-improvements.md (#138) and docs/cli-report-summaries.md (#140); the derive
# functions (#142) describe themselves.
OPERATIONS: tuple[Operation, ...] = (
    # 136: twenty operations for `report`; `summarize` accepts ten of them.
    *_options(
        136,
        "projection",
        _REPORT,
        ("--fields FIELD,FIELD", "Select columns and their output order."),
        ("--omit FIELD,FIELD", "Exclude columns from the output."),
    ),
    *_options(
        136,
        "filter",
        _BOTH,
        ("--where FIELD=VALUE", "Keep exact, case-sensitive string matches; repeat to require every condition."),
    ),
    *_options(
        136,
        "filter",
        _REPORT,
        ("--not FIELD=VALUE", "Remove exact, case-sensitive string matches; repeat for several exclusions."),
        ("--contains FIELD=TEXT", "Keep values containing text, ignoring case."),
        ("--prefix FIELD=TEXT", "Keep values beginning with text, ignoring case."),
        ("--suffix FIELD=TEXT", "Keep values ending with text, ignoring case."),
        ("--present FIELD", "Keep values other than null or an empty string; zero and false are present."),
        ("--missing FIELD", "Keep null or empty-string values."),
    ),
    *_options(
        136,
        "sort",
        _BOTH,
        ("--sort FIELD", "Sort by a field; repeat for ordered sort keys."),
        ("--descending", "Reverse the requested sort direction."),
    ),
    *_options(
        136,
        "page",
        _BOTH,
        ("--offset N", "Skip the first N matching, ordered rows."),
        ("--limit N", "Show at most N rows after the offset."),
    ),
    *_options(
        136,
        "selection",
        _REPORT,
        ("--unique FIELD", "Keep the first row for each field value; repeat to form a composite key."),
    ),
    *_options(136, "count", _REPORT, ("--count", "Print the matching row count before pagination.")),
    *_choices(
        136,
        "format",
        _BOTH,
        "--format {}",
        ("jsonl", "Emit one JSON object per line."),
        ("csv", "Emit comma-separated columns with a header."),
        ("tsv", "Emit tab-separated columns with a header."),
        ("markdown", "Emit a Markdown table."),
    ),
    *_options(136, "page", _BOTH, ("--page-info", "Wrap default JSON output with pagination metadata.")),
    # 138: forty more for `report`; `summarize` shares the filters.
    *_options(
        138,
        "filter",
        _BOTH,
        ("--ieq FIELD=TEXT", "Text equality ignoring case, using Unicode case folding."),
        ("--ine FIELD=TEXT", "Text inequality ignoring case."),
        ("--not-contains FIELD=TEXT", "Exclude substring matches, ignoring case."),
        ("--not-prefix FIELD=TEXT", "Exclude prefix matches, ignoring case."),
        ("--not-suffix FIELD=TEXT", "Exclude suffix matches, ignoring case."),
        ("--gt FIELD=NUMBER", "Keep numeric values strictly above the threshold."),
        ("--ge FIELD=NUMBER", "Keep numeric values at or above the threshold."),
        ("--lt FIELD=NUMBER", "Keep numeric values strictly below the threshold."),
        ("--le FIELD=NUMBER", "Keep numeric values at or below the threshold."),
        ("--between FIELD=LOW,HIGH", "Keep values within inclusive numeric bounds."),
        ("--outside FIELD=LOW,HIGH", "Keep values strictly outside inclusive numeric bounds."),
        ("--in FIELD=JSON_ARRAY", "Keep typed membership matches, including nested JSON values."),
        ("--not-in FIELD=JSON_ARRAY", "Exclude typed membership matches."),
        ("--empty FIELD", "Keep null, empty string, empty array or empty object."),
        ("--nonempty FIELD", "Exclude null, empty string, empty array or empty object; zero and false remain."),
        ("--is-type FIELD=TYPE", "Select values of type string, number, boolean, array, object or null."),
        ("--length FIELD=N", "Select strings, arrays or objects with exactly N elements."),
        ("--min-length FIELD=N", "Select strings, arrays or objects with at least N elements."),
        ("--max-length FIELD=N", "Select strings, arrays or objects with at most N elements."),
        ("--glob FIELD=PATTERN", "Case-sensitive shell wildcards (*, ?, [abc]), over report text."),
    ),
    *_options(
        138,
        "transform",
        _REPORT,
        ("--lower FIELD", "Lowercase strings for output; other types retain their values."),
        ("--upper FIELD", "Uppercase strings for output."),
        ("--strip FIELD", "Remove whitespace from both ends of strings."),
        ("--lstrip FIELD", "Remove leading string whitespace."),
        ("--rstrip FIELD", "Remove trailing string whitespace."),
        ("--replace FIELD=JSON_PAIR", 'Replace substrings; pair is ["old","new"], with nonempty old text.'),
        ("--fill FIELD=JSON", "Replace null with a JSON value; empty strings, zero and false remain."),
        ("--null-if FIELD=JSON", "Replace typed matches with null."),
        ("--stringify FIELD", "Convert to report text: strings unchanged, null empty, others canonical JSON."),
        ("--encode-json FIELD", "Serialize any value, including strings and null, into a JSON string."),
        ("--decode-json FIELD", "Parse strings as JSON; nonstrings retain their values and invalid JSON is an error."),
        ("--length-of FIELD", "Output string/array/object length, or null for other types."),
        ("--round FIELD=DIGITS", "Round finite JSON numbers to 0-15 decimal places for output only."),
    ),
    *_options(
        138,
        "column",
        _REPORT,
        ("--rename FIELD=NAME", "Rename output columns simultaneously; swaps are supported."),
        ("--constant NAME=JSON", "Append a constant output column."),
        ("--row-number NAME", "Append a 1-based row position within the result before pagination."),
    ),
    *_options(138, "sort", _REPORT, ("--sort-ci FIELD", "Case-insensitive ordering; repeat for ordered tie breakers.")),
    *_options(
        138,
        "window",
        _REPORT,
        ("--reverse-rows", "Reverse the ordered rows."),
        ("--tail N", "Retain the last N rows before pagination (N >= 1)."),
        ("--every N", "Retain every Nth row, starting with the first (N >= 1)."),
    ),
    # 140: forty summary operations for `summarize`; only `count` reads no field.
    *_choices(140, "summary", _SUMMARIZE, "--metric NAME={}", ("count", "Number of rows.")),
    *_choices(
        140,
        "summary",
        _SUMMARIZE,
        "--metric NAME={}:FIELD",
        ("present", "Number of nonmissing values."),
        ("missing", "Number of null or empty-string values."),
        ("empty", "Number of null, empty-string, empty-array or empty-object values."),
        ("nonempty", "Number of values that are not empty."),
        ("distinct", "Number of distinct typed values, including missing values."),
        ("duplicates", "Number of values beyond their first occurrence."),
        ("first", "First value, including null."),
        ("last", "Last value, including null."),
        ("first-present", "First nonmissing value."),
        ("last-present", "Last nonmissing value."),
        ("mode", "Most frequent typed value."),
        ("mode-count", "Frequency of the most frequent typed value."),
        ("values", "All field values in source order."),
        ("distinct-values", "Distinct typed values in first-encountered order."),
        ("number-count", "Number of finite numeric values."),
        ("number-distinct", "Number of distinct parsed finite numbers."),
        ("number-sum", "Sum of finite numbers."),
        ("number-min", "Smallest finite number."),
        ("number-max", "Largest finite number."),
        ("number-mean", "Arithmetic mean of finite numbers."),
        ("number-median", "Median of finite numbers; mean of the middle pair for even counts."),
        ("number-range", "Largest minus smallest finite number."),
        ("positive-count", "Number of finite numbers above zero."),
        ("negative-count", "Number of finite numbers below zero."),
        ("zero-count", "Number of finite numbers equal to zero."),
        ("positive-sum", "Sum of finite numbers above zero."),
        ("negative-sum", "Sum of finite numbers below zero."),
        ("absolute-sum", "Sum of the absolute values of finite numbers."),
        ("true-count", "Number of JSON true values; numeric 1 is excluded."),
        ("false-count", "Number of JSON false values; numeric 0 is excluded."),
        ("string-count", "Number of strings, including empty strings."),
        ("array-count", "Number of arrays, including empty arrays."),
        ("object-count", "Number of objects, including empty objects."),
        ("length-sum", "Sum of string lengths, array lengths and object key counts."),
        ("length-min", "Smallest length among strings, arrays and objects."),
        ("length-max", "Largest length among strings, arrays and objects."),
        ("length-mean", "Mean length among strings, arrays and objects."),
        ("text-min", "Smallest string in case-sensitive Unicode order."),
        ("text-max", "Largest string in case-sensitive Unicode order."),
    ),
    # 142: fifty --derive functions, for both commands, in the order `report derive-functions` lists them.
    *(
        Operation(
            "derive",
            function.name,
            _BOTH,
            f"--derive NAME={function.name}:FIELD" + (f":{function.argument}" if function.argument else ""),
            function.description,
            142,
        )
        for function in report_derive.FUNCTIONS
    ),
    # 143: thirty more: filters, keyed selection, summaries, grouping steps and formats.
    *_options(
        143,
        "filter",
        _BOTH,
        ("--regex FIELD=PATTERN", "Keep rows whose text matches a regular expression."),
        ("--not-regex FIELD=PATTERN", "Exclude rows whose text matches a regular expression."),
        ("--iglob FIELD=PATTERN", "Keep shell wildcard matches, ignoring case."),
        ("--not-glob FIELD=PATTERN", "Exclude case-sensitive shell wildcard matches."),
        ("--contains-any FIELD=JSON_ARRAY", "Keep rows containing any listed text, ignoring case."),
        ("--contains-all FIELD=JSON_ARRAY", "Keep rows containing every listed text, ignoring case."),
        ("--date-from FIELD=YYYY-MM-DD", "Keep dates on or after a day."),
        ("--date-to FIELD=YYYY-MM-DD", "Keep dates on or before a day."),
        ("--has-item FIELD=JSON", "Keep arrays containing a typed item."),
        ("--has-key FIELD=KEY", "Keep objects containing a key."),
    ),
    *_options(
        143,
        "selection",
        _REPORT,
        ("--duplicates FIELD", "Keep rows whose key occurs more than once."),
        ("--singletons FIELD", "Keep rows whose key occurs exactly once."),
        ("--unique-last FIELD", "Keep the last row for each key."),
    ),
    *_choices(
        143,
        "summary",
        _SUMMARIZE,
        "--metric NAME={}:FIELD",
        ("date-min", "Earliest date."),
        ("date-max", "Latest date."),
        ("date-count", "Number of date values."),
        ("date-span", "Whole days between the earliest and latest date."),
        ("number-variance", "Population variance of finite numbers."),
        ("number-stdev", "Population standard deviation of finite numbers."),
        ("number-q1", "First quartile of finite numbers."),
        ("number-q3", "Third quartile of finite numbers."),
        ("value-counts", "Each distinct typed value with its count, most frequent first."),
        ("repeated-values", "Distinct typed values that occur more than once."),
    ),
    *_options(
        143,
        "group",
        _SUMMARIZE,
        ("--having FILTER:NAME=VALUE", "Keep summary rows passing a filter on a grouping or metric column."),
        ("--totals", "Append a final row summarizing every filtered source row."),
    ),
    *_choices(
        143,
        "format",
        _BOTH,
        "--format {}",
        ("html", "Emit an escaped HTML table."),
        ("text", "Emit an aligned plain-text table."),
        ("records", "Emit one field-per-line block per row."),
        ("lines", "Emit one raw value per line from a single column."),
        ("json-columns", "Emit one JSON array per column."),
    ),
)


def rows() -> list[dict[str, Any]]:
    """Every operation as a report row, numbered from 1 in catalog order."""
    return [
        {
            "number": number,
            "family": item.family,
            "operation": item.operation,
            "commands": list(item.commands),
            "syntax": item.syntax,
            "summary": item.summary,
            "issue": item.issue,
        }
        for number, item in enumerate(OPERATIONS, 1)
    ]
