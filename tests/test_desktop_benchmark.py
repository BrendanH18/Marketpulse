"""The benchmark must measure valid engine operations without using inherited user paths."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_desktop.py"


def test_benchmark_runs_on_fictional_data_and_ignores_inherited_paths(tmp_path):
    data = tmp_path / "do-not-open"
    data.mkdir()
    ledger = data / "marketpulse.db"
    ledger.write_bytes(b"Not a database: inherited data must never be opened")
    config = tmp_path / "do-not-read.toml"
    config.write_text("Invalid TOML: inherited config must never be loaded", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--samples", "1", "--delay-ms", "1"],
        env={**os.environ, "MARKETPULSE_DATA": str(data), "MARKETPULSE_CONFIG": str(config)},
        capture_output=True,
        check=True,
        timeout=120,
    )
    report = json.loads(result.stdout)
    assert report["workload"] == {"transactions": 5000, "accounts": 4, "positions": 12, "currencies": ["CAD", "USD"]}
    assert set(report["scenarios"]) == {"0.0", "1.0"}
    for scenario in report["scenarios"].values():
        timings = scenario["timings"]
        assert timings["startup"]["samples"][0]["requests"] == 0
        assert timings["edit"]["samples"][0]["requests"] == 0
        assert timings["refresh"]["samples"][0]["requests"] == 2  # prices then FX
        assert timings["reused_fresh"]["samples"][0]["requests"] == 1  # FX still cached
        assert timings["reused_cached"]["samples"][0]["requests"] == 0
        assert timings["edit_refresh"]["median_ms"] > timings["edit"]["median_ms"]
        assert timings["refresh"]["samples"][0]["stdout_bytes"] > 5000
    assert ledger.read_bytes() == b"Not a database: inherited data must never be opened"
    assert sorted(p.name for p in data.iterdir()) == ["marketpulse.db"]
    assert config.read_text(encoding="utf-8") == "Invalid TOML: inherited config must never be loaded"


def test_quote_fixture_refuses_unexpected_requests():
    spec = importlib.util.spec_from_file_location("benchmark_desktop", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = module.FixtureTransport(0)
    with pytest.raises(AssertionError, match="no fixture"):
        fixture.get_json("https://unexpected.invalid", {})
    from marketpulse.market import SPARK_URL

    with pytest.raises(KeyError):
        fixture.get_json(SPARK_URL, {"symbols": "UNEXPECTED"})
