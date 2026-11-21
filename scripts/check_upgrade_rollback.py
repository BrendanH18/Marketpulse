"""Rehearse the MarketPulse 3.2.0 CLI upgrade and rollback on a fictional ledger."""

import argparse
import csv
import io
import json
import os
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory


def run(cli: Path, data: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update(MARKETPULSE_DATA=str(data), MARKETPULSE_CONFIG=str(data.parent / "config.toml"))
    result = subprocess.run([str(cli), *args], env=env, capture_output=True, text=True, timeout=30, check=False)
    if check and result.returncode:
        raise SystemExit(f"{cli} {' '.join(args)} exited {result.returncode}:\n{result.stderr or result.stdout}")
    return result


def expect(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise SystemExit(f"{label}: expected {expected!r}, got {actual!r}")


def schema_version(database: Path) -> int:
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def seed(cli: Path, data: Path) -> None:
    account = "Fictional Taxable"
    run(cli, data, "accounts", "add", account, "--type", "NONREG", "--currency", "CAD", "--track-cash")
    trade_options = ("-a", account, "-c", "CAD", "-d")
    run(cli, data, "deposit", "2000", *trade_options, "2025-01-02")
    run(cli, data, "buy", "FICTION.TO", "10", "100", *trade_options, "2025-01-03")
    run(cli, data, "sell", "FICTION.TO", "4", "150", *trade_options, "2025-06-02")


def reports(cli: Path, data: Path) -> dict[str, list[dict]]:
    return {
        "positions": json.loads(run(cli, data, "positions", "--json").stdout),
        "cash": json.loads(run(cli, data, "cash", "--json").stdout),
        "transactions": list(csv.DictReader(io.StringIO(run(cli, data, "export").stdout))),
        "tax": json.loads(run(cli, data, "tax", "--year", "2025", "--json").stdout),
    }


def rehearse(previous: Path, candidate: Path, scratch: Path) -> None:
    live = scratch / "upgrade"
    recovered = scratch / "recovered"
    database = live / "marketpulse.db"
    (scratch / "config.toml").write_text('base_currency = "CAD"\ntheme = "tokyo-night"\n', encoding="utf-8")

    expect(run(previous, live, "--version").stdout.strip(), "MarketPulse, version 3.1.0", "Previous executable")
    seed(previous, live)
    expect(schema_version(database), 1, "Original schema")
    baseline = reports(previous, live)
    expect([(row["quantity"], row["book"]) for row in baseline["positions"]], [(6, 600)], "Seeded position")
    expect([row["balance"] for row in baseline["cash"]], [1600], "Seeded cash")
    expect([row["type"] for row in baseline["transactions"]], ["DEPOSIT", "BUY", "SELL"], "Seeded transactions")
    expect([row["gain"] for row in baseline["tax"]], [200], "Seeded capital gain")
    print(
        "PASS: v3.1.0 seeded schema 1 with 3 transactions, 6 units at CAD 600 book cost, "
        "CAD 1,600 cash and a CAD 200 capital gain"
    )

    upgraded = reports(candidate, live)
    expect(schema_version(database), 3, "Upgraded schema")
    for label, expected in baseline.items():
        expect(upgraded[label], expected, f"Upgraded {label}")
    backups = list((live / "backups").glob("marketpulse-*-pre-v3.db"))
    expect(len(backups), 1, "Pre-upgrade backup count")
    backup = backups[0]
    expect(schema_version(backup), 1, "Pre-upgrade backup schema")
    print("PASS: candidate upgraded to schema 3, preserved all four reports and saved a schema 1 pre-v3 backup")

    refused = run(previous, live, "positions", "--json", check=False)
    schema_error = "uses schema version 3, but this MarketPulse only understands up to 1"
    if refused.returncode == 0 or schema_error not in refused.stderr:
        raise SystemExit(f"Expected v3.1.0 to refuse schema 3 (exit {refused.returncode}):\n{refused.stderr}")
    expect(schema_version(database), 3, "Live schema after refusal")
    print("PASS: v3.1.0 refused to open the schema 3 ledger")

    run(previous, recovered, "backup", "restore", str(backup), "--yes")
    expect(schema_version(recovered / "marketpulse.db"), 1, "Recovered schema")
    restored = reports(previous, recovered)
    for label, expected in baseline.items():
        expect(restored[label], expected, f"Restored {label}")
    print("PASS: v3.1.0 restored the pre-upgrade backup into a clean directory and reproduced all four reports")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("previous", type=Path, help="Path to the v3.1.0 marketpulse executable")
    parser.add_argument("candidate", type=Path, help="Path to the 3.2.0 candidate marketpulse executable")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="marketpulse-upgrade-") as directory:
        rehearse(args.previous.absolute(), args.candidate.absolute(), Path(directory).resolve())
