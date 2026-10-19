"""scripts/install.sh against a fake release served from file:// (no network, no real app).

The fake app is a copy of /usr/bin/true in a bundle with MarketPulse's ID, ad-hoc signed and
zipped with `ditto` the way scripts/release.py packages the real one.
"""

import importlib.util
import platform
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install.sh"
VERSION = "9.8.7"
ARCH = platform.machine()

macos = pytest.mark.skipif(sys.platform != "darwin", reason="installs a macOS app")


@pytest.fixture(scope="module")
def release_module():
    spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_app(folder: Path, *, version: str = VERSION, bundle_id: str = "dev.marketpulse.app") -> Path:
    app = folder / "MarketPulse.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    shutil.copy("/usr/bin/true", app / "Contents" / "MacOS" / "MarketPulseBar")
    plist = {"CFBundleIdentifier": bundle_id, "CFBundleExecutable": "MarketPulseBar"}
    plist |= {"CFBundleShortVersionString": version, "CFBundleVersion": version}
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["codesign", "--force", "--sign", "-", app], check=True, capture_output=True)
    return app


def publish(root: Path, release_module, *, tamper_zip=False, tamper_app=False, app_version=VERSION) -> str:
    """Lay out `root` like github.com/<repo>/releases and return its file:// URL."""
    folder = root / "download" / f"v{VERSION}"
    folder.mkdir(parents=True)
    build = root / "build"
    build.mkdir()
    app = make_app(build, version=app_version)
    if tamper_app:  # after signing, so the signature no longer covers it
        (app / "Contents" / "MacOS" / "extra").write_text("added later")
    zip_path = folder / f"MarketPulse-{VERSION}-macos-{ARCH}.zip"
    subprocess.run(["ditto", "-c", "-k", "--keepParent", app, zip_path], check=True)
    shutil.copy(SCRIPT, folder / "install.sh")
    release_module.write_sums(folder)
    if tamper_zip:  # after SHA256SUMS, like a download altered in transit
        with open(zip_path, "ab") as f:
            f.write(b"\0")
    return root.as_uri()


def install(base_url: str, dest: Path, *args: str) -> subprocess.CompletedProcess:
    command = ["bash", str(SCRIPT), "--base-url", base_url, "--dir", str(dest), "--no-open", *args]
    return subprocess.run(command, capture_output=True, text=True, timeout=120)


def installed_version(dest: Path) -> str:
    with open(dest / "MarketPulse.app" / "Contents" / "Info.plist", "rb") as f:
        return plistlib.load(f)["CFBundleShortVersionString"]


def leftovers(dest: Path) -> list[str]:
    return sorted(p.name for p in dest.iterdir() if p.name != "MarketPulse.app") if dest.exists() else []


@macos
def test_installs_a_verified_release(tmp_path, release_module):
    url = publish(tmp_path / "releases", release_module)
    dest = tmp_path / "Applications"
    result = install(url, dest, "--version", f"v{VERSION}")
    assert result.returncode == 0, result.stderr
    assert "Checksum verified" in result.stdout
    assert installed_version(dest) == VERSION
    assert leftovers(dest) == []  # no staging folder left behind
    subprocess.run(["codesign", "--verify", "--deep", "--strict", dest / "MarketPulse.app"], check=True)


@macos
def test_upgrade_replaces_the_previous_app(tmp_path, release_module):
    url = publish(tmp_path / "releases", release_module)
    dest = tmp_path / "Applications"
    dest.mkdir()
    make_app(dest, version="1.0.0")
    result = install(url, dest, "--version", VERSION)  # the leading v is optional
    assert result.returncode == 0, result.stderr
    assert installed_version(dest) == VERSION
    assert leftovers(dest) == []


@macos
def test_waits_for_the_open_app_to_quit_before_replacing_it(tmp_path, release_module):
    url = publish(tmp_path / "releases", release_module)
    dest = tmp_path.resolve() / "Applications"  # the script resolves symlinks like /var -> /private/var
    dest.mkdir()
    make_app(dest, version="1.0.0")
    # A process that looks like the installed app in `ps`, and quits after two seconds.
    running = dest / "MarketPulse.app" / "Contents" / "MacOS" / "MarketPulseBar"
    app = subprocess.Popen(["bash", "-c", f'exec -a "{running}" sleep 2'])
    try:
        time.sleep(0.5)
        started = time.monotonic()
        result = install(url, dest, "--version", VERSION)
        assert result.returncode == 0, result.stderr
        assert "Quit it" in result.stdout
        assert app.poll() is not None  # replaced only after the app was gone
        assert time.monotonic() - started >= 1
        assert installed_version(dest) == VERSION
    finally:
        app.kill()


@macos
@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("tamper_zip", "doesn't match its checksum"),
        ("tamper_app", "signature doesn't verify"),
        ("app_version", "not 9.8.7"),
    ],
)
def test_refuses_a_tampered_or_wrong_download_and_keeps_the_old_app(tmp_path, release_module, kind, message):
    options = {"app_version": "1.2.3"} if kind == "app_version" else {kind: True}
    url = publish(tmp_path / "releases", release_module, **options)
    dest = tmp_path / "Applications"
    dest.mkdir()
    make_app(dest, version="1.0.0")
    result = install(url, dest, "--version", f"v{VERSION}")
    assert result.returncode != 0
    assert message in result.stderr
    assert installed_version(dest) == "1.0.0"
    assert leftovers(dest) == []


@macos
@pytest.mark.parametrize("change", ["drop", "duplicate"])
def test_refuses_a_release_without_one_checksum_for_this_mac(tmp_path, release_module, change):
    root = tmp_path / "releases"
    url = publish(root, release_module)
    sums = root / "download" / f"v{VERSION}" / "SHA256SUMS"
    lines = sums.read_text().splitlines()
    ours = [line for line in lines if ARCH in line and line.endswith(".zip")]
    if change == "drop":
        lines = [line for line in lines if line not in ours]
    else:  # a second, different hash for the same file: ambiguous, even if one of them matches
        lines += [("0" * 64) + "  " + ours[0].split("  ")[1]]
    sums.write_text("".join(line + "\n" for line in lines))
    dest = tmp_path / "Applications"
    result = install(url, dest, "--version", f"v{VERSION}")
    assert result.returncode != 0
    assert "no single entry" in result.stderr
    assert not (dest / "MarketPulse.app").exists()


@macos
def test_wont_replace_something_that_isnt_marketpulse(tmp_path, release_module):
    url = publish(tmp_path / "releases", release_module)
    dest = tmp_path / "Applications"
    dest.mkdir()
    make_app(dest, bundle_id="com.example.other")
    result = install(url, dest, "--version", f"v{VERSION}")
    assert result.returncode != 0
    assert "isn't a MarketPulse app" in result.stderr
    with open(dest / "MarketPulse.app" / "Contents" / "Info.plist", "rb") as f:
        assert plistlib.load(f)["CFBundleIdentifier"] == "com.example.other"


@macos
@pytest.mark.parametrize("version", ["v1.0", "1.0.0/../x", "v1.0.0;id", "latest", "1.0.0\n../x"])
def test_rejects_versions_that_arent_plain(tmp_path, version):
    result = install((tmp_path / "missing").as_uri(), tmp_path / "Applications", "--version", version)
    assert result.returncode != 0
    assert "isn't a version like" in result.stderr
    assert not (tmp_path / "Applications").exists()


@pytest.mark.skipif(sys.platform == "darwin", reason="checks the message on other systems")
def test_explains_that_the_app_is_macos_only(tmp_path):
    result = install((tmp_path / "missing").as_uri(), tmp_path / "Applications", "--version", "v1.0.0")
    assert result.returncode != 0
    assert "MarketPulse.app is for macOS" in result.stderr


def test_help_and_unknown_options():
    help_text = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True, check=True).stdout
    assert "--version vX.Y.Z" in help_text and "~/.marketpulse is never touched" in help_text
    result = subprocess.run(["bash", str(SCRIPT), "--bogus"], capture_output=True, text=True)
    assert result.returncode != 0 and "unknown option --bogus" in result.stderr
