# Windows backend builds

[App plan](app-plan.md) · [Contributing](../CONTRIBUTING.md)

The Windows x64 backend is a self-contained Python engine for the future Windows
app ([#51](https://github.com/BrendanH18/Marketpulse/issues/51)). It includes the
CLI, TUI, and desktop JSON bridge. The native Windows interface (#50/#52) and
installer/release packaging (#53) are separate work.

## Build and verify

On Windows x64, install Git and uv, then run these commands in PowerShell from
the repository root:

```powershell
uv sync --locked --dev --python 3.14
uv run --locked pytest -q
uv run --locked python scripts/build_windows_backend.py --out "dist/Windows backend"
```

The builder downloads pinned CPython 3.14.7 from python-build-standalone through
uv, builds the project wheel, and installs only binary dependencies exported
from `uv.lock`, with their hashes checked. Running the resulting backend needs
neither uv nor an installed Python. Preserve the whole output folder when
copying it to another computer.

The default build includes a smoke test after relocation to a path with spaces.
It checks the backend and Python versions, a fictional desktop snapshot,
writing/exporting a scratch transaction, and loading native dependencies. All
smoke-test data is temporary; it never uses your portfolio. CI runs this build
on `windows-latest` and uploads the verified backend as a workflow artifact.
These artifacts are development builds, not published releases or installers.

## Paths and platform behavior

Windows keeps existing paths, with `~` meaning your Windows user profile:

| Purpose | Default | Override |
| --- | --- | --- |
| Ledger and backups | `~/.marketpulse` | `MARKETPULSE_DATA` |
| Configuration | `~/.config/marketpulse/config.toml` | `MARKETPULSE_CONFIG`; `XDG_CONFIG_HOME` also applies |

There is no migration to AppData. Use a directory you control: Windows uses
inherited filesystem ACLs, rather than Unix owner-only permission bits, for
configuration files (which can contain your optional provider key).

Desktop notifications currently return without displaying a Windows toast.
Alert evaluation still works. Timezone data is packaged on Windows so market
hours calculations do not depend on an operating-system IANA database.

The supported bundle target is x64. The locked dependencies, including
`curl_cffi`, also resolve to binary wheels for Windows ARM64, but this build
does not produce or verify an ARM64 bundle.

## Run the bundled engine

For a fictional snapshot, point both locations at a new scratch directory before
running the bundled interpreter. These PowerShell commands use the output path
from the build example above:

```powershell
$env:MARKETPULSE_DATA = Join-Path ([System.IO.Path]::GetTempPath()) ("marketpulse-demo-" + [guid]::NewGuid())
$env:MARKETPULSE_CONFIG = Join-Path $env:MARKETPULSE_DATA "config.toml"
& ".\dist\Windows backend\x86_64\MarketPulse-backend\python\python.exe" -I -B -X utf8 -m marketpulse desktop snapshot --demo
```

The convenience `marketpulse.cmd` beside the `python` folder also accepts CLI
commands, for example `marketpulse.cmd --version`. It uses Windows shell syntax.
Native interfaces should invoke `python/python.exe` directly with an argument
array beginning `-I`, `-B`, `-X`, `utf8`, `-m`, `marketpulse`, followed by the
command arguments. This preserves arbitrary user text without shell expansion;
put user-entered positional values after `--` as with the Mac interface. Decode
stdout as UTF-8. Isolated mode ignores user Python settings, `-B` avoids writing
bytecode into the bundle, and `-X utf8` keeps JSON and CSV output consistent on
Windows regardless of the system code page.
