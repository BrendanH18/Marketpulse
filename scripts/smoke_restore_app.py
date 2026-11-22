"""Drive a packaged MarketPulse.app's restore sheet on a fictional scratch ledger.

    uv run --locked python scripts/smoke_restore_app.py --app "$RUNNER_TEMP/app/arm64/MarketPulse.app"

The bundle smoke in build_app.py only runs the bundled CLI. This launches the app itself, opens
Automation › Backups › Restore… through the Accessibility API (scripts/drive_app.swift), and checks
that the sheet is wired to the backend:

1. Cancel after the preview leaves the ledger untouched.
2. Restore after the ledger changed since the preview is refused, shows the backend's reason, and
   leaves the changed ledger untouched.
3. Preview again, then Restore, does restore: proof the steps above reached the real button.

The app runs from the bundle as built, with its own backend, on a scratch data folder and config.
It drives the screen for about a minute, and needs the Accessibility permission for the terminal
or CI runner. The app's own defaults (dev.marketpulse.app: window position, last update check) are
saved first and put back afterwards. macOS only; CI runs it in the menubar job.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from marketpulse import __version__
from marketpulse.db import RESTORE_ID_KEY

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ID = "dev.marketpulse.app"
STALE = "changed since the preview"  # the backend's refusal, shown in the sheet


def run(*args: str | Path, **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("check", True)
    return subprocess.run([str(a) for a in args], **kwargs)


def ledger(data: Path) -> dict:
    """What a restore replaces, read without writing to the ledger."""
    with closing(sqlite3.connect(f"{(data / 'marketpulse.db').as_uri()}?mode=ro", uri=True)) as conn:
        return {
            "accounts": conn.execute("SELECT * FROM accounts ORDER BY id").fetchall(),
            "transactions": conn.execute("SELECT * FROM transactions ORDER BY id").fetchall(),
            "restore_id": conn.execute("SELECT value FROM meta WHERE key = ?", (RESTORE_ID_KEY,)).fetchall(),
            "pre_restore_backups": sorted(p.name for p in (data / "backups").glob("*-pre-restore*.db")),
        }


def amounts(data: Path) -> list[float]:
    with closing(sqlite3.connect(f"{(data / 'marketpulse.db').as_uri()}?mode=ro", uri=True)) as conn:
        return [amount for (amount,) in conn.execute("SELECT amount FROM transactions ORDER BY id")]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")
    print(f"PASS: {message}", flush=True)


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("The packaged app smoke runs on macOS only.")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app", type=Path, required=True, help="The MarketPulse.app that build_app.py produced.")
    args = parser.parse_args()
    app: Path = args.app.resolve()
    binary = app / "Contents" / "MacOS" / "MarketPulseBar"
    cli = app / "Contents" / "Resources" / "backend" / "bin" / "marketpulse"
    if not (binary.is_file() and cli.is_file()):
        raise SystemExit(f"{app} isn't a packaged MarketPulse.app with a bundled backend.")
    running = run("pgrep", "-f", "MarketPulse.app/Contents/MacOS/", check=False, capture_output=True)
    if running.returncode == 0:
        raise SystemExit("Quit MarketPulse first: the smoke launches its own copy of the app.")

    with tempfile.TemporaryDirectory(prefix="marketpulse-restore-smoke-") as tmp:
        scratch = Path(tmp)
        data = scratch / "data"
        feed = scratch / "update-feed.json"  # the update check reads this instead of GitHub
        feed.write_text(json.dumps({"tag_name": f"v{__version__}", "prerelease": False, "draft": False}))
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": os.environ["HOME"],
            "MARKETPULSE_DATA": str(data),
            "MARKETPULSE_CONFIG": str(scratch / "config.toml"),
            "MARKETPULSE_UPDATE_FEED": str(feed),
            "NO_COLOR": "1",
        }

        def cli_run(*cli_args: str) -> str:
            return run(cli, *cli_args, env=env, cwd="/", capture_output=True, text=True).stdout

        # A fictional ledger: one deposit in the backup, a second one after it.
        cli_run("deposit", "--currency", "CAD", "--date", "2026-01-05", "--", "100")
        cli_run("backup", "now")
        cli_run("deposit", "--currency", "CAD", "--date", "2026-02-05", "--", "250")
        start = ledger(data)
        check(amounts(data) == [100, 250] and not start["pre_restore_backups"], "seeded the fictional ledger")

        driver = scratch / "drive_app"
        run("swiftc", "-O", ROOT / "scripts" / "drive_app.swift", "-o", driver)
        defaults = scratch / "defaults.plist"
        domains = run("defaults", "domains", capture_output=True, text=True).stdout.strip().split(", ")
        had_defaults = BUNDLE_ID in domains
        if had_defaults:
            run("defaults", "export", BUNDLE_ID, defaults)  # stops here, before launch, if it can't be saved
        # Launched directly rather than with `open`, so it gets exactly this environment. English for
        # this process only, since the driver finds controls by their English labels.
        process = subprocess.Popen([str(binary), "-AppleLanguages", "(en)"], env=env, cwd="/")
        try:

            def drive(command: str, argument: str) -> None:
                run(driver, str(process.pid), command, argument)

            drive("workspace", "Automation")
            drive("press-prefix", "Restore the backup from")
            drive("wait-enabled", "Restore")  # enabled once the preview is ready

            drive("press", "Cancel")
            drive("wait-gone", "Restore")
            check(ledger(data) == start, "Cancel after a preview left the ledger untouched")

            drive("press-prefix", "Restore the backup from")
            drive("wait-enabled", "Restore")
            cli_run("deposit", "--currency", "CAD", "--date", "2026-03-05", "--", "75")
            changed = ledger(data)
            check(amounts(data) == [100, 250, 75], "changed the ledger after the preview")
            drive("press", "Restore")
            drive("wait-text", STALE)
            check(ledger(data) == changed, "Restore after a stale preview was refused and left the ledger untouched")

            drive("press", "Preview again")
            drive("wait-enabled", "Restore")
            drive("press", "Restore")
            drive("wait-gone", "Restore")
            restored = ledger(data)
            check(
                amounts(data) == [100] and len(restored["pre_restore_backups"]) == 1,
                "Restore after a fresh preview restored the backup (the sheet reaches the backend)",
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
            if had_defaults:
                run("defaults", "import", BUNDLE_ID, defaults)
            else:
                run("defaults", "delete", BUNDLE_ID, check=False, capture_output=True)


if __name__ == "__main__":
    main()
