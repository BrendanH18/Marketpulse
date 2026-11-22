# Roadmap

[Back to the README](../README.md) · [User guide](usage.md) · [App 1.0 plan](app-plan.md) · [Contributing](../CONTRIBUTING.md)

MarketPulse is a free app that Canadian investors can download and use without a
terminal on macOS, with the CLI and TUI staying first-class on macOS and Linux.
There is no Windows build. Feature direction is **local-first Canadian ledger
correctness**; the decisions behind the app are in the [App 1.0 plan](app-plan.md).

**GitHub issues are the source of truth** for agents and humans. This page is a
pointer: claim and track work on the issues themselves.

## Status (2026-11-20)

- **Published:** [v3.1.0](https://github.com/BrendanH18/Marketpulse/releases/tag/v3.1.0)
  (2026-11-19) is the latest release, after
  [v3.0.0](https://github.com/BrendanH18/Marketpulse/releases/tag/v3.0.0)
  (2026-11-14), the first with the Mac app. The maintainer confirmed the
  published 3.0.0 works on a Mac and closed the app epic
  [#32](https://github.com/BrendanH18/Marketpulse/issues/32). No release has
  completed the [QA checklist](qa.md): the [2026-11-20 UI audit](ui-audit-2026-11-20.md)
  left 17 of 28 items unverified, including the clean install.
- **3.2.0 release preparation:** backup restore preview (#171, #173), `backup verify
  --all` (#176), automation history (#180, schema version 2), the T1135 estimate
  (#179, schema version 3), and privacy, search and recovery fixes (#186). An
  older app refuses a ledger migrated to a newer schema. The CLI upgrade and
  rollback rehearsal passed. [Rehearsal #197](https://github.com/BrendanH18/Marketpulse/issues/197) ·
  [Changelog](../CHANGELOG.md#320)
- **Dropped:** Windows. The maintainer decided on 2026-11-14 to support macOS and
  Linux only ([#150](https://github.com/BrendanH18/Marketpulse/issues/150)).

## Next

The proposed plan for December 2026 to May 2027 is in
[plan-2026-12-to-2027-05.md](plan-2026-12-to-2027-05.md). It covers five themes:

1. Release 3.2.0 and close safety gaps: restore confirmation that checks the live
   ledger, private file permissions, and the 2027 TFSA limit (December).
2. Tax and contribution-room correctness, released before tax slips arrive
   (January to mid February).
3. Mac app parity and resilience (February to March).
4. Trust in the release: a decision on signing, attested artifacts, a complete QA
   pass, and the #25 threat model (March to April).
5. Broker imports and walkthroughs with real users (April to May).

The [3.2.0 release preparation issue](https://github.com/BrendanH18/Marketpulse/issues/202)
tracks the version bump and packaging dry run. Publication and the full Mac QA
checklist are separate. File the remaining work as scoped issues before starting
it. Bulk "N improvements" batches and new `report`/`summarize` datasets are paused
for this milestone.

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
| Offline CLI inspection, `report` and `summarize` (69 datasets, 197 shared operations) | 20 issues from #104 to #143, #145, #153, #162, PR #191 and [#212](https://github.com/BrendanH18/Marketpulse/issues/212) |
| New and imported sales checked at their date | #149 |
| MarketPulse 3.1.0 | #169 |
| Backup restore preview and verification (unreleased) | #171, #173, #176 |
| Automation history and T1135 estimate (unreleased) | #179, #180 |

## Closed as not planned

| Issue | Why |
| --- | --- |
| [#27](https://github.com/BrendanH18/Marketpulse/issues/27) | The old roadmap issue, superseded by this page. |
| [#47](https://github.com/BrendanH18/Marketpulse/issues/47) | Accessibility: the code shipped in 3.0.0 (#83), but the Accessibility Inspector audit and the VoiceOver walkthrough are not planned. Unverified as a result: whether VoiceOver reads Overview's three metric cards as separate items ([QA](qa.md) item 26). |
| [#48](https://github.com/BrendanH18/Marketpulse/issues/48) | Persistent backend process: the [measurements](performance.md) supported deferring it (a zero-delay offline engine refresh takes about 0.2 s on hosted macOS), and the Windows app it would also have served was dropped. Open a new issue with native app timings if refreshes feel slow. |

## Dropped

Windows (#26, #50–#53, #97, #99, #100, #114): built, then removed before any
release. See [#150](https://github.com/BrendanH18/Marketpulse/issues/150) and
[ADR 0002](adr/0002-no-windows-build.md).

## For agents

Read [AGENTS.md](../AGENTS.md) first: it covers claiming issues, checks, and the
handoff protocol for switching between agents mid-task.

1. Pick **one** open issue outside Later (prefer `agent-ready`; skip
   `needs-decision`). If there is none, ask the maintainer instead of starting
   unlisted work.
2. Treat that issue's scope and acceptance checkboxes as the contract.
3. Keep the work to that issue; do not bundle unrelated roadmap items.
4. Use fictional portfolio data in tests, docs, and screenshots.
5. Never report an app QA item as passing that you did not see.
