# Windows app and backend builds

[App plan](app-plan.md) · [Contributing](../CONTRIBUTING.md)

This page is about building MarketPulse for Windows. To install a released version, see
[Install on Windows](install.md#windows).

The Windows x64 backend is a self-contained Python engine for the Windows
app ([#51](https://github.com/BrendanH18/Marketpulse/issues/51)). It includes the
CLI, TUI, and desktop JSON bridge. The Avalonia portfolio app is described below;
[Build the installer](#build-the-installer) packages both into the Windows release files.

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
These artifacts are development builds; release files come from
[Build the installer](#build-the-installer).

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

## Windows portfolio app

The app uses **Avalonia with C#/XAML**, as recorded in [ADR 0001](adr/0001-windows-app-stack.md).
Its project directory retains the original spike name, `windows/MarketPulse.Demo`,
but the published executable is **MarketPulse.exe**. It reads the version-1 desktop
bridge and sends writes through the existing CLI. Financial calculations remain
in Python. It shares the CLI's ledger and configuration paths by default.

The window provides Overview, Holdings, Activity, Accounts, Watchlist and alerts,
Income, and Automation. Record transactions and preview a CSV before importing it.
Activity uses the bridge's signed cash-flow direction. Archived accounts stay out
of the workspaces and totals. Privacy hides portfolio details in both the window
and tray. Closing the window keeps the app running in the tray; choose **Open
MarketPulse** to reopen it or **Exit** to stop it and its active backend request.
A failed refresh displays an error rather than a zero balance.

Windows desktop notifications are not implemented; alert state remains visible in
the app. Automatic startup is not implemented. The installer and portable zip are
built as described in [Build the installer](#build-the-installer).

### Build and run on Windows x64

Install .NET SDK **10.0.403** and uv. Avalonia **12.1.5** and its transitive
packages are pinned in the NuGet lock. From the repository root in PowerShell:

```powershell
uv sync --locked --dev --python 3.14
uv run --locked python scripts/build_windows_backend.py
dotnet restore windows/MarketPulse.Demo/MarketPulse.Demo.csproj --locked-mode -p:RuntimeIdentifier=win-x64 -p:SelfContained=true
dotnet publish windows/MarketPulse.Demo/MarketPulse.Demo.csproj -c Release -r win-x64 --self-contained true --no-restore -o dist/windows/app
Copy-Item -Recurse -Force dist/windows/x86_64/MarketPulse-backend dist/windows/app/MarketPulse-backend
```

Use a fresh `dist/windows/app` output for repeat builds to avoid nesting a second
backend. Keep the entire published folder together when relocating it. The CI
artifact **marketpulse-windows-x64-app** includes .NET and Python; no developer
runtime is required to run it. It is a development artifact; releases ship the
installer and portable zip from [Build the installer](#build-the-installer).

Run the decoder and scratch-ledger checks, then verify the published bundle:

```powershell
$python = (Resolve-Path dist/windows/app/MarketPulse-backend/python/python.exe).Path
dotnet run --project windows/MarketPulse.BridgeCheck -- "$python"
$check = Start-Process -FilePath dist/windows/app/MarketPulse.exe -ArgumentList "--check-bridge" -Wait -PassThru -NoNewWindow
if ($check.ExitCode -ne 0) { throw "Bridge check failed." }
& ./dist/windows/app/MarketPulse.exe --demo
```

`--check-bridge` always uses fictional data and exits before starting Avalonia.
`--demo` opens a read-only fictional portfolio without reading real data or making
quote requests. Launch without `--demo` to open the normal portfolio.

### Build the installer

Install Inno Setup 6.3 or later as well as the .NET SDK and uv above. CI pins Inno
Setup 6.7.4 and checks its SHA-256 (`.github/actions/install-inno-setup`). From the
repository root in PowerShell:

```powershell
uv run --locked python scripts/build_windows_release.py --out dist/windows-release
```

The script builds and smoke-tests the backend with `build_windows_backend.py`,
publishes `MarketPulse.exe` with the package version as its file and product
version, adds the backend as `MarketPulse-backend`, and runs `--check-bridge`. It
then writes the release folder:

| File | Contents |
| --- | --- |
| `MarketPulse-<version>-windows-x64-setup.exe` | Per-user Inno Setup installer from `windows/installer/MarketPulse.iss` |
| `MarketPulse-<version>-windows-x64.zip` | Portable copy: one `MarketPulse/` folder with `MarketPulse.exe` and `MarketPulse-backend/` |
| `install.ps1` | A copy of `scripts/install.ps1` |
| `SHA256SUMS` | `<sha256>  <name>` for the three files above |

The installer needs no administrator rights. It installs to
`%LOCALAPPDATA%\Programs\MarketPulse`, adds a Start menu shortcut (and optionally a
desktop shortcut) and appears in Settings › Apps. Upgrades replace the whole
backend folder, and setup and uninstall close a running MarketPulse first.
Uninstalling removes only the install folder, never `~/.marketpulse` or
`~/.config/marketpulse`. Neither the installer nor the app is code-signed. Keep the
`AppId` in the `.iss` file unchanged; upgrades and the uninstall entry depend on it.

After building, the script installs the setup silently into a temporary folder. It
checks the installed version, bridge, shortcut, and uninstall entry, then upgrades
in place over a running app and uninstalls. Because the test uses the real `AppId`,
it stops if MarketPulse is already installed for your Windows account. Uninstall it
first, or pass `--skip-install-test` while debugging locally. `--skip-smoke` skips
the backend smoke test. ISCC is taken from `--iscc`, then `PATH`, then the standard
Inno Setup 6 folders. `--work DIR` keeps the assembled app in `DIR/MarketPulse` and
the backend in `DIR/backend`. To check an existing release folder on any system, run
`scripts/build_windows_release.py --verify dist/windows-release`. CI builds all of
this on `windows-latest`, uploads it as **marketpulse-windows-x64-release**, and runs
`scripts/check_windows_install.py` against it. The Release workflow attaches the same
files to the draft GitHub Release.

### Scratch-ledger QA

Create a fresh fictional ledger and sample CSV with the helper. It prints paths
as JSON and never reuses an existing directory:

```powershell
$qa = uv run --locked python scripts/qa_windows.py | ConvertFrom-Json
& ./dist/windows/app/MarketPulse.exe --data-dir "$($qa.data)" --config "$($qa.config)"
```

The initial ledger uses manual CAD assets so its snapshot needs no market
requests. The sample CSV includes valid and skipped rows, including an archived
account. Use its path (`$qa.csv`) for import QA. Adding market symbols or alerts
can request quotes through the existing providers. Pass **both** path overrides:
passing just one is rejected to prevent mixing scratch data with normal settings.
Follow the [Windows QA checklist](qa.md#windows-app). Build and bridge checks do
not establish that the window, tray, keyboard or Narrator work on Windows.

### Development on Linux or macOS

Avalonia can build the Windows target from other systems. To run with an installed
development backend, first run `uv sync --locked --dev`, then:

```bash
dotnet restore windows/MarketPulse.Demo/MarketPulse.Demo.csproj --locked-mode -p:UseAppHost=false
dotnet run --project windows/MarketPulse.Demo --no-restore -p:UseAppHost=false -- --demo --python "$PWD/.venv/bin/python"
dotnet run --project windows/MarketPulse.Demo --no-restore -p:UseAppHost=false -- --check-bridge --python "$PWD/.venv/bin/python"
dotnet run --project windows/MarketPulse.BridgeCheck -- "$PWD/.venv/bin/python"
```

For writable QA, run `scripts/qa_windows.py` and replace `--demo` with both printed
`--data-dir` and `--config` paths. Desktop/tray availability depends on the host;
Linux/macOS checks do not establish Windows UI behavior. `UseAppHost=false` runs
through `dotnet`, keeping runtime targets independent of the developer machine.
The SwiftUI app remains the supported Mac interface.
