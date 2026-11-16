# MarketPulse App 1.0 plan

[Back to the README](../README.md) · [Roadmap](roadmap.md) · [QA checklist](qa.md) · [Agent guide](../AGENTS.md)

**Status is tracked on GitHub, not here.** App 1.0 shipped as v3.0.0, and its epic
[#32](https://github.com/BrendanH18/Marketpulse/issues/32) is closed; each step below is an
issue with its own scope and acceptance criteria. This page records the goal,
the decisions behind it, and how the pieces fit, so any contributor or agent can
pick up the work without the conversation that produced it.

## Goal

A free, open-source app that any Canadian investor can download and use without a
terminal: track TFSA, RRSP, FHSA, and taxable accounts with correct adjusted cost
base (ACB), privately, on their own computer. The app is for macOS; the CLI and TUI
stay first-class on macOS and Linux for people who prefer them.

## Decisions

| Decision | Why |
| --- | --- |
| Open source (MIT), no paid tier | Maintainer's choice. Keeps scope on usefulness, not billing. |
| Canadian investors are the audience | Registered accounts, pooled ACB, superficial losses, and contribution room are poorly served by international trackers. |
| **Unsigned builds** (no Apple Developer ID) | Maintainer's choice to avoid the yearly cost. Install docs handle the OS prompts (below). |
| Bundle the Python engine inside the app | Reuses the tested ledger, tax, and import code. Users never install Python. |
| The app talks to the engine only through the versioned desktop JSON bridge | One contract between the interface and the engine; the interface stays replaceable. |
| Local-first; no broker credentials, ever | Privacy is the product. Canada's open-banking framework has no firm date, and credential scraping is fragile. |
| **No Windows build**; macOS and Linux only | Maintainer's choice on 2026-11-14. The Windows app was built but never run on a real Windows desktop, and it was holding up the first release. See [ADR 0002](adr/0002-no-windows-build.md). |

## Architecture

```
                                                ┌─ ledger, ACB, tax, FX, import (Python)
SwiftUI app (macOS) ───── desktop JSON bridge ──┤
                          `marketpulse desktop` └─ SQLite in ~/.marketpulse (shared with CLI/TUI)
```

- The app runs the bundled `marketpulse` CLI. `desktop snapshot` returns version 1
  of the bridge payload; writes use the ordinary CLI commands. Data stays in
  `~/.marketpulse`, so the app, CLI, and TUI share one ledger.
- **Bridge rules:** adding fields is fine. Removing or changing a field's meaning
  requires bumping `version` and updating every interface. `scripts/check_native_bridge.py`
  decodes a real Python payload with the app's Swift models in CI; extend it with
  every bridge change. `status --json` is a separate, stable contract.
- The app keeps one-shot CLI calls. A persistent helper process
  ([#48](https://github.com/BrendanH18/Marketpulse/issues/48)) was measured and
  closed as not planned on 2026-11-15: a refresh on a 5,000-transaction ledger takes
  about 0.2 s on hosted macOS. If refreshes become slow, start from the repeatable
  offline baseline in [Desktop refresh measurements](performance.md).

## Distributing without code signing

**macOS.** Apple Silicon Macs only run native code that carries a signature, and an
ad-hoc one (`codesign --sign -`, no certificate) is enough
([macOS 11 release notes](https://developer.apple.com/documentation/macos-release-notes/macos-big-sur-11_0_1-universal-apps-release-notes)).
The linker signs the binary that way; the build re-signs the whole bundle ad-hoc so the
signature also covers its Info.plist and icon. That satisfies the OS, not Gatekeeper:
browsers quarantine downloads, and macOS blocks
quarantined apps that Apple hasn't notarized. On macOS 15 and later, the
Control-click → Open shortcut no longer bypasses this; users go to **System
Settings › Privacy & Security › Open Anyway**. Files downloaded with `curl` aren't
quarantined, so the primary install path is a script that downloads the release
with `curl`, checks its SHA-256 against the published `SHA256SUMS`, and installs it.
The DMG with Open Anyway instructions is the alternative, and building from the tag
(`marketpulse desktop install`) remains available. See
[#35](https://github.com/BrendanH18/Marketpulse/issues/35).

**Trust without signatures:** releases are built only by the tag-triggered
workflow, every artifact has a published SHA-256, and anyone can rebuild from the tag.

**Updates:** no silent self-update (unsigned). The app checks GitHub Releases at
most daily and offers the install command
([#37](https://github.com/BrendanH18/Marketpulse/issues/37)).

## Phases

Prerequisite: [#31](https://github.com/BrendanH18/Marketpulse/pull/31) (native
workspace, desktop bridge, review fixes, app icon) merges first.

**Phase 1: a downloadable Mac app**

| Issue | What |
| --- | --- |
| [#33](https://github.com/BrendanH18/Marketpulse/issues/33) | Bundle a pinned Python backend inside the app |
| [#34](https://github.com/BrendanH18/Marketpulse/issues/34) | Release workflow: unsigned app on version tags |
| [#35](https://github.com/BrendanH18/Marketpulse/issues/35) | Install script, DMG guide, uninstall |
| [#36](https://github.com/BrendanH18/Marketpulse/issues/36) | First-run onboarding |
| [#38](https://github.com/BrendanH18/Marketpulse/issues/38) | Settings window, light/dark appearance |
| [#39](https://github.com/BrendanH18/Marketpulse/issues/39) | Restore from a backup |
| [#37](https://github.com/BrendanH18/Marketpulse/issues/37) | Update check |

**Phase 2: everyday workflows in the app**

| Issue | What |
| --- | --- |
| [#40](https://github.com/BrendanH18/Marketpulse/issues/40) | Edit and delete transactions |
| [#41](https://github.com/BrendanH18/Marketpulse/issues/41) | Transfer, DRIP, split, return-of-capital forms |
| [#42](https://github.com/BrendanH18/Marketpulse/issues/42) | Edit/archive accounts, contribution room |
| [#43](https://github.com/BrendanH18/Marketpulse/issues/43) | Tax workspace and export |
| [#21](https://github.com/BrendanH18/Marketpulse/issues/21), [#22](https://github.com/BrendanH18/Marketpulse/issues/22) → [#44](https://github.com/BrendanH18/Marketpulse/issues/44) | Broker CSV profiles and importer ergonomics, then the app's import sheet |
| [#45](https://github.com/BrendanH18/Marketpulse/issues/45) | Fixed-income/manual assets, target allocation |

**Phase 3: quality and polish**

| Issue | What |
| --- | --- |
| [#46](https://github.com/BrendanH18/Marketpulse/issues/46) | French localization |
| [#47](https://github.com/BrendanH18/Marketpulse/issues/47) | Accessibility and keyboard: code shipped in #83; the Inspector audit and VoiceOver walkthrough are not planned |
| [#49](https://github.com/BrendanH18/Marketpulse/issues/49) | Pluggable quote providers (with [#23](https://github.com/BrendanH18/Marketpulse/issues/23)) |
| [#48](https://github.com/BrendanH18/Marketpulse/issues/48) | Persistent backend helper: measured, not built (closed as not planned) |
| [#20](https://github.com/BrendanH18/Marketpulse/issues/20) | Coverage gates for the financial core |

**Phase 4: Windows** (dropped)

The Windows backend, app and installer (#50–#53) were built and then removed
before any release: see [ADR 0002](adr/0002-no-windows-build.md) and
[#150](https://github.com/BrendanH18/Marketpulse/issues/150).

Phases 2 and 3 can run alongside Phase 1 once #31 merges.

## App 1.0 for macOS: definition of done

- Phase 1 complete, plus editing transactions (#40), account management (#42), and the tax workspace (#43).
- A person with no developer tools installs from the README in under five minutes.
- `docs/qa.md` passes on the released build, including the fresh-install and onboarding items.
- `CHANGELOG.md` has the release section; the tag's workflow produced every artifact.

v3.0.0 met this on 2026-11-15, except that the QA checklist wasn't recorded item by
item: the maintainer installed the published release on a Mac and confirmed it works.

## Not doing

- Broker logins or credential-based sync; trading of any kind.
- Accounts, cloud storage, telemetry, or analytics. The only network calls are quotes, FX, and the opt-out update check.
- A paid tier.
- A Windows build ([ADR 0002](adr/0002-no-windows-build.md)).

## Risks

| Risk | Mitigation |
| --- | --- |
| Yahoo's unofficial endpoints change or block requests | Stale-cache fallback is visible today; pluggable providers with a user-supplied key (#49). |
| Users distrust unsigned apps | Plain explanations, checksums, tag-only builds, rebuild-from-source path. |
| Bundle size or relocation problems with native wheels | Measure in #33; strip unused stdlib; test on a clean user account. |
| Tax numbers wrong | Tax math changes only with tests on fictional fixtures; app shows a "check against your slips" note. |
| One maintainer, several agents | Issues as the source of truth, small PRs, and the handoff protocol in `AGENTS.md`. |

## Changing this plan

Edit this page in the same PR as the issue changes that motivate it. Record new
settled decisions in the table above; put open questions on an issue labelled
`needs-decision`.
