"""scripts/install.ps1: static checks everywhere, and its refusals in real PowerShell on Windows.

A faithful fake of the Inno Setup installer would need a Windows build, so the installs themselves are
checked by scripts/check_windows_install.py against the real release (in CI and before publishing).
Here, a fake release on a local mirror shows that install.ps1 runs nothing unless the download matches
exactly one well-formed SHA256SUMS line, and that it reports a failing setup program. The "setup"
program is a copy of whoami.exe, which rejects Inno's switches and exits with 1.
"""

import importlib.util
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install.ps1"
VERSION = "9.8.7"
SETUP = f"MarketPulse-{VERSION}-windows-x64-setup.exe"
windows = pytest.mark.skipif(os.name != "nt", reason="installs on Windows only")


def _shells() -> list[str]:
    names = ["powershell.exe", "pwsh.exe"] if os.name == "nt" else ["pwsh"]
    return [path for name in names if (path := shutil.which(name))]


SHELLS = _shells()
needs_powershell = pytest.mark.skipif(not SHELLS, reason="PowerShell isn't installed")


@pytest.fixture(scope="module")
def check_module():
    spec = importlib.util.spec_from_file_location(
        "check_windows_install", ROOT / "scripts" / "check_windows_install.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(shell: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    command = [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-OutputFormat", "Text"]
    command += ["-File", str(SCRIPT), *args]
    env = {**os.environ, "NO_COLOR": "1", **(env or {})}
    return subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, env=env
    )


def test_is_plain_ascii_without_a_byte_order_mark():
    # Windows PowerShell 5.1 reads BOM-less scripts in the system code page, and `irm | iex` breaks on a BOM.
    data = SCRIPT.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    assert data.isascii(), [line for line in data.splitlines() if not line.isascii()]


def test_options_and_the_call_on_the_last_line():
    text = SCRIPT.read_text(encoding="ascii")
    params = re.search(r"^param\((.*?)^\)", text, re.S | re.M)
    assert params, "install.ps1 needs a script-level param() block"
    for option in ("[string]$Version", "[string]$Dir", "[switch]$NoLaunch", "[string]$BaseUrl", "[switch]$Help"):
        assert option in params.group(1)
    # A download cut short must run nothing: the only top-level command is the last line.
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines[-1].startswith("Install-MarketPulse -Version $Version ")
    assert "-UseBasicParsing" in text and "Tls12" in text
    assert "RunAs" not in text  # never asks for administrator rights
    assert "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-" in " ".join(re.findall(r"'(/[A-Z-]+)'", text))


def test_finds_the_install_by_the_installers_app_id():
    iss = (ROOT / "windows" / "installer" / "MarketPulse.iss").read_text(encoding="utf-8")
    app_id = re.search(r"^AppId=\{(\{[0-9A-F-]{36}\})$", iss, re.M)
    assert app_id, "MarketPulse.iss has no AppId"
    assert f"\\Uninstall\\{app_id.group(1)}_is1'" in SCRIPT.read_text(encoding="ascii")


@needs_powershell
@pytest.mark.parametrize("shell", SHELLS)
def test_parses_and_explains_its_options(shell):
    parser = "[System.Management.Automation.Language.Parser]"
    check = f"$e = $null; $null = {parser}::ParseFile('{SCRIPT}', [ref]$null, [ref]$e); $e.Count"
    parsed = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", check], capture_output=True, text=True)
    assert parsed.stdout.strip() == "0", parsed.stdout + parsed.stderr
    help_run = run(shell, "-Help")
    assert help_run.returncode == 0, help_run.stderr
    assert "-Version vX.Y.Z" in help_run.stdout and ".marketpulse is never touched" in help_run.stdout
    bogus = run(shell, "-Bogus")
    assert bogus.returncode == 1 and "unknown option -Bogus" in bogus.stderr


@pytest.fixture
def mirror(tmp_path, check_module):
    """A fake release on 127.0.0.1 whose "setup program" is whoami.exe; yields (mirror, SHA256SUMS path)."""
    release = tmp_path / "release"
    release.mkdir()
    shutil.copy(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "whoami.exe", release / SETUP)
    (release / f"MarketPulse-{VERSION}-windows-x64.zip").write_bytes(b"portable")
    shutil.copy(SCRIPT, release / "install.ps1")
    check_module._release().write_sums(release)
    server = check_module.Mirror(tmp_path / "mirror", f"v{VERSION}")
    folder = check_module.publish(release, server.root, VERSION)
    with server.serving():
        yield server, folder / "SHA256SUMS"


def install(shell: str, server, dest: Path, *args: str) -> subprocess.CompletedProcess:
    return run(shell, "-BaseUrl", server.url, "-Dir", str(dest), "-NoLaunch", *args)


@windows
@pytest.mark.parametrize("shell", SHELLS)
def test_reports_a_failing_setup_after_checking_the_latest_release(shell, mirror, tmp_path):
    server, _ = mirror
    result = install(shell, server, tmp_path / "Programs" / "MarketPulse")  # no -Version: the latest release
    assert result.returncode == 1
    assert "HEAD /latest" in server.requests
    assert "Checksum verified" in result.stdout
    assert re.search(r"setup exited with code [1-9]", result.stderr), result.stderr


@windows
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("tamper", "doesn't match its checksum"),
        ("drop", "no single entry"),
        ("duplicate", "no single entry"),
        ("malformed", "malformed line"),
    ],
)
def test_runs_nothing_without_one_matching_checksum(shell, mirror, tmp_path, change, message):
    server, sums = mirror
    lines = sums.read_text(encoding="utf-8").splitlines()
    ours = next(line for line in lines if line.endswith(f"  {SETUP}"))
    if change == "tamper":
        lines = [("0" * 64) + f"  {SETUP}" if line == ours else line for line in lines]
    elif change == "drop":
        lines.remove(ours)
    elif change == "duplicate":  # ambiguous, even though one of them matches
        lines.append(("0" * 64) + f"  {SETUP}")
    else:
        lines.append(f"{ours.split()[0]} *{SETUP}")
    sums.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    dest = tmp_path / "Programs" / "MarketPulse"
    result = install(shell, server, dest, "-Version", f"v{VERSION}")
    assert result.returncode == 1
    assert message in result.stderr
    assert "Installing" not in result.stdout
    assert not dest.exists()


@windows
@pytest.mark.parametrize("shell", SHELLS)
def test_a_script_block_throws_instead_of_exiting(shell, mirror, tmp_path, check_module):
    server, sums = mirror
    sums.write_text(("0" * 64) + f"  {SETUP}\n", encoding="utf-8")
    command = (
        f"try {{ & ([scriptblock]::Create((irm '{server.url}/latest/download/install.ps1')))"
        f" -BaseUrl '{server.url}' -Dir '{tmp_path / 'x'}' -NoLaunch -Version v{VERSION} }}"
        " catch { [Console]::Out.WriteLine('caught: ' + $_.Exception.Message) }; 'shell still running'"
    )
    command_line = [shell, "-NoProfile", "-NonInteractive", "-OutputFormat", "Text", *check_module.encoded(command)]
    result = subprocess.run(command_line, capture_output=True, text=True, timeout=180)
    assert "caught: MarketPulse install:" in result.stdout and "doesn't match its checksum" in result.stdout
    assert "shell still running" in result.stdout


@windows
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["-BaseUrl", "http://example.com/releases", "-Version", "v1.0.0"], "-BaseUrl must start with https://"),
        (["-Version", "v1.0"], "isn't a version like"),
        (["-Version", "1.0.0/../x"], "isn't a version like"),
        (["-Version", "v1.0.0", "-Dir", 'a"b'], "can't contain a double quote"),
    ],
)
def test_rejects_bad_options_before_downloading(shell, tmp_path, args, message):
    base = [] if "-BaseUrl" in args else ["-BaseUrl", "https://127.0.0.1:9/unused"]  # never reached
    result = run(shell, "-NoLaunch", *base, *args)
    assert result.returncode == 1
    assert message in result.stderr
