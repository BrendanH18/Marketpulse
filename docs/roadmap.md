# Roadmap

[Back to the README](../README.md) · [User guide](usage.md) · [Contributing](../CONTRIBUTING.md)

MarketPulse’s near-term focus is **local-first Canadian ledger correctness and distribution trust**, not UI chrome.

**GitHub issues are the source of truth** for agents and humans. This page is only a pointer; claim and track work on the issues themselves.

## Tracking

- **Epic:** [Roadmap (#27)](https://github.com/BrendanH18/Marketpulse/issues/27) — priority-ordered index and status blurb
- Open an issue or comment on an existing one before large financial-calculation changes ([CONTRIBUTING](../CONTRIBUTING.md))

## Workstreams (priority order)

| Priority | Issue | Summary |
| --- | --- | --- |
| P0 | [#18](https://github.com/BrendanH18/Marketpulse/issues/18) | Tagged release, version bump, CHANGELOG / release notes |
| P0/P1 | [#19](https://github.com/BrendanH18/Marketpulse/issues/19) | Versioned install path (PyPI or documented git tag) |
| P1 | [#20](https://github.com/BrendanH18/Marketpulse/issues/20) | Coverage gates for ledger, tax, and migrations |
| P1 | [#21](https://github.com/BrendanH18/Marketpulse/issues/21) | Broker CSV import profiles |
| P1 | [#22](https://github.com/BrendanH18/Marketpulse/issues/22) | Importer ergonomics (dry-run, duplicates, clearer errors) |
| P2 | [#23](https://github.com/BrendanH18/Marketpulse/issues/23) | Market-data stale-cache docs / resilience |
| P2 | [#24](https://github.com/BrendanH18/Marketpulse/issues/24) | Split oversized `cli.py` / `tui/app.py` (behavior-preserving) |
| Later | [#25](https://github.com/BrendanH18/Marketpulse/issues/25) | Optional at-rest encryption |
| Later | [#26](https://github.com/BrendanH18/Marketpulse/issues/26) | Windows packaging and platform polish |

## For agents

1. Pick **one** open issue from the table (prefer higher priority).
2. Treat that issue’s scope and acceptance checkboxes as the contract.
3. Open a focused PR that links the issue; do not bundle unrelated roadmap items.
4. Use fictional portfolio data in tests, docs, and screenshots.
