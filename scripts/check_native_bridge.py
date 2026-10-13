"""Compile native models and check them against an actual offline Python payload."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from marketpulse.desktop import demo_snapshot

root = Path(__file__).resolve().parents[1]
sources = root / "macos/MarketPulseBar/Sources/MarketPulseBar"
if sys.platform != "darwin":
    raise SystemExit("Native bridge checks require macOS and the Swift Command Line Tools.")
with tempfile.TemporaryDirectory(prefix="marketpulse-bridge-") as tmp:
    binary = Path(tmp) / "bridge-check"
    fixture = Path(tmp) / "demo.json"
    fixture.write_text(json.dumps(demo_snapshot(), allow_nan=False))
    subprocess.run(
        [
            "swiftc",
            str(sources / "Models.swift"),
            str(sources / "DesktopModels.swift"),
            str(root / "scripts/check_native_bridge.swift"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    subprocess.run([str(binary), str(fixture)], check=True)
