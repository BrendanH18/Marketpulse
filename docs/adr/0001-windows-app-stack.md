# ADR 0001: Windows app stack

**Status:** accepted by the maintainer on 2026-11-07, before implementing the spike.
**Date:** 2026-11-07
**Issue:** [#50](https://github.com/BrendanH18/Marketpulse/issues/50)

## Context

MarketPulse has a SwiftUI macOS interface and a relocatable Windows x64 Python
backend. The Windows interface must consume the existing versioned desktop JSON
bridge, preserve local data paths, and support unsigned distribution. The next
step is a small architecture spike, not the full workspace (#52) or installer
(#53).

## Decision

Use **Avalonia with C# and XAML**, published as a self-contained .NET folder.
This is a maintenance judgment based on the documented integration paths, not
a measured performance or bundle-size result. The maintainer explicitly approved
Avalonia with C#/XAML for the demo and Windows UI direction.

Avalonia supplies tray integration and Windows UI Automation support with a
standard .NET CLI build. It also permits Windows cross-compilation from Linux
and macOS, useful for contributors working on the existing Python/macOS project.
Pin framework/package versions and use documentation matching that major version:
the current Avalonia documentation covers version 12, while version 11 has a
separate documentation site.

## Alternatives

| Criterion | WinUI 3 (.NET) | Avalonia (.NET) | Tauri (Rust + web) | Flutter |
| --- | --- | --- | --- | --- |
| Windows appearance | Native Windows Fluent controls | Fluent theme; self-rendered controls | HTML/CSS in WebView2; conventions require design work | Custom widgets; Fluent styling uses community packages |
| Unsigned distribution | Unpackaged, self-contained folder; carries Windows App SDK and .NET dependencies | Self-contained .NET folder, suitable for ZIP or later classic installer | MSI/NSIS support; WebView2 availability must be handled | ZIP or classic installer; carries Flutter and native runtime dependencies |
| System tray | Win32 interop or wrapper library | Built-in TrayIcon and native menu | First-party tray API | Community package or Win32 implementation |
| Existing Python bridge | C# process and JSON APIs | C# process and JSON APIs | Rust process and JSON APIs | Dart process and JSON APIs |
| Accessibility | Windows UIA and automation peers | Windows UIA and automation peers | Web semantics through WebView2 | Widget semantics and platform accessibility bridge |
| Windows CI | Windows toolchain and Windows App SDK | Standard .NET CLI; cross-compilation also possible | Rust/MSVC and web tooling | Flutter SDK and Visual Studio C++ workload |
| Contributor guidance | Microsoft Learn, official samples and CI guidance | Official CLI, controls, platform and deployment guides | Official desktop integration and GitHub Actions guides | Official Windows guides; community desktop integrations |
| Maintenance judgment | Best native appearance; extra deployment and tray plumbing | Best fit for this scope: one UI toolchain with built-in tray | Strong fallback; adds Rust and web tooling | More desktop integration dependencies without a mobile requirement |

All four can reuse the backend without moving financial calculations into the
interface. All require real Windows keyboard, screen-reader and tray checks;
framework accessibility documentation is not proof of application accessibility.
Unsigned distribution still carries Windows reputation/security prompts.

## Spike and proof

- A window showing the net worth and currency supplied by the demo snapshot.
- A tray icon with an open-window action and an explicit exit action.
- Launch the bundled interpreter directly with an argument array:
  `-I -B -X utf8 -m marketpulse desktop snapshot --demo`.
- Point data and config environment overrides at scratch paths; never open real
  financial data. Keep the complete relocated backend tree alongside the app.
- Decode and check the bridge version, run the subprocess asynchronously, and
  show launch/decode errors rather than a misleading zero value.
- Document build/run commands and add Windows CI build/bridge verification.
  Record separately whether Windows visual, tray and Narrator checks were observed.

The spike pins .NET SDK 10.0.403 and Avalonia 12.1.5, with a NuGet dependency lock.
It uses a
folder publish: bundled Python already requires multiple files. A successful
spike does not establish the full Windows MVP or installer acceptance criteria.
Build and verification commands are in [the Windows guide](../windows.md#windows-portfolio-app).

## Consequences

The project gains C#/XAML and .NET dependencies. Avalonia's controls are drawn
with Skia rather than native Windows controls; choosing it accepts that visual
tradeoff. Windows remains the target, and the SwiftUI Mac app stays in place.
Cross-compilation improves development access but cannot replace Windows runtime
verification. Future custom controls need automation metadata and testing.

## Sources

- Avalonia: [Windows integration](https://docs.avaloniaui.net/docs/platform-specific-guides/windows/),
  [architecture and rendering](https://docs.avaloniaui.net/docs/fundamentals/cross-platform-architecture),
  [tray icon](https://docs.avaloniaui.net/controls/navigation/trayicon),
  [accessibility](https://docs.avaloniaui.net/docs/app-development/accessibility),
  [version 11 docs](https://v11.docs.avaloniaui.net/).
- .NET: [publishing modes](https://learn.microsoft.com/en-us/dotnet/core/deploying/),
  [process argument arrays](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.processstartinfo.argumentlist).
- WinUI: [framework overview](https://learn.microsoft.com/en-us/windows/apps/winui/),
  [unpackaged distribution](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/unpackage-winui-app),
  [Windows CI](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/ci-for-winui3?pivots=winui3-packaged-csharp),
  [notification-area integration](https://learn.microsoft.com/en-us/windows/win32/shell/notification-area).
- Tauri: [tray](https://v2.tauri.app/learn/system-tray/),
  [sidecars](https://v2.tauri.app/develop/sidecar/),
  [Windows packaging and WebView2](https://v2.tauri.app/distribute/windows-installer/),
  [CI](https://v2.tauri.app/distribute/pipelines/github/).
- Flutter: [Windows build and distribution](https://docs.flutter.dev/platform-integration/windows/building),
  [toolchain](https://docs.flutter.dev/platform-integration/windows/setup),
  [accessibility](https://docs.flutter.dev/ui/accessibility),
  [process invocation](https://api.dart.dev/dart-io/Process/start.html),
  [community tray package](https://pub.dev/packages/tray_manager).
