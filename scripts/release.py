"""Package, verify, and describe a MarketPulse release. Used by .github/workflows/release.yml.

    uv run --locked python scripts/release.py check-tag v2.2.0       # the tag must match __version__
    uv run --locked python scripts/release.py notes 2.2.0 > notes.md   # that version's CHANGELOG section
    uv run --locked python scripts/release.py package --apps dist/app --python-dist dist/python --out dist/release
    uv run --locked python scripts/release.py verify dist/release --require-smoke arm64
    uv run --locked python scripts/release.py combine --out dist/publish dist/release dist/windows-release

`package` turns each `<apps>/<arch>/MarketPulse.app` from scripts/build_app.py into a zip
(`ditto -c -k --keepParent`, which keeps symlinks and signatures) and a DMG, copies the wheel,
sdist, and scripts/install.sh, and writes SHA256SUMS. `verify` checks the checksums, then opens every
zip and DMG and checks the versions, architectures, and signatures inside, and smoke-tests each app this
Mac can run. `combine` merges the checked macOS and Windows release folders into the one folder a
GitHub Release publishes, with a single SHA256SUMS; unlike `package` and `verify`, it runs anywhere.
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
INSTALLER = "install.sh"
INSTALLER_PS1 = "install.ps1"


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


def macos_release_names(version: str) -> set[str]:
    """What the macOS release folder from `package` holds (besides SHA256SUMS)."""
    names = {f"MarketPulse-{version}-macos-{a}.{ext}" for a in ("arm64", "x86_64") for ext in ("zip", "dmg")}
    return names | {f"marketpulse-{version}-py3-none-any.whl", f"marketpulse-{version}.tar.gz", INSTALLER}


def windows_release_names(version: str) -> set[str]:
    """What the Windows release folder holds (besides SHA256SUMS)."""
    stem = f"MarketPulse-{version}-windows-x64"
    return {f"{stem}-setup.exe", f"{stem}.zip", INSTALLER_PS1}


def release_names(version: str) -> set[str]:
    """Every file a published GitHub Release holds (besides SHA256SUMS)."""
    return macos_release_names(version) | windows_release_names(version)


def release_notes(changelog: str, version: str) -> str:
    repo = "https://github.com/BrendanH18/Marketpulse"
    stem = f"MarketPulse-{version}-windows-x64"
    return (
        changelog_section(changelog, version)
        + "\n\n## Downloads\n\n### Mac\n\n"
        + "Install the Mac app with one command, which checks the download against `SHA256SUMS` and avoids "
        + f"macOS's security prompt ([read the script]({repo}/blob/v{version}/scripts/{INSTALLER}) first):\n\n"
        + f"```bash\ncurl -fsSL {repo}/releases/download/v{version}/{INSTALLER}"
        + f" | bash -s -- --version v{version}\n```\n\n"
        + f"Or download it yourself and follow the [install guide]({repo}/blob/v{version}/docs/install.md). "
        + f"`MarketPulse-{version}-macos-arm64` is for Apple silicon Macs, `-x86_64` for Intel Macs; each "
        + "comes as a zip and a DMG. The apps are ad-hoc signed, not notarized by Apple. Check what you "
        + f"downloaded against `{SUMS}`:\n\n```bash\nshasum -a 256 -c {SUMS} --ignore-missing\n```\n"
        + "\n### Windows\n\n"
        + "Install for your Windows account (no administrator rights) with one PowerShell command, which "
        + f"checks the installer against `{SUMS}` ([read the script]({repo}/blob/v{version}/scripts/{INSTALLER_PS1})"
        + " first):\n\n"
        + f"```powershell\n& ([scriptblock]::Create((irm {repo}/releases/download/v{version}/{INSTALLER_PS1})))"
        + f" -Version v{version}\n```\n\n"
        + f"Or download `{stem}-setup.exe` (installer) or `{stem}.zip` (portable; unzip and run "
        + '`MarketPulse.exe`). They aren\'t code-signed, so SmartScreen says "Windows protected your PC" the '
        + "first time: click **More info**, then **Run anyway**. Check a download against "
        + f"`{SUMS}` first; this prints `True` when it matches:\n\n"
        + f'```powershell\n$file = "{stem}-setup.exe"\n'
        + f'$expected = (Select-String -LiteralPath {SUMS} -SimpleMatch "  $file").Line.Split(" ")[0]\n'
        + "(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -eq $expected\n```\n"
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
    shutil.copy2(ROOT / "scripts" / INSTALLER, out / INSTALLER)
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
    expected = macos_release_names(version)
    if {p.name for p in files} != expected:
        raise SystemExit(f"Expected exactly {sorted(expected)}, found {sorted(p.name for p in files)}.")
    if (folder / INSTALLER).read_bytes() != (ROOT / "scripts" / INSTALLER).read_bytes():
        raise SystemExit(f"{INSTALLER} isn't this checkout's scripts/{INSTALLER}.")
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


def combine(out: Path, folders: list[Path], version: str = __version__) -> None:
    """Merge checked release folders into a fresh `out` that holds the full release and one SHA256SUMS."""
    if not folders:
        raise SystemExit("Name at least one release folder to combine.")
    for folder in folders:
        if out == folder or out in folder.parents or folder in out.parents:
            raise SystemExit(f"--out {out} overlaps the input folder {folder}; pick a new folder.")
    sources: dict[str, Path] = {}
    for folder in folders:
        if not (folder / SUMS).is_file():
            raise SystemExit(f"{folder} has no {SUMS}; is it a release folder?")
        files = check_sums(folder)
        print(f"{folder}: {SUMS} matches its {len(files)} files.")
        for path in files:
            if path.name in sources:
                raise SystemExit(f"{path.name} is in both {sources[path.name].parent} and {folder}.")
            sources[path.name] = path
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name, path in sorted(sources.items()):
        shutil.copy2(path, out / name)
    write_sums(out)
    files = check_sums(out)
    expected = release_names(version)
    found = {p.name for p in files}
    if found != expected:
        missing, extra = sorted(expected - found), sorted(found - expected)
        raise SystemExit(f"The combined release for {version} is missing {missing} and has unexpected {extra}.")
    for installer in (INSTALLER, INSTALLER_PS1):
        if (out / installer).read_bytes() != (ROOT / "scripts" / installer).read_bytes():
            raise SystemExit(f"{installer} isn't this checkout's scripts/{installer}.")
    for path in files:
        print(f"{path.name}  ({path.stat().st_size / 1_000_000:.0f} MB)")
    print(f"{SUMS}: {len(files)} files, the full MarketPulse {version} release.")


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
    merge = commands.add_parser("combine", help="Merge checked macOS and Windows release folders for publishing.")
    merge.add_argument("folders", type=Path, nargs="+")
    merge.add_argument("--out", type=Path, required=True)
    merge.add_argument("--version", default=__version__)
    args = parser.parse_args()

    if args.command == "check-tag":
        check_tag(args.tag)
        print(f"{args.tag} matches MarketPulse {__version__}.")
    elif args.command == "notes":
        sys.stdout.write(release_notes((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), args.version))
    elif args.command == "combine":
        combine(args.out.resolve(), [folder.resolve() for folder in args.folders], args.version)
    elif sys.platform != "darwin":
        raise SystemExit("Packaging and verifying the macOS app need macOS.")
    elif args.command == "package":
        package(args.apps.resolve(), args.python_dist.resolve(), args.out.resolve())
    else:
        verify(args.folder.resolve(), args.version, tuple(args.require_smoke))


if __name__ == "__main__":
    main()
