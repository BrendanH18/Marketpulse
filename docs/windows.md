# Windows backend builds

[App plan](app-plan.md) · [Contributing](../CONTRIBUTING.md)

The Windows x64 backend is a self-contained Python engine for the future Windows
app ([#51](https://github.com/BrendanH18/Marketpulse/issues/51)). It includes the
CLI, TUI, and desktop JSON bridge. An Avalonia window/tray demo is described below;
the full Windows interface (#52) and installer/release packaging (#53) are separate work.

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

## Windows UI demo

The maintainer chose **Avalonia with C#/XAML** for the Windows interface.
[ADR 0001](adr/0001-windows-app-stack.md) compares WinUI 3, Avalonia, Tauri, and
Flutter and records the tradeoffs. `windows/MarketPulse.Demo` is a small
fictional-data demo, not the full Windows app or an installer. It shows net worth
from `desktop snapshot --demo`; every request overrides data/config locations
with a new temporary directory that is removed afterwards. It never loads your
portfolio and makes no quote or update requests.

The window opens at launch. **Refresh demo** reloads the fictional portfolio.
Closing the window hides it to the tray; **Open MarketPulse demo** opens it again.
The tray menu can also refresh it or exit the process. Use **Exit** in the tray
menu to quit. A missing backend,
timeout, or incompatible/invalid snapshot shows an error instead of a zero balance.

### Build and run on Windows x64

Install .NET SDK **10.0.403** and uv. Avalonia **12.1.5** and its transitive
dependencies are pinned in the project's NuGet lock. From the repository root
in PowerShell:

```powershell
uv sync --locked --dev --python 3.14
uv run --locked python scripts/build_windows_backend.py
dotnet restore windows/MarketPulse.Demo/MarketPulse.Demo.csproj --locked-mode -r win-x64 -p:SelfContained=true
dotnet publish windows/MarketPulse.Demo/MarketPulse.Demo.csproj -c Release -r win-x64 --self-contained true --no-restore -o dist/windows/demo
Copy-Item -Recurse -Force dist/windows/x86_64/MarketPulse-backend dist/windows/demo/MarketPulse-backend
```

For a clean repeat build, remove only the previous generated `dist/windows/demo`
output first, so `Copy-Item` does not nest a second backend inside the existing
one. Keep the entire published folder together when relocating it. It includes
the .NET runtime and Python backend, so the user needs neither installed.
The CI artifact **marketpulse-windows-x64-demo** contains this folder; it is a
development artifact rather than a signed or published release.

Run the decoder/error-path checks against the real bundled interpreter, then the
published executable's bridge check, then open the window:

```powershell
$python = (Resolve-Path dist/windows/demo/MarketPulse-backend/python/python.exe).Path
dotnet run --project windows/MarketPulse.BridgeCheck -- "$python"
$check = Start-Process -FilePath dist/windows/demo/MarketPulse.Demo.exe -ArgumentList "--check-bridge" -Wait -PassThru -NoNewWindow
if ($check.ExitCode -ne 0) { throw "Bridge check failed." }
& ./dist/windows/demo/MarketPulse.Demo.exe
```

The check mode runs before Avalonia starts and uses the same subprocess and
decoder as the window. CI publishes on `windows-latest`, runs both checks, and
uploads the complete demo and backend. Follow the [Windows demo QA checklist](qa.md#windows-demo)
to verify the actual window, tray and accessibility; a build/bridge check does
not verify those UI interactions.

### Development on Linux or macOS

Avalonia can build the Windows target from other development systems. To run the
demo locally with an installed development backend, first run `uv sync --locked --dev`,
then pass its interpreter explicitly (use the absolute path):

```bash
dotnet run --project windows/MarketPulse.Demo -- --python "$PWD/.venv/bin/python"
dotnet run --project windows/MarketPulse.Demo -- --check-bridge --python "$PWD/.venv/bin/python"
dotnet run --project windows/MarketPulse.BridgeCheck -- "$PWD/.venv/bin/python"
```

These commands still request only fictional data. Desktop/tray availability
depends on the host, and Linux/macOS checks do not establish Windows UI behavior.
The SwiftUI Mac app remains the supported Mac interface.
