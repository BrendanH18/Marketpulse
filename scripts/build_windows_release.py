"""Build and verify the Windows x64 release: an Inno Setup installer, a portable zip, install.ps1, and SHA256SUMS.

    uv run --locked python scripts/build_windows_release.py
    uv run --locked python scripts/build_windows_release.py --out "dist/windows-release" --iscc "C:/Inno Setup/ISCC.exe"
    uv run --locked python scripts/build_windows_release.py --verify dist/windows-release

Build on Windows x64 with uv, the .NET SDK, and Inno Setup 6.3 or later (ISCC.exe from --iscc, PATH, or
the standard install folders). The build reuses scripts/build_windows_backend.py (including its relocation
smoke test), publishes MarketPulse.exe with the package version, adds the backend as MarketPulse-backend,
runs the app's fictional bridge check, then writes into --out (default dist/windows-release):

    MarketPulse-<version>-windows-x64-setup.exe   per-user installer (windows/installer/MarketPulse.iss)
    MarketPulse-<version>-windows-x64.zip         portable copy: MarketPulse/MarketPulse.exe + MarketPulse-backend/
    install.ps1                                   copy of scripts/install.ps1
    SHA256SUMS

Finally it installs the setup silently into a temporary folder, checks the installed version, bridge, upgrade
in place, uninstall registry entry, and Start menu shortcut, then uninstalls it. Everything it runs uses
fictional data in temporary folders. --verify checks an existing release folder without building.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from types import ModuleType

from marketpulse import __version__

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "windows" / "MarketPulse.Demo" / "MarketPulse.Demo.csproj"
ISS = ROOT / "windows" / "installer" / "MarketPulse.iss"
INSTALL_SCRIPT = "install.ps1"
APP_DIR = "MarketPulse"  # the portable zip's single top-level folder
EXE = "MarketPulse.exe"
BACKEND = "MarketPulse-backend"
PUBLISHER = "MarketPulse contributors"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
SILENT = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
TIMEOUT = 600  # seconds for one setup or uninstall run


def _script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*args: str | Path, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def setup_name(version: str = __version__) -> str:
    return f"MarketPulse-{version}-windows-x64-setup.exe"


def zip_name(version: str = __version__) -> str:
    return f"MarketPulse-{version}-windows-x64.zip"


def app_id() -> str:
    """The installer's fixed AppId GUID, read from the .iss so it's defined in one place."""
    match = re.search(r"^AppId=\{\{([0-9A-Fa-f-]{36})\}\s*$", ISS.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise SystemExit(f"No AppId={{{{GUID}} line in {ISS}.")
    return match.group(1).upper()


def scratch_env(scratch: Path) -> dict[str, str]:
    """The current environment, with MarketPulse's data and settings pointed at a scratch folder."""
    env = dict(os.environ)
    env.update(MARKETPULSE_DATA=str(scratch / "data"), MARKETPULSE_CONFIG=str(scratch / "config.toml"))
    return env


def find_iscc(explicit: Path | None) -> Path:
    if explicit:
        if not explicit.is_file():
            raise SystemExit(f"--iscc {explicit} doesn't exist.")
        return explicit
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for root in filter(None, roots):
        for candidate in (
            Path(root) / "Inno Setup 6" / "ISCC.exe",
            Path(root) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        ):
            if candidate.is_file():
                return candidate
    raise SystemExit("Couldn't find ISCC.exe; install Inno Setup 6 or pass --iscc.")


def file_versions(exe: Path) -> tuple[str, str]:
    """(ProductVersion, FileVersion) from the executable's version resource, as Windows reports them."""
    script = "$v = (Get-Item -LiteralPath $env:MARKETPULSE_VERSION_FILE).VersionInfo; "
    script += '"$($v.ProductVersion)|$($v.FileVersion)"'
    env = dict(os.environ, MARKETPULSE_VERSION_FILE=str(exe))
    out = run(
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        script,
        env=env,
        capture_output=True,
        text=True,
    ).stdout.strip()
    product, _, file = out.partition("|")
    return product.strip(), file.strip()


def check_exe_version(exe: Path, version: str = __version__) -> None:
    product, file = file_versions(exe)
    if product != version or not (file == version or file.startswith(f"{version}.")):
        raise SystemExit(f"{exe}: ProductVersion {product!r}, FileVersion {file!r}; expected {version}.")


def check_bridge(exe: Path) -> None:
    """MarketPulse.exe --check-bridge reads a fictional snapshot through the bundled backend."""
    with tempfile.TemporaryDirectory(prefix="marketpulse-bridge-check-") as tmp:
        result = subprocess.run(
            [str(exe), "--check-bridge"],
            env=scratch_env(Path(tmp)),
            cwd=tmp,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    print(result.stdout.strip() or "(no output)")
    if result.returncode != 0:
        raise SystemExit(f"{exe} --check-bridge exited {result.returncode}: {result.stderr.strip()}")


def publish_app(backend: Path, app: Path, version: str = __version__) -> None:
    """Publish the self-contained app into a fresh `app` folder and add the backend beside MarketPulse.exe."""
    env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1")
    rid = ["-p:RuntimeIdentifier=win-x64", "-p:SelfContained=true"]
    run("dotnet", "restore", PROJECT, "--locked-mode", *rid, env=env)
    publish: list[str | Path] = [
        "publish",
        PROJECT,
        "-c",
        "Release",
        "-r",
        "win-x64",
        "--self-contained",
        "true",
        "--no-restore",
    ]
    run("dotnet", *publish, f"-p:Version={version}", "-o", app, env=env)
    if not (app / EXE).is_file():
        raise SystemExit(f"dotnet publish didn't produce {app / EXE}.")
    if (app / BACKEND).exists():
        raise SystemExit(f"{app / BACKEND} already exists; publish into a fresh folder.")
    shutil.copytree(backend, app / BACKEND)


def write_zip(app: Path, path: Path) -> None:
    """Zip `app` under one top-level MarketPulse/ folder."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
        for file in sorted(p for p in app.rglob("*") if p.is_file()):
            archive.write(file, f"{APP_DIR}/{file.relative_to(app).as_posix()}")


def compile_installer(iscc: Path, app: Path, out: Path, version: str = __version__) -> Path:
    run(iscc, "/Q", f"/DAppVersion={version}", f"/DAppSource={app}", f"/O{out}", ISS)
    setup = out / setup_name(version)
    if not setup.is_file():
        raise SystemExit(f"ISCC didn't produce {setup}.")
    return setup


def uninstall_entry(guid: str) -> dict[str, str] | None:
    """The per-user Settings > Apps entry Inno Setup writes for this AppId, or None."""
    if sys.platform != "win32":
        raise SystemExit("Reading the uninstall entry needs Windows.")
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{UNINSTALL_KEY}\{{{guid}}}_is1") as key:
            values: dict[str, str] = {}
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    return values
                values[name] = str(value)
                index += 1
    except FileNotFoundError:
        return None


def silent(command: str, *, cwd: Path, log: Path | None = None) -> None:
    """Run setup or uninstall with a command line as Inno Setup documents it (/DIR="...")."""
    # A string, not a list, so /DIR="C:\path with spaces" reaches Inno Setup exactly as documented.
    result = subprocess.run(command, cwd=cwd, timeout=TIMEOUT)
    if result.returncode != 0:
        if log and log.is_file():
            print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]))
        raise SystemExit(f"{command} exited {result.returncode}.")


def start_app(exe: Path, scratch: Path) -> subprocess.Popen | None:
    """Leave the installed app running (read-only fictional portfolio) so setup and uninstall must close it."""
    process = subprocess.Popen([str(exe), "--demo"], env=scratch_env(scratch), cwd=scratch)
    time.sleep(8)
    if process.poll() is not None:
        print(f"  Note: MarketPulse.exe --demo exited ({process.returncode}) on its own; closing it isn't exercised.")
        return None
    return process


def wait_closed(process: subprocess.Popen | None, step: str) -> None:
    if process is None:
        return
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        raise SystemExit(f"{step} left MarketPulse.exe running.") from None
    print(f"  {step} closed the running app.")


def smoke_test_installer(setup: Path, version: str = __version__) -> None:
    """Install, upgrade in place, and uninstall `setup` in a temporary folder."""
    guid = app_id()
    if uninstall_entry(guid) is not None:
        raise SystemExit(
            "MarketPulse is already installed for this Windows user; uninstall it or pass --skip-install-test "
            "(the test installs and uninstalls the same app)."
        )
    shortcut = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "MarketPulse.lnk"
    with tempfile.TemporaryDirectory(prefix="marketpulse-installer-smoke-", ignore_cleanup_errors=True) as tmp:
        # Long path names: the uninstaller matches running programs by their full path under {app}.
        scratch = Path(tmp).resolve()
        target = scratch / "Programs" / "MarketPulse test"
        log = scratch / "setup.log"
        install = f'"{setup}" {" ".join(SILENT)} /SP- /DIR="{target}" /LOG="{log}"'
        uninstaller = target / "unins000.exe"
        app: subprocess.Popen | None = None
        try:
            silent(install, cwd=scratch, log=log)
            exe = target / EXE
            for path in (exe, uninstaller, target / BACKEND / "python" / "python.exe", shortcut):
                if not path.is_file():
                    raise SystemExit(f"Installing didn't create {path}.")
            check_exe_version(exe, version)
            check_bridge(exe)
            entry = uninstall_entry(guid)
            if entry is None:
                raise SystemExit(f"No HKCU uninstall entry for {{{guid}}}_is1.")
            expected = {"DisplayName": "MarketPulse", "DisplayVersion": version, "Publisher": PUBLISHER}
            if any(entry.get(k) != v for k, v in expected.items()):
                raise SystemExit(f"Uninstall entry {entry} doesn't match {expected}.")
            if Path(entry.get("InstallLocation", "")).resolve() != target.resolve():
                raise SystemExit(f"Uninstall entry points at {entry.get('InstallLocation')!r}, not {target}.")
            print(f"  Installed {version} to {target}: version, bridge, shortcut, and uninstall entry OK.")

            stale = target / BACKEND / "stale-from-older-version.txt"
            stale.write_text("fictional leftover", encoding="utf-8")
            app = start_app(exe, scratch)
            silent(install, cwd=scratch, log=log)
            wait_closed(app, "Upgrading")
            if stale.exists() or not exe.is_file():
                raise SystemExit("Upgrading in place didn't replace the backend cleanly.")
            check_bridge(exe)
            print("  Upgrade in place removed stale backend files.")

            app = start_app(exe, scratch)
            silent(f'"{uninstaller}" {" ".join(SILENT)}', cwd=scratch)
            # The uninstaller copies itself to %TEMP% and returns at once; wait for that copy to finish.
            deadline = time.monotonic() + TIMEOUT
            while target.exists() or uninstall_entry(guid) is not None or shortcut.exists():
                if time.monotonic() > deadline:
                    raise SystemExit(f"Uninstalling left {target}, its registry entry, or the shortcut behind.")
                time.sleep(2)
            wait_closed(app, "Uninstalling")
            print("  Uninstalled: install folder, registry entry, and shortcut removed.")
        finally:
            if app is not None and app.poll() is None:
                app.kill()
            if uninstaller.exists():  # a failed check: leave this Windows user as we found them
                subprocess.run([str(uninstaller), *SILENT], timeout=TIMEOUT)
    print(f"PASS: {setup.name} installs, upgrades in place, and uninstalls.")


def verify(folder: Path, version: str = __version__) -> None:
    """A Windows release folder holds exactly the setup, zip, and install.ps1, and they match SHA256SUMS."""
    release = _script("release")
    files = release.check_sums(folder)
    expected = release.windows_release_names(version)  # what `release.py combine` expects too
    if expected != {setup_name(version), zip_name(version), INSTALL_SCRIPT}:
        raise SystemExit("scripts/release.py and this script disagree on the Windows release file names.")
    if {p.name for p in files} != expected:
        raise SystemExit(f"Expected exactly {sorted(expected)}, found {sorted(p.name for p in files)}.")
    if (folder / INSTALL_SCRIPT).read_bytes() != (ROOT / "scripts" / INSTALL_SCRIPT).read_bytes():
        raise SystemExit(f"{INSTALL_SCRIPT} isn't this checkout's scripts/{INSTALL_SCRIPT}.")
    if (folder / setup_name(version)).read_bytes()[:2] != b"MZ":
        raise SystemExit(f"{setup_name(version)} isn't a Windows executable.")
    with zipfile.ZipFile(folder / zip_name(version)) as archive:
        names = archive.namelist()
    if not names or any(not n.startswith(f"{APP_DIR}/") for n in names):
        raise SystemExit(f"{zip_name(version)} must hold one top-level {APP_DIR}/ folder.")
    if f"{APP_DIR}/{EXE}" not in names:
        raise SystemExit(f"{zip_name(version)} has no {APP_DIR}/{EXE}.")
    site = f"{APP_DIR}/{BACKEND}/python/Lib/site-packages/"
    dist_infos = sorted({n[len(site) :].split("/")[0] for n in names if re.match(rf"{re.escape(site)}marketpulse-", n)})
    if dist_infos != [f"marketpulse-{version}.dist-info"]:
        raise SystemExit(f"{zip_name(version)} bundles {dist_infos}, expected marketpulse-{version}.dist-info.")
    print(f"PASS: {folder} is a complete MarketPulse {version} Windows release.")


def build(out: Path, work: Path, iscc: Path, *, backend_smoke: bool, install_test: bool) -> None:
    if not (ROOT / "scripts" / INSTALL_SCRIPT).is_file():
        raise SystemExit(f"scripts/{INSTALL_SCRIPT} is missing.")
    backend_script = _script("build_windows_backend")
    (work / "backend-build").mkdir(parents=True)
    backend = backend_script.build("x86_64", work / "backend", work / "backend-build")
    if backend_smoke:
        backend_script.smoke_test(backend)
    else:
        print("Skipped the backend smoke test.")
    app = work / APP_DIR
    publish_app(backend, app)
    check_exe_version(app / EXE)
    check_bridge(app / EXE)

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    write_zip(app, out / zip_name())
    setup = compile_installer(iscc, app, out)
    shutil.copy2(ROOT / "scripts" / INSTALL_SCRIPT, out / INSTALL_SCRIPT)
    _script("release").write_sums(out)
    for path in sorted(out.iterdir()):
        print(f"{path.name}  ({path.stat().st_size / 1_000_000:.0f} MB)")
    verify(out)
    if install_test:
        smoke_test_installer(setup)
    else:
        print("Skipped the installer smoke test.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "windows-release")
    parser.add_argument("--iscc", type=Path, help="Inno Setup's ISCC.exe (default: PATH, then Program Files).")
    parser.add_argument(
        "--work",
        type=Path,
        help="Keep intermediate files here (must be new or empty); the app is in <work>/MarketPulse.",
    )
    parser.add_argument("--skip-smoke", action="store_true", help="Skip the backend smoke test (local debugging only).")
    parser.add_argument(
        "--skip-install-test", action="store_true", help="Skip installing and uninstalling (local debugging only)."
    )
    parser.add_argument("--verify", type=Path, metavar="FOLDER", help="Only check an existing Windows release folder.")
    args = parser.parse_args()
    if args.verify:
        verify(args.verify.resolve())
        return
    if sys.platform != "win32":
        raise SystemExit("Build the Windows release on Windows.")
    iscc = find_iscc(args.iscc)
    options = {"backend_smoke": not args.skip_smoke, "install_test": not args.skip_install_test}
    if args.work:
        work = args.work.expanduser().resolve()
        if work.exists() and any(work.iterdir()):
            raise SystemExit(f"--work {work} isn't empty.")
        build(args.out.expanduser().resolve(), work, iscc, **options)
    else:
        with tempfile.TemporaryDirectory(prefix="marketpulse-windows-release-") as tmp:
            build(args.out.expanduser().resolve(), Path(tmp), iscc, **options)


if __name__ == "__main__":
    main()
