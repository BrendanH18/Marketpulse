"""`summarize` with --having, --totals and --derive (#143, specification sections A and E).

Every expected value is worked out by hand from the specification: nothing here calls the derive,
filter, metric or format code to build an expectation. Fixed rows stand in for saved sources (the
source name only selects a schema), and one fictional ledger shows the same steps on real data.
"""

import copy
import csv
import io
import json
import os

import pytest
from click.testing import CliRunner

from marketpulse.cli import main, reports
from marketpulse.cli.base import App
from marketpulse.models import Account, AccountType, Transaction, TxnType

# The dashed filter names --having accepts, in the order the specification lists them.
HAVING_FILTERS = (
    "ieq ine not-contains not-prefix not-suffix gt ge lt le between outside in not-in empty nonempty is-type "
    "length min-length max-length glob regex not-regex iglob not-glob contains-any contains-all date-from date-to "
    "has-item has-key"
).split()
UNKNOWN_FILTER = f"--having requires FILTER:NAME=VALUE with a filter from: {', '.join(HAVING_FILTERS)}."


def printed(result):
    """Printed text as the report wrote it: a Windows text stream turns each \\n into os.linesep."""
    text = result.stdout_bytes.decode("utf-8")
    return text.replace(os.linesep, "\n") if os.linesep != "\n" else text


def invoke(*arguments):
    return CliRunner().invoke(main, ["summarize", *arguments])


def typed(value):
    """JSON text, which keeps true apart from 1, 1 apart from 1.0 and "10" apart from 10."""
    return json.dumps(value, ensure_ascii=False)


def output(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def column(result, name):
    return [row[name] for row in output(result)]


def error(result):
    """The usage error Click prints after "Error: " for a query rejected with exit code 2."""
    assert result.exit_code == 2, result.output
    return result.output.rsplit("Error: ", 1)[1].rstrip("\n")


@pytest.fixture
def serve(monkeypatch):
    """Serve a copy of fixed rows as the saved source and return that copy."""

    def serve(rows):
        served = copy.deepcopy(rows)
        monkeypatch.setattr(reports, "load_source", lambda *args: served)
        return served

    return serve


@pytest.fixture
def unloaded(monkeypatch):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("an invalid query loaded the source"))


# Recorded deposits and withdrawals, in ledger order. Groups by account: TFSA 4 rows, net 4249.75;
# USD Margin 2 rows, net 1800; RRSP 3 rows, net 4250.5; all nine rows net 10300.25.
FLOW_FIELDS = ("date", "account_id", "account", "amount", "currency")
FLOWS = [
    dict(zip(FLOW_FIELDS, values, strict=True))
    for values in (
        ("2023-11-30", 1, "Fictional TFSA", 750.0, "CAD"),
        ("2023-12-27", 3, "Fictional USD Margin", 1000.0, "USD"),
        ("2024-01-02", 1, "Fictional TFSA", 5000.0, "CAD"),
        ("2024-01-15", 2, "Fictional RRSP", 2500.5, "CAD"),
        ("2024-02-01", 1, "Fictional TFSA", -1200.0, "CAD"),
        ("2024-02-29", 3, "Fictional USD Margin", 800.0, "USD"),
        ("2024-03-04", 2, "Fictional RRSP", 1500.0, "CAD"),
        ("2024-03-28", 1, "Fictional TFSA", -300.25, "CAD"),
        ("2024-04-30", 2, "Fictional RRSP", 250.0, "CAD"),
    )
]


# ---------------------------------------------------------------------------------------------
# --having: numeric filters read decimal-string metric results as numbers.

# Group sums 10, 9, 20 and 18; means 5, 9, 10 and 9; population deviations 1, 0, 10 and 9. All are
# decimal strings, and as text "10" sorts before "9", so only a numeric reading gives these results.
SPREAD = [
    {"key": "x", "value": "4"},
    {"key": "y", "value": 9},
    {"key": "z", "value": 0},
    {"key": "x", "value": 6},
    {"key": "w", "value": "0"},
    {"key": "z", "value": "20"},
    {"key": "w", "value": 18.0},
]
SPREAD_QUERY = (
    "config",
    "--group-by",
    "key",
    "--metric",
    "n=count",
    "--metric",
    "total=number-sum:value",
    "--metric",
    "mean=number-mean:value",
    "--metric",
    "spread=number-stdev:value",
)
SPREAD_ROWS = {
    "x": {"key": "x", "n": 2, "total": "10", "mean": "5", "spread": "1"},
    "y": {"key": "y", "n": 1, "total": "9", "mean": "9", "spread": "0"},
    "z": {"key": "z", "n": 2, "total": "20", "mean": "10", "spread": "10"},
    "w": {"key": "w", "n": 2, "total": "18", "mean": "9", "spread": "9"},
}


def test_spread_groups_before_having(serve):
    served = serve(SPREAD)
    before = typed(served)
    assert typed(output(invoke(*SPREAD_QUERY))) == typed(list(SPREAD_ROWS.values()))
    assert typed(served) == before


@pytest.mark.parametrize(
    ("condition", "kept"),
    [
        ("gt:total=9.5", "xzw"),
        ("le:total=10", "xy"),
        ("ge:mean=9", "yzw"),
        ("lt:mean=9", "x"),
        ("gt:spread=8.5", "zw"),
        ("lt:spread=1", "y"),
        ("le:spread=1", "xy"),
        ("between:total=9,18", "xyw"),
        ("outside:total=9,18", "z"),
        ("between:mean=9,9", "yw"),
        ("gt:n=1", "xzw"),
        ("lt:n=2", "y"),
    ],
)
def test_having_reads_decimal_string_results_as_numbers(serve, condition, kept):
    serve(SPREAD)
    result = invoke(*SPREAD_QUERY, "--having", condition)
    assert typed(output(result)) == typed([SPREAD_ROWS[key] for key in kept])


def test_having_compares_scientific_notation_results_as_numbers(serve):
    # 6e20 + 4e20 is written "1E+21": larger than 21 nines, although it sorts before them as text.
    nines = "9" * 21
    serve([{"key": "big", "value": "6e20"}, {"key": "big", "value": "4e20"}, {"key": "nines", "value": nines}])
    query = ("config", "--group-by", "key", "--metric", "total=number-sum:value")
    assert output(invoke(*query)) == [{"key": "big", "total": "1E+21"}, {"key": "nines", "total": nines}]
    assert output(invoke(*query, "--having", f"gt:total={nines}")) == [{"key": "big", "total": "1E+21"}]
    assert output(invoke(*query, "--having", "lt:total=1e21")) == [{"key": "nines", "total": nines}]


def test_having_compares_decimal_strings_exactly(serve):
    # The variance of 1, 2 and 4 is 14/9, which 28 significant digits write as 1.555...556 (26 fives).
    # Read as floats, the bounds below would equal it; read exactly, it lies on one side of each.
    variance = "1." + "5" * 26 + "6"
    serve([{"key": "a", "value": 1}, {"key": "a", "value": 2}, {"key": "a", "value": 4}, {"key": "b", "value": 3}])
    query = ("config", "--group-by", "key", "--metric", "var=number-variance:value")
    assert output(invoke(*query)) == [{"key": "a", "var": variance}, {"key": "b", "var": "0"}]
    assert column(invoke(*query, "--having", "gt:var=1." + "5" * 28), "key") == ["a"]
    assert column(invoke(*query, "--having", "ge:var=1." + "5" * 26 + "61"), "key") == []
    assert column(invoke(*query, "--having", f"le:var={variance}0"), "key") == ["a", "b"]
    assert column(invoke(*query, "--having", f"lt:var={variance}"), "key") == ["b"]


def test_having_membership_on_decimal_string_results_stays_typed(serve):
    # in and not-in are typed membership tests, not numeric filters: the result "10" is a string.
    serve(SPREAD)
    assert column(invoke(*SPREAD_QUERY, "--having", 'in:total=["10", "20"]'), "key") == ["x", "z"]
    assert column(invoke(*SPREAD_QUERY, "--having", "in:total=[10, 20]"), "key") == []
    assert column(invoke(*SPREAD_QUERY, "--having", "not-in:total=[10, 20]"), "key") == ["x", "y", "z", "w"]
    assert column(invoke(*SPREAD_QUERY, "--having", "in:n=[2]"), "key") == ["x", "z", "w"]
    assert column(invoke(*SPREAD_QUERY, "--having", 'in:n=["2"]'), "key") == []


# ---------------------------------------------------------------------------------------------
# --having: text, typed and structural filters on grouping columns and metrics.

NAMES = [
    {"key": "Fictional TFSA", "value": 1},
    {"key": "Fictional RRSP", "value": 2},
    {"key": "fictional cash", "value": 3},
    {"key": "Other Fund", "value": 4},
    {"key": "Fictional TFSA", "value": 5},
]
NAMES_QUERY = ("config", "--group-by", "key", "--metric", "n=count")


@pytest.mark.parametrize(
    ("condition", "kept"),
    [
        ("ieq:key=FICTIONAL tfsa", ["Fictional TFSA"]),
        ("glob:key=Fictional *", ["Fictional TFSA", "Fictional RRSP"]),
        ("glob:key=*[Cc]ash", ["fictional cash"]),
        ("iglob:key=FICTIONAL *", ["Fictional TFSA", "Fictional RRSP", "fictional cash"]),
        ("iglob:key=other?fund", ["Other Fund"]),
        ("regex:key=SP", ["Fictional RRSP"]),
        ("regex:key=(?i)^fictional (tfsa|cash)$", ["Fictional TFSA", "fictional cash"]),
        ('contains-any:key=["CASH", "fund"]', ["fictional cash", "Other Fund"]),
        ("contains-any:key=[]", []),
        ('contains-all:key=["FICTIONAL", "r"]', ["Fictional RRSP"]),
        ("contains-all:key=[]", ["Fictional TFSA", "Fictional RRSP", "fictional cash", "Other Fund"]),
        ("not-regex:key=^F", ["fictional cash", "Other Fund"]),
        ("not-glob:key=Fictional *", ["fictional cash", "Other Fund"]),
        # Text filters read a metric's report text too.
        ("glob:n=2", ["Fictional TFSA"]),
        ("regex:n=^1$", ["Fictional RRSP", "fictional cash", "Other Fund"]),
    ],
)
def test_having_text_filters(serve, condition, kept):
    serve(NAMES)
    assert column(invoke(*NAMES_QUERY, "--having", condition), "key") == kept


# One group per typed value: 1 and 1.0 share a group (shown as 1), while "1", true, 0 and false stay apart.
TYPED = [
    {"key": 1, "value": "a"},
    {"key": "1", "value": "b"},
    {"key": True, "value": "c"},
    {"key": 1.0, "value": "d"},
    {"key": None, "value": "e"},
    {"key": "", "value": "f"},
    {"key": [1], "value": "g"},
    {"key": {}, "value": "h"},
    {"key": 0, "value": "i"},
    {"key": False, "value": "j"},
]


@pytest.mark.parametrize(
    ("condition", "kept"),
    [
        ("in:key=[1]", [1]),
        ("in:key=[1.0]", [1]),
        ('in:key=["1"]', ["1"]),
        ("in:key=[true]", [True]),
        ("in:key=[0]", [0]),
        ("in:key=[false]", [False]),
        ('in:key=[null, ""]', [None, ""]),
        ("in:key=[[1]]", [[1]]),
        ("in:key=[{}]", [{}]),
        ("in:key=[]", []),
        ("not-in:key=[1, true, null, {}]", ["1", "", [1], 0, False]),
        ("not-in:key=[]", [1, "1", True, None, "", [1], {}, 0, False]),
        ("is-type:key=number", [1, 0]),
        ("is-type:key=string", ["1", ""]),
        ("is-type:key=boolean", [True, False]),
        ("is-type:key=null", [None]),
        ("is-type:key=array", [[1]]),
        ("is-type:key=object", [{}]),
        ("empty:key", [None, "", {}]),
        ("nonempty:key", [1, "1", True, [1], 0, False]),
        # Text filters read the report text: true is "true", null is "", 1 and "1" are both "1".
        ("ieq:key=TRUE", [True]),
        ("ieq:key=", [None, ""]),
        ("glob:key=1*", [1, "1"]),
        ("regex:key=^[\\[{]", [[1], {}]),
        ("in:n=[2]", [1]),
        ('in:n=["2"]', []),
    ],
)
def test_having_typed_membership_type_and_emptiness(serve, condition, kept):
    serve(TYPED)
    result = invoke("config", "--group-by", "key", "--metric", "n=count", "--having", condition)
    assert typed(column(result, "key")) == typed(kept)


def issue(txn_id, date, code, details, message="Fictional ledger issue"):
    # Rows in the shape of the `ledger-issues` source; only the fields the queries name matter.
    return {
        "transaction_id": txn_id,
        "date": date,
        "account_id": None,
        "account": None,
        "code": code,
        "message": message,
        "details": details,
    }


ISSUES = [
    issue(4, "2024-03-01", "sell_exceeds_held", {"symbol": "FIC.TO", "quantity": 5.0, "held": 2.0}),
    issue(6, "2024-02-20", "transfer_nothing_held", {"symbol": "FICB.V"}),
    issue(9, "2024-06-14", "split_nothing_held", {"symbol": "FIC.TO"}),
    issue(12, "2024-07-02", "sell_exceeds_held", {"symbol": "FIC.TO", "quantity": 1.0, "held": 0.0}),
    issue(None, "", "hidden_account_issue", {}, "Issue in a hidden account."),
    issue(15, "2024-08-30", "sell_exceeds_held", {"symbol": "FICB.V", "quantity": 2.0, "held": 0.0}),
]
ISSUE_QUERY = ("ledger-issues", "--group-by", "code", "--metric", "rows=count")
ISSUE_SUMMARY = (
    *ISSUE_QUERY,
    "--metric",
    "ids=values:transaction_id",
    "--metric",
    "latest=date-max:date",
    "--metric",
    "detail=first:details",
)
# The four summary rows by letter: Sell, Transfer, sPlit and Hidden, in first-encountered order.
ISSUE_ROWS = {
    "S": {
        "code": "sell_exceeds_held",
        "rows": 3,
        "ids": [4, 12, 15],
        "latest": "2024-08-30",
        "detail": {"symbol": "FIC.TO", "quantity": 5.0, "held": 2.0},
    },
    "T": {
        "code": "transfer_nothing_held",
        "rows": 1,
        "ids": [6],
        "latest": "2024-02-20",
        "detail": {"symbol": "FICB.V"},
    },
    "P": {"code": "split_nothing_held", "rows": 1, "ids": [9], "latest": "2024-06-14", "detail": {"symbol": "FIC.TO"}},
    "H": {"code": "hidden_account_issue", "rows": 1, "ids": [None], "latest": None, "detail": {}},
}
# Each of the thirty filters as a --having condition, on a grouping column or on a metric.
EVERY_FILTER = [
    ("ieq", "code=SPLIT_NOTHING_HELD", "P"),
    ("ine", "code=Hidden_Account_Issue", "STP"),
    ("not-contains", "code=NOTHING", "SH"),
    ("not-prefix", "code=S", "TH"),
    ("not-suffix", "code=_HELD", "H"),
    ("gt", "rows=1", "S"),
    ("ge", "rows=1", "STPH"),
    ("lt", "rows=3", "TPH"),
    ("le", "rows=1", "TPH"),
    ("between", "rows=2,3", "S"),
    ("outside", "rows=2,3", "TPH"),
    ("in", 'code=["split_nothing_held", "hidden_account_issue"]', "PH"),
    ("not-in", "rows=[1]", "S"),
    ("empty", "detail", "H"),
    ("nonempty", "latest", "STP"),
    ("is-type", "latest=null", "H"),
    ("length", "ids=1", "TPH"),
    ("min-length", "ids=2", "S"),
    ("max-length", "code=18", "SP"),
    ("glob", "code=*_nothing_held", "TP"),
    ("regex", "code=^s", "SP"),
    ("not-regex", "code=held$", "H"),
    ("iglob", "code=*NOTHING*", "TP"),
    ("not-glob", "code=s*", "TH"),
    ("contains-any", 'code=["SPLIT", "hidden"]', "PH"),
    ("contains-all", 'code=["nothing", "TRANS"]', "T"),
    ("date-from", "latest=2024-06-14", "SP"),
    ("date-to", "latest=2024-06-14", "TP"),
    ("has-item", "ids=12", "S"),
    ("has-key", "detail=held", "S"),
]


def test_issue_summary_before_having(serve):
    serve(ISSUES)
    assert typed(output(invoke(*ISSUE_SUMMARY))) == typed(list(ISSUE_ROWS.values()))


def test_every_filter_name_is_covered():
    assert [name for name, _, _ in EVERY_FILTER] == HAVING_FILTERS
    assert len(HAVING_FILTERS) == 30


@pytest.mark.parametrize(("name", "condition", "kept"), EVERY_FILTER, ids=[case[0] for case in EVERY_FILTER])
def test_every_row_filter_works_as_a_having_condition(serve, name, condition, kept):
    serve(ISSUES)
    result = invoke(*ISSUE_SUMMARY, "--having", f"{name}:{condition}")
    assert typed(output(result)) == typed([ISSUE_ROWS[letter] for letter in kept])


@pytest.mark.parametrize(
    ("condition", "kept"),
    [
        ("has-item:ids=12.0", ["sell_exceeds_held"]),
        ('has-item:ids="12"', []),
        ("has-item:ids=null", ["hidden_account_issue"]),
        ("has-item:ids=[12]", []),
        ("length:ids=3", ["sell_exceeds_held"]),
        ("max-length:ids=0", []),
        ("date-from:latest=2024-08-30", ["sell_exceeds_held"]),
        ("date-to:latest=2024-02-19", []),
        # Arrays and objects are matched by canonical JSON text, with object keys sorted.
        ("ieq:ids=[4, 12, 15]", ["sell_exceeds_held"]),
        ("ieq:ids=[null]", ["hidden_account_issue"]),
        ('glob:detail={"held": 2.0, *', ["sell_exceeds_held"]),
    ],
)
def test_having_on_array_and_date_metrics(serve, condition, kept):
    serve(ISSUES)
    assert column(invoke(*ISSUE_SUMMARY, "--having", condition), "code") == kept


def test_having_on_value_counts_pairs(serve):
    # CAD flows: the TFSA four times and the RRSP three times; USD flows: the margin account twice.
    serve(FLOWS)
    query = ("cash-flows", "--group-by", "currency", "--metric", "counts=value-counts:account")
    assert output(invoke(*query)) == [
        {"currency": "CAD", "counts": [["Fictional TFSA", 4], ["Fictional RRSP", 3]]},
        {"currency": "USD", "counts": [["Fictional USD Margin", 2]]},
    ]
    assert column(invoke(*query, "--having", 'has-item:counts=["Fictional TFSA", 4]'), "currency") == ["CAD"]
    assert column(invoke(*query, "--having", 'has-item:counts=["Fictional TFSA", "4"]'), "currency") == []
    assert column(invoke(*query, "--having", "length:counts=1"), "currency") == ["USD"]


# ---------------------------------------------------------------------------------------------
# --having: which column, repetition, and its place before sorting and pagination.


def test_having_on_a_grouping_column_versus_a_metric_and_repetition_is_and(serve):
    serve(FLOWS)
    query = ("cash-flows", "--group-by", "account_id", "--metric", "net=number-sum:amount")
    assert output(invoke(*query)) == [
        {"account_id": 1, "net": "4249.75"},
        {"account_id": 3, "net": "1800"},
        {"account_id": 2, "net": "4250.5"},
    ]
    assert column(invoke(*query, "--having", "gt:account_id=1"), "account_id") == [3, 2]
    assert column(invoke(*query, "--having", "gt:net=2000"), "account_id") == [1, 2]
    assert column(invoke(*query, "--having", "gt:account_id=1", "--having", "gt:net=2000"), "account_id") == [2]
    assert column(invoke(*query, "--having", "gt:net=2000", "--having", "gt:account_id=1"), "account_id") == [2]


def test_having_that_removes_every_group(serve):
    serve(NAMES)
    query = (*NAMES_QUERY, "--having", "gt:n=2")
    assert output(invoke(*query)) == []
    assert output(invoke(*query, "--page-info")) == {
        "source": "config",
        "total": 0,
        "offset": 0,
        "limit": None,
        "rows": [],
    }
    result = invoke(*query, "--format", "csv")
    assert result.exit_code == 0, result.output
    assert list(csv.reader(io.StringIO(printed(result), newline=""))) == [["key", "n"]]
    # The closing row still counts all five rows.
    assert output(invoke(*query, "--totals")) == [{"key": None, "n": 5}]


def test_having_splits_at_the_first_colon_and_the_first_equals_sign(serve):
    serve([{"key": "a:b", "value": 1}, {"key": "c", "value": 2}, {"key": "a=b", "value": 3}])
    query = ("config", "--group-by", "key", "--metric", "n=count")
    assert column(invoke(*query, "--having", "regex:key=^[^:]+$"), "key") == ["c", "a=b"]
    assert column(invoke(*query, "--having", "ieq:key=A:B"), "key") == ["a:b"]
    assert column(invoke(*query, "--having", "ieq:key=A=B"), "key") == ["a=b"]
    assert column(invoke(*query, "--having", "glob:key=*=*"), "key") == ["a=b"]


def test_having_runs_before_sort_and_pagination_and_sets_the_page_total(serve):
    serve(SPREAD)
    # z (deviation "10") fails lt 9.5; the totals 18, 10 and 9 then sort numerically.
    kept = (*SPREAD_QUERY, "--having", "lt:spread=9.5", "--sort", "total")
    assert column(invoke(*kept), "key") == ["y", "x", "w"]
    assert column(invoke(*kept, "--descending"), "key") == ["w", "x", "y"]
    assert output(invoke(*kept, "--descending", "--offset", "1", "--limit", "1", "--page-info")) == {
        "source": "config",
        "total": 3,
        "offset": 1,
        "limit": 1,
        "rows": [SPREAD_ROWS["x"]],
    }
    assert output(invoke(*kept, "--offset", "2", "--page-info")) == {
        "source": "config",
        "total": 3,
        "offset": 2,
        "limit": None,
        "rows": [SPREAD_ROWS["w"]],
    }
    assert output(invoke(*kept, "--offset", "3", "--page-info")) == {
        "source": "config",
        "total": 3,
        "offset": 3,
        "limit": None,
        "rows": [],
    }


def test_having_without_group_by_filters_the_single_summary_row(serve):
    # The specification does not require --group-by for --having; the one ungrouped row is filtered.
    serve(FLOWS)
    assert output(invoke("cash-flows", "--metric", "rows=count", "--having", "gt:rows=8")) == [{"rows": 9}]
    assert output(invoke("cash-flows", "--metric", "rows=count", "--having", "gt:rows=9", "--page-info")) == {
        "source": "cash-flows",
        "total": 0,
        "offset": 0,
        "limit": None,
        "rows": [],
    }


# ---------------------------------------------------------------------------------------------
# --having validation: usage errors (exit code 2) before the source is loaded.


@pytest.mark.parametrize(
    "condition",
    [
        "gt",
        "rows=1",
        "",
        ":rows=1",
        "bigger:rows=1",
        "GT:rows=1",
        # Underscore spellings and option names that are not dashed filter names.
        "not_contains:code=x",
        "min_length:code=2",
        "in_values:rows=[1]",
        "in-values:rows=[1]",
        # Older report options that are not FIELD=VALUE row filters.
        "where:code=x",
        "not:code=x",
        "contains:code=x",
        "prefix:code=x",
        "suffix:code=x",
        "present:code",
        "missing:code",
        "unique:code",
    ],
)
def test_having_rejects_a_missing_colon_or_an_unknown_filter(unloaded, condition):
    assert error(invoke(*ISSUE_QUERY, "--having", condition)) == UNKNOWN_FILTER


# Conditions each filter rejects: bad numbers, bad JSON, bad regular expressions, bad dates and others.
BAD_CONDITIONS = [
    ("gt", "many"),
    ("ge", "NaN"),
    ("le", "Infinity"),
    ("between", "1"),
    ("outside", "3,1"),
    ("in", "[x"),
    ("not-in", '"x"'),
    ("has-item", "["),
    ("has-item", "NaN"),
    ("contains-any", '["a", 1]'),
    ("contains-all", "x"),
    ("regex", "("),
    ("not-regex", "[a-"),
    ("date-from", "2024-02-30"),
    ("date-to", "2024-3-5"),
    ("is-type", "date"),
    ("length", "-1"),
    ("max-length", "two"),
]


@pytest.mark.parametrize(("name", "text"), BAD_CONDITIONS)
def test_bad_having_condition_quotes_it_with_the_filters_own_message(unloaded, name, text):
    condition = f"{name}:code={text}"
    message = error(invoke(*ISSUE_QUERY, "--having", condition))
    # The filter's own message is the one the same condition gives as a row filter on `code`.
    own = error(invoke("ledger-issues", "--metric", "rows=count", f"--{name}", f"code={text}"))
    assert message == f"--having {condition}: {own}"


@pytest.mark.parametrize("name", ["gt", "between", "in", "not-in", "regex", "date-to", "has-item", "has-key"])
def test_having_condition_without_a_value(unloaded, name):
    message = error(invoke(*ISSUE_QUERY, "--having", f"{name}:code"))
    own = error(invoke("ledger-issues", "--metric", "rows=count", f"--{name}", "code"))
    assert message == f"--having {name}:code: {own}"


@pytest.mark.parametrize(
    ("arguments", "condition", "name"),
    [
        # A source field that is neither grouped nor a metric.
        ((), "gt:transaction_id=1", "transaction_id"),
        ((), "regex:message=Sell", "message"),
        # A derived column that is not grouped.
        (("--derive", "day=date:date"), "is-type:day=null", "day"),
        # empty and nonempty take just FILTER:NAME.
        ((), "empty:rows=1", "rows=1"),
        ((), "nonempty:", ""),
    ],
)
def test_having_names_a_grouping_column_or_a_metric(unloaded, arguments, condition, name):
    message = error(invoke(*ISSUE_QUERY, *arguments, "--having", condition))
    assert message.startswith(f"--having {condition}: ")
    assert f"'{name}'" in message


# ---------------------------------------------------------------------------------------------
# --totals.

FLOW_QUERY = ("cash-flows", "--group-by", "account", "--metric", "rows=count", "--metric", "net=number-sum:amount")
TFSA = {"account": "Fictional TFSA", "rows": 4, "net": "4249.75"}
MARGIN = {"account": "Fictional USD Margin", "rows": 2, "net": "1800"}
RRSP = {"account": "Fictional RRSP", "rows": 3, "net": "4250.5"}
ALL_FLOWS = {"account": None, "rows": 9, "net": "10300.25"}


def test_totals_row_follows_the_groups(serve):
    served = serve(FLOWS)
    before = typed(served)
    assert typed(output(invoke(*FLOW_QUERY, "--totals"))) == typed([TFSA, MARGIN, RRSP, ALL_FLOWS])
    assert typed(served) == before


def test_totals_stay_last_after_sorting_and_pagination_and_outside_the_page_total(serve):
    serve(FLOWS)
    ordered = (*FLOW_QUERY, "--sort", "net", "--descending", "--totals")
    assert typed(output(invoke(*ordered))) == typed([RRSP, TFSA, MARGIN, ALL_FLOWS])
    assert typed(output(invoke(*ordered, "--offset", "1", "--limit", "1", "--page-info"))) == typed(
        {"source": "cash-flows", "total": 3, "offset": 1, "limit": 1, "rows": [TFSA, ALL_FLOWS]}
    )
    assert typed(output(invoke(*ordered, "--limit", "2"))) == typed([RRSP, TFSA, ALL_FLOWS])
    # Past the last group only the closing row is left.
    assert typed(output(invoke(*ordered, "--offset", "3", "--page-info"))) == typed(
        {"source": "cash-flows", "total": 3, "offset": 3, "limit": None, "rows": [ALL_FLOWS]}
    )


def test_totals_cover_groups_removed_by_having_and_pagination(serve):
    serve(FLOWS)
    # TFSA (4 rows) fails --having. The closing row (9 rows) would fail it too, but it is never filtered.
    having = (*FLOW_QUERY, "--having", "lt:rows=4", "--totals")
    assert typed(output(invoke(*having))) == typed([MARGIN, RRSP, ALL_FLOWS])
    assert typed(output(invoke(*having, "--sort", "rows", "--limit", "1", "--page-info"))) == typed(
        {"source": "cash-flows", "total": 2, "offset": 0, "limit": 1, "rows": [MARGIN, ALL_FLOWS]}
    )
    nothing = (*FLOW_QUERY, "--having", "gt:rows=9", "--totals", "--page-info")
    assert typed(output(invoke(*nothing))) == typed(
        {"source": "cash-flows", "total": 0, "offset": 0, "limit": None, "rows": [ALL_FLOWS]}
    )


def test_totals_follow_a_real_group_whose_grouping_value_is_null(serve):
    # A group can hold null itself; it sorts last among the groups and the closing row still follows it.
    serve(TYPED)
    query = ("config", "--group-by", "key", "--metric", "n=count", "--metric", "letters=values:value")
    everything = {"key": None, "n": 10, "letters": list("abcdefghij")}
    result = invoke(*query, "--having", 'in:key=[null, "1"]', "--sort", "key", "--descending", "--totals")
    assert typed(output(result)) == typed(
        [{"key": "1", "n": 1, "letters": ["b"]}, {"key": None, "n": 1, "letters": ["e"]}, everything]
    )


# CAD rows only: TFSA 750, 5000, -1200 and -300.25; RRSP 2500.5, 1500 and 250.
CAD_METRICS = (
    "--where",
    "currency=CAD",
    "--metric",
    "rows=count",
    "--metric",
    "net=number-sum:amount",
    "--metric",
    "low=number-min:amount",
    "--metric",
    "high=number-max:amount",
    "--metric",
    "q1=number-q1:amount",
    "--metric",
    "q3=number-q3:amount",
    "--metric",
    "first=first:account",
    "--metric",
    "last=last:date",
    "--metric",
    "earliest=date-min:date",
    "--metric",
    "latest=date-max:date",
    "--metric",
    "span=date-span:date",
    "--metric",
    "accounts=distinct-values:account",
    "--metric",
    "counts=value-counts:account_id",
    "--metric",
    "repeated=repeated-values:account",
)
CAD_TFSA = {
    "account": "Fictional TFSA",
    "rows": 4,
    "net": "4249.75",
    "low": "-1200",
    "high": "5000",
    "q1": "-525.1875",
    "q3": "1812.5",
    "first": "Fictional TFSA",
    "last": "2024-03-28",
    "earliest": "2023-11-30",
    "latest": "2024-03-28",
    "span": 119,
    "accounts": ["Fictional TFSA"],
    "counts": [[1, 4]],
    "repeated": ["Fictional TFSA"],
}
CAD_RRSP = {
    "account": "Fictional RRSP",
    "rows": 3,
    "net": "4250.5",
    "low": "250",
    "high": "2500.5",
    "q1": "875",
    "q3": "2000.25",
    "first": "Fictional RRSP",
    "last": "2024-04-30",
    "earliest": "2024-01-15",
    "latest": "2024-04-30",
    "span": 106,
    "accounts": ["Fictional RRSP"],
    "counts": [[2, 3]],
    "repeated": ["Fictional RRSP"],
}
CAD_ALL = {
    "rows": 7,
    "net": "8500.25",
    "low": "-1200",
    "high": "5000",
    "q1": "-25.125",
    "q3": "2000.25",
    "first": "Fictional TFSA",
    "last": "2024-04-30",
    "earliest": "2023-11-30",
    "latest": "2024-04-30",
    "span": 152,
    "accounts": ["Fictional TFSA", "Fictional RRSP"],
    "counts": [[1, 4], [2, 3]],
    "repeated": ["Fictional TFSA", "Fictional RRSP"],
}


def test_totals_equal_the_ungrouped_summary_of_the_filtered_rows(serve):
    serve(FLOWS)
    ungrouped = output(invoke("cash-flows", *CAD_METRICS))
    assert typed(ungrouped) == typed([CAD_ALL])
    grouped = output(invoke("cash-flows", "--group-by", "account", *CAD_METRICS, "--totals"))
    assert typed(grouped) == typed([CAD_TFSA, CAD_RRSP, {"account": None, **CAD_ALL}])
    # The closing row is the ungrouped summary of the same filtered rows, with a null grouping column.
    assert typed(grouped[-1]) == typed({"account": None, **ungrouped[0]})


def test_totals_with_several_grouping_fields_and_metrics(serve):
    serve(FLOWS)
    result = invoke(
        "cash-flows",
        "--group-by",
        "currency",
        "--group-by",
        "account",
        "--metric",
        "rows=count",
        "--metric",
        "net=number-sum:amount",
        "--metric",
        "latest=date-max:date",
        "--metric",
        "ids=distinct-values:account_id",
        "--totals",
    )
    tfsa = {"currency": "CAD", "account": "Fictional TFSA", "rows": 4, "net": "4249.75", "latest": "2024-03-28"}
    margin = {"currency": "USD", "account": "Fictional USD Margin", "rows": 2, "net": "1800", "latest": "2024-02-29"}
    rrsp = {"currency": "CAD", "account": "Fictional RRSP", "rows": 3, "net": "4250.5", "latest": "2024-04-30"}
    everything = {"currency": None, "account": None, "rows": 9, "net": "10300.25", "latest": "2024-04-30"}
    assert typed(output(result)) == typed(
        [{**tfsa, "ids": [1]}, {**margin, "ids": [3]}, {**rrsp, "ids": [2]}, {**everything, "ids": [1, 3, 2]}]
    )


EMPTY_METRICS = (
    "--metric",
    "rows=count",
    "--metric",
    "net=number-sum:amount",
    "--metric",
    "mean=number-mean:amount",
    "--metric",
    "spread=number-stdev:amount",
    "--metric",
    "dates=date-count:date",
    "--metric",
    "span=date-span:date",
    "--metric",
    "first=first:account",
    "--metric",
    "names=values:account",
    "--metric",
    "counts=value-counts:account",
    "--metric",
    "repeated=repeated-values:account",
)
EMPTY_TOTALS = {
    "account": None,
    "rows": 0,
    "net": "0",
    "mean": None,
    "spread": None,
    "dates": 0,
    "span": None,
    "first": None,
    "names": [],
    "counts": [],
    "repeated": [],
}


@pytest.mark.parametrize(("rows", "filters"), [([], ()), (FLOWS, ("--where", "currency=EUR"))], ids=["empty", "none"])
def test_totals_without_rows_hold_empty_input_results(serve, rows, filters):
    serve(rows)
    query = ("cash-flows", *filters, "--group-by", "account", *EMPTY_METRICS, "--totals")
    assert typed(output(invoke(*query))) == typed([EMPTY_TOTALS])
    assert typed(output(invoke(*query, "--page-info"))) == typed(
        {"source": "cash-flows", "total": 0, "offset": 0, "limit": None, "rows": [EMPTY_TOTALS]}
    )


FORMAT_ROWS = [
    {"key": "Fictional TFSA", "value": "12.5"},
    {"key": "Fictional RRSP", "value": 100},
    {"key": "Fictional TFSA", "value": 7},
]
FORMAT_QUERY = (
    "config",
    "--group-by",
    "key",
    "--metric",
    "rows=count",
    "--metric",
    "total=number-sum:value",
    "--totals",
)
FORMAT_JSON = [
    {"key": "Fictional TFSA", "rows": 2, "total": "19.5"},
    {"key": "Fictional RRSP", "rows": 1, "total": "100"},
    {"key": None, "rows": 3, "total": "119.5"},
]
# Report text of every cell, header first: null is empty, numbers are their JSON text.
FORMAT_CELLS = [
    ["key", "rows", "total"],
    ["Fictional TFSA", "2", "19.5"],
    ["Fictional RRSP", "1", "100"],
    ["", "3", "119.5"],
]
# The formats #143 specifies exactly. In text only the counts are JSON numbers, so only they align right.
EXACT_FORMATS = {
    "html": (
        "<table>\n<thead>\n<tr><th>key</th><th>rows</th><th>total</th></tr>\n</thead>\n<tbody>\n"
        "<tr><td>Fictional TFSA</td><td>2</td><td>19.5</td></tr>\n"
        "<tr><td>Fictional RRSP</td><td>1</td><td>100</td></tr>\n"
        "<tr><td></td><td>3</td><td>119.5</td></tr>\n"
        "</tbody>\n</table>\n"
    ),
    "text": (
        "key             rows  total\n"
        "--------------  ----  -----\n"
        "Fictional TFSA     2  19.5\n"
        "Fictional RRSP     1  100\n"
        "                   3  119.5\n"
    ),
    "records": (
        "key: Fictional TFSA\nrows: 2\ntotal: 19.5\n"
        "\n"
        "key: Fictional RRSP\nrows: 1\ntotal: 100\n"
        "\n"
        "key:\nrows: 3\ntotal: 119.5\n"
    ),
    "json-columns": (
        '{"key": ["Fictional TFSA", "Fictional RRSP", null], "rows": [2, 1, 3], "total": ["19.5", "100", "119.5"]}\n'
    ),
}


@pytest.mark.parametrize(
    "output_format", ["json", "jsonl", "csv", "tsv", "markdown", "html", "text", "records", "json-columns"]
)
def test_totals_in_every_output_format(serve, output_format):
    serve(FORMAT_ROWS)
    result = invoke(*FORMAT_QUERY, "--format", output_format)
    assert result.exit_code == 0, result.output
    text = printed(result)
    if output_format == "json":
        assert typed(json.loads(text)) == typed(FORMAT_JSON)
    elif output_format == "jsonl":
        assert text.endswith("\n")
        assert typed([json.loads(line) for line in text.splitlines()]) == typed(FORMAT_JSON)
    elif output_format in ("csv", "tsv"):
        delimiter = "," if output_format == "csv" else "\t"
        assert list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)) == FORMAT_CELLS
    elif output_format == "markdown":
        lines = text.splitlines()
        assert lines[1] == "| --- | --- | --- |"
        cells = [[cell.strip() for cell in line.strip("|").split("|")] for line in [lines[0], *lines[2:]]]
        assert cells == FORMAT_CELLS
    else:
        assert text == EXACT_FORMATS[output_format]


def test_totals_leave_too_many_columns_for_the_lines_format(unloaded):
    assert error(invoke(*FORMAT_QUERY, "--format", "lines")) == "--format lines requires exactly one output column."


@pytest.mark.parametrize("extra", [(), ("--having", "gt:rows=0"), ("--sort", "rows"), ("--page-info",)])
def test_totals_require_group_by(unloaded, extra):
    assert error(invoke("cash-flows", "--metric", "rows=count", "--totals", *extra)) == "--totals requires --group-by."


# ---------------------------------------------------------------------------------------------
# --derive in summarize.

# Weekdays of the 2024 flows: Jan 2 Tue, Jan 15 Mon, Feb 1 Thu, Feb 29 Thu, Mar 4 Mon, Mar 28 Thu, Apr 30 Tue.
MONTHS = (
    "cash-flows",
    "--derive",
    "month=year-month:date",
    "--derive",
    "weekday=weekday-name:date",
    "--regex",
    "month=^2024-",
    "--group-by",
    "month",
    "--metric",
    "rows=count",
    "--metric",
    "days=distinct-values:weekday",
    "--metric",
    "net=number-sum:amount",
    "--sort",
    "month",
    "--descending",
    "--totals",
)
JANUARY = {"month": "2024-01", "rows": 2, "days": ["Tuesday", "Monday"], "net": "7500.5"}
FEBRUARY = {"month": "2024-02", "rows": 2, "days": ["Thursday"], "net": "-400"}
MARCH = {"month": "2024-03", "rows": 2, "days": ["Monday", "Thursday"], "net": "1199.75"}
APRIL = {"month": "2024-04", "rows": 1, "days": ["Tuesday"], "net": "250"}
IN_2024 = {"month": None, "rows": 7, "days": ["Tuesday", "Monday", "Thursday"], "net": "8550.25"}


def test_derived_groups_with_a_derived_filter_metric_having_sort_and_totals(serve):
    served = serve(FLOWS)
    before = typed(served)
    assert typed(output(invoke(*MONTHS))) == typed([APRIL, MARCH, FEBRUARY, JANUARY, IN_2024])
    assert typed(output(invoke(*MONTHS, "--having", 'has-item:days="Monday"'))) == typed([MARCH, JANUARY, IN_2024])
    assert typed(output(invoke(*MONTHS, "--having", "glob:month=2024-0[23]"))) == typed([MARCH, FEBRUARY, IN_2024])
    both = ("--having", "regex:month=-0[12]$", "--having", 'has-item:days="Thursday"')
    assert typed(output(invoke(*MONTHS, *both))) == typed([FEBRUARY, IN_2024])
    # Saved values are never modified.
    assert typed(served) == before


def test_derived_columns_appear_only_when_grouped(serve):
    serve(FLOWS)
    result = invoke("cash-flows", "--derive", "month=year-month:date", "--metric", "rows=count")
    assert output(result) == [{"rows": 9}]
    result = invoke(
        "cash-flows", "--derive", "month=year-month:date", "--group-by", "currency", "--metric", "rows=count"
    )
    assert output(result) == [{"currency": "CAD", "rows": 7}, {"currency": "USD", "rows": 2}]


def test_where_and_older_filters_read_derived_columns(serve):
    serve(FLOWS)
    month = ("cash-flows", "--derive", "month=year-month:date", "--where", "month=2024-03", "--group-by", "account")
    result = invoke(*month, "--metric", "net=number-sum:amount")
    assert output(result) == [
        {"account": "Fictional RRSP", "net": "1500"},
        {"account": "Fictional TFSA", "net": "-300.25"},
    ]
    # A derived number matches --where by its report text and --gt by its value.
    result = invoke("cash-flows", "--derive", "year=year:date", "--where", "year=2023", "--metric", "dates=values:date")
    assert output(result) == [{"dates": ["2023-11-30", "2023-12-27"]}]
    result = invoke("cash-flows", "--derive", "year=year:date", "--gt", "year=2023", "--metric", "rows=count")
    assert output(result) == [{"rows": 7}]


def test_numeric_derived_groups_sort_numerically_and_stay_integers(serve):
    serve(FLOWS)
    direction = ("cash-flows", "--derive", "direction=sign:amount", "--group-by", "direction", "--metric", "rows=count")
    direction = (*direction, "--metric", "net=number-sum:amount")
    assert typed(output(invoke(*direction, "--sort", "direction"))) == typed(
        [{"direction": -1, "rows": 2, "net": "-1500.25"}, {"direction": 1, "rows": 7, "net": "11800.5"}]
    )
    assert typed(output(invoke(*direction, "--having", "lt:direction=0", "--totals"))) == typed(
        [{"direction": -1, "rows": 2, "net": "-1500.25"}, {"direction": None, "rows": 9, "net": "10300.25"}]
    )
    # Bands of 1,000: 0 holds 750, 800 and 250; 1000 holds 1000 and 1500; the others hold one flow each.
    band = ("cash-flows", "--derive", "band=bin:amount:1000", "--group-by", "band", "--metric", "rows=count")
    band = (*band, "--metric", "net=number-sum:amount")
    assert typed(column(invoke(*band, "--sort", "band"), "band")) == typed([-2000, -1000, 0, 1000, 2000, 5000])
    result = invoke(*band, "--having", "ge:rows=2", "--sort", "band", "--descending", "--totals")
    assert typed(output(result)) == typed(
        [
            {"band": 1000, "rows": 2, "net": "2500"},
            {"band": 0, "rows": 3, "net": "1800"},
            {"band": None, "rows": 9, "net": "10300.25"},
        ]
    )


def test_chained_derived_columns_feed_groups_and_metrics(serve):
    serve(
        [
            {"key": "2024-03-01T09:30:00", "value": 1},
            {"key": "2024-03-01 16:00", "value": 2},
            {"key": "2024-04-15", "value": 3},
            {"key": "not a date", "value": 4},
        ]
    )
    result = invoke(
        "config",
        "--derive",
        "day=date:key",
        "--derive",
        "month=month-name:day",
        "--derive",
        "letters=length:month",
        "--group-by",
        "month",
        "--group-by",
        "letters",
        "--metric",
        "rows=count",
        "--metric",
        "days=distinct-values:day",
        "--metric",
        "total=number-sum:value",
    )
    assert typed(output(result)) == typed(
        [
            {"month": "March", "letters": 5, "rows": 2, "days": ["2024-03-01"], "total": "3"},
            {"month": "April", "letters": 5, "rows": 1, "days": ["2024-04-15"], "total": "3"},
            {"month": None, "letters": None, "rows": 1, "days": [None], "total": "4"},
        ]
    )


def test_a_derived_column_reads_only_source_fields_and_earlier_columns(unloaded):
    result = invoke(
        "config", "--derive", "letters=length:month", "--derive", "month=month-name:key", "--metric", "n=count"
    )
    assert error(result).startswith("Unknown field 'month'. Choose from: ")


def test_derived_names_cannot_reuse_a_source_field_or_an_earlier_derived_name(unloaded):
    result = invoke("cash-flows", "--derive", "account=lower:account", "--metric", "rows=count")
    assert error(result) == "Derived field 'account' duplicates an existing field."
    result = invoke(
        "cash-flows", "--derive", "month=year-month:date", "--derive", "month=year:date", "--metric", "n=count"
    )
    assert error(result) == "Derived field 'month' duplicates an existing field."


def test_a_metric_cannot_share_the_name_of_a_grouped_derived_column(unloaded):
    result = invoke("cash-flows", "--derive", "month=year-month:date", "--group-by", "month", "--metric", "month=count")
    assert "'month'" in error(result)


def test_a_metric_may_share_the_name_of_an_ungrouped_derived_column(serve):
    # Not settled by the specification. Like an ungrouped source field, an ungrouped derived column
    # may share a metric's name: the output column and --having name the metric, while metrics still
    # read the derived column.
    serve(FLOWS)
    result = invoke(
        "cash-flows",
        "--derive",
        "month=year-month:date",
        "--metric",
        "month=count",
        "--metric",
        "months=distinct-values:month",
    )
    months = ["2023-11", "2023-12", "2024-01", "2024-02", "2024-03", "2024-04"]
    assert typed(output(result)) == typed([{"month": 9, "months": months}])
    result = invoke(
        "cash-flows", "--derive", "month=year-month:date", "--metric", "month=count", "--having", "gt:month=8"
    )
    assert output(result) == [{"month": 9}]


@pytest.mark.parametrize(
    "arguments",
    [
        ("--having", "gt:rows=1"),
        ("--totals",),
        ("--derive", "month=year-month:date"),
        ("--derive", "not a derived column"),
        ("--group-by", "account", "--metric", "rows=count", "--having", "gt:rows=1", "--totals"),
    ],
)
def test_describe_rejects_having_totals_and_derive(unloaded, arguments):
    result = invoke("cash-flows", "--describe", *arguments)
    assert result.exit_code == 2, result.output


# ---------------------------------------------------------------------------------------------
# The summarize processing order, composed and worked out by hand.


def test_processing_order_worked_by_hand(serve):
    served = serve(FLOWS)
    before = typed(served)
    result = invoke(
        "cash-flows",
        # (1) Derive: months 2023-11, 2023-12, 2024-01 twice, 2024-02 twice, 2024-03 twice, 2024-04.
        "--derive",
        "month=year-month:date",
        # (2) Filters, here also on the derived column: six CAD rows from 2024 remain.
        "--where",
        "currency=CAD",
        "--regex",
        "month=^2024-",
        # (3) Groups: 2024-01 (5000, 2500.5), 2024-02 (-1200), 2024-03 (1500, -300.25), 2024-04 (250).
        "--group-by",
        "month",
        "--metric",
        "rows=count",
        "--metric",
        "net=number-sum:amount",
        "--metric",
        "last=date-max:date",
        # (4) --having drops 2024-01, whose net 7500.5 is not below 5000.
        "--having",
        "lt:net=5000",
        # (5) Sorting by net, descending: 2024-03 (1199.75), 2024-04 (250), 2024-02 (-1200).
        "--sort",
        "net",
        "--descending",
        # (6) The page total counts those three groups; (7) the page holds the second of them.
        "--page-info",
        "--offset",
        "1",
        "--limit",
        "1",
        # (8) The closing row covers all six filtered rows, including the groups removed above.
        "--totals",
    )
    assert typed(output(result)) == typed(
        {
            "source": "cash-flows",
            "total": 3,
            "offset": 1,
            "limit": 1,
            "rows": [
                {"month": "2024-04", "rows": 1, "net": "250", "last": "2024-04-30"},
                {"month": None, "rows": 6, "net": "7750.25", "last": "2024-04-30"},
            ],
        }
    )
    assert typed(served) == before


# ---------------------------------------------------------------------------------------------
# A real fictional ledger.


@pytest.fixture
def ledger(tracker, monkeypatch):
    """Saved fictional entries; those of the archived account must never show."""
    store = tracker.store
    tfsa = store.add_account(Account("Fictional TFSA", type=AccountType.TFSA, track_cash=True))
    rrsp = store.add_account(Account("Fictional RRSP", type=AccountType.RRSP))
    archived = store.add_account(Account("Fictional Archived", type=AccountType.TFSA, archived=True))
    # Entered out of date order on purpose: the sources read the ledger by date.
    for txn in (
        Transaction(tfsa.saved_id, TxnType.BUY, "2024-01-15", "FIC.TO", 10, 20, currency="CAD"),
        Transaction(tfsa.saved_id, TxnType.DEPOSIT, "2023-12-28", amount=5000, currency="CAD"),
        Transaction(tfsa.saved_id, TxnType.BUY, "2024-01-31", "FICB.V", 5, 8, currency="CAD"),
        Transaction(rrsp.saved_id, TxnType.DEPOSIT, "2024-02-15", amount=3000, currency="CAD"),
        Transaction(rrsp.saved_id, TxnType.BUY, "2024-02-29", "FIC.TO", 4, 22, currency="CAD"),
        Transaction(tfsa.saved_id, TxnType.DIVIDEND, "2024-03-15", "FIC.TO", amount=12.5, currency="CAD"),
        Transaction(tfsa.saved_id, TxnType.SELL, "2024-03-28", "FICB.V", 5, 9, currency="CAD"),
        Transaction(tfsa.saved_id, TxnType.WITHDRAWAL, "2024-04-02", amount=1200, currency="CAD"),
        Transaction(rrsp.saved_id, TxnType.BUY, "2024-12-30", "MADEUP", 1, 100, currency="USD"),
        Transaction(archived.saved_id, TxnType.DEPOSIT, "2024-05-01", amount=999, currency="CAD"),
        Transaction(archived.saved_id, TxnType.BUY, "2024-06-03", "HIDDEN.TO", 3, 1, currency="CAD"),
    ):
        store.add_transaction(txn)
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    return store


def test_real_ledger_transactions_per_type_and_month(ledger, fake):
    changes = ledger._conn.total_changes
    result = invoke(
        "transactions",
        "--group-by",
        "type",
        "--metric",
        "rows=count",
        "--metric",
        "quantity=number-sum:quantity",
        "--having",
        "gt:rows=1",
        "--sort",
        "rows",
        "--descending",
        "--totals",
    )
    # Nine visible entries: 2 deposits, 4 buys (10 + 5 + 4 + 1 units), a dividend, a sale of 5, a withdrawal.
    assert typed(output(result)) == typed(
        [
            {"type": "BUY", "rows": 4, "quantity": "20"},
            {"type": "DEPOSIT", "rows": 2, "quantity": "0"},
            {"type": None, "rows": 9, "quantity": "25"},
        ]
    )
    result = invoke(
        "transactions",
        "--derive",
        "month=year-month:date",
        "--group-by",
        "month",
        "--metric",
        "rows=count",
        "--metric",
        "first=date-min:date",
        "--metric",
        "last=date-max:date",
        "--metric",
        "days=date-span:date",
        "--sort",
        "month",
        "--totals",
    )
    assert typed(output(result)) == typed(
        [
            {"month": "2023-12", "rows": 1, "first": "2023-12-28", "last": "2023-12-28", "days": 0},
            {"month": "2024-01", "rows": 2, "first": "2024-01-15", "last": "2024-01-31", "days": 16},
            {"month": "2024-02", "rows": 2, "first": "2024-02-15", "last": "2024-02-29", "days": 14},
            {"month": "2024-03", "rows": 2, "first": "2024-03-15", "last": "2024-03-28", "days": 13},
            {"month": "2024-04", "rows": 1, "first": "2024-04-02", "last": "2024-04-02", "days": 0},
            {"month": "2024-12", "rows": 1, "first": "2024-12-30", "last": "2024-12-30", "days": 0},
            # 2023-12-28 to 2024-12-30 spans the leap day: 366 + 2 days.
            {"month": None, "rows": 9, "first": "2023-12-28", "last": "2024-12-30", "days": 368},
        ]
    )
    assert fake.calls == []
    assert ledger._conn.total_changes == changes


def test_real_ledger_flows_per_account(ledger, fake):
    changes = ledger._conn.total_changes
    query = ("cash-flows", "--group-by", "account", "--metric", "flows=count", "--metric", "net=number-sum:amount")
    query = (*query, "--metric", "latest=date-max:date")
    tfsa = {"account": "Fictional TFSA", "flows": 2, "net": "3800", "latest": "2024-04-02"}
    assert typed(output(invoke(*query))) == typed(
        [tfsa, {"account": "Fictional RRSP", "flows": 1, "net": "3000", "latest": "2024-02-15"}]
    )
    result = invoke(*query, "--having", "gt:flows=1", "--totals")
    # The archived account's deposit of 999 is not among the flows the closing row covers.
    assert typed(output(result)) == typed([tfsa, {"account": None, "flows": 3, "net": "6800", "latest": "2024-04-02"}])
    assert fake.calls == []
    assert ledger._conn.total_changes == changes
