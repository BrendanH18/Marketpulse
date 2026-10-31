"""Fail if the financial core's test coverage drops below its floors.

Run after `uv run --locked pytest --cov`. The floors live in pyproject.toml under
[tool.marketpulse.coverage-floors]; coverage.py's own `fail_under` only checks the
total, which presentation code would dilute.
"""

import io
import sys
import tomllib
from pathlib import Path

import coverage

root = Path(__file__).resolve().parents[1]
floors = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["marketpulse"]["coverage-floors"]

cov = coverage.Coverage(data_file=str(root / ".coverage"), config_file=str(root / "pyproject.toml"))
cov.load()
measured = {Path(f).resolve() for f in cov.get_data().measured_files()}
if not measured:
    raise SystemExit("No coverage data. Run `uv run --locked pytest --cov` first.")

failures = []
print(f"{'module':<30} {'cover':>7} {'floor':>7}")
for module, floor in floors.items():
    path = (root / "src" / module).resolve()
    if path not in measured:
        # A renamed or unimported module must not quietly fall out of the gate.
        failures.append(f"{module}: no coverage data")
        print(f"{module:<30} {'-':>7} {floor:>6}%")
        continue
    percent = cov.report(include=[str(path)], file=io.StringIO())
    print(f"{module:<30} {percent:>6.1f}% {floor:>6}%")
    if percent < floor:
        failures.append(f"{module}: {percent:.1f}% is below the {floor}% floor")

if failures:
    print("\nCoverage gate failed:\n  " + "\n  ".join(failures), file=sys.stderr)
    print("Add tests for the uncovered lines (`pytest --cov --cov-report=term-missing`).", file=sys.stderr)
    sys.exit(1)
print("\nCoverage gate passed.")
