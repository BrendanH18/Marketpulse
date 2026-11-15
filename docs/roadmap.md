# Roadmap

[Back to the README](../README.md) · [User guide](usage.md) · [App 1.0 plan](app-plan.md) · [Contributing](../CONTRIBUTING.md)

MarketPulse's goal is a free app that Canadian investors can download and use
without a terminal on macOS, with the CLI and TUI staying first-class on macOS
and Linux. There is no Windows build. The goal, decisions and phases are in the [App 1.0 plan](app-plan.md).

**GitHub issues are the source of truth** for agents and humans. This page is a
pointer: claim and track work on the issues themselves. The epic is
[#32](https://github.com/BrendanH18/Marketpulse/issues/32).

## Status (2026-11-14)

The Mac app is built but not yet published.

- **Published:** v2.1.0 (2026-10-06), a CLI and TUI release with no app download.
- **Next release:** 3.0.0, the first with the Mac app. `main` is prepared for it
  (version, changelog section, install docs) but it is not tagged. 2.2.0 was
  prepared ([#84](https://github.com/BrendanH18/Marketpulse/pull/84)) and never
  tagged, so 3.0.0 carries its changes too. Until it is published, the README's
  one-line installer has nothing to download.
- **Unreleased on `main`:** the Mac app, a second quote provider, French (Canada)
  in the app, and the offline `report` and `summarize` commands with the other
  CLI additions in the [changelog](../CHANGELOG.md).
- **Dropped:** Windows. The maintainer decided on 2026-11-14 to support macOS and
  Linux only ([#150](https://github.com/BrendanH18/Marketpulse/issues/150)). The
  Windows app and installer were built but never run on a real Windows desktop,
  and have been removed.

Each item below is tracked in three steps: implemented (merged), verified on a
real Mac, and published. Most open work is in the second and third.

## Next milestone: publish the first downloadable release

No new features are needed for this milestone. It is done when a person with no
developer tools can install from the README on a Mac.

| Work | Issue | What remains |
| --- | --- | --- |
| Mac release QA | [#32](https://github.com/BrendanH18/Marketpulse/issues/32) | Run the [QA checklist](qa.md) on the 3.0.0 build. Items no one has observed yet: 1, 10 and 12–26 (table on [#84](https://github.com/BrendanH18/Marketpulse/pull/84)) and the layout check in 27 ([#85](https://github.com/BrendanH18/Marketpulse/pull/85)). Then a fresh install from the published release. These need a person at a Mac. |
| Mac accessibility | [#47](https://github.com/BrendanH18/Marketpulse/issues/47) | Accessibility Inspector audit and a spoken VoiceOver walkthrough. The code merged in #83. |
| Tag, publish, check the README installer | [#32](https://github.com/BrendanH18/Marketpulse/issues/32) | Maintainer release checklist in [CONTRIBUTING](../CONTRIBUTING.md), from step 7. If the tag is pushed on another day, change the date of the 3.0.0 changelog section first. |

Broad feature batches wait until this milestone is published.

## Waiting on a maintainer decision

| Issue | Question |
| --- | --- |
| [#48](https://github.com/BrendanH18/Marketpulse/issues/48) | Persistent backend process. The measurements are done ([performance](performance.md)) and recommend deferring it. |
| [#149](https://github.com/BrendanH18/Marketpulse/issues/149) | Whether, and when, to check new and imported sales at their date. |

## After the release

- **Check new sales and imports against the ledger at their date**
  ([#149](https://github.com/BrendanH18/Marketpulse/issues/149)). Edits and
  deletes already replay the ledger; a new backdated sale is only compared with
  current holdings, and imports skip the check. It changes ledger validation, so
  it waits for the maintainer's go-ahead.
- Choose further work from what people run into when using the released app.

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
| Offline CLI inspection, `report` and `summarize` (57 datasets, 180 shared operations) | 20 issues from #104 to #143, and #145 |

## Dropped

Windows (#26, #50–#53, #97, #99, #100, #114): built, then removed before any
release. See [#150](https://github.com/BrendanH18/Marketpulse/issues/150) and
[ADR 0002](adr/0002-no-windows-build.md).

## For agents

Read [AGENTS.md](../AGENTS.md) first: it covers claiming issues, checks, and the
handoff protocol for switching between agents mid-task.

1. Pick **one** open issue from the milestone table (prefer `agent-ready`; skip `needs-decision`).
2. Treat that issue's scope and acceptance checkboxes as the contract.
3. Keep the work to that issue; do not bundle unrelated roadmap items.
4. Use fictional portfolio data in tests, docs, and screenshots.
5. Never report an app QA item as passing that you did not see.
