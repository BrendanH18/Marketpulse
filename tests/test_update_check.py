"""The Mac app's update check (UpdateCheck.swift), compiled with scripts/check_update_check.swift.

Version comparison, the update decision, the daily throttle and the fetch (against a stub
URLProtocol, never the network). Needs macOS and swiftc, which Command Line Tools provide.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "macos/MarketPulseBar/Sources/MarketPulseBar/UpdateCheck.swift"
CHECK = ROOT / "scripts/check_update_check.swift"


@pytest.mark.skipif(sys.platform != "darwin" or shutil.which("swiftc") is None, reason="needs macOS and swiftc")
def test_update_check(tmp_path: Path) -> None:
    binary = tmp_path / "update-check"
    build = subprocess.run(
        ["swiftc", str(SOURCE), str(CHECK), "-o", str(binary)], capture_output=True, text=True, timeout=600
    )
    assert build.returncode == 0, build.stdout + build.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "all checks passed" in run.stdout
