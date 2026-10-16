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


def swift_build(arch: str | None = None) -> Path:
    """Compile the Swift app in release mode and return the executable (`arch`: arm64 or x86_64)."""
    args = ["swift", "build", "-c", "release", "--package-path", str(PROJECT_DIR)]
    if arch:
        args += ["--arch", arch]
    subprocess.run(args, check=True)
    bin_dir = subprocess.run(args + ["--show-bin-path"], check=True, capture_output=True, text=True).stdout.strip()
    return Path(bin_dir) / "MarketPulseBar"


def info_plist(name: str, bundle_id: str, version: str, *, menubar: bool) -> dict:
    return {
        "CFBundleName": name,
        "CFBundleDisplayName": name,
        "CFBundleIdentifier": bundle_id,
        "CFBundleExecutable": "MarketPulseBar",
        "CFBundleIconFile": "AppIcon",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": "14.0",
        "LSUIElement": menubar,
        "NSHighResolutionCapable": True,
    }


def assemble_app(app: Path, binary: Path, plist: dict) -> None:
    """Lay out an unsigned bundle: executable, icon and Info.plist. Callers sign it."""
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (app / "Contents" / "Resources").mkdir()
    shutil.copy2(binary, macos / "MarketPulseBar")
    # Dock, Finder and Login Items icon (regenerate with scripts/make_app_icon.swift).
    icon = PROJECT_DIR / "AppIcon.icns"
    if icon.is_file():
        shutil.copy2(icon, app / "Contents" / "Resources" / "AppIcon.icns")
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(plist, f)


def build_and_install(log=print, *, desktop: bool = False) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("The menu bar companion is macOS-only. On Omarchy, use `marketpulse status --waybar`.")
    if not (PROJECT_DIR / "Package.swift").is_file():
        raise RuntimeError(f"Swift sources not found at {PROJECT_DIR}. Install MarketPulse from a source checkout.")
    if shutil.which("swift") is None:
        raise RuntimeError("Swift toolchain not found. Install Xcode or the Command Line Tools: xcode-select --install")

    log("Compiling MarketPulse Bar (swift build -c release)…")
    binary = swift_build()

    app = app_path()
    if app.exists():
        subprocess.run(["pkill", "-x", "MarketPulseBar"], check=False, capture_output=True)
        shutil.rmtree(app)
    from . import __version__

    assemble_app(app, binary, info_plist(APP_NAME, BUNDLE_ID, __version__, menubar=not desktop))
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=False, capture_output=True)
    subprocess.run(["defaults", "write", BUNDLE_ID, "cliPath", cli_path()], check=False)
    env_data = os.environ.get("MARKETPULSE_DATA")
    for key, value in (("dataDir", env_data), ("configPath", os.environ.get("MARKETPULSE_CONFIG"))):
        command = (
            ["defaults", "write", BUNDLE_ID, key, str(Path(value).expanduser().resolve())]
            if value
            else ["defaults", "delete", BUNDLE_ID, key]
        )
        try:
            subprocess.run(command, check=False, capture_output=not value, timeout=30)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"`defaults` timed out while updating {key}; run the install again.") from e
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
