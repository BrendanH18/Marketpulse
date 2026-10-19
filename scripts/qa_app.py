"""Build a throwaway copy of the native app on a fictional scratch ledger, for manual or
computer-use QA. Never touches your real ledger, settings, or installed app.

    uv run --locked python scripts/qa_app.py              # desktop mode (Dock icon)
    uv run --locked python scripts/qa_app.py --menubar    # menu bar mode
    uv run --locked python scripts/qa_app.py --out ~/mp-qa --fresh
    uv run --locked python scripts/qa_app.py --bundled     # with its own Python, as releases ship
    uv run --locked python scripts/qa_app.py --empty       # a brand-new ledger, for first-run onboarding

The default folder is in your per-user temp directory ($TMPDIR on macOS), which other
users can't write to. Then run the printed `launch.sh`, and follow docs/qa.md.
"""

from __future__ import annotations

import argparse
import os
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

from marketpulse import __version__
from marketpulse.config import config_path
from marketpulse.db import Store
from marketpulse.menubar import assemble_app, info_plist, swift_build
from marketpulse.models import Account, AccountType, Alert, Transaction, TxnType

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
    if not out.exists():
        return
    # Reusing a folder (the default is in the shared /tmp): it must be ours, made by this script,
    # and free of symlinks, or a link inside it (say `data`) could point the QA app at real data.
    if out.stat().st_uid != os.getuid():
        raise SystemExit(f"{out} belongs to another user. Choose another folder.")
    if any(out.iterdir()) and not (out / MARKER).is_file():
        raise SystemExit(f"{out} exists and wasn't created by this script. Choose a new or empty folder.")
    for root, dirs, files in os.walk(out):
        for name in dirs + files:
            if (Path(root) / name).is_symlink():
                raise SystemExit(f"{Path(root) / name} is a symbolic link. Delete {out} and run again.")
        if Path(root) == out and f"{APP_NAME}.app" in dirs:
            dirs.remove(f"{APP_NAME}.app")  # rebuilt each run; a bundled Python has its own links


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


def build_app(out: Path, menubar: bool, bundled: bool) -> Path:
    if bundled:  # the release layout, with its own Python backend (scripts/build_app.py)
        from build_app import build, build_wheel  # scripts/ is on sys.path when this runs as a script

        arch = "arm64" if platform.machine() == "arm64" else "x86_64"
        with tempfile.TemporaryDirectory(prefix="marketpulse-qa-build-") as tmp:
            wheel = build_wheel(Path(tmp) / "wheel")
            return build(arch, out, wheel, Path(tmp), name=APP_NAME, bundle_id=BUNDLE_ID, menubar=menubar)
    app = out / f"{APP_NAME}.app"
    shutil.rmtree(app, ignore_errors=True)
    assemble_app(app, swift_build(), info_plist(APP_NAME, BUNDLE_ID, __version__, menubar=menubar))
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=False, capture_output=True)
    return app


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("The QA app is macOS-only.")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Per-user (not the shared /tmp), so no other account can plant links in it.
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "marketpulse-qa")
    parser.add_argument("--menubar", action="store_true", help="Menu bar mode (no Dock icon, no window at launch).")
    parser.add_argument("--fresh", action="store_true", help="Reset the scratch ledger, settings, and app defaults.")
    parser.add_argument("--bundled", action="store_true", help="Bundle a Python backend, as releases do.")
    parser.add_argument(
        "--empty", action="store_true", help="Start from an empty ledger, as a new user does. Implies --fresh."
    )
    args = parser.parse_args()
    args.fresh = args.fresh or args.empty
    out: Path = args.out.expanduser().resolve()
    check_out(out)
    if not out.exists():
        try:
            out.mkdir(parents=True)  # fails if anything (say, a symlink) appeared here since the check
        except FileExistsError:
            raise SystemExit(f"{out} appeared while setting up. Choose another folder.") from None
    if out.is_symlink() or not out.is_dir():
        raise SystemExit(f"{out} changed while setting up. Choose another folder.")
    check_out(out)  # again, on what's actually there now
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
        if not args.empty:
            seed(data)
    sample_csv(out / "sample-import.csv")
    app = build_app(out, args.menubar, args.bundled)
    # The bundled app finds its own backend; otherwise point it at this checkout's CLI.
    checkout_cli = shlex.quote(str(Path(sys.executable).parent / "marketpulse"))
    cli = "" if args.bundled else f"--env MARKETPULSE_CLI={checkout_cli} "
    launch = out / "launch.sh"
    launch.write_text(
        "#!/bin/sh\n# Opens the QA app on the scratch ledger; run it again to send a Dock-style reopen event.\n"
        f"exec open {cli}--env MARKETPULSE_DATA={shlex.quote(str(data))} "
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
