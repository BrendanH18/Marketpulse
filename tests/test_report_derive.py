"""Derived report fields: composition, validation before loading, and edge cases."""

import csv
import io
import json
from decimal import Context, getcontext, localcontext

import click
import pytest
from click.testing import CliRunner

from marketpulse.cli import main, reports
from marketpulse.cli.base import App
from marketpulse.cli.report_derive import FUNCTIONS, DerivePlan
from marketpulse.config import Config
from marketpulse.models import Account, Transaction, TxnType

SCHEMA = reports.SOURCES["transactions"]


def _txn(**values):
    return {**dict.fromkeys(SCHEMA), **values}


LEDGER = [
    _txn(id=1, date="2024-01-15", type="BUY", symbol="FIC.TO", quantity=10, price=20.5, amount=0, currency="CAD"),
    _txn(id=2, date="2024-01-31", type="DIVIDEND", symbol="FIC.TO", quantity=0, price=0, amount=12.5, currency="CAD"),
    _txn(id=3, date="2024-02-29", type="BUY", symbol="FICB.V", quantity=4, price=2.25, amount=0, currency="CAD"),
    _txn(id=4, date="2024-04-01", type="DIVIDEND", symbol="FICUS", quantity=0, price=0, amount=7.5, currency="USD"),
    _txn(id=5, date=None, type="FEE", symbol="", quantity=0, price=0, amount=1, currency="CAD"),
]


@pytest.fixture
def ledger(monkeypatch):
    before = json.dumps(LEDGER)
    monkeypatch.setattr(reports, "load_source", lambda *args: LEDGER)
    yield LEDGER
    assert json.dumps(LEDGER) == before  # derived fields never write back to loaded rows


def _run(*arguments):
    result = CliRunner().invoke(main, list(arguments))
    assert result.exit_code == 0, result.output
    return result.output


def _column(plan_specifications, values, schema=("value", "other")):
    plan = DerivePlan(schema, plan_specifications)
    rows = [dict(zip(schema, value if isinstance(value, tuple) else (value, None), strict=True)) for value in values]
    return [row[plan.schema[-1]] for row in plan.apply(rows)]


def test_plan_appends_chained_columns_and_leaves_rows_untouched():
    rows = [{"date": "2024-03-05", "amount": "2.5"}]
    plan = DerivePlan(("date", "amount"), ("month=year-month:date", "label=upper:month", "double=multiply:amount:2"))
    assert plan.schema == ("date", "amount", "month", "label", "double")
    assert plan.apply(rows) == [
        {"date": "2024-03-05", "amount": "2.5", "month": "2024-03", "label": "2024-03", "double": 5}
    ]
    assert rows == [{"date": "2024-03-05", "amount": "2.5"}]
    empty = DerivePlan(("date",), ())
    assert empty.schema == ("date",) and empty.apply(rows) is rows


def test_report_uses_derived_columns_like_source_fields(ledger):
    arguments = ["--derive", "month=year-month:date", "--derive", "cost=multiply-field:quantity:price"]
    rows = json.loads(
        _run("report", "transactions", *arguments, "--where", "month=2024-01", "--fields", "id,month,cost")
    )
    assert rows == [{"id": 1, "month": "2024-01", "cost": 205}, {"id": 2, "month": "2024-01", "cost": 0}]
    rows = json.loads(
        _run("report", "transactions", *arguments, "--gt", "cost=5", "--sort", "cost", "--descending", "--fields", "id")
    )
    assert rows == [{"id": 1}, {"id": 3}]
    assert _run("report", "transactions", *arguments, "--missing", "month", "--count") == "1\n"
    rows = json.loads(_run("report", "transactions", *arguments, "--unique", "month", "--fields", "month"))
    assert rows == [{"month": "2024-01"}, {"month": "2024-02"}, {"month": "2024-04"}, {"month": None}]
    rows = json.loads(_run("report", "transactions", *arguments, "--omit", "cost", "--limit", "1"))
    assert list(rows[0]) == [*SCHEMA, "month"]


def test_report_output_transforms_and_exports_include_derived_columns(ledger):
    output = _run(
        "report",
        "transactions",
        "--derive",
        "exchange=after-last:symbol:.",
        "--derive",
        "weekday=weekday-name:date",
        "--present",
        "weekday",
        "--lower",
        "exchange",
        "--fill",
        'exchange="none"',
        "--rename",
        "weekday=day_name",
        "--fields",
        "id,exchange,day_name",
        "--format",
        "csv",
    )
    assert list(csv.reader(io.StringIO(output))) == [
        ["id", "exchange", "day_name"],
        ["1", "to", "Monday"],
        ["2", "to", "Wednesday"],
        ["3", "v", "Thursday"],
        ["4", "", "Monday"],
    ]
    page = json.loads(
        _run(
            "report", "transactions", "--derive", "q=year-quarter:date", "--fields", "q", "--limit", "2", "--page-info"
        )
    )
    assert page == {"source": "transactions", "total": 5, "offset": 0, "limit": 2, "rows": [{"q": "2024-Q1"}] * 2}


def test_summarize_groups_filters_and_measures_derived_fields(ledger):
    rows = json.loads(
        _run(
            "summarize",
            "transactions",
            "--derive",
            "month=year-month:date",
            "--derive",
            'income=equals:type:"DIVIDEND"',
            "--nonempty",
            "month",
            "--group-by",
            "month",
            "--metric",
            "rows=count",
            "--metric",
            "payouts=true-count:income",
            "--metric",
            "amount=number-sum:amount",
            "--sort",
            "month",
            "--descending",
        )
    )
    assert rows == [
        {"month": "2024-04", "rows": 1, "payouts": 1, "amount": "7.5"},
        {"month": "2024-02", "rows": 1, "payouts": 0, "amount": "0"},
        {"month": "2024-01", "rows": 2, "payouts": 1, "amount": "12.5"},
    ]
    rows = json.loads(
        _run(
            "summarize",
            "transactions",
            "--derive",
            "cost=multiply-field:quantity:price",
            "--derive",
            "bucket=bin:cost:100",
            "--where",
            "type=BUY",
            "--group-by",
            "bucket",
            "--metric",
            "cost=number-sum:cost",
        )
    )
    assert rows == [{"bucket": 200, "cost": "205"}, {"bucket": 0, "cost": "9"}]


@pytest.mark.parametrize(
    ("specification", "message"),
    [
        ("month", "NAME=FUNCTION:FIELD"),
        ("month=year-month", "NAME=FUNCTION:FIELD"),
        ("2x=year:date", "ASCII identifier NAME"),
        ("mon th=year:date", "ASCII identifier NAME"),
        ("=year:date", "ASCII identifier NAME"),
        ("date=year:date", "duplicates an existing field"),
        ("x=fortnight:date", "Unknown --derive function 'fortnight'"),
        ("x=Year:date", "Unknown --derive function 'Year'"),
        ("x=year:when", "Unknown field 'when'"),
        ("x=year:", "Unknown field ''"),
        ("x=year:date:2024", "'year' takes no argument"),
        ("x=upper:symbol:", "'upper' takes no argument"),
        ("x=days-from:date", "'days-from' requires FIELD:DATE"),
        ("x=days-from:date:2024-02-30", "valid DATE as YYYY-MM-DD"),
        ("x=days-from:date:2024-01-01T00:00", "valid DATE as YYYY-MM-DD"),
        ("x=round:amount", "'round' requires FIELD:DIGITS"),
        ("x=round:amount:16", "DIGITS from 0 to 15"),
        ("x=round:amount:016", "DIGITS from 0 to 15"),
        ("x=round:amount:-1", "DIGITS from 0 to 15"),
        ("x=round:amount:1.5", "DIGITS from 0 to 15"),
        ("x=round:amount:" + "9" * 5000, "DIGITS from 0 to 15"),
        ("x=bin:amount:0", "finite WIDTH above zero"),
        ("x=bin:amount:-5", "finite WIDTH above zero"),
        ("x=bin:amount:wide", "finite WIDTH above zero"),
        ("x=bin:amount:Infinity", "finite WIDTH above zero"),
        ("x=add:amount:NaN", "requires a NUMBER"),
        ("x=multiply:amount:true", "requires a NUMBER"),
        ("x=add-field:amount:nope", "requires a second field from"),
        ("x=divide-field:amount", "'divide-field' requires FIELD:FIELD"),
        ("x=left:symbol:0", "whole number N from 1 to 999999999"),
        ("x=left:symbol:two", "whole number N from 1 to 999999999"),
        ("x=left:symbol:" + "9" * 5000, "whole number N from 1 to 999999999"),
        ("x=item:note:1.0", "whole number N from -999999999 to 999999999"),
        ("x=before:symbol:", "requires nonempty TEXT"),
        ("x=after-last:symbol:", "requires nonempty TEXT"),
        ("x=coalesce:note:{bad", "requires finite JSON"),
        ("x=equals:amount:NaN", "requires finite JSON"),
        ("x=key:note", "'key' requires FIELD:NAME"),
    ],
)
@pytest.mark.parametrize("command", ["report", "summarize"])
def test_invalid_derivations_fail_before_loading(monkeypatch, command, specification, message):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("loaded the source"))
    arguments = [command, "transactions", "--derive", specification]
    if command == "summarize":
        arguments += ["--metric", "rows=count"]
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 2, result.output
    assert message in result.output


def test_later_options_cannot_name_missing_or_duplicate_derivations(monkeypatch):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("loaded the source"))
    for arguments, message in (
        (["report", "transactions", "--derive", "m=month:date", "--derive", "m=year:date"], "duplicates an existing"),
        (["report", "transactions", "--derive", "a=upper:b", "--derive", "b=lower:symbol"], "Unknown field 'b'"),
        (["report", "transactions", "--derive", "m=month:date", "--constant", "m=1"], "already exists"),
        (["report", "transactions", "--derive", "m=month:date", "--row-number", "m"], "already exists"),
        (["report", "transactions", "--where", "m=1"], "Use FIELD=VALUE with a field from"),
        (
            ["summarize", "transactions", "--derive", "m=month:date", "--group-by", "m", "--metric", "m=count"],
            "duplicates",
        ),
        (["summarize", "transactions", "--group-by", "m", "--metric", "rows=count"], "Choose distinct --group-by"),
        (["report", "transactions", "--describe", "--derive", "m=month:date"], "--describe cannot combine"),
        (["summarize", "transactions", "--describe", "--derive", "m=month:date"], "--describe cannot combine"),
    ):
        result = CliRunner().invoke(main, arguments)
        assert result.exit_code == 2, result.output
        assert message in result.output


def test_describe_and_plain_output_ignore_the_new_option(monkeypatch):
    data = [dict.fromkeys(reports.SOURCES["accounts"], "Alpha")]
    monkeypatch.setattr(reports, "load_source", lambda *args: data)
    assert json.loads(_run("report", "accounts")) == data
    assert json.loads(_run("report", "accounts", "--describe"))["fields"] == list(reports.SOURCES["accounts"])
    assert json.loads(_run("summarize", "accounts", "--describe"))["fields"] == list(reports.SOURCES["accounts"])


def test_dates_are_strict_iso_text_read_as_written():
    values = [
        "2000-02-29",
        "1900-02-29",  # not a leap year
        "2024-06-30T23:59:60",  # no leap seconds
        "2024-06-30T23:59:59.123456789+14:00",
        "2024-06-30T23:59:59+24:00",
        "2024-06-30t10:00",  # the separator is T or one space
        "2024-06-30  10:00",
        "2024-06-30T10",
        "0000-01-01",
        "9999-12-31",
        "２０２４-06-30",  # only ASCII digits
        "2024-06-30\n",
        " 2024-06-30",
        20240630,
        ["2024-06-30"],
    ]
    expected = ["2000-02-29", None, None, "2024-06-30", None, None, None, None, None, "9999-12-31", *[None] * 5]
    assert _column(("day=date:value",), values) == expected
    # Offsets never move the calendar date: the text is read as written.
    assert (
        _column(("day=date:value",), ["2024-01-01T00:30:00+05:00", "2024-01-01T23:30:00-05:00"]) == ["2024-01-01"] * 2
    )


def test_calendar_boundaries():
    assert _column(("w=year-week:value",), ["2020-12-31", "2021-01-04", "2026-12-31", "2027-01-03", "2027-01-04"]) == [
        "2020-W53",
        "2021-W01",
        "2026-W53",
        "2026-W53",
        "2027-W01",
    ]
    assert _column(("w=iso-week:value",), ["2020-12-31", "2021-01-04", "2018-12-31"]) == [53, 1, 1]
    assert _column(("d=day-of-year:value",), ["2023-03-01", "2024-03-01", "1900-12-31", "2000-12-31"]) == [
        60,
        61,
        365,
        366,
    ]
    last = "9999-12-31"
    for function, value in (
        ("week-start", "9999-12-27"),
        ("month-end", last),
        ("quarter-end", last),
        ("year-end", last),
        ("year-week", "9999-W52"),
        ("weekday-name", "Friday"),
    ):
        assert _column((f"x={function}:value",), [last]) == [value]
    assert _column(("x=quarter-end:value",), ["2023-02-28", "2023-05-31", "2023-08-31", "2023-11-30"]) == [
        "2023-03-31",
        "2023-06-30",
        "2023-09-30",
        "2023-12-31",
    ]
    assert _column(("n=days-from:value:2024-03-01",), ["2024-02-28", "2024-02-29", "0001-01-01", "9999-12-31"]) == [
        -2,
        -1,
        -738945,
        2913113,
    ]


def test_numbers_use_exact_decimals_and_json_types():
    assert _column(("n=number:value",), [0.1, "0.10", " 7 ", "1_000", 10**15, 10**14, "1e400", "-1e400"]) == [
        0.1,
        0.1,
        7,
        1000,
        1e15,
        10**14,
        None,
        None,
    ]
    assert json.dumps(_column(("n=number:value",), [10**15, 10**14, 2.0, -0.0, "1e-400", "-1e-400"])) == (
        "[1000000000000000.0, 100000000000000, 2, 0, 0, 0]"
    )
    assert (
        _column(("n=number:value",), ["NaN", "Infinity", "-inf", "", "1,5", "0x10", None, True, [1], {"n": 1}])
        == [None] * 10
    )
    assert _column(("n=add:value:0.1",), [0.2, 0.7]) == [0.3, 0.8]  # not 0.30000000000000004
    assert _column(("n=multiply:value:3",), ["0.1", 1.1]) == [0.3, 3.3]
    assert _column(("n=negate:value",), [0, "0.0", "-0"]) == [0, 0, 0]
    assert _column(("n=sign:value",), ["1e-400", "-1e400", "0.000"]) == [1, -1, 0]
    assert _column(("n=floor:value",), ["1e20", -0.5, "-1e-400"]) == [1e20, -1, -1]
    assert _column(("n=ceil:value",), [0.5, -0.5, "1e-400"]) == [1, 0, 1]
    assert _column(("n=multiply:value:1e300",), ["1e300", 2]) == [None, 2e300]
    # Beyond the decimal exponent range as well as a double's.
    assert _column(("n=multiply:value:10",), ["9e999999"]) == [None]


def test_rounding_and_buckets():
    assert _column(("n=round:value:0",), [0.5, 1.5, 2.5, -0.5, "2.50001"]) == [0, 2, 2, 0, 3]
    assert _column(("n=round:value:1",), [0.25, 0.35, "1e30", 12345678901234567890.123]) == [
        0.2,
        0.4,
        1e30,
        1.2345678901234567e19,
    ]
    assert _column(("n=round:value:002",), [1.125]) == [1.12]  # leading zeros, as in 015
    assert _column(("n=round:value:15",), ["0.12345678901234565", "1.00000000000000049"]) == [
        0.123456789012346,
        1,
    ]
    assert _column(("n=bin:value:0.1",), [0.3, 0.25, -0.05, "0.999"]) == [0.3, 0.2, -0.1, 0.9]
    assert _column(("n=bin:value:2.5",), [5, 4.99, 7.5, -0.01]) == [5, 2.5, 7.5, -2.5]
    assert _column(("n=bin:value:1e400",), [1]) == [0]
    # A quotient just below a bucket edge is not rounded up into the next bucket.
    assert _column(("n=bin:value:0.10000000000000000000000000000000001",), [1, -1, "0.9"]) == [0.9, -1, 0.8]
    assert _column(("n=bin:value:3",), ["-3.000000000000000000000000001"]) == [-6]  # nor up toward zero


def test_two_field_arithmetic():
    rows = [(1, 3), ("0.3", "0.1"), (5, 0), (5, "0.0"), ("1e300", "1e-300"), (0, 5), (None, 1), (1, None), (True, 1)]
    assert _column(("n=divide-field:value:other",), rows) == [
        0.3333333333333333,
        3,
        None,
        None,
        None,
        0,
        None,
        None,
        None,
    ]
    assert _column(("n=subtract-field:value:other",), [(0.3, 0.1), ("1e400", "1e400"), (2, 5)]) == [0.2, 0, -3]
    assert _column(("n=multiply-field:value:other",), [("1e200", "1e200"), (1.5, 2), (-0.0, 5)]) == [None, 3, 0]
    assert _column(("n=add-field:value:value",), [(4, None), ("x", None)]) == [8, None]


def test_arithmetic_is_independent_of_the_ambient_decimal_context():
    with localcontext(Context(prec=3)):
        before = getcontext().copy()
        assert _column(("n=add:value:0.000001",), ["123456.789"]) == [123456.789001]
        assert _column(("n=divide-field:value:other",), [(1, 3)]) == [0.3333333333333333]
        assert _column(("n=round:value:4",), ["123456.78905"]) == [123456.789]
        assert _column(("n=number:value",), ["not a number"]) == [None]
        after = getcontext()
        assert (after.prec, after.rounding, after.flags) == (before.prec, before.rounding, before.flags)


def test_text_and_value_functions():
    assert _column(("x=left:value:2",), ["éa", "a", "", None]) == ["é", "a", "", None]  # code points
    assert _column(("x=before:value: - ",), ["FIC - Fictional - Fund", "plain"]) == ["FIC", "plain"]
    assert _column(("x=after-last:value: - ",), ["FIC - Fictional - Fund", "plain"]) == ["Fund", ""]
    assert _column(("x=before:value:=",), ["a=b=c", "=x"]) == ["a", ""]
    assert _column(("x=after-last:value:=",), ["a=b=c", "x="]) == ["c", ""]
    assert _column(("x=key:value:",), [{"": 1}, {"a": 1}]) == [1, None]
    assert _column(("x=key:value:a:b",), [{"a:b": [1]}, {"a": {"b": 1}}]) == [[1], None]
    assert _column(("x=item:value:0",), [[None, 1], [[2]], [], "ab"]) == [None, [2], None, None]
    assert _column(("x=item:value:-2",), [[1, 2, 3], [1]]) == [2, None]
    assert _column(("x=item:value:5",), [[1, 2, 3]]) == [None]
    assert _column(('x=coalesce:value:[1, {"a": null}]',), [None, [], "kept"]) == [[1, {"a": None}], [], "kept"]
    assert _column(
        ('x=equals:value:{"b": [1, false], "a": null}',), [{"a": None, "b": [1.0, False]}, {"a": None, "b": [1, 0]}]
    ) == [
        True,
        False,
    ]
    assert _column(("x=equals:value:null",), [None, "", 0]) == [True, False, False]
    assert _column(('x=equals:value:"BUY"',), ["BUY", "buy"]) == [True, False]
    assert _column(("x=type:value",), [0, 0.0, False, "0"]) == ["number", "number", "boolean", "string"]
    assert _column(("x=length:value",), ["日本語", "é"]) == [3, 2]


def test_function_catalog_is_complete_and_well_formed():
    names = [function.name for function in FUNCTIONS]
    assert len(names) == len(set(names)) == 50
    assert {function.family for function in FUNCTIONS} == {"date", "number", "text", "value"}
    assert {function.result for function in FUNCTIONS} == {"integer", "number", "string", "boolean", "value"}
    assert all(function.description.endswith(".") for function in FUNCTIONS)
    schema = ("value", "other")
    for function in FUNCTIONS:
        # A function either takes exactly its documented argument or none at all.
        bare, extra = f"x={function.name}:value", f"x={function.name}:value:other"
        if function.argument is None:
            DerivePlan(schema, (bare,))
            with pytest.raises(click.UsageError, match="takes no argument"):
                DerivePlan(schema, (extra,))
        else:
            with pytest.raises(click.UsageError, match=f"requires FIELD:{function.argument}"):
                DerivePlan(schema, (bare,))


@pytest.fixture
def fictional_ledger(tracker, monkeypatch):
    store = tracker.store
    active = store.add_account(Account("Fictional Cash", track_cash=True))
    archived = store.add_account(Account("Archived Fictional", track_cash=True, archived=True))
    for account in (active, archived):
        for txn in (
            Transaction(account.saved_id, TxnType.DEPOSIT, "2024-01-02", amount=1000, currency="CAD"),
            Transaction(account.saved_id, TxnType.BUY, "2024-01-15", "FIC.TO", 10, 20, currency="CAD"),
            Transaction(account.saved_id, TxnType.DIVIDEND, "2024-02-15", "FIC.TO", amount=5, currency="CAD"),
            Transaction(account.saved_id, TxnType.DIVIDEND, "2024-05-15", "FIC.TO", amount=6, currency="CAD"),
        ):
            store.add_transaction(txn)
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    return store


def test_real_sources_derive_offline_without_writes(fictional_ledger, fake):
    store = fictional_ledger
    changes = store._conn.total_changes
    snapshots, backups = store.snapshots(), store.backups()
    rows = json.loads(
        _run(
            "summarize",
            "payouts",
            "--derive",
            "quarter=year-quarter:date",
            "--group-by",
            "quarter",
            "--metric",
            "payouts=count",
            "--metric",
            "amount=number-sum:amount",
        )
    )
    assert rows == [
        {"quarter": "2024-Q1", "payouts": 1, "amount": "5"},
        {"quarter": "2024-Q2", "payouts": 1, "amount": "6"},
    ]
    rows = json.loads(
        _run(
            "report",
            "positions",
            "--derive",
            "unit_cost=divide-field:book:quantity",
            "--derive",
            "held_days=days-from:first_date:2024-01-01",
            "--fields",
            "account,symbol,unit_cost,held_days",
        )
    )
    assert rows == [{"account": "Fictional Cash", "symbol": "FIC.TO", "unit_cost": 20, "held_days": 14}]
    output = _run("report", "transactions", "--derive", "month=month-name:date", "--where", "month=January", "--count")
    assert output == "2\n"  # the archived account's rows stay hidden
    assert fake.calls == []
    assert store._conn.total_changes == changes
    assert store.snapshots() == snapshots
    assert store.backups() == backups


@pytest.mark.parametrize("source", sorted(reports.SOURCES))
def test_no_dataset_or_derived_field_reveals_the_api_key(fictional_ledger, source):
    secret = "fictional-key-that-must-not-appear"
    config = Config.load()
    config.quote_api_key = secret
    config.save()  # to the isolated configuration file every command below loads
    assert Config.load().quote_api_key == secret
    first = reports.SOURCES[source][0]
    for arguments in (
        [],
        ["--derive", f"derived_text=text:{first}"],
        ["--derive", f"derived_type=type:{first}", "--format", "csv"],
    ):
        assert secret not in _run("report", source, *arguments)
    assert secret not in _run("summarize", source, "--metric", f"all=values:{first}")
