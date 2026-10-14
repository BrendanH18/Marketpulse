"""Build a throwaway copy of the native app on a fictional scratch ledger, for manual or
computer-use QA. Never touches your real ledger, settings, or installed app.

    uv run --locked python scripts/qa_app.py              # desktop mode (Dock icon)
    uv run --locked python scripts/qa_app.py --menubar    # menu bar mode
    uv run --locked python scripts/qa_app.py --out /tmp/mp-qa --fresh

Then run the printed `launch.sh`, and follow docs/qa.md.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shlex
import shutil
import signal
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from marketpulse.config import config_path
from marketpulse.db import Store
from marketpulse.models import Account, AccountType, Alert, Transaction, TxnType

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "macos" / "MarketPulseBar"
BUNDLE_ID = "dev.marketpulse.qa"  # separate from the real app's defaults and login item
APP_NAME = "MarketPulse QA"
MARKER = ".marketpulse-qa"  # written into --out, so the script only ever reuses or resets its own folder


def check_out(out: Path) -> None:
    """Refuse any --out that could touch a real portfolio: it must not overlap the real data
    folder or config file, and an existing folder must be one this script created."""
    real = (
        Path(os.environ.get("MARKETPULSE_DATA") or Path.home() / ".marketpulse").expanduser().resolve(),
        config_path().expanduser().resolve(),
    )
    for path in real:
        if out == path or out in path.parents or path in out.parents:
            raise SystemExit(f"--out {out} overlaps your real MarketPulse data or settings ({path}).")
    if out.is_dir() and any(out.iterdir()) and not (out / MARKER).exists():
        raise SystemExit(f"{out} exists and wasn't created by this script. Choose a new or empty folder.")


def seed(data: Path) -> None:
    """Fictional ledger covering the cases docs/qa.md checks."""
    store = Store(data / "marketpulse.db")
    try:
        day = lambda n: (date.today() - timedelta(days=n)).isoformat()  # noqa: E731
        tfsa = store.add_account(Account(name="Everyday TFSA", type=AccountType.TFSA, institution="Wealthsimple"))
        cash = store.add_account(Account(name="Cash Account", currency="USD", track_cash=True))
        old = store.add_account(Account(name="Old RRSP", type=AccountType.RRSP))
        rows = [
            (tfsa, TxnType.BUY, 60, {"symbol": "XEQT.TO", "quantity": 100, "price": 30, "currency": "CAD"}),
            (tfsa, TxnType.DIVIDEND, 20, {"symbol": "XEQT.TO", "amount": 45.5, "currency": "CAD"}),
            (cash, TxnType.DEPOSIT, 50, {"amount": 5000, "currency": "USD"}),
            (cash, TxnType.BUY, 45, {"symbol": "AAPL", "quantity": 5, "price": 200, "currency": "USD"}),
            (cash, TxnType.SELL, 10, {"symbol": "AAPL", "quantity": 1, "price": 230, "currency": "USD"}),
            (cash, TxnType.FEE, 5, {"amount": 9.99, "currency": "USD"}),
            (tfsa, TxnType.SPLIT, 3, {"symbol": "XEQT.TO", "ratio": 2}),
            (old, TxnType.BUY, 90, {"symbol": "MSFT", "quantity": 3, "price": 380, "currency": "USD"}),
        ]
        for acct, kind, ago, fields in rows:
            store.add_transaction(Transaction(account_id=acct.saved_id, type=kind, date=day(ago), **fields))
        old.archived = True  # must be hidden everywhere, and left out of totals
        store.update_account(old)
        store.add_alert(Alert(symbol="AAPL", condition="above", threshold=1, note="always fires"))
        store.add_watch(["NVDA", "VFV.TO"])
    finally:
        store.close()


def sample_csv(path: Path) -> None:
    today = date.today().isoformat()
    path.write_text(
        "date,account,type,symbol,quantity,price,currency,amount\n"
        f"{today},Everyday TFSA,BUY,VFV.TO,2,140,CAD,\n"
        f"{today},Old RRSP,BUY,MSFT,1,400,USD,\n"  # skipped: archived account
        f"{today},New FHSA,DEPOSIT,,,,CAD,500\n"  # creates New FHSA
        "2024-13-40,Everyday TFSA,BUY,VFV.TO,1,1,CAD,\n",  # skipped: invalid date
        encoding="utf-8",
    )


def quit_running(app: Path) -> None:
    """Quit processes running this exact QA executable, and nothing else."""
    exe = str(app / "Contents" / "MacOS" / "MarketPulseBar")
    listing = subprocess.run(["ps", "-Ao", "pid=,command="], capture_output=True, text=True, check=False).stdout
    pids = []
    for line in listing.splitlines():
        pid, _, command = line.strip().partition(" ")
        if command == exe or command.startswith(exe + " "):
            pids.append(int(pid))
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # exited since the listing
    deadline = time.monotonic() + 5
    while pids and time.monotonic() < deadline:
        time.sleep(0.1)
        pids = [pid for pid in pids if _alive(pid)]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def build_app(out: Path, menubar: bool) -> Path:
    subprocess.run(["swift", "build", "-c", "release", "--package-path", str(PACKAGE)], check=True)
    bin_dir = subprocess.run(
        ["swift", "build", "-c", "release", "--package-path", str(PACKAGE), "--show-bin-path"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    app = out / f"{APP_NAME}.app"
    shutil.rmtree(app, ignore_errors=True)
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Resources").mkdir()
    shutil.copy2(Path(bin_dir) / "MarketPulseBar", app / "Contents" / "MacOS" / "MarketPulseBar")
    shutil.copy2(PACKAGE / "AppIcon.icns", app / "Contents" / "Resources" / "AppIcon.icns")
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(
            {
                "CFBundleName": APP_NAME,
                "CFBundleIdentifier": BUNDLE_ID,
                "CFBundleExecutable": "MarketPulseBar",
                "CFBundleIconFile": "AppIcon",
                "CFBundlePackageType": "APPL",
                "LSMinimumSystemVersion": "14.0",
                "LSUIElement": menubar,
            },
            f,
        )
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=False, capture_output=True)
    return app


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("The QA app is macOS-only.")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("/tmp/marketpulse-qa"))
    parser.add_argument("--menubar", action="store_true", help="Menu bar mode (no Dock icon, no window at launch).")
    parser.add_argument("--fresh", action="store_true", help="Reset the scratch ledger, settings, and app defaults.")
    args = parser.parse_args()
    out: Path = args.out.expanduser().resolve()
    check_out(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("Created by scripts/qa_app.py (MarketPulse QA). Safe to delete.\n", encoding="utf-8")
    data = out / "data"
    # A QA copy that's still running keeps its old mode (desktop vs menu bar) and state,
    # and `open` would just reactivate it; quit it before rebuilding.
    quit_running(out / f"{APP_NAME}.app")
    if args.fresh:
        # A known starting point: ledger, settings (e.g. privacy left on), and the app's defaults.
        shutil.rmtree(data, ignore_errors=True)
        (out / "config.toml").unlink(missing_ok=True)
        subprocess.run(["defaults", "delete", BUNDLE_ID], check=False, capture_output=True)
    if not (data / "marketpulse.db").exists():
        data.mkdir(parents=True, exist_ok=True)
        seed(data)
    sample_csv(out / "sample-import.csv")
    app = build_app(out, args.menubar)
    cli = Path(sys.executable).parent / "marketpulse"
    launch = out / "launch.sh"
    launch.write_text(
        "#!/bin/sh\n# Opens the QA app on the scratch ledger; run it again to send a Dock-style reopen event.\n"
        f"exec open --env MARKETPULSE_CLI={shlex.quote(str(cli))} --env MARKETPULSE_DATA={shlex.quote(str(data))} "
        f"--env MARKETPULSE_CONFIG={shlex.quote(str(out / 'config.toml'))} {shlex.quote(str(app))}\n",
        encoding="utf-8",
    )
    launch.chmod(0o755)
    print(f"QA app:        {app}")
    print(f"Scratch data:  {data}")
    print(f"Sample CSV:    {out / 'sample-import.csv'}")
    print(f"Launch:        {launch}")
    print("Checklist:     docs/qa.md")


if __name__ == "__main__":
    main()
