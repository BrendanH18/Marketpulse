"""scripts/release.py's platform-independent parts: the tag check, release notes, and SHA256SUMS."""

import importlib.util
from pathlib import Path

import pytest

from marketpulse import __version__

ROOT = Path(__file__).resolve().parents[1]

CHANGELOG = """# Changelog

## [Unreleased]

- Something not shipped yet.

## [1.2.0] - 2026-01-02

### Added

- A feature.

## [1.1.0] - 2025-12-01

- An older change.
"""


@pytest.fixture(scope="module")
def release():
    spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tag_must_match_the_package_version(release):
    release.check_tag(f"v{__version__}")
    for tag in (__version__, f"v{__version__}.1", "v0.0.0"):
        with pytest.raises(SystemExit, match="doesn't match"):
            release.check_tag(tag)


def test_notes_are_only_that_versions_section(release):
    assert release.changelog_section(CHANGELOG, "1.2.0") == "### Added\n\n- A feature."
    assert release.changelog_section(CHANGELOG, "1.1.0") == "- An older change."
    notes = release.release_notes(CHANGELOG, "1.2.0")
    assert notes.startswith("### Added\n\n- A feature.\n\n## Downloads")
    assert "MarketPulse-1.2.0-macos-arm64" in notes and "shasum -a 256 -c SHA256SUMS" in notes
    assert "releases/download/v1.2.0/install.sh | bash -s -- --version v1.2.0" in notes
    assert "blob/v1.2.0/scripts/install.sh" in notes and "blob/v1.2.0/docs/install.md" in notes
    assert "not shipped" not in notes and "older" not in notes


def test_notes_explain_the_windows_downloads(release):
    notes = release.release_notes(CHANGELOG, "1.2.0")
    windows = notes[notes.index("### Windows") :]
    assert "irm https://github.com/BrendanH18/Marketpulse/releases/download/v1.2.0/install.ps1" in windows
    assert "-Version v1.2.0" in windows and "blob/v1.2.0/scripts/install.ps1" in windows
    assert "MarketPulse-1.2.0-windows-x64-setup.exe" in windows and "MarketPulse-1.2.0-windows-x64.zip" in windows
    assert "Windows protected your PC" in windows and "**More info**" in windows and "**Run anyway**" in windows
    assert "Get-FileHash" in windows and "SHA256SUMS" in windows


def test_notes_fail_without_a_section(release):
    with pytest.raises(SystemExit, match=r"no '## \[1.3.0\]'"):
        release.changelog_section(CHANGELOG, "1.3.0")
    with pytest.raises(SystemExit, match=r"no '## \[1.2\]'"):  # not a prefix match on 1.2.0
        release.changelog_section(CHANGELOG, "1.2")
    with pytest.raises(SystemExit, match="empty"):
        release.changelog_section("## [2.0.0]\n\n## [1.0.0]\n- x\n", "2.0.0")


def test_the_real_changelog_has_this_versions_notes(release):
    assert release.changelog_section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), __version__)


def test_sums_cover_every_file_and_catch_changes(tmp_path, release):
    (tmp_path / "a.zip").write_bytes(b"app")
    (tmp_path / "b.whl").write_bytes(b"wheel")
    sums = release.write_sums(tmp_path)
    lines = sums.read_text().splitlines()
    assert [line.split("  ")[1] for line in lines] == ["a.zip", "b.whl"]  # shasum -c format
    assert [p.name for p in release.check_sums(tmp_path)] == ["a.zip", "b.whl"]

    (tmp_path / "b.whl").write_bytes(b"tampered")
    with pytest.raises(SystemExit, match="b.whl doesn't match"):
        release.check_sums(tmp_path)
    release.write_sums(tmp_path)
    (tmp_path / "extra.dmg").write_bytes(b"unlisted")
    with pytest.raises(SystemExit, match="but the folder has"):
        release.check_sums(tmp_path)
    (tmp_path / "extra.dmg").unlink()
    (tmp_path / "a.zip").unlink()
    with pytest.raises(SystemExit, match="but the folder has"):
        release.check_sums(tmp_path)


def make_release(release, root: Path) -> tuple[Path, Path]:
    """Fake macOS and Windows release folders for this version, each with its own SHA256SUMS."""
    mac, win = root / "mac", root / "windows"
    for folder, names in (
        (mac, release.macos_release_names(__version__)),
        (win, release.windows_release_names(__version__)),
    ):
        folder.mkdir(parents=True)
        for name in names:
            installer = ROOT / "scripts" / name
            if installer.exists():
                (folder / name).write_bytes(installer.read_bytes())
            else:
                (folder / name).write_bytes(f"fake {name}".encode())
        release.write_sums(folder)
    return mac, win


def test_combine_merges_the_mac_and_windows_releases(tmp_path, release):
    mac, win = make_release(release, tmp_path)
    out = tmp_path / "publish"
    out.mkdir()
    (out / "stale.txt").write_text("from an earlier run")
    release.combine(out, [mac, win])
    files = release.check_sums(out)
    assert {p.name for p in files} == release.release_names(__version__)
    assert {"install.sh", "install.ps1", f"MarketPulse-{__version__}-windows-x64-setup.exe"} <= {p.name for p in files}
    assert (out / "SHA256SUMS").read_text().count("\n") == len(files)  # one SHA256SUMS for everything
    assert release.check_sums(mac) and release.check_sums(win)  # inputs untouched


def test_combine_refuses_a_tampered_file(tmp_path, release):
    mac, win = make_release(release, tmp_path)
    (win / f"MarketPulse-{__version__}-windows-x64.zip").write_bytes(b"changed after SHA256SUMS")
    with pytest.raises(SystemExit, match="windows-x64.zip doesn't match"):
        release.combine(tmp_path / "publish", [mac, win])
    assert not (tmp_path / "publish").exists()


def test_combine_refuses_a_name_in_two_folders(tmp_path, release):
    mac, win = make_release(release, tmp_path)
    (win / "install.sh").write_bytes((mac / "install.sh").read_bytes())
    release.write_sums(win)
    with pytest.raises(SystemExit, match="install.sh is in both"):
        release.combine(tmp_path / "publish", [mac, win])


def test_combine_refuses_an_incomplete_release(tmp_path, release):
    mac, win = make_release(release, tmp_path)
    (win / "install.ps1").unlink()
    release.write_sums(win)
    with pytest.raises(SystemExit, match=r"missing \['install.ps1'\]"):
        release.combine(tmp_path / "publish", [mac, win])
    with pytest.raises(SystemExit, match="missing"):
        release.combine(tmp_path / "publish-mac", [mac])  # the macOS release alone isn't the full release


def test_combine_wants_this_checkouts_installers_and_a_new_folder(tmp_path, release):
    mac, win = make_release(release, tmp_path)
    (win / "install.ps1").write_text("# a different script\n")
    release.write_sums(win)
    with pytest.raises(SystemExit, match="install.ps1 isn't this checkout's"):
        release.combine(tmp_path / "publish", [mac, win])
    with pytest.raises(SystemExit, match="overlaps"):
        release.combine(mac / "out", [mac, win])


def test_verify_still_expects_only_the_mac_release(release):
    assert "install.ps1" not in release.macos_release_names("1.2.0")
    assert release.windows_release_names("1.2.0") == {
        "MarketPulse-1.2.0-windows-x64-setup.exe",
        "MarketPulse-1.2.0-windows-x64.zip",
        "install.ps1",
    }
