"""The #162 inventory counts new dataset/operation combinations and three CLI improvements."""

import re
from pathlib import Path

from marketpulse.cli import report_operations, reports


def test_documented_inventory_is_exactly_two_hundred_improvements():
    guide = (Path(__file__).parent.parent / "docs" / "cli-discovery-improvements.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (\d+) \| `report-fields` \| ([a-z]+) \| `(.+)` \|$", guide, re.MULTILINE)
    assert list(reports.SOURCES)[57] == "report-fields"
    assert [(int(number), family, syntax) for number, family, syntax in rows] == [
        (number, operation.family, operation.syntax) for number, operation in enumerate(report_operations.OPERATIONS, 1)
    ]
    additions = re.findall(r"^\| (19[89]|200) \| (Suggest .+?) \| `(.+)` \|$", guide, re.MULTILINE)
    assert additions == [
        ("198", "Suggest a close report source name.", "marketpulse report report-fiels"),
        (
            "199",
            "Suggest a close summary source name.",
            "marketpulse summarize report-fiels --metric rows=count",
        ),
        (
            "200",
            "Suggest a close derived-field function name.",
            "marketpulse report report-fields --derive label=uppper:field",
        ),
    ]
    assert len(rows) == 197
    assert len(rows) + len(additions) == 200
