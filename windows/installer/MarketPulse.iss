; Per-user, unsigned Windows installer for MarketPulse (Inno Setup 6.3 or later).
;
; scripts/build_windows_release.py compiles this with:
;   ISCC.exe /Q /DAppVersion=<marketpulse.__version__> /DAppSource=<folder> /O<output folder> MarketPulse.iss
; where <folder> holds MarketPulse.exe and MarketPulse-backend\ (the same layout as the portable zip).
;
; Installs to %LOCALAPPDATA%\Programs\MarketPulse without administrator rights. Uninstalling removes
; only the install folder: the ledger in %USERPROFILE%\.marketpulse and the settings in
; %USERPROFILE%\.config\marketpulse are never touched.
;
; Silent use (scripts/install.ps1, CI):
;   MarketPulse-<version>-windows-x64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- [/DIR="..."]
;   "<install folder>\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART

#if Ver < 0x06030000
  #error Inno Setup 6.3 or later is required (for x64compatible).
#endif
#ifndef AppVersion
  #error Pass the MarketPulse version: ISCC /DAppVersion=<version>
#endif
#ifndef AppSource
  #error Pass the assembled app folder: ISCC /DAppSource=<folder with MarketPulse.exe and MarketPulse-backend>
#endif

[Setup]
; Never change AppId: it identifies the installation for upgrades and uninstalling, and
; scripts/build_windows_release.py reads it from here to find the uninstall registry entry.
AppId={{1BE3F098-91CE-4FF2-BE8A-06DCE09BD7BF}
AppName=MarketPulse
AppVersion={#AppVersion}
AppVerName=MarketPulse {#AppVersion}
AppPublisher=MarketPulse contributors
AppPublisherURL=https://github.com/BrendanH18/Marketpulse
AppSupportURL=https://github.com/BrendanH18/Marketpulse/issues
AppUpdatesURL=https://github.com/BrendanH18/Marketpulse/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName=MarketPulse
VersionInfoDescription=MarketPulse Setup
; No administrator rights and no "install for all users" choice: {autopf} is %LOCALAPPDATA%\Programs.
PrivilegesRequired=lowest
DefaultDirName={autopf}\MarketPulse
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
SetupIconFile={#SourcePath}..\MarketPulse.Demo\Assets\app.ico
UninstallDisplayIcon={app}\MarketPulse.exe
UninstallDisplayName=MarketPulse
OutputDir={#SourcePath}..\..\dist\windows-installer
OutputBaseFilename=MarketPulse-{#AppVersion}-windows-x64-setup
Compression=lzma2/max
SolidCompression=yes
; The app keeps running in the notification area. Close it (and any backend request) before
; replacing files; silent installs always close it. Don't restart the old copy afterwards.
CloseApplications=force
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Upgrades replace the whole backend so no file from an older version is left behind.
Type: filesandordirs; Name: "{app}\MarketPulse-backend"

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\MarketPulse"; Filename: "{app}\MarketPulse.exe"
Name: "{autodesktop}\MarketPulse"; Filename: "{app}\MarketPulse.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MarketPulse.exe"; Description: "{cm:LaunchProgram,MarketPulse}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only the bundled backend, which this installer owns entirely. Never the ledger or settings.
Type: filesandordirs; Name: "{app}\MarketPulse-backend"

[Code]
// Stop MarketPulse.exe and its bundled Python, but only copies started from this install folder.
// The tray app holds no unsaved work: every ledger change is written by a completed CLI command.
procedure StopInstalledProcesses();
var
  Folder: String;
  ResultCode: Integer;
begin
  Folder := AddBackslash(ExpandConstant('{app}'));
  // Escape the folder for a PowerShell single-quoted string (which also treats curly quotes as quotes).
  StringChangeEx(Folder, '''', '''''', True);
  StringChangeEx(Folder, #$2018, #$2018#$2018, True);
  StringChangeEx(Folder, #$2019, #$2019#$2019, True);
  StringChangeEx(Folder, #$201A, #$201A#$201A, True);
  StringChangeEx(Folder, #$201B, #$201B#$201B, True);
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' +
    '$folder = ''' + Folder + '''; ' +
    'Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and ' +
    '$_.ExecutablePath.StartsWith($folder, [StringComparison]::OrdinalIgnoreCase) -and ' +
    '@(''MarketPulse.exe'', ''python.exe'', ''pythonw.exe'') -contains $_.Name } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; ' +
    'Start-Sleep -Milliseconds 500"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Log('Could not run PowerShell to stop MarketPulse: ' + SysErrorMessage(ResultCode))
  else
    Log('Stopped any MarketPulse processes in ' + Folder + ' (exit code ' + IntToStr(ResultCode) + ').');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  // Interactive installs offer to close the app on the Restart Manager page instead.
  if WizardSilent() then
    StopInstalledProcesses();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopInstalledProcesses();
end;
