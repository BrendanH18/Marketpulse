"""The operation catalog agrees with the real `report` and `summarize` commands, checked both ways."""

import json
import os
import re
from dataclasses import asdict

import click
import pytest
from click.testing import CliRunner

from marketpulse.cli import (
    main,
    report_derive,
    report_filters,
    report_formats,
    report_metrics,
    report_operations,
    report_output,
    reports,
)
from marketpulse.cli.report_operations import OPERATIONS

COMMANDS = ("report", "summarize")
FAMILIES = {
    "projection",
    "filter",
    "sort",
    "page",
    "selection",
    "count",
    "format",
    "transform",
    "column",
    "window",
    "summary",
    "derive",
    "group",
}
# Options the catalog does not count as operations: the schema, the destination and help.
# On `summarize`, `--group-by` only sets up the groups that its operations work on.
HOUSEKEEPING = {
    "report": {"--describe", "--output", "--help"},
    "summarize": {"--describe", "--output", "--help", "--group-by"},
}


def spelled(names):
    """Implementation names as the CLI spells them.

    Underscores become dashes; `in_values` and `round_values` are the options `--in` and `--round`.
    """
    return tuple({"in_values": "in", "round_values": "round"}.get(name, name.replace("_", "-")) for name in names)


# The documented order: each batch in turn and, inside it, each family block with its operations.
# A block the implementation keeps as an ordered list is read from there.
LAYOUT = (
    (136, "projection", ("fields", "omit")),
    (136, "filter", ("where", "not", "contains", "prefix", "suffix", "present", "missing")),
    (136, "sort", ("sort", "descending")),
    (136, "page", ("offset", "limit")),
    (136, "selection", ("unique",)),
    (136, "count", ("count",)),
    (136, "format", ("jsonl", "csv", "tsv", "markdown")),
    (136, "page", ("page-info",)),
    (138, "filter", spelled(report_filters.FILTER_OPTIONS)),
    (138, "transform", spelled(report_output.CELL_OPTIONS)),
    (138, "column", spelled(report_output.EXTRA_OPTIONS)),
    (138, "sort", ("sort-ci",)),
    (138, "window", ("reverse-rows", "tail", "every")),
    (140, "summary", report_metrics.OPERATIONS),
    (142, "derive", tuple(function.name for function in report_derive.FUNCTIONS)),
    (143, "filter", spelled(report_filters.EXPANSION_FILTERS)),
    (143, "selection", ("duplicates", "singletons", "unique-last")),
    (143, "summary", report_metrics.EXPANSION_OPERATIONS),
    (143, "group", ("having", "totals")),
    (143, "format", report_formats.FORMATS),
)

# A fictional argument for every placeholder a syntax uses, so each entry can run on the catalog itself.
EXAMPLES = {
    "FIELD,FIELD": "issue,family",
    "FIELD": "issue",
    "NAME": "result",
    "VALUE": "x",
    "TEXT": "x",
    "KEY": "x",
    "PATTERN": "x*",
    "N": "2",
    "NUMBER": "2",
    "LOW": "1",
    "HIGH": "2",
    "DIGITS": "2",
    "WIDTH": "10",
    "TYPE": "number",
    "JSON": '"x"',
    "JSON_ARRAY": '["x"]',
    "JSON_PAIR": '["x","y"]',
    "YYYY-MM-DD": "2024-01-31",
    "DATE": "2024-01-31",
    "FILTER": "ieq",
}
PLACEHOLDER = re.compile(r"FIELD,FIELD|YYYY-MM-DD|[A-Z]+(?:_[A-Z]+)*")


def options(command):
    """Every long option of a real command, with its Click parameter."""
    return {
        spelling: parameter
        for parameter in main.commands[command].params
        if isinstance(parameter, click.Option)
        for spelling in parameter.opts
        if spelling.startswith("--")
    }


def option_of(item):
    """The option an entry is written with: the first token of its syntax."""
    return item.syntax.split()[0]


def accepting(item):
    """The real commands that have an entry's option and, for `--format`, that choice."""
    option, _, choice = item.syntax.partition(" ")
    found = []
    for command in COMMANDS:
        parameter = options(command).get(option)
        if parameter is not None and (option != "--format" or choice in parameter.type.choices):
            found.append(command)
    return tuple(found)


def invocation(command, item):
    """An entry's syntax as arguments for one command, with what its option needs beside it."""
    option, _, argument = item.syntax.partition(" ")
    arguments = [command, "report-operations", option]
    if argument:
        arguments.append(PLACEHOLDER.sub(lambda match: EXAMPLES[match.group()], argument))
    if command == "summarize":
        # Every summary needs a metric; `result` is also the column that --having filters.
        if option != "--metric":
            arguments += ["--metric", "result=count"]
        # Grouping on the example field lets --sort and --totals run; lines output takes one column only.
        if item.syntax != "--format lines":
            arguments += ["--group-by", "issue"]
    elif item.syntax == "--format lines":
        arguments += ["--fields", "issue"]
    if option == "--descending":
        arguments += ["--sort", "issue"]
    return arguments


def run(*arguments):
    """The output of a real CLI call that must succeed."""
    result = CliRunner().invoke(main, list(arguments))
    assert result.exit_code == 0, result.output
    return result.output


def test_catalog_holds_five_batches_of_distinct_operations():
    assert len(OPERATIONS) == 180
    assert [item.issue for item in OPERATIONS] == [136] * 20 + [138] * 40 + [140] * 40 + [142] * 50 + [143] * 30
    assert {item.family for item in OPERATIONS} == FAMILIES
    assert len({item.syntax for item in OPERATIONS}) == 180
    assert len({(item.family, item.operation) for item in OPERATIONS}) == 180


def test_catalog_follows_the_documented_layout():
    expected = [(issue, family, name) for issue, family, names in LAYOUT for name in names]
    assert [(item.issue, item.family, item.operation) for item in OPERATIONS] == expected


def test_every_operation_is_named_in_its_own_syntax():
    for item in OPERATIONS:
        option, _, argument = item.syntax.partition(" ")
        assert option.startswith("--"), item
        # The name is the option itself, or the format, summary operation or derive function it chooses.
        assert item.operation in (option[2:], *re.split("[=:]", argument)), item


def test_every_summary_is_one_plain_sentence():
    for item in OPERATIONS:
        summary = item.summary
        # Derive functions (#142) reuse their own descriptions, some of which start with "-1".
        assert (summary[0].isupper() or not summary[0].isalpha()) and summary.endswith("."), item
        # Plain in every export format: printable ASCII without Markdown code spans.
        assert summary.isascii() and summary.isprintable() and "`" not in summary, item
        # One sentence: nothing follows a period.
        assert ". " not in summary and summary == summary.strip(), item


def test_rows_number_the_catalog_in_the_source_schema():
    rows = report_operations.rows()
    assert [row["number"] for row in rows] == list(range(1, 181))
    assert all(tuple(row) == reports.SOURCES["report-operations"] for row in rows)
    assert all(type(row["commands"]) is list for row in rows)
    unnumbered = [{key: value for key, value in row.items() if key != "number"} for row in rows]
    assert unnumbered == [{**asdict(item), "commands": list(item.commands)} for item in OPERATIONS]


def test_each_entry_lists_exactly_the_commands_that_accept_it():
    listed = {item.syntax: item.commands for item in OPERATIONS}
    assert listed == {item.syntax: accepting(item) for item in OPERATIONS}


@pytest.mark.parametrize("command", COMMANDS)
def test_every_operation_of_a_command_is_cataloged(command):
    listed = [item for item in OPERATIONS if command in item.commands]
    assert {option_of(item) for item in listed} == set(options(command)) - HOUSEKEEPING[command]
    formats = options(command)["--format"]
    cataloged = {item.operation for item in listed if item.family == "format"}
    assert cataloged == set(formats.type.choices) - {formats.default}


def test_every_syntax_runs_on_each_command_that_lists_it():
    failures = {}
    for item in OPERATIONS:
        for command in item.commands:
            result = CliRunner().invoke(main, invocation(command, item))
            if result.exit_code != 0:
                failures[command, item.syntax] = result.output or repr(result.exception)
    assert not failures


def test_report_emits_the_catalog_without_opening_saved_data():
    assert json.loads(run("report", "report-operations")) == report_operations.rows()
    assert run("report", "report-operations", "--count") == "180\n"
    assert not os.path.exists(os.environ["MARKETPULSE_DATA"])


def test_summarize_counts_each_batch():
    output = run("summarize", "report-operations", "--group-by", "issue", "--metric", "operations=count")
    assert json.loads(output) == [
        {"issue": 136, "operations": 20},
        {"issue": 138, "operations": 40},
        {"issue": 140, "operations": 40},
        {"issue": 142, "operations": 50},
        {"issue": 143, "operations": 30},
    ]


def test_lines_format_prints_the_derive_functions():
    output = run(
        "report", "report-operations", "--where", "family=derive", "--fields", "operation", "--format", "lines"
    )
    assert output.splitlines() == [function.name for function in report_derive.FUNCTIONS]


def test_has_item_counts_the_operations_summarize_accepts():
    listed = sum("summarize" in item.commands for item in OPERATIONS)
    assert run("report", "report-operations", "--has-item", 'commands="summarize"', "--count") == f"{listed}\n"
