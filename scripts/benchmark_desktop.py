"""Offline desktop latency benchmark; always creates and removes its own fictional ledger.

Run with: uv run --locked python scripts/benchmark_desktop.py > /tmp/desktop-benchmark.json
No production code is patched outside the worker processes. See docs/performance.md.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

ROWS = 5000
SYMBOLS = {f"BENCH{i:02}": "CAD" if i % 2 == 0 else "USD" for i in range(12)}


def seed(root: Path) -> None:
    from marketpulse.config import Config
    from marketpulse.db import Store
    from marketpulse.models import Account, AccountType, Transaction, TxnType

    (root / "data").mkdir(parents=True)
    Config(theme="studio", market_strip=[]).save(root / "config.toml")
    store = Store(root / "data" / "marketpulse.db")
    try:
        accounts = [
            store.add_account(
                Account(
                    name=f"Fictional {i}",
                    type=AccountType.TFSA if i < 2 else AccountType.NONREG,
                    currency="CAD" if i % 2 == 0 else "USD",
                    track_cash=True,
                )
            )
            for i in range(4)
        ]
        rows = []
        for i in range(ROWS // 4):
            symbol = list(SYMBOLS)[i % len(SYMBOLS)]
            common = {
                "account_id": accounts[i % len(accounts)].saved_id,
                "date": (date(2020, 1, 1) + timedelta(days=i)).isoformat(),
                "currency": SYMBOLS[symbol],
            }
            rows.extend(
                [
                    Transaction(**common, type=TxnType.DEPOSIT, amount=1000),
                    Transaction(**common, type=TxnType.BUY, symbol=symbol, quantity=10, price=20),
                    Transaction(**common, type=TxnType.SELL, symbol=symbol, quantity=2, price=21),
                    Transaction(**common, type=TxnType.DIVIDEND, symbol=symbol, amount=2),
                ]
            )
        store.add_transactions(rows)
        if len(store.transactions()) != ROWS or store.ledger().issues:
            raise RuntimeError("Invalid fictional benchmark ledger")
    finally:
        store.close()


class FixtureTransport:
    """Fixed spark responses, optionally delayed per request. Unexpected URLs fail closed."""

    def __init__(self, delay_ms: float):
        self.delay_ms = delay_ms
        self.calls = 0

    def get_json(self, url: str, params: dict) -> dict:
        from marketpulse.market import SPARK_URL

        if url != SPARK_URL:
            raise AssertionError(f"Benchmark has no fixture for {url}")
        self.calls += 1
        time.sleep(self.delay_ms / 1000)
        result = []
        for symbol in params["symbols"].split(","):
            currency = "CAD" if symbol == "USDCAD=X" else SYMBOLS[symbol]
            price = 1.35 if symbol == "USDCAD=X" else 25.0
            result.append(
                {
                    "symbol": symbol,
                    "response": [
                        {
                            "meta": {
                                "symbol": symbol,
                                "currency": currency,
                                "regularMarketPrice": price,
                                "previousClose": price,
                                "longName": f"Fictional {symbol}",
                            },
                            "indicators": {"quote": [{"close": [price]}]},
                        }
                    ],
                }
            )
        return {"spark": {"result": result, "error": None}}


def worker(root: Path, delay_ms: float, operation: str) -> None:
    # Override inherited paths before importing the application. No user ledger or config is read.
    os.environ["MARKETPULSE_DATA"] = str(root / "data")
    os.environ["MARKETPULSE_CONFIG"] = str(root / "config.toml")
    if not (root / "config.toml").is_file() or not (root / "data" / "marketpulse.db").is_file():
        raise RuntimeError("Worker requires a seeded scratch ledger")
    from marketpulse.cli import main
    from marketpulse.market import CurlTransport

    fixture = FixtureTransport(delay_ms)
    CurlTransport.get_json = lambda self, url, params: fixture.get_json(url, params)
    measured_ms = None
    if operation.startswith("reused_"):
        from marketpulse.desktop import snapshot
        from marketpulse.services import Tracker

        tracker = Tracker.open()
        try:
            snapshot(tracker)  # untimed warm-up, including the 15-second in-memory quote cache
            fixture.calls = 0
            start = time.perf_counter()
            payload = json.dumps(snapshot(tracker, fresh=operation == "reused_fresh"), allow_nan=False)
            measured_ms = (time.perf_counter() - start) * 1000
            print(payload)
        finally:
            tracker.store.close()
    else:
        commands = {
            # Opens the normal CLI context/Tracker/SQLite, without ledger replay or market requests.
            "startup": ["desktop", "transaction-status", "00000000-0000-0000-0000-000000000000"],
            "refresh": ["desktop", "snapshot"],
            # Edit a price, exercising the real replay validation without changing the row count.
            "edit": ["txn", "edit", "2", "--price", "21"],
        }
        main.main(args=commands[operation], standalone_mode=False)
    (root / "worker-metrics.json").write_text(
        json.dumps({"requests": fixture.calls, "body_ms": measured_ms}), encoding="utf-8"
    )


def invoke(root: Path, delay_ms: float, operation: str) -> tuple[dict, bytes]:
    start = time.perf_counter()
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker", str(root), str(delay_ms), operation],
        capture_output=True,
        check=True,
        timeout=120,
    )
    elapsed = (time.perf_counter() - start) * 1000
    metrics = json.loads((root / "worker-metrics.json").read_text(encoding="utf-8"))
    return {**metrics, "process_ms": elapsed, "stdout_bytes": len(result.stdout)}, result.stdout


def validate_snapshot(output: bytes) -> dict:
    payload = json.loads(output)
    if (
        len(payload["activity"]) != ROWS
        or len(payload["positions"]) != 12
        or payload["warnings"]
        or payload["automation"]["errors"]
        or payload["automation"]["quote_errors"]
        or payload["status"]["stale"]
    ):
        raise RuntimeError("Benchmark snapshot is incomplete")
    return payload


def summarize(samples: list[dict], key: str = "process_ms") -> dict:
    values = [s[key] for s in samples]
    return {"median_ms": statistics.median(values), "min_ms": min(values), "max_ms": max(values), "samples": samples}


def benchmark(samples: int, delay_ms: float) -> dict:
    report = {
        "schema_version": 1,
        "environment": {"platform": platform.platform(), "machine": platform.machine(), "python": sys.version},
        "workload": {"transactions": ROWS, "accounts": 4, "positions": 12, "currencies": ["CAD", "USD"]},
        "scenarios": {},
    }
    with tempfile.TemporaryDirectory(prefix="marketpulse-benchmark-") as folder:
        root = Path(folder)
        baseline, work = root / "baseline", root / "work"
        seed(baseline)
        # Record a fresh backup and today's snapshot once; routine samples retain those real paths.
        _, output = invoke(baseline, 0, "refresh")
        validate_snapshot(output)
        for delay in dict.fromkeys((0.0, delay_ms)):
            measurements: dict[str, list[dict]] = {
                name: [] for name in ("startup", "refresh", "edit", "edit_refresh", "reused_fresh", "reused_cached")
            }
            for _ in range(samples):
                for operation in ("startup", "refresh", "edit_refresh", "reused_fresh", "reused_cached"):
                    if work.exists():
                        shutil.rmtree(work)
                    shutil.copytree(baseline, work)
                    if operation == "edit_refresh":
                        edit, _ = invoke(work, delay, "edit")
                        refresh, output = invoke(work, delay, "refresh")
                        payload = validate_snapshot(output)
                        if next(t for t in payload["activity"] if t["id"] == 2)["price"] != 21:
                            raise RuntimeError("Benchmark edit was not saved")
                        measurements["edit"].append(edit)
                        measurements[operation].append(
                            {
                                "process_ms": edit["process_ms"] + refresh["process_ms"],
                                "requests": edit["requests"] + refresh["requests"],
                            }
                        )
                    else:
                        measured, output = invoke(work, delay, operation)
                        if operation != "startup":
                            validate_snapshot(output)
                        measurements[operation].append(measured)
            report["scenarios"][str(delay)] = {
                "delay_per_request_ms": delay,
                "timings": {
                    name: summarize(values, "body_ms" if name.startswith("reused_") else "process_ms")
                    for name, values in measurements.items()
                },
            }
    return report


def main() -> None:
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        worker(Path(sys.argv[2]).resolve(), float(sys.argv[3]), sys.argv[4])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=7, help="Measured repetitions per case (default: 7).")
    parser.add_argument("--delay-ms", type=float, default=100, help="Simulated wait per request (default: 100 ms).")
    args = parser.parse_args()
    if args.samples < 1 or not 0 <= args.delay_ms <= 1000:
        parser.error("samples must be positive and delay-ms must be between 0 and 1000")
    print(json.dumps(benchmark(args.samples, args.delay_ms), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
