"""The bundled-backend pieces that run without building an app: the bridge's backend field,
`python -m marketpulse`, and scripts/build_app.py's stripping and launcher."""

import importlib.util
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from marketpulse import __version__
from marketpulse.cli import main

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def build_app():
    spec = importlib.util.spec_from_file_location("build_app", ROOT / "scripts" / "build_app.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_reports_backend():
    payload = json.loads(CliRunner().invoke(main, ["desktop", "snapshot", "--demo"], catch_exceptions=False).output)
    assert payload["backend"] == {"version": __version__, "python": platform.python_version()}


def test_module_entry_point_is_the_cli():
    result = subprocess.run(
        [sys.executable, "-m", "marketpulse", "--help"], capture_output=True, text=True, check=True, cwd=ROOT
    )
    assert result.stdout.startswith("Usage: marketpulse ")


def test_strip_keeps_the_interpreter_and_stdlib(tmp_path, build_app):
    python = tmp_path / "python"
    for rel in [
        "bin/python3.14",
        "bin/pip3",
        "bin/idle3",
        "bin/python3-config",
        "lib/libpython3.14.dylib",
        "lib/libtcl9.0.dylib",
        "lib/tcl9.0/init.tcl",
        "lib/python3.14/os.py",
        "lib/python3.14/LICENSE.txt",
        "lib/python3.14/__pycache__/os.cpython-314.pyc",
        "lib/python3.14/lib-dynload/_ssl.cpython-314-darwin.so",
        "lib/python3.14/lib-dynload/_tkinter.cpython-314-darwin.so",
        "lib/python3.14/test/test_os.py",
        "lib/python3.14/tkinter/__init__.py",
        "lib/python3.14/site-packages/pip/__init__.py",
        "include/python3.14/Python.h",
    ]:
        (python / rel).parent.mkdir(parents=True, exist_ok=True)
        (python / rel).write_text("")
    (python / "bin/python3").symlink_to("python3.14")
    build_app.strip(python)
    left = sorted(str(p.relative_to(python)) for p in python.rglob("*") if not p.is_dir() or p.is_symlink())
    assert left == [
        "bin/python3",
        "bin/python3.14",
        "lib/python3.14/LICENSE.txt",
        "lib/python3.14/lib-dynload/_ssl.cpython-314-darwin.so",
        "lib/python3.14/os.py",
    ]
    assert (python / "lib/python3.14/site-packages").is_dir()  # emptied, then filled by the install step


def test_is_macho(tmp_path, build_app):
    (tmp_path / "lib.so").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 12)
    (tmp_path / "script").write_text("#!/bin/sh\n")
    (tmp_path / "link.so").symlink_to("lib.so")
    assert build_app.is_macho(tmp_path / "lib.so")
    assert not build_app.is_macho(tmp_path / "script")
    assert not build_app.is_macho(tmp_path / "link.so")  # signed through its target


@pytest.mark.skipif(not Path("/bin/realpath").exists() or os.name != "posix", reason="needs /bin/realpath")
def test_launcher_runs_bundled_python_isolated_through_links_and_spaces(tmp_path, build_app):
    backend = tmp_path / "My Apps" / "MarketPulse.app" / "backend"
    (backend / "bin").mkdir(parents=True)
    (backend / "python" / "bin").mkdir(parents=True)
    fake_python = backend / "python" / "bin" / "python3"
    fake_python.write_text('#!/bin/sh\nfor a in "$@"; do echo "$a"; done\n')
    fake_python.chmod(0o755)
    launcher = backend / "bin" / "marketpulse"
    launcher.write_text(build_app.LAUNCHER)
    launcher.chmod(0o755)
    (tmp_path / "mp").symlink_to(launcher)
    env = {"PATH": "/usr/bin:/bin"}
    for exe in (launcher, tmp_path / "mp"):
        out = subprocess.run([str(exe), "add", "a note"], env=env, capture_output=True, text=True, check=True).stdout
        assert out.splitlines() == ["-I", "-B", "-m", "marketpulse", "add", "a note"]
