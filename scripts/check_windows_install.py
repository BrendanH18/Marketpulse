"""Install a Windows release with scripts/install.ps1 from a local mirror, check it, and uninstall it.

    uv run --locked python scripts/check_windows_install.py "<windows release folder>"

The folder holds what a release publishes for Windows: MarketPulse-<version>-windows-x64-setup.exe,
the portable zip, install.ps1 and SHA256SUMS. The script serves it on 127.0.0.1 in GitHub's layout
(`latest` redirects to `tag/v<version>`; files are under `download/v<version>/`, as
application/octet-stream like GitHub's assets), then, in Windows PowerShell 5.1 and in PowerShell 7
if it is installed:

- runs install.ps1 as a file with -Version, and through `irm` in a script block without -Version
  (so it resolves the latest release), each into a scratch folder with -NoLaunch;
- checks MarketPulse.exe's ProductVersion and the per-user uninstall entry, then uninstalls silently
  and waits for the folder to disappear;
- checks that a mirror whose SHA256SUMS has the wrong hash for the installer makes install.ps1 fail
  without installing anything, in both ways of running it;
- reports whether a file downloaded with Invoke-WebRequest gets a Zone.Identifier stream (the Mark of
  the Web) as evidence for docs/install.md.

The child shells get scratch MARKETPULSE_DATA, MARKETPULSE_CONFIG and home folders with sentinel
files, which must be unchanged at the end. Needs Windows; exits non-zero on any failure.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


class CheckFailed(Exception):
    pass


def _release() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release_version(folder: Path) -> str:
    found = [
        m.group(1) for p in folder.iterdir() if (m := re.fullmatch(r"MarketPulse-(.+)-windows-x64-setup\.exe", p.name))
    ]
    if len(found) != 1:
        raise CheckFailed(f"Expected one MarketPulse-<version>-windows-x64-setup.exe in {folder}, found {len(found)}.")
    return found[0]


class Mirror:
    """A GitHub-releases-shaped tree served on 127.0.0.1 from a background thread."""

    def __init__(self, root: Path, tag: str) -> None:
        self.root, self.tag = root, tag
        self.requests: list[str] = []
        mirror = self

        class Handler(http.server.BaseHTTPRequestHandler):
            # Keep-alive like GitHub. Over HTTP/1.0, .NET sometimes reuses a connection the server has
            # just closed ("The response ended prematurely").
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:
                self._respond(body=True)

            def do_HEAD(self) -> None:
                self._respond(body=False)

            def log_message(self, format: str, *args: object) -> None:
                pass

            def _respond(self, *, body: bool) -> None:
                path = unquote(urlsplit(self.path).path)
                mirror.requests.append(f"{self.command} {path}")
                parts = [p for p in path.split("/") if p]
                if parts == ["latest"]:
                    return self._redirect(f"/tag/{mirror.tag}")
                if len(parts) == 3 and parts[:2] == ["latest", "download"]:
                    return self._redirect(f"/download/{mirror.tag}/{parts[2]}")
                if len(parts) == 2 and parts[0] == "tag":
                    return self._send(200, f"Release {parts[1]}".encode(), "text/html; charset=utf-8", body)
                if len(parts) == 3 and parts[0] == "download" and all(p not in (".", "..") for p in parts):
                    file = mirror.root / "download" / parts[1] / parts[2]
                    if file.is_file():
                        return self._send(200, file.read_bytes(), "application/octet-stream", body)
                self._send(404, b"Not Found", "text/plain", body)

            def _redirect(self, path: str) -> None:
                self.send_response(302)
                self.send_header("Location", f"{mirror.url}{path}")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _send(self, status: int, data: bytes, content_type: str, body: bool) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if body:
                    self.wfile.write(data)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    @contextmanager
    def serving(self) -> Iterator[Mirror]:
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        try:
            yield self
        finally:
            self.server.shutdown()
            self.server.server_close()


def publish(folder: Path, root: Path, version: str, *, wrong_hash: bool = False) -> Path:
    """Copy the release into root/download/v<version>/; optionally break the installer's SHA256SUMS line."""
    target = root / "download" / f"v{version}"
    target.mkdir(parents=True)
    for path in folder.iterdir():
        if path.is_file():
            shutil.copy2(path, target / path.name)
    if wrong_hash:
        setup = f"MarketPulse-{version}-windows-x64-setup.exe"
        sums = target / "SHA256SUMS"
        lines = sums.read_text(encoding="utf-8").splitlines()
        bad = hashlib.sha256(b"not the installer").hexdigest()
        lines = [f"{bad}  {setup}" if line.endswith(f"  {setup}") else line for line in lines]
        sums.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return target


def encoded(command: str) -> list[str]:
    """-EncodedCommand avoids every layer of command-line quoting."""
    return ["-EncodedCommand", base64.b64encode(command.encode("utf-16-le")).decode("ascii")]


def run_shell(shell: str, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # Text, not the CLIXML that -EncodedCommand otherwise writes to a redirected stderr.
    command = [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-OutputFormat", "Text", *args]
    return subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=900
    )


def product_version(shell: str, exe: Path, env: dict[str, str]) -> str:
    env = {**env, "MP_CHECK_EXE": str(exe)}
    result = run_shell(shell, encoded("(Get-Item -LiteralPath $env:MP_CHECK_EXE).VersionInfo.ProductVersion"), env)
    return result.stdout.strip()


def uninstall_entries(folder: Path) -> list[dict[str, str]]:
    """HKCU Inno Setup uninstall entries whose install folder is `folder`."""
    if sys.platform != "win32":
        return []
    import winreg

    entries = []
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as root:
        for index in range(winreg.QueryInfoKey(root)[0]):
            name = winreg.EnumKey(root, index)
            if not name.endswith("_is1"):
                continue
            with winreg.OpenKey(root, name) as key:
                values = {}
                for value in ("DisplayName", "DisplayVersion", "Inno Setup: App Path", "UninstallString"):
                    try:
                        values[value] = str(winreg.QueryValueEx(key, value)[0])
                    except OSError:
                        values[value] = ""
            app_path = values["Inno Setup: App Path"]
            if app_path and os.path.normcase(os.path.abspath(app_path)) == os.path.normcase(os.path.abspath(folder)):
                entries.append({"key": name, **values})
    return entries


def existing_install() -> str | None:
    """The folder MarketPulse is installed in for this Windows account (by the installer's AppId), if any."""
    if sys.platform != "win32":
        return None
    import winreg

    iss = (ROOT / "windows" / "installer" / "MarketPulse.iss").read_text(encoding="utf-8")
    match = re.search(r"^AppId=\{(\{[0-9A-Fa-f-]{36}\})\s*$", iss, re.M)
    if not match:
        raise CheckFailed("windows/installer/MarketPulse.iss has no AppId.")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{UNINSTALL_KEY}\{match.group(1)}_is1") as key:
            try:
                return str(winreg.QueryValueEx(key, "Inno Setup: App Path")[0])
            except OSError:
                return "an unknown folder"
    except FileNotFoundError:
        return None


def uninstall(folder: Path, timeout: float = 180) -> None:
    uninstaller = folder / "unins000.exe"
    if not uninstaller.is_file():
        raise CheckFailed(f"{uninstaller} is missing.")
    # Inno's uninstaller copies itself to a temporary folder, relaunches from there and exits at once,
    # so wait for the install folder to go rather than for the process.
    subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True, timeout=120)
    deadline = time.monotonic() + timeout
    while folder.exists() or uninstall_entries(folder):
        if time.monotonic() > deadline:
            left = sorted(str(p.relative_to(folder)) for p in folder.rglob("*")) if folder.exists() else []
            raise CheckFailed(
                f"Uninstalling didn't finish in {timeout:.0f} s; left {left[:20]} and {uninstall_entries(folder)}."
            )
        time.sleep(1)


class Checker:
    def __init__(self, folder: Path, work: Path) -> None:
        self.folder, self.work = folder, work
        self.version = release_version(folder)
        self.tag = f"v{self.version}"
        self.failures: list[str] = []
        self.runs = 0
        home = work / "home"
        self.sentinels = {
            home / ".marketpulse" / "sentinel.txt": "fictional ledger placeholder\n",
            home / ".config" / "marketpulse" / "config.toml": "# fictional config placeholder\n",
            work / "data" / "sentinel.txt": "scratch MARKETPULSE_DATA\n",
        }
        for path, text in self.sentinels.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.env = {
            **os.environ,
            "MARKETPULSE_DATA": str(work / "data"),
            "MARKETPULSE_CONFIG": str(work / "data" / "config.toml"),
            "USERPROFILE": str(home),
            "HOME": str(home),
            "NO_COLOR": "1",  # plain error text from PowerShell 7
        }

    def check_folder(self) -> None:
        release = _release()
        files = release.check_sums(self.folder)
        names = {p.name for p in files}
        if names != release.windows_release_names(self.version):
            raise CheckFailed(f"Expected {sorted(release.windows_release_names(self.version))}, found {sorted(names)}.")
        script = ROOT / "scripts" / release.INSTALLER_PS1
        if (self.folder / release.INSTALLER_PS1).read_bytes() != script.read_bytes():
            raise CheckFailed(f"{release.INSTALLER_PS1} in {self.folder} isn't this checkout's {script}.")
        print(f"{self.folder}: SHA256SUMS matches {len(files)} files for MarketPulse {self.version}.")

    def fail(self, message: str) -> None:
        print(f"  FAIL: {message}")
        self.failures.append(message)

    def target(self) -> Path:
        self.runs += 1
        return self.work / f"install {self.runs} with spaces" / "MarketPulse"

    def install_command(self, mirror: Mirror, target: Path, *, as_file: bool, pinned: bool) -> list[str]:
        version = ["-Version", self.tag] if pinned else []
        if as_file:
            script = mirror.root / "download" / self.tag / "install.ps1"
            return ["-File", str(script), "-BaseUrl", mirror.url, "-Dir", str(target), "-NoLaunch", *version]
        # The documented form for passing options: & ([scriptblock]::Create((irm <url>))) -Option ...
        # Run that way, install.ps1 throws rather than exits; print the message unwrapped and exit 1.
        pinned_arg = f" -Version {self.tag}" if pinned else ""
        return encoded(
            f"try {{ & ([scriptblock]::Create((irm '{mirror.url}/latest/download/install.ps1')))"
            f" -BaseUrl '{mirror.url}' -Dir $env:MP_CHECK_DIR -NoLaunch{pinned_arg} }}"
            " catch { [Console]::Error.WriteLine('threw: ' + $_.Exception.Message); exit 1 }"
        )

    def install(self, shell: str, label: str, mirror: Mirror, *, as_file: bool, pinned: bool) -> None:
        way = "-File" if as_file else "irm in a script block"
        how = f"{label}, {way}, {'-Version ' + self.tag if pinned else 'latest'}"
        print(f"{how}:")
        target = self.target()
        start = len(mirror.requests)
        env = {**self.env, "MP_CHECK_DIR": str(target)}
        result = run_shell(shell, self.install_command(mirror, target, as_file=as_file, pinned=pinned), env)
        for line in (result.stdout + result.stderr).strip().splitlines():
            print(f"    {line}")
        try:
            if result.returncode != 0:
                raise CheckFailed(f"{how}: install.ps1 exited with {result.returncode}.")
            if "Checksum verified" not in result.stdout:
                raise CheckFailed(f"{how}: install.ps1 didn't report a verified checksum.")
            if not pinned and "HEAD /latest" not in mirror.requests[start:]:
                raise CheckFailed(f"{how}: install.ps1 didn't look up the latest release ({mirror.requests[start:]}).")
            exe = target / "MarketPulse.exe"
            if not exe.is_file():
                raise CheckFailed(f"{how}: {exe} wasn't installed.")
            found = product_version(shell, exe, self.env)
            if found != self.version:
                raise CheckFailed(f"{how}: MarketPulse.exe's ProductVersion is {found!r}, expected {self.version}.")
            entries = uninstall_entries(target)
            if [e["DisplayVersion"] for e in entries] != [self.version]:
                raise CheckFailed(
                    f"{how}: expected one HKCU uninstall entry with DisplayVersion {self.version}: {entries}."
                )
            print(f"  installed {exe} (ProductVersion {found}, uninstall entry {entries[0]['key']})")
        except CheckFailed as error:
            self.fail(str(error))
        finally:
            if target.exists():
                try:
                    uninstall(target)
                    print("  uninstalled; the install folder and its uninstall entry are gone")
                except (CheckFailed, subprocess.SubprocessError, OSError) as error:
                    self.fail(f"{how}: uninstall: {error}")

    def refuse(self, shell: str, label: str, mirror: Mirror, *, as_file: bool) -> None:
        how = f"{label}, {'-File' if as_file else 'irm in a script block'}, wrong SHA256SUMS"
        print(f"{how}:")
        target = self.target()
        env = {**self.env, "MP_CHECK_DIR": str(target)}
        result = run_shell(shell, self.install_command(mirror, target, as_file=as_file, pinned=True), env)
        output = result.stdout + result.stderr
        for line in output.strip().splitlines():
            print(f"    {line}")
        failed = len(self.failures)
        if result.returncode == 0:
            self.fail(f"{how}: install.ps1 succeeded.")
        if "doesn't match its checksum" not in output:
            self.fail(f"{how}: install.ps1 didn't report the checksum mismatch.")
        if not as_file and "threw: MarketPulse install:" not in output:
            self.fail(f"{how}: install.ps1 didn't throw its error to the caller.")
        if target.exists() or uninstall_entries(target):
            self.fail(f"{how}: something was installed in {target}.")
            if (target / "unins000.exe").exists():
                uninstall(target)
        if len(self.failures) == failed:
            print("  refused with a non-zero exit; nothing installed")

    def mark_of_the_web(self, shell: str, label: str, mirror: Mirror) -> None:
        """Evidence for docs/install.md: does Invoke-WebRequest -OutFile write a Zone.Identifier stream?"""
        path = self.work / f"motw-{Path(shell).stem}.txt"
        script = (
            f"Invoke-WebRequest -Uri '{mirror.url}/download/{self.tag}/SHA256SUMS' -OutFile $env:MP_CHECK_FILE"
            " -UseBasicParsing; "
            "$zone = Get-Item -LiteralPath $env:MP_CHECK_FILE -Stream Zone.Identifier -ErrorAction SilentlyContinue; "
            "if ($zone) { 'present'; Get-Content -LiteralPath $env:MP_CHECK_FILE -Stream Zone.Identifier } "
            "else { 'absent' }"
        )
        result = run_shell(shell, encoded(script), {**self.env, "MP_CHECK_FILE": str(path)})
        if result.returncode != 0:
            self.fail(f"{label}: Mark-of-the-Web probe failed: {result.stderr.strip()}")
            return
        lines = result.stdout.strip().splitlines()
        print(f"{label}: Invoke-WebRequest -OutFile Zone.Identifier stream: {' | '.join(lines)}")

    def check_sentinels(self) -> None:
        for path, text in self.sentinels.items():
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                self.fail(f"{path} changed or disappeared.")
        print("Scratch home, config and data sentinels are unchanged.")


def shells() -> list[tuple[str, str]]:
    found = []
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise CheckFailed("Windows PowerShell 5.1 (powershell.exe) isn't on PATH.")
    found.append((powershell, "Windows PowerShell 5.1"))
    pwsh = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if pwsh:
        found.append((pwsh, "PowerShell 7"))
    else:
        print("PowerShell 7 (pwsh) isn't installed; checking Windows PowerShell only.")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path, help="A Windows release folder (setup exe, zip, install.ps1, SHA256SUMS).")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("This check installs the Windows app; run it on Windows.")
    try:
        with tempfile.TemporaryDirectory(prefix="marketpulse-install-check-", ignore_cleanup_errors=True) as tmp:
            work = Path(tmp)
            checker = Checker(args.folder.resolve(), work)
            checker.check_folder()
            if folder := existing_install():
                # The scratch installs share its uninstall entry; uninstalling them would orphan it.
                raise CheckFailed(
                    f"MarketPulse is already installed for this Windows account (in {folder}). "
                    "Uninstall it first, or run this check on another account or a CI runner."
                )
            good = Mirror(work / "mirror", checker.tag)
            publish(checker.folder, good.root, checker.version)
            bad = Mirror(work / "bad-mirror", checker.tag)
            publish(checker.folder, bad.root, checker.version, wrong_hash=True)
            with good.serving(), bad.serving():
                for shell, label in shells():
                    print(f"\n== {label}: {shell}")
                    checker.mark_of_the_web(shell, label, good)
                    checker.install(shell, label, good, as_file=True, pinned=True)
                    checker.install(shell, label, good, as_file=False, pinned=False)
                    checker.refuse(shell, label, bad, as_file=True)
                    checker.refuse(shell, label, bad, as_file=False)
            checker.check_sentinels()
            failures = checker.failures
    except CheckFailed as error:
        raise SystemExit(f"FAIL: {error}") from None
    if failures:
        print(f"\n{len(failures)} check(s) failed:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)
    print("\nAll Windows install checks passed.")


if __name__ == "__main__":
    main()
