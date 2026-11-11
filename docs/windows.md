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
Income, Tax, Automation, and Allocation. Record transactions and preview a CSV before importing it.
Activity uses the bridge's signed cash-flow direction. Archived accounts stay out
of the workspaces and totals. Privacy hides portfolio details in both the window
and tray. Closing the window keeps the app running in the tray; choose **Open
MarketPulse** to reopen it or **Exit** to stop it and its active backend request.
A failed refresh displays an error rather than a zero balance.

### Watchlists and alerts

In **Watchlist & alerts**, use **Move up** and **Move down** to change the saved
symbol order. The first and last rows disable moves past the ends. Symbols whose
quotes are unavailable stay in the list and can still be moved or removed.

Each alert offers **Edit alert** for its threshold and note, and **Pause** or
**Resume** for whether it is enabled. Editing, pausing and resuming preserve its
last trigger time: resuming a triggered alert does not make it fire again.
**Rearm alert…** asks for confirmation, then enables the alert and clears its trigger
history so the next matching fresh price can fire again. Stale prices never fire
alerts. Windows toast notifications remain unavailable.

Filter the list by state without changing saved alerts: **Armed** means enabled
and not yet triggered, **Paused** means disabled (even with a previous trigger),
and **Triggered** means enabled with a saved trigger time. **All** shows every
alert. Privacy hides identifying details and the demo disables writes.

The version-1 desktop snapshot adds `watchlist_symbols`, the saved symbol order
including unpriced entries. Older engines omit it; the Windows app then shows
the quoted symbols available in their snapshot and disables reordering until
the engine is updated.

### Tax reports

Open **Tax** to calculate capital gains with the existing Python engine. Choose a
year to see proceeds, pooled cost base, net and taxable gains, denied losses, and
the individual dispositions. Superficial-loss details explain the denied amount
and replacement-share window. All report amounts use the stated base currency;
the app does not calculate tax figures itself.

Reports load when you open Tax and reload after relevant ledger or settings
changes. Other workspaces do not calculate tax during routine refreshes.
**Recalculate** retries a failed report or requests fresh figures. Missing exchange
rates and ledger issues are shown explicitly: unknown amounts display as a dash,
and incomplete sales are excluded from the engine's totals. Archived taxable
transactions remain in tax reports, labelled as archived without their account
names; ordinary portfolio workspaces continue to hide archived accounts.

**Export CSV…** saves the selected year's dispositions through the same engine
used by the report. Review any export warnings before sharing the file with your
accountant. Cancelling the file picker writes nothing. Privacy hides the report
and its messages; turn it off to read them. The offline demo includes fictional
tax figures and disables export. Figures are estimates: check them against your
slips before filing.

### Custom assets and allocation

In **Holdings**, choose **Add GIC or bond** to record a principal, annual rate,
compounding method, start and maturity date. Choose **Add manually valued asset**
for property, private shares or other assets you value yourself. Each form uses
an active account and defaults to its currency. Symbols must be new to the
portfolio, including archived accounts. The forms send `--new-symbol` to the
engine, which checks the complete ledger before changing pricing metadata.
The engine supplies accrual and valuation results; no quotes are requested for
these custom assets. A purchase reduces the account's tracked cash balance.

Manual holdings offer **Record a valuation**, with a date and value per unit.
The valuation applies to that symbol across accounts, including archived ones.
Every holding offers **Change asset class**, which changes its classification
across accounts without changing transactions. Holdings show the saved valuation
date or the fixed-income term and rate.

**Allocation** shows each asset class's value and share in the portfolio's base
currency. **Set targets** or **Change targets** replaces the saved percentages;
each must be between 0 and 100, with a total at or below 100. A blank field means
no target for that class. **Clear targets** removes all targets after confirmation
and keeps holdings and transactions. The engine supplies target drift and
suggested adjustments. These are suggestions only; MarketPulse does not trade.
Review warnings about missing prices or exchange rates before using the totals.

Privacy hides holdings and allocation details. Demo mode displays fictional
allocation and targets but disables changes. If an asset save has an uncertain
result, the dialog keeps the submitted fields fixed: retry submits the same
request safely, rather than recording the asset or valuation twice.

### Backups and restore

In **Automation › Backups and restore**, **Back up now** saves a consistent copy
of the ledger in the engine's backup folder. The list shows each backup's file
name, time, reason and size. **Restore this backup…** asks you to confirm the
selected file and that entries recorded after it will be replaced. Configuration
is kept; it is not part of the backup.

The engine validates the selected database and creates a **Before a restore**
backup of the current ledger before replacing it. If validation or that safety
copy fails, the restore is refused. To undo a successful restore, restore the
corresponding **Before a restore** copy. The app refreshes after creating or
restoring a backup. A successful restore followed by a failed refresh is reported
as restored, with a separate refresh error. If a timeout or crash leaves the
restore result unknown, refresh and inspect Activity and the backup list before
confirming another restore. Confirmation rechecks the current ledger and backup
metadata through the engine, including edits made by the CLI or another app.
This includes saved assets, watchlists (even symbols without quotes), alerts,
and allocation targets as well as ledger entries and accounts.

Privacy hides backup paths and details. The fictional demo cannot create or
restore backups. These controls use the same engine commands as the CLI; no
backup file is uploaded. Backups outside the configured folder can still be
restored using the [CLI](data.md#restore-a-database).

The focused headless UI regression check runs against an installed or bundled
Python engine and creates its own fictional cash ledger:

```powershell
dotnet restore windows/MarketPulse.BackupUiCheck --locked-mode -p:UseAppHost=false
dotnet run --project windows/MarketPulse.BackupUiCheck --no-restore -p:UseAppHost=false -- "$python"
```

`$python` is the absolute engine interpreter path from the build checks below.
An optional second argument saves rendered screenshots to that directory.
The check exercises create/restore button events, confirmation and cancellation,
stale confirmations, privacy, and demo controls. Linux additionally injects a
missing backend and a failed post-restore refresh. These headless checks run in
Windows CI too; they do not replace the Windows desktop and Narrator checklist.

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
