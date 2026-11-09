# Install MarketPulse on Windows from a GitHub Release.
#
#   irm https://github.com/BrendanH18/Marketpulse/releases/latest/download/install.ps1 | iex
#   & ([scriptblock]::Create((irm https://github.com/BrendanH18/Marketpulse/releases/latest/download/install.ps1))) -Version v2.3.0
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Version v2.3.0
#
# MarketPulse isn't code-signed (see docs/install.md), so Windows warns about its installer when
# a browser downloads it. This script downloads the per-user installer itself and checks it first:
# its SHA-256 must match the release's SHA256SUMS, or nothing runs. It then installs silently for
# your account only (no administrator rights) and checks that the installed MarketPulse.exe is the
# version you asked for.
#
# Runs on Windows PowerShell 5.1 and PowerShell 7. Keep this file plain ASCII without a byte-order
# mark: Windows PowerShell reads BOM-less files in the system code page, and `irm | iex` would
# choke on a BOM. Every command runs from Install-MarketPulse, called on the last line, so a
# download cut short runs nothing. Helpers are nested inside it so `iex` leaves only that one
# function (and the parameters below) behind in your session.

param(
    [string]$Version = '',
    [string]$Dir = '',
    [switch]$NoLaunch,
    [string]$BaseUrl = 'https://github.com/BrendanH18/Marketpulse/releases',
    [switch]$Help
)

function Install-MarketPulse {
    param(
        [string]$Version,
        [string]$Dir,
        [switch]$NoLaunch,
        [string]$BaseUrl,
        [switch]$Help,
        [object[]]$Unknown,
        [switch]$AsFile
    )
    # Scoped to this function, so `iex` doesn't change the caller's preferences.
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue' # Windows PowerShell's progress bar makes downloads crawl
    Set-StrictMode -Version 2.0

    $repo = 'BrendanH18/Marketpulse'

    function Fail([string]$Message) { throw $Message }
    function Say([string]$Message) { Write-Host $Message }

    function Show-Usage {
        Say @"
Install MarketPulse for Windows from a GitHub Release.

Usage: install.ps1 [-Version vX.Y.Z] [-Dir FOLDER] [-NoLaunch]

  -Version vX.Y.Z  Install this release (default: the latest release).
  -Dir FOLDER      Install into FOLDER (default: %LOCALAPPDATA%\Programs\MarketPulse,
                   or wherever MarketPulse is already installed).
  -NoLaunch        Don't start MarketPulse after installing.
  -BaseUrl URL     Download from a mirror of https://github.com/$repo/releases
                   (same layout: URL/latest, URL/download/<tag>/<file>). The checksums
                   come from the mirror too, so only use a mirror you trust.
  -Help            Show this help.

With irm | iex, pass options like this:
  & ([scriptblock]::Create((irm <url of install.ps1>))) -Version vX.Y.Z

Installs for your account only; it never asks for administrator rights. Your portfolio in
%USERPROFILE%\.marketpulse is never touched. Reinstalling or upgrading replaces only the app.
"@
    }

    function Invoke-Request([hashtable]$Request) {
        # Three tries, like install.sh's curl --retry: networks drop connections now and then.
        for ($attempt = 1; ; $attempt++) {
            try {
                return Invoke-WebRequest @Request -UseBasicParsing
            } catch {
                if ($attempt -ge 3) { throw }
                Start-Sleep -Seconds (2 * $attempt)
            }
        }
    }

    function Get-Download([string]$Url, [string]$Path) {
        Invoke-Request @{ Uri = $Url; OutFile = $Path } | Out-Null
    }

    function Get-LatestTag([string]$Base) {
        # Like install.sh: follow the /latest redirect to .../tag/vX.Y.Z.
        try {
            $response = Invoke-Request @{ Uri = "$Base/latest"; Method = 'Head' }
        } catch {
            Fail "couldn't look up the latest release at $Base/latest ($($_.Exception.Message))."
        }
        $raw = $response.BaseResponse
        $final = ''
        if ($raw.PSObject.Properties['ResponseUri']) {
            $final = [string]$raw.ResponseUri.AbsoluteUri # Windows PowerShell: HttpWebResponse
        } elseif ($raw.PSObject.Properties['RequestMessage']) {
            $final = [string]$raw.RequestMessage.RequestUri.AbsoluteUri # PowerShell 7: HttpResponseMessage
        }
        if ($final -cmatch '/tag/([^/?#]+)/?\z') { return [Uri]::UnescapeDataString($Matches[1]) }
        Fail "couldn't find the latest release (got $final). Pass -Version vX.Y.Z."
    }

    function Find-InstalledFolder {
        # Where setup put MarketPulse: an upgrade keeps the folder of the existing install. The key
        # is Inno Setup's per-user uninstall entry, named after the AppId in windows/installer/MarketPulse.iss.
        $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{1BE3F098-91CE-4FF2-BE8A-06DCE09BD7BF}_is1'
        $values = Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue
        if ($values -and $values.PSObject.Properties['Inno Setup: App Path']) { return [string]$values.'Inno Setup: App Path' }
        return ''
    }

    function Invoke-Install {
        if ($Help) { Show-Usage; return }
        $extra = @($Unknown | Where-Object { $null -ne $_ })
        if ($extra.Count -gt 0) { Fail "unknown option $($extra[0]) (see -Help)." }

        if ($PSVersionTable.PSVersion.Major -lt 5) { Fail 'this script needs Windows PowerShell 5.1 or PowerShell 7.' }
        if ($PSVersionTable.PSEdition -eq 'Core' -and -not $IsWindows) {
            Fail "MarketPulse for Windows needs Windows. On a Mac, use install.sh: https://github.com/$repo/blob/main/docs/install.md"
        }
        if (-not [Environment]::Is64BitOperatingSystem) { Fail 'MarketPulse needs 64-bit Windows.' }

        $base = $BaseUrl.TrimEnd('/')
        # Over plain HTTP, anyone in between could swap the installer and SHA256SUMS together. Plain
        # HTTP is allowed only to this computer, for testing a local mirror.
        if ($base -notmatch '\Ahttps://' -and $base -notmatch '\Ahttp://(127\.0\.0\.1|localhost)(:[0-9]+)?(/|\z)') {
            Fail '-BaseUrl must start with https://.'
        }

        # Windows PowerShell 5.1 may still default to TLS 1.0, which GitHub refuses. Add 1.2 (process-wide,
        # and harmless to the rest of the session).
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

        $number = $Version
        if (-not $number) { $number = Get-LatestTag $base }
        if ($number.StartsWith('v')) { $number = $number.Substring(1) }
        # Only plain version strings reach a URL or a path. (\z, not $, which also matches before a newline.)
        if ($number -cnotmatch '\A[0-9]+\.[0-9]+\.[0-9]+([.+-]?[0-9A-Za-z]+)*\z') {
            Fail "`"$number`" isn't a version like v2.2.0."
        }
        $tag = "v$number"
        $setupName = "MarketPulse-$number-windows-x64-setup.exe"

        $target = ''
        if ($Dir) {
            if ($Dir.Contains('"')) { Fail '-Dir can''t contain a double quote.' }
            # Relative to this PowerShell location, not the process's working folder.
            $target = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Dir).TrimEnd('\', '/')
            if ($target -match '\A[A-Za-z]:\z') { Fail '-Dir must be a folder, not the root of a drive.' }
            if (Test-Path -LiteralPath $target -PathType Leaf) { Fail "$target is a file, not a folder." }
        }

        $temp = Join-Path ([IO.Path]::GetTempPath()) ('marketpulse-install-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $temp | Out-Null
        try {
            $sumsPath = Join-Path $temp 'SHA256SUMS'
            $setupPath = Join-Path $temp $setupName
            $logPath = Join-Path $temp 'setup.log'

            Say "Downloading MarketPulse $number for Windows x64..."
            try { Get-Download "$base/download/$tag/SHA256SUMS" $sumsPath } catch {
                Fail "couldn't download SHA256SUMS for $tag ($($_.Exception.Message)). Check that the release exists and has Windows downloads: https://github.com/$repo/releases"
            }
            try { Get-Download "$base/download/$tag/$setupName" $setupPath } catch {
                Fail "couldn't download $setupName from release $tag ($($_.Exception.Message))."
            }

            # Exactly one well-formed line for the installer, or nothing runs.
            $expected = @()
            foreach ($line in [IO.File]::ReadAllLines($sumsPath)) {
                if ($line.Trim() -eq '') { continue }
                if ($line -cmatch '\A([0-9a-f]{64})  (.+)\z') {
                    if ($Matches[2] -ceq $setupName) { $expected += $Matches[1] }
                } else {
                    Fail "SHA256SUMS for $tag has a malformed line: $line"
                }
            }
            if ($expected.Count -ne 1) { Fail "SHA256SUMS for $tag has no single entry for $setupName." }
            # .NET rather than Get-FileHash: Windows PowerShell started from PowerShell 7 inherits a
            # PSModulePath that hides Get-FileHash, but SHA256 is always there.
            $stream = [IO.File]::OpenRead($setupPath)
            try {
                $sha = [Security.Cryptography.SHA256]::Create()
                try { $digest = $sha.ComputeHash($stream) } finally { $sha.Dispose() }
            } finally { $stream.Dispose() }
            $actual = ([BitConverter]::ToString($digest) -replace '-', '').ToLowerInvariant()
            if ($actual -cne $expected[0]) {
                Fail "$setupName doesn't match its checksum in SHA256SUMS (expected $($expected[0]), got $actual). Nothing was installed."
            }
            Say "Checksum verified: $actual"

            # Invoke-WebRequest doesn't normally add the Mark of the Web (a Zone.Identifier stream), but
            # some security software and policies do. A marked, unsigned program makes Windows ask
            # before it runs, which would stall a silent install with a prompt nobody sees. The mark
            # says "this came from the internet"; the checksum above is the stronger check that it is
            # the file the release published, so remove the mark from this verified copy only.
            $zone = $null
            try { $zone = Get-Item -LiteralPath $setupPath -Stream 'Zone.Identifier' -ErrorAction SilentlyContinue } catch { $zone = $null }
            if ($zone) {
                Say 'The download carries the Mark of the Web (Zone.Identifier); removing it from the verified copy.'
                Unblock-File -LiteralPath $setupPath
            }

            if (Get-Process -Name 'MarketPulse' -ErrorAction SilentlyContinue) {
                Say 'MarketPulse is running; setup closes it before replacing it.'
            }
            $setupArgs = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', "/LOG=`"$logPath`"")
            if ($target) { $setupArgs += "/DIR=`"$target`"" }
            Say 'Installing for this Windows account (no administrator rights needed)...'
            # Not Start-Process -Wait: that also waits for every process setup starts. And with
            # UseShellExecute off, Windows refuses (rather than prompts) if setup ever asked for admin.
            $start = New-Object System.Diagnostics.ProcessStartInfo
            $start.FileName = $setupPath
            $start.Arguments = $setupArgs -join ' '
            $start.UseShellExecute = $false
            try { $process = [System.Diagnostics.Process]::Start($start) } catch {
                Fail ("Windows wouldn't start setup ($($_.Exception.Message)). If Smart App Control is on, it may block " +
                    "programs that aren't code-signed, including MarketPulse: https://github.com/$repo/blob/main/docs/install.md#windows")
            }
            $process.WaitForExit()
            if ($process.ExitCode -ne 0) {
                if (Test-Path -LiteralPath $logPath) {
                    Say 'Setup log (last lines):'
                    Get-Content -LiteralPath $logPath -Tail 20 | ForEach-Object { Say "  $_" }
                }
                Fail "setup exited with code $($process.ExitCode); see https://jrsoftware.org/ishelp/topic_setupexitcodes.htm"
            }

            $folder = $target
            if (-not $folder) { $folder = Find-InstalledFolder }
            if (-not $folder) { $folder = Join-Path $env:LOCALAPPDATA 'Programs\MarketPulse' }
            $exe = Join-Path $folder 'MarketPulse.exe'
            if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { Fail "setup finished, but $exe is missing." }
            $installed = (Get-Item -LiteralPath $exe).VersionInfo.ProductVersion
            if ($installed -cne $number) { Fail "$exe reports version $installed, not $number." }
        } finally {
            Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
        }

        $data = Join-Path $HOME '.marketpulse'
        if ($env:MARKETPULSE_DATA) { $data = $env:MARKETPULSE_DATA }
        Say "Installed MarketPulse $number to $folder"
        Say "Your portfolio in $data was not touched. To uninstall, use Settings > Apps > Installed apps, or run $(Join-Path $folder 'unins000.exe')."
        if (-not $NoLaunch) { Start-Process -FilePath $exe }
    }

    try {
        Invoke-Install
    } catch {
        $message = "MarketPulse install: $($_.Exception.Message)"
        if ($AsFile) {
            # Run as a file (powershell -File install.ps1): print the reason and exit with status 1.
            [Console]::Error.WriteLine($message)
            exit 1
        }
        # Run through iex or a script block: exit would close the user's PowerShell window, so throw.
        throw $message
    }
}

Install-MarketPulse -Version $Version -Dir $Dir -NoLaunch:$NoLaunch -BaseUrl $BaseUrl -Help:$Help -Unknown $args -AsFile:($MyInvocation.MyCommand.CommandType -eq 'ExternalScript')
