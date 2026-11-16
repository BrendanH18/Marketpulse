# Roadmap

[Back to the README](../README.md) · [User guide](usage.md) · [App 1.0 plan](app-plan.md) · [Contributing](../CONTRIBUTING.md)

MarketPulse is a free app that Canadian investors can download and use without a
terminal on macOS, with the CLI and TUI staying first-class on macOS and Linux.
There is no Windows build. Feature direction is **local-first Canadian ledger
correctness**; the decisions behind the app are in the [App 1.0 plan](app-plan.md).

**GitHub issues are the source of truth** for agents and humans. This page is a
pointer: claim and track work on the issues themselves.

## Status (2026-11-15)

App 1.0 is out.

- **Published:** [v3.0.0](https://github.com/BrendanH18/Marketpulse/releases/tag/v3.0.0),
  the first release with the Mac app: a DMG and a zip for Apple Silicon and Intel,
  the wheel and sdist, the one-line installer and `SHA256SUMS`. The maintainer
  installed the published release on a Mac and confirmed it works, which closed the
  app epic [#32](https://github.com/BrendanH18/Marketpulse/issues/32). The
  [QA checklist](qa.md) was not recorded item by item for this release.
- **Unreleased on `main`:** fixes and additions since 3.0.0, listed under
  Unreleased in the [changelog](../CHANGELOG.md). The most important is
  [#149](https://github.com/BrendanH18/Marketpulse/issues/149): sales are now
  checked against what the account held on the sale's date, and CSV imports check
  them too; before, an import could leave the ledger with an oversell. The rest are
  the [#153](https://github.com/BrendanH18/Marketpulse/issues/153) CLI and terminal
  app additions and smaller fixes, including the Mac app's "Get a Alpha Vantage key"
  wording.
- **Dropped:** Windows. The maintainer decided on 2026-11-14 to support macOS and
  Linux only ([#150](https://github.com/BrendanH18/Marketpulse/issues/150)).

## Next

1. **Release what's on `main`.** People who install today get 3.0.0, without the
   #149 fix. Unreleased includes additions, so the next version is a minor bump
   (3.1.0) unless the maintainer decides otherwise. Follow the maintainer release
   checklist in [CONTRIBUTING](../CONTRIBUTING.md).
2. **Choose further work from what people run into** when using the released app.
   Open an issue for each piece of work before starting it.

There are no open `agent-ready` issues.

## Later

| Issue | Summary |
| --- | --- |
| [#25](https://github.com/BrendanH18/Marketpulse/issues/25) | Optional at-rest encryption |

## Done

| Area | Issues |
| --- | --- |
| Release trust and install path | #18, #19 |
| Financial-core coverage gates | #20 |
| Broker CSV profiles and importer ergonomics | #21, #22 |
| Quote resilience and a second provider | #23, #49 |
| CLI and TUI module splits | #24 |
| Mac app: Phases 1 and 2 of the plan, and French (Canada) | #31, #33–#46, #55 |
| App 1.0 for macOS, released as v3.0.0 | #32, #152 |
| Offline CLI inspection, `report` and `summarize` (57 datasets, 197 shared operations) | 20 issues from #104 to #143, #145 and #153 |
| New and imported sales checked at their date | #149 |

## Closed without doing

| Issue | Why |
| --- | --- |
| [#47](https://github.com/BrendanH18/Marketpulse/issues/47) | Accessibility: the code shipped in 3.0.0 (#83), but the Accessibility Inspector audit and the VoiceOver walkthrough are not planned. |
| [#48](https://github.com/BrendanH18/Marketpulse/issues/48) | Persistent backend process: [measurements](performance.md) show a refresh takes about 0.2 s on hosted macOS, so it isn't needed. |

## Dropped

Windows (#26, #50–#53, #97, #99, #100, #114): built, then removed before any
release. See [#150](https://github.com/BrendanH18/Marketpulse/issues/150) and
[ADR 0002](adr/0002-no-windows-build.md).

## For agents

Read [AGENTS.md](../AGENTS.md) first: it covers claiming issues, checks, and the
handoff protocol for switching between agents mid-task.

1. Pick **one** open issue (prefer `agent-ready`; skip `needs-decision`). If there
   is none, ask the maintainer instead of starting unlisted work.
2. Treat that issue's scope and acceptance checkboxes as the contract.
3. Keep the work to that issue; do not bundle unrelated roadmap items.
4. Use fictional portfolio data in tests, docs, and screenshots.
5. Never report an app QA item as passing that you did not see.
