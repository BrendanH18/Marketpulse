"""Build and install the native macOS menu bar companion (macos/MarketPulseBar)."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

BUNDLE_ID = "dev.marketpulse.bar"
APP_NAME = "MarketPulse Bar"
PROJECT_DIR = Path(__file__).resolve().parents[2] / "macos" / "MarketPulseBar"


def app_path() -> Path:
    return Path.home() / "Applications" / f"{APP_NAME}.app"


def cli_path() -> str:
    """Absolute path of the marketpulse executable the menu bar should run."""
    found = shutil.which("marketpulse")
    if found:
        return str(Path(found).resolve())
    argv0 = Path(sys.argv[0])
    if argv0.name in ("marketpulse", "mp") and argv0.exists():
        return str(argv0.resolve())
    return str(Path(sys.executable).parent / "marketpulse")


def build_and_install(log=print) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("The menu bar companion is macOS-only. On Omarchy, use `marketpulse status --waybar`.")
    if not (PROJECT_DIR / "Package.swift").is_file():
        raise RuntimeError(f"Swift sources not found at {PROJECT_DIR}. Install MarketPulse from a source checkout.")
    if shutil.which("swift") is None:
        raise RuntimeError("Swift toolchain not found. Install Xcode or the Command Line Tools: xcode-select --install")

    log("Compiling MarketPulse Bar (swift build -c release)…")
    subprocess.run(["swift", "build", "-c", "release", "--package-path", str(PROJECT_DIR)], check=True)
    bin_dir = subprocess.run(
        ["swift", "build", "-c", "release", "--package-path", str(PROJECT_DIR), "--show-bin-path"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    binary = Path(bin_dir) / "MarketPulseBar"

    app = app_path()
    if app.exists():
        subprocess.run(["pkill", "-x", "MarketPulseBar"], check=False, capture_output=True)
        shutil.rmtree(app)
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (app / "Contents" / "Resources").mkdir()
    shutil.copy2(binary, macos / "MarketPulseBar")
    from . import __version__

    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(
            {
                "CFBundleName": APP_NAME,
                "CFBundleDisplayName": APP_NAME,
                "CFBundleIdentifier": BUNDLE_ID,
                "CFBundleExecutable": "MarketPulseBar",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": __version__,
                "CFBundleVersion": __version__,
                "LSMinimumSystemVersion": "14.0",
                "LSUIElement": True,  # menu bar only, no Dock icon
                "NSHighResolutionCapable": True,
            },
            f,
        )
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=False, capture_output=True)
    subprocess.run(["defaults", "write", BUNDLE_ID, "cliPath", cli_path()], check=False)
    env_data = os.environ.get("MARKETPULSE_DATA")
    if env_data:
        subprocess.run(["defaults", "write", BUNDLE_ID, "dataDir", env_data], check=False)
    log(f"Installed {app}")
    subprocess.run(["open", str(app)], check=False)
    return app


def uninstall(log=print) -> bool:
    app = app_path()
    subprocess.run(["pkill", "-x", "MarketPulseBar"], check=False, capture_output=True)
    if app.exists():
        shutil.rmtree(app)
        log(f"Removed {app}")
        return True
    return False
