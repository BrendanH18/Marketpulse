"""Build MarketPulse.app with its own Python backend, so users need no Python, uv, or Xcode.

    uv run --locked python scripts/build_app.py                       # this Mac's architecture
    uv run --locked python scripts/build_app.py --arch arm64 --arch x86_64
    uv run --locked python scripts/build_app.py --out ~/mp-build --skip-smoke

Each architecture lands in `<out>/<arch>/MarketPulse.app` (default `dist/app`). The bundle carries
a pinned, relocatable CPython (python-build-standalone, the builds uv installs) with the wheel and
its locked dependencies under `Contents/Resources/backend/`, and is ad-hoc signed: no Developer ID,
by decision (docs/app-plan.md). Building needs uv and the Swift toolchain; running the app needs neither.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from marketpulse import __version__
from marketpulse.menubar import assemble_app, info_plist, swift_build

ROOT = Path(__file__).resolve().parents[1]
PYTHON = "3.14.7"  # bump deliberately; the smoke test checks the bundle reports this version
APP_NAME = "MarketPulse"
BUNDLE_ID = "dev.marketpulse.app"
ARCHES = {"arm64": ("aarch64", "aarch64-apple-darwin"), "x86_64": ("x86_64", "x86_64-apple-darwin")}
MACHO_MAGIC = {
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
}
# Never used by the CLI, TUI, or bridge: GUI toolkits, IDLE, the test suite, headers, and pip.
STRIP = [
    "BUILD",
    "include",
    "share",
    "lib/pkgconfig",
    "lib/itcl*",
    "lib/tcl*",
    "lib/tk*",
    "lib/thread*",
    "lib/libtcl*",
    "lib/libpython*.dylib",  # bin/python links the interpreter statically
    "lib/python3.*/test",
    "lib/python3.*/idlelib",
    "lib/python3.*/tkinter",
    "lib/python3.*/turtledemo",
    "lib/python3.*/ensurepip",
    "lib/python3.*/config-*",
    "lib/python3.*/lib-dynload/_tkinter*",
    "lib/python3.*/site-packages/*",
    "bin/idle*",
    "bin/pip*",
    "bin/pydoc*",
    "bin/*-config",
]
LAUNCHER = """#!/bin/sh
# MarketPulse's bundled backend. Runs the app's own Python in isolated mode (-I), so nothing from
# the user's Python setup (PYTHONPATH, user site-packages) leaks in, and never writes bytecode (-B)
# into the signed bundle. Resolves symlinks, so a link on PATH works too.
here=$(dirname "$(/bin/realpath "$0")") || exit 1
exec "$here/../python/bin/python3" -I -B -m marketpulse "$@"
"""


def run(*args: str | Path, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def build_wheel(dest: Path) -> Path:
    run("uv", "build", "--wheel", "--no-sources", "--out-dir", dest, cwd=ROOT)
    (wheel,) = dest.glob("marketpulse-*.whl")
    if wheel.name.split("-")[1] != __version__:
        raise SystemExit(f"{wheel.name} doesn't match marketpulse {__version__}.")
    return wheel


def fetch_python(arch: str, cache: Path) -> Path:
    """The pinned python-build-standalone install for `arch` (arm64 or x86_64)."""
    key = f"cpython-{PYTHON}-macos-{ARCHES[arch][0]}-none"
    run("uv", "python", "install", key, "--install-dir", cache, "--no-bin")
    return cache / key


def strip(python: Path) -> None:
    for pattern in STRIP:
        for path in python.glob(pattern):
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
    for cache in python.rglob("__pycache__"):
        shutil.rmtree(cache)


def install_packages(python: Path, arch: str, wheel: Path, work: Path) -> None:
    """Install the locked dependencies, then the wheel, without running the target interpreter
    (so an Intel bundle builds on Apple Silicon without Rosetta)."""
    (site,) = python.glob("lib/python3.*/site-packages")
    requirements = work / "requirements.txt"
    run("uv", "export", "--locked", "--no-dev", "--no-emit-project", "--no-header", "-q", "-o", requirements, cwd=ROOT)
    common = ["--target", site, "--python-platform", ARCHES[arch][1], "--python-version", PYTHON]
    common += ["--only-binary", ":all:", "--no-deps"]
    run("uv", "pip", "install", *common, "--require-hashes", "-r", requirements)
    run("uv", "pip", "install", *common, wheel)
    for script_dir in site.glob("bin"):  # console scripts carry build-machine shebangs; the launcher replaces them
        shutil.rmtree(script_dir)


def precompile(python: Path, host_python: Path) -> None:
    """Bytecode for everything, checked by hash rather than timestamp so copies and archives stay
    valid. Uses this Mac's copy of the same Python, since the bundle's may be another architecture."""
    (lib,) = python.glob("lib/python3.*")
    exe = host_python / "bin" / "python3"
    run(exe, "-I", "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash", lib)


def is_macho(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    with open(path, "rb") as f:
        return f.read(4) in MACHO_MAGIC


def sign(app: Path) -> None:
    """Ad-hoc sign every Mach-O, innermost first, then the bundle (which seals the rest), and verify."""
    nested = [p for p in (app / "Contents" / "Resources").rglob("*") if is_macho(p)]
    nested.sort(key=lambda p: len(p.parts), reverse=True)
    for i in range(0, len(nested), 50):
        run("codesign", "--force", "--sign", "-", "--timestamp=none", *nested[i : i + 50], capture_output=True)
    run("codesign", "--force", "--sign", "-", "--timestamp=none", app)
    run("codesign", "--verify", "--deep", "--strict", "--verbose=2", app)


def can_run(arch: str) -> bool:
    if arch == platform.machine():
        return True
    return subprocess.run(["/usr/bin/arch", f"-{arch}", "/usr/bin/true"], capture_output=True).returncode == 0


def smoke_test(app: Path, arch: str) -> None:
    """Run the bundled CLI with an empty environment and scratch data, so nothing on this Mac
    (Python, uv, PATH, a real ledger) can stand in for what the bundle carries."""
    cli = app / "Contents" / "Resources" / "backend" / "bin" / "marketpulse"
    with tempfile.TemporaryDirectory(prefix="marketpulse-smoke-") as tmp:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": tmp,
            "MARKETPULSE_DATA": f"{tmp}/data",
            "MARKETPULSE_CONFIG": f"{tmp}/config.toml",
            "NO_COLOR": "1",
        }

        def cli_run(*args: str) -> str:
            command = ["/usr/bin/arch", f"-{arch}", str(cli), *args]
            return run(*command, env=env, cwd="/", capture_output=True, text=True).stdout

        if not cli_run("--version").strip().endswith(__version__):
            raise SystemExit(f"Bundled backend doesn't report version {__version__}.")
        backend = json.loads(cli_run("desktop", "snapshot", "--demo"))["backend"]
        if backend != {"version": __version__, "python": PYTHON}:
            raise SystemExit(f"Bundled backend reports {backend}, expected {__version__} on Python {PYTHON}.")
        cli_run("deposit", "--currency", "CAD", "--", "100")
        if "DEPOSIT" not in cli_run("export"):
            raise SystemExit("The bundled backend didn't record a transaction.")
        python = app / "Contents" / "Resources" / "backend" / "python" / "bin" / "python3"
        command = ["/usr/bin/arch", f"-{arch}", str(python), "-I", "-B", "-c", "import curl_cffi, textual"]
        run(*command, env=env, cwd="/")  # native libraries load after relocation


def size_mb(path: Path) -> float:
    total = sum(p.lstat().st_size for p in path.rglob("*") if p.is_file() or p.is_symlink())
    return total / 1_000_000


def build(
    arch: str,
    out: Path,
    wheel: Path,
    work: Path,
    *,
    name: str = APP_NAME,
    bundle_id: str = BUNDLE_ID,
    menubar: bool = False,
) -> Path:
    app = out / f"{name}.app"
    if app.exists():
        shutil.rmtree(app)
    out.mkdir(parents=True, exist_ok=True)
    assemble_app(app, swift_build(arch), info_plist(name, bundle_id, __version__, menubar=menubar))
    backend = app / "Contents" / "Resources" / "backend"
    pythons = work / "python"
    shutil.copytree(fetch_python(arch, pythons), backend / "python", symlinks=True)
    strip(backend / "python")
    install_packages(backend / "python", arch, wheel, work)
    host = "arm64" if platform.machine() == "arm64" else "x86_64"
    precompile(backend / "python", fetch_python(host, pythons))
    (backend / "bin").mkdir()
    (backend / "bin" / "marketpulse").write_text(LAUNCHER, encoding="utf-8")
    (backend / "bin" / "marketpulse").chmod(0o755)
    sign(app)
    return app


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("MarketPulse.app builds on macOS only.")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arch", action="append", choices=sorted(ARCHES), help="Repeatable (default: this Mac's).")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "app")
    parser.add_argument("--wheel", type=Path, help="Bundle this wheel instead of building one.")
    parser.add_argument("--skip-smoke", action="store_true", help="Don't run the bundled backend after building.")
    args = parser.parse_args()
    arches = args.arch or ["arm64" if platform.machine() == "arm64" else "x86_64"]
    with tempfile.TemporaryDirectory(prefix="marketpulse-build-") as tmp:
        work = Path(tmp)
        wheel = args.wheel.resolve() if args.wheel else build_wheel(work / "wheel")
        with zipfile.ZipFile(wheel) as z:
            if f"marketpulse-{__version__}.dist-info/METADATA" not in z.namelist():
                raise SystemExit(f"{wheel.name} isn't marketpulse {__version__}.")
        for arch in arches:
            app = build(arch, args.out.expanduser().resolve() / arch, wheel, work)
            if args.skip_smoke:
                print(f"Skipped the smoke test for {arch}.")
            elif can_run(arch):
                smoke_test(app, arch)
            else:
                print(f"This Mac can't run {arch} code (Rosetta tests Intel builds); skipped the smoke test.")
            print(f"{app}  ({arch}, {size_mb(app):.0f} MB, MarketPulse {__version__}, Python {PYTHON})")


if __name__ == "__main__":
    main()
