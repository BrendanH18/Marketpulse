"""The #164 inventory pairs one catalog with the existing report operations and adds three suggestions."""

import re
import shlex
from itertools import groupby
from pathlib import Path

from click.testing import CliRunner

from marketpulse.cli import main, report_operations, reports

GUIDE = Path(__file__).parent.parent / "docs" / "cli-command-parameter-improvements.md"


def test_numbered_inventory_is_exactly_two_hundred_improvements():
    guide = GUIDE.read_text(encoding="utf-8")
    assert list(reports.SOURCES)[58] == "command-parameters"
    assert re.findall(r"^\| `([a-z_]+)` \|", guide, re.MULTILINE) == list(reports.SOURCES["command-parameters"])

    ranges = re.findall(r"^\| (\d+)–(\d+) \| .+ \| (\d+) \|$", guide, re.MULTILINE)
    operation_rows = report_operations.rows()
    expected = []
    for _, rows in groupby(operation_rows, key=lambda row: row["issue"]):
        batch = list(rows)
        expected.append((batch[0]["number"], batch[-1]["number"], len(batch)))
    assert [tuple(map(int, row)) for row in ranges] == expected
    assert len(operation_rows) == 197

    suggestions = re.findall(r"^\| (\d+) \| `marketpulse (.+?)` \| `([a-z-]+)` \|$", guide, re.MULTILINE)
    assert [int(number) for number, _, _ in suggestions] == [198, 199, 200]
    assert len(operation_rows) + len(suggestions) == 200
    for _, invocation, suggestion in suggestions:
        result = CliRunner().invoke(main, shlex.split(invocation))
        assert result.exit_code == 2, result.output
        assert f"Did you mean '{suggestion}'?" in result.output
