"""Malformed report and summary queries diagnose typos before loading data."""

import pytest
from click.testing import CliRunner

from marketpulse.cli import main, reports


@pytest.fixture
def reject_without_loading(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid queries must not load data")

    monkeypatch.setattr(reports, "load_source", forbidden)
    output = tmp_path / "result.json"

    def invoke(*args):
        result = CliRunner().invoke(main, [*args, "--output", str(output)], catch_exceptions=False)
        assert result.exit_code == 2, result.output
        assert not output.exists()
        return result.output

    return invoke


@pytest.mark.parametrize(
    "expression,expected", [("counnt", "count"), ("number-p01:field_count", "number-p10"), ("zzzzzz", None)]
)
def test_metric_operation_hint(reject_without_loading, expression, expected):
    operation = expression.split(":", 1)[0]
    error = reject_without_loading("summarize", "sources", "--metric", f"size={expression}")
    assert f"Unknown summary operation '{operation}'. Use --describe to list operations." in error
    if expected is None:
        assert "Did you mean" not in error
    else:
        assert f"Did you mean '{expected}'?" in error


@pytest.mark.parametrize(
    "condition,expected",
    [
        ("contains-anyy:size=[]", "contains-any"),
        ("not_contains:size=x", "not-contains"),
        ("min_length:size=2", "min-length"),
        ("glbo:source=account*", "glob"),
        ("gilob:source=ACCOUNT*", "iglob"),
        ("gtt:size=1", "gt"),
        ("gte:size=1", None),
        ("contains-anyy", None),
        ("zzzzzz:size=1", None),
    ],
)
def test_having_filter_hint(reject_without_loading, condition, expected):
    error = reject_without_loading(
        "summarize", "sources", "--metric", "size=count", "--group-by", "source", "--having", condition
    )
    assert "--having requires FILTER:NAME=VALUE with a filter from:" in error
    if expected is None:
        assert "Did you mean" not in error
    else:
        assert f"Did you mean '{expected}'?" in error


@pytest.mark.parametrize("command", ["report", "summarize"])
@pytest.mark.parametrize("field,expected", [("sourcce", "source"), ("zzzzzz", None)])
def test_derive_input_field_hint(reject_without_loading, command, field, expected):
    error = reject_without_loading(command, "sources", "--derive", f"label=upper:{field}")
    assert f"Unknown field '{field}'. Choose from:" in error
    if expected is None:
        assert "Did you mean" not in error
    else:
        assert f"Did you mean '{expected}'?" in error
