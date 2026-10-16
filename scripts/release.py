"""Package, verify, and describe a MarketPulse release. Used by .github/workflows/release.yml.

    uv run --locked python scripts/release.py check-tag v2.2.0       # the tag must match __version__
    uv run --locked python scripts/release.py notes 2.2.0 > notes.md   # that version's CHANGELOG section
    uv run --locked python scripts/release.py package --apps dist/app --python-dist dist/python --out dist/release
    uv run --locked python scripts/release.py verify dist/release --require-smoke arm64

`package` turns each `<apps>/<arch>/MarketPulse.app` from scripts/build_app.py into a zip
(`ditto -c -k --keepParent`, which keeps symlinks and signatures) and a DMG, copies the wheel and
sdist, and writes SHA256SUMS. `verify` checks the checksums, then opens every zip and DMG and checks
the versions, architectures, and signatures inside, and smoke-tests each app this Mac can run.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from marketpulse import __version__

ROOT = Path(__file__).resolve().parents[1]
APP = "MarketPulse.app"
SUMS = "SHA256SUMS"


def _build_app():
    spec = importlib.util.spec_from_file_location("build_app", ROOT / "scripts" / "build_app.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*args: str | Path, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def check_tag(tag: str, version: str = __version__) -> None:
    if tag != f"v{version}":
        raise SystemExit(f"Tag {tag} doesn't match MarketPulse {version}; tag v{version} or bump __version__.")


def changelog_section(changelog: str, version: str) -> str:
    """The body of `## [version]` (without its heading), up to the next `## [` heading."""
    lines = changelog.splitlines()
    heading = re.compile(rf"^## \[{re.escape(version)}\](\s|$)")
    starts = [i for i, line in enumerate(lines) if heading.match(line)]
    if not starts:
        raise SystemExit(f"CHANGELOG.md has no '## [{version}]' section.")
    body = []
    for line in lines[starts[0] + 1 :]:
        if line.startswith("## ["):
            break
        body.append(line)
    text = "\n".join(body).strip()
    if not text:
        raise SystemExit(f"CHANGELOG.md's '## [{version}]' section is empty.")
    return text


def release_notes(changelog: str, version: str) -> str:
    return (
        changelog_section(changelog, version)
        + "\n\n## Downloads\n\n"
        + f"`MarketPulse-{version}-macos-arm64` is for Apple silicon Macs, `-x86_64` for Intel Macs; each "
        + "comes as a zip and a DMG. The apps are ad-hoc signed, not notarized by Apple. Check what you "
        + f"downloaded against `{SUMS}`:\n\n```bash\nshasum -a 256 -c {SUMS} --ignore-missing\n```\n"
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_sums(folder: Path) -> Path:
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.name != SUMS)
    sums = folder / SUMS
    sums.write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files), encoding="utf-8")
    return sums


def check_sums(folder: Path) -> list[Path]:
    """Every file in `folder` is listed in SHA256SUMS with a matching hash, and nothing listed is missing."""
    listed: dict[str, str] = {}
    for line in (folder / SUMS).read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not name or "/" in name:
            raise SystemExit(f"Malformed {SUMS} line: {line!r}")
        listed[name] = digest
    present = {p.name for p in folder.iterdir() if p.is_file() and p.name != SUMS}
    if present != set(listed):
        raise SystemExit(f"{SUMS} lists {sorted(listed)}, but the folder has {sorted(present)}.")
    for name, digest in listed.items():
        if sha256(folder / name) != digest:
            raise SystemExit(f"{name} doesn't match its checksum in {SUMS}.")
    return [folder / name for name in sorted(listed)]


def make_dmg(app: Path, dmg: Path, volume: str) -> None:
    with tempfile.TemporaryDirectory(prefix="marketpulse-dmg-") as tmp:
        stage = Path(tmp) / volume
        stage.mkdir()
        run("ditto", app, stage / app.name)
        (stage / "Applications").symlink_to("/Applications")
        command = ["hdiutil", "create", "-quiet", "-volname", volume, "-srcfolder", stage, "-fs", "HFS+"]
        command += ["-format", "UDZO", "-ov", dmg]
        for attempt in range(3):  # hdiutil on CI runners fails now and then with "Resource busy"
            if subprocess.run([str(a) for a in command]).returncode == 0:
                return
            time.sleep(5 * (attempt + 1))
        raise SystemExit(f"hdiutil couldn't create {dmg.name}.")


def package(apps: Path, python_dist: Path, out: Path, version: str = __version__) -> None:
    arches = sorted(p.parent.name for p in apps.glob(f"*/{APP}"))
    if not arches:
        raise SystemExit(f"No {APP} under {apps}/<arch>/; run scripts/build_app.py first.")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for arch in arches:
        app = apps / arch / APP
        stem = f"MarketPulse-{version}-macos-{arch}"
        run("ditto", "-c", "-k", "--keepParent", app, out / f"{stem}.zip")
        make_dmg(app, out / f"{stem}.dmg", f"MarketPulse {version}")
    for pattern in (f"marketpulse-{version}-*.whl", f"marketpulse-{version}.tar.gz"):
        found = sorted(python_dist.glob(pattern))
        if len(found) != 1:
            raise SystemExit(
                f"Expected one {pattern} in {python_dist}, found {len(found)}; run `uv build --no-sources`."
            )
        shutil.copy2(found[0], out / found[0].name)
    write_sums(out)
    for path in sorted(out.iterdir()):
        print(f"{path.name}  ({path.stat().st_size / 1_000_000:.0f} MB)")


def lipo_archs(path: Path) -> set[str]:
    return set(run("lipo", "-archs", path, capture_output=True, text=True).stdout.split())


def check_app(app: Path, arch: str, version: str, *, smoke: bool) -> None:
    """The bundle is this version and architecture throughout, its signature holds, and (if `smoke`) it runs."""
    with open(app / "Contents" / "Info.plist", "rb") as f:
        plist = plistlib.load(f)
    for key in ("CFBundleShortVersionString", "CFBundleVersion"):
        if plist.get(key) != version:
            raise SystemExit(f"{app}: {key} is {plist.get(key)!r}, expected {version}.")
    if plist.get("CFBundleIdentifier") != "dev.marketpulse.app":
        raise SystemExit(f"{app}: unexpected bundle ID {plist.get('CFBundleIdentifier')!r}.")
    python = app / "Contents" / "Resources" / "backend" / "python"
    for binary in (app / "Contents" / "MacOS" / plist["CFBundleExecutable"], python / "bin" / "python3"):
        if lipo_archs(binary) != {arch}:
            raise SystemExit(f"{binary} is built for {sorted(lipo_archs(binary))}, expected {arch}.")
    dist_infos = sorted(p.name for p in python.glob("lib/python3.*/site-packages/marketpulse-*.dist-info"))
    if dist_infos != [f"marketpulse-{version}.dist-info"]:
        raise SystemExit(f"{app}: bundled backend is {dist_infos}, expected marketpulse {version}.")
    run("codesign", "--verify", "--deep", "--strict", app)
    if smoke:
        _build_app().smoke_test(app, arch)
    print(f"  {app.name} ({arch}): MarketPulse {version}, signature valid, {'ran' if smoke else 'not run here'}")


def verify(folder: Path, version: str = __version__, require_smoke: tuple[str, ...] = ()) -> None:
    if version != __version__:
        raise SystemExit(f"This checkout is MarketPulse {__version__}; check out v{version} to verify its artifacts.")
    files = check_sums(folder)
    print(f"{SUMS}: {len(files)} files match.")
    build_app = _build_app()
    pattern = re.compile(rf"MarketPulse-{re.escape(version)}-macos-(arm64|x86_64)\.(zip|dmg)")
    apps = [(p, m.group(1)) for p in files if (m := pattern.fullmatch(p.name))]
    expected = {f"MarketPulse-{version}-macos-{a}.{ext}" for a in ("arm64", "x86_64") for ext in ("zip", "dmg")}
    expected |= {f"marketpulse-{version}-py3-none-any.whl", f"marketpulse-{version}.tar.gz"}
    if {p.name for p in files} != expected:
        raise SystemExit(f"Expected exactly {sorted(expected)}, found {sorted(p.name for p in files)}.")
    ran = set()
    for path, arch in apps:
        smoke = build_app.can_run(arch)
        with tempfile.TemporaryDirectory(prefix="marketpulse-verify-") as tmp:
            print(path.name)
            if path.suffix == ".zip":
                run("ditto", "-x", "-k", path, tmp)
                check_app(Path(tmp) / APP, arch, version, smoke=smoke)
            else:
                mount = Path(tmp) / "mnt"
                run("hdiutil", "attach", "-quiet", "-readonly", "-nobrowse", "-noautoopen", "-mountpoint", mount, path)
                try:
                    if not (mount / "Applications").is_symlink():
                        raise SystemExit(f"{path.name} has no Applications shortcut.")
                    check_app(mount / APP, arch, version, smoke=smoke)
                finally:
                    run("hdiutil", "detach", "-quiet", mount, "-force")
        if smoke:
            ran.add(arch)
    missing = set(require_smoke) - ran
    if missing:
        raise SystemExit(f"Couldn't run the {', '.join(sorted(missing))} app on this Mac, but it was required.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    tag = commands.add_parser("check-tag", help="Fail unless TAG is v<__version__>.")
    tag.add_argument("tag")
    notes = commands.add_parser("notes", help="Print the release notes for VERSION from CHANGELOG.md.")
    notes.add_argument("version", nargs="?", default=__version__)
    pack = commands.add_parser("package", help="Zip, DMG, and checksum the built apps and Python packages.")
    pack.add_argument("--apps", type=Path, default=ROOT / "dist" / "app")
    pack.add_argument("--python-dist", type=Path, default=ROOT / "dist")
    pack.add_argument("--out", type=Path, default=ROOT / "dist" / "release")
    check = commands.add_parser("verify", help="Check a packaged release folder.")
    check.add_argument("folder", type=Path)
    check.add_argument("--version", default=__version__)
    check.add_argument("--require-smoke", action="append", default=[], choices=["arm64", "x86_64"])
    args = parser.parse_args()

    if args.command == "check-tag":
        check_tag(args.tag)
        print(f"{args.tag} matches MarketPulse {__version__}.")
    elif args.command == "notes":
        sys.stdout.write(release_notes((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), args.version))
    elif sys.platform != "darwin":
        raise SystemExit("Packaging and verifying the macOS app need macOS.")
    elif args.command == "package":
        package(args.apps.resolve(), args.python_dist.resolve(), args.out.resolve())
    else:
        verify(args.folder.resolve(), args.version, tuple(args.require_smoke))


if __name__ == "__main__":
    main()
