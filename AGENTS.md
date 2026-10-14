# Agent guide

Instructions for AI coding agents (Claude Code, Codex, Cursor, and others) and
the people directing them. The maintainer switches between agents, so **write
everything down where the next agent will find it**: the issue, the branch, and
the PR. Chat history is not shared and is not the backlog.

## What this project is

MarketPulse is a local-first investment tracker for Canadian investors: a Python
engine (ledger, pooled ACB, FX, tax, CSV import, quotes) with a CLI and TUI, plus
a native SwiftUI app for macOS that talks to the engine through a versioned JSON
bridge. The current goal is a downloadable app: [docs/app-plan.md](docs/app-plan.md),
epic [#32](https://github.com/BrendanH18/Marketpulse/issues/32).

| Path | What's there |
| --- | --- |
| `src/marketpulse/` | Engine and CLI. `models.py`, `ledger.py`, `valuation.py`, `services.py` (core); `csvio.py` (import/export); `market.py` (quotes); `db.py` (SQLite, backups, migrations); `cli.py`; `tui/` |
| `src/marketpulse/desktop.py`, `automation.py` | Desktop JSON bridge and the shared refresh/backup/alert cycle |
| `macos/MarketPulseBar/` | SwiftUI app (menu bar + portfolio window), `AppIcon.icns` |
| `scripts/` | Bridge check, QA app builder, icon generator, README preview |
| `tests/` | pytest with isolated data, fake Yahoo transport, mocked notifications |
| `docs/` | User guides, plan, QA checklist, roadmap |

## Start of every session

1. Read this file, then the issue you're working on **including its latest comments**.
   A `Handoff` comment means another agent started; continue from it.
2. `git fetch origin` and check for an existing branch or PR for the issue
   (`gh pr list --search "<issue number>"`). Continue it rather than starting over.
3. If the issue is unclaimed, claim it with a comment:
   `Claiming for <agent/model>. Branch: <branch>.`
4. Prefer issues labelled `agent-ready`. Skip `needs-decision` issues; ask the maintainer instead.

## Branches, commits, PRs

- Branch from `main` as `<issue>-<short-slug>`, e.g. `33-bundle-backend`. One issue per PR.
- Push early and open a **draft PR** that says `Closes #<issue>`, so work survives if your session ends.
- Commit messages: imperative summary line; explain *why* in the body.
- Add a line to `CHANGELOG.md` under **Unreleased** for user-visible changes, and update the docs you affect.
- Never push to `main`, force-push someone else's branch, or close issues you didn't resolve.
- Some tools (e.g. T3 Code worktrees) rename local branches. Before pushing, run
  `git branch -vv` and push explicitly to the PR's head branch: `git push origin HEAD:<pr-branch>`.

## Checks

```bash
uv sync --locked --dev
uv run --locked ruff check . && uv run --locked ruff format --check . && uv run --locked mypy
uv run --locked pytest -q
# macOS, for app or bridge changes:
swift build -c release --package-path macos/MarketPulseBar
uv run --locked python scripts/check_native_bridge.py
```

All must pass before you mark a PR ready. Paste the results, not a summary of them.

## Verifying app changes

Build the throwaway QA app on a fictional ledger and follow [docs/qa.md](docs/qa.md):

```bash
uv run --locked python scripts/qa_app.py --fresh && "$TMPDIR/marketpulse-qa/launch.sh"
```

If you have computer use, run the checklist and post the PASS / FAIL / UNVERIFIED
table on the PR. If you don't, say which items you couldn't verify. Never report a
UI item as passing that you didn't see.

## Rules

- **Never touch real financial data.** Use fictional data in tests, docs, fixtures,
  and screenshots. For manual runs set `MARKETPULSE_DATA` and `MARKETPULSE_CONFIG`
  to a scratch directory; never read or write `~/.marketpulse`.
- **Financial math** (ACB, FX, tax, valuation, contribution room) changes only under
  an issue that calls for it, with tests on fictional fixtures that show the before and after.
- **Desktop bridge:** adding fields is fine; removing or changing one requires bumping
  `version` and updating the Swift models and `scripts/check_native_bridge.*`.
  `status --json` is a separate stable contract; note any change in the changelog.
- **Invariants that tests protect; keep them:** archived accounts are hidden everywhere
  and left out of totals; a CSV preview runs the real import against a temporary copy, so
  preview equals import; text typed in the app reaches the CLI after `--`; stale quotes
  never fire alerts or record snapshots.
- No new network calls, telemetry, or accounts beyond what an issue specifies. No secrets in the repo.
- Keep PRs focused. Refactors stay behavior-preserving.

## Handoff protocol

Hand off whenever you might not finish: usage limits, a long-running task, a
blocker, or the end of a session. It takes two minutes and saves the next agent an hour.

1. Commit whatever works, even partial (`WIP:` commits are fine on your branch), and push.
2. Make sure the draft PR exists and its description reflects the current state.
3. Post this comment **on the issue**:

```markdown
### Handoff — <agent/model>, <YYYY-MM-DD>
**Status:** in progress | blocked | ready for review
**Branch / PR:** `<branch>` / #<pr>
**Done:**
- …
**Next steps (in order):**
1. …
**Verified:** <commands run and results; QA items checked>
**Not verified / known issues:** …
**Gotchas:** <anything surprising: environment quirks, failed approaches, decisions made>
**Open questions for the maintainer:** …
```

The next agent starts from the latest handoff comment, not from scratch.

## Agent-specific notes

- **Claude Code** reads `CLAUDE.md`, which imports this file and adds architecture notes.
- **Codex** and **Cursor** read `AGENTS.md` directly.
- Agents without GitHub access can't read issues: the maintainer should paste the
  issue and its latest handoff comment into the session.
