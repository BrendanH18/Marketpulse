# ADR 0002: No Windows build

**Status:** decided by the maintainer on 2026-11-14.
**Date:** 2026-11-14
**Issue:** [#150](https://github.com/BrendanH18/Marketpulse/issues/150)
**Supersedes:** [ADR 0001](0001-windows-app-stack.md)

## Context

The App 1.0 plan was macOS first, then Windows. Between 2026-11-07 and 2026-11-11
the Windows work merged: a bundled x64 Python backend, an Avalonia app covering the
Mac app's workspaces, and an unsigned installer with a PowerShell install script.

None of it was ever run on a real Windows desktop. The evidence was Windows CI
(builds, bridge checks, a silent install and uninstall) and headless Avalonia
checks on Linux. All 31 Windows items in the QA checklist were unverified, and the
installer items could only be checked against a tagged release. Meanwhile the first
downloadable release had not been published, and the Windows files were part of it.

## Decision

MarketPulse does not build for Windows. The supported platforms are:

- **macOS:** the app, the CLI and the TUI.
- **Linux:** the CLI and the TUI.

The Windows app, installer, install script, backend bundle and their CI and
release jobs are removed. The code remains in Git history up to
[`bb393ef`](https://github.com/BrendanH18/Marketpulse/tree/bb393ef/windows).

## Consequences

- Releases contain the macOS files and one `SHA256SUMS`, as 2.2.0 was prepared.
- CI no longer runs the Python tests on Windows, so the CLI and TUI are untested
  there. Portability code in the engine (explicit UTF-8, the `tzdata` dependency
  on Windows) stays, because it is harmless and removing it gains nothing.
- The desktop bridge is unchanged. Commands and fields added during the Windows
  work stay, since the Mac app uses the tax commands and removing a field would
  need a version bump.
- Reversing this means restoring the code from history and doing the Windows
  desktop QA that was never done, before any Windows release.
