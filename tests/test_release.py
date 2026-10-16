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
    assert "not shipped" not in notes and "older" not in notes


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
