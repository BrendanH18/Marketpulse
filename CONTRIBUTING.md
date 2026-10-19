# Contributing to MarketPulse

Thanks for helping improve MarketPulse. Documentation, reproducible bug reports,
and focused code changes are all useful contributions. Please follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Before you start

Search existing [issues](https://github.com/BrendanH18/Marketpulse/issues) and
pull requests. For a large feature or a change to financial calculations, open
an issue describing the problem and proposed behavior before spending substantial
time on implementation. Small fixes can go straight to a pull request.

Report security vulnerabilities privately using [SECURITY.md](SECURITY.md).
Use fictional records in public reports and remove personal information from
screenshots and diagnostics.

To regenerate the README's dashboard preview from the real TUI with fictional
data and no network requests, run `uv run --locked python scripts/render_preview.py`.

## Development setup

End users should install a **pinned release tag** (see [README Get started](README.md#get-started)).
This section is for contributors working on the code.

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git:

```bash
git clone https://github.com/BrendanH18/Marketpulse.git
cd Marketpulse
uv sync --locked --dev --python 3.11
```

To run the installed CLI/TUI against your checkout (including the macOS menu bar
companion, which needs the Swift sources on disk), use an editable tool install:

```bash
uv tool install --python 3.11 --editable .
```

Use an isolated portfolio for manual testing:

```bash
MARKETPULSE_DATA="$PWD/.marketpulse/dev" MARKETPULSE_CONFIG="$PWD/.marketpulse/dev.toml" uv run --locked marketpulse
```

Tests automatically isolate data and configuration, mock desktop notifications,
and use a fake Yahoo transport. They do not need a real portfolio or live quotes.

## Checks

Run these before submitting code changes:

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest -q
uv build --no-sources
```

Use `uv run --locked ruff format .` to apply formatting. To run a focused test,
use a file path or `-k`, for example `uv run --locked pytest tests/test_csvio.py -q`.
For documentation-only changes, check links, examples, and descriptions against
the current CLI rather than adding tests that merely repeat the prose.

On macOS, changes to the companion should also pass:

```bash
swift build -c release --package-path macos/MarketPulseBar
uv run --locked python scripts/check_native_bridge.py
```

To build the standalone `MarketPulse.app`, with its own Python backend, as releases ship it
(details in [docs/desktop.md](docs/desktop.md#build-the-standalone-app)):

```bash
uv run --locked python scripts/build_app.py                 # dist/app/<arch>/MarketPulse.app
uv run --locked python scripts/build_app.py --arch arm64 --arch x86_64
```

For changes you can see in the app, also run the [QA checklist](docs/qa.md) against a
throwaway copy of the app on a fictional ledger
(`uv run --locked python scripts/qa_app.py --fresh`; add `--bundled` for changes to
the bundle or how the app finds its backend). AI agents should read
[AGENTS.md](AGENTS.md); the app's direction is in the [App 1.0 plan](docs/app-plan.md).

CI runs lint, formatting, type checks, Python tests on Linux and macOS, Python
distribution builds with an installed-wheel smoke check, and the Swift build.
Dependency changes should include the updated `uv.lock`; use `uv lock` and
verify `uv sync --locked --dev` succeeds.
Dependabot is configured to propose monthly updates to Python dependencies and
GitHub Actions; these updates still require review and passing checks.

## Architecture

The CLI, TUI, and macOS companion share the same ledger and service layer.
The Swift app consumes the CLI's JSON status output.

| Module | Responsibility |
| --- | --- |
| `models.py` | Accounts, transactions, assets, quotes, and validation |
| `ledger.py` | Replay transactions into holdings, cost, cash, income, and contribution room |
| `db.py` | SQLite storage, schema migrations, backups, and legacy JSON import |
| `market.py` | Yahoo transport, quotes, history, FX, search, and caching |
| `valuation.py` | Combine ledger state and prices into a portfolio view |
| `tax.py` | Pooled ACB, trade-date FX, superficial losses, and deemed dispositions |
| `analytics.py` | Performance, allocation, income, and other portfolio analysis |
| `services.py` | Tracker facade used by the interfaces |
| `render.py`, `charts.py`, `fmt.py` | Shared rendering and formatting |
| `themes.py`, `themes_data.py` | Theme resolution and bundled palettes |
| `cli.py`, `tui/` | Click commands, Textual workspaces, and forms |
| `macos/MarketPulseBar/` | SwiftUI menu bar application |

## Guidelines for changes

- Keep business rules in the ledger, tax, analytics, or services layer so the
  interfaces agree. Use the existing fake transport for market-related tests.
- Cover changed financial behavior with concrete transaction examples and
  expected amounts. Explain any assumptions, currency conversions, or rounding.
- Add database upgrades as sequential entries in `MIGRATIONS` in `db.py`.
  Do not alter a previously shipped migration or rely on changing `SCHEMA`
  to update existing databases. Verify upgrades and backup behavior with the
  migration tests.
- Preserve the `status --json` contract consumed by the Swift models when
  changing the payload, and update both sides when necessary.
- Treat `themes_data.py` as generated data. Preserve upstream attribution when
  updating palettes; do not reformat the generated file with the rest of the code.
- Update user docs for changed commands or behavior. Avoid unrelated rewrites
  in a focused fix.

## Pull requests

Use a descriptive title and explain the problem, resulting behavior, and checks
you ran. Include screenshots for visible TUI or companion changes using sample
data. Link the relevant issue if one exists; a new issue is not required for every fix.
Keep changes small enough to review, and mention limitations or follow-up work.

Contributions are made under the project's [MIT License](LICENSE). Include the
origin and license for any third-party code or assets you add.

## Maintainer release checklist

Ship version bumps and changelog updates through a pull request. Do not
force-push `main`. Tag and publish the GitHub Release only after the release
commit is on `main` and CI is green.

1. Run the checks above and confirm CI passes on the release PR. Optionally
   dry-run the release workflow on the release branch (see below).
2. Update `__version__` in `src/marketpulse/__init__.py`; package metadata and
   the CLI use this single source. Refresh `uv.lock` if dependencies changed.
3. Update [CHANGELOG.md](CHANGELOG.md) (Keep a Changelog) with user-visible
   changes and upgrade notes (backup before upgrade, schema migrations, any
   companion JSON contract changes).
4. Review installation and upgrade instructions in the README and
   [docs/data.md](docs/data.md). Confirm the README git-tag examples match the
   tag you are about to publish (for example `v2.1.0`).
5. Build and install the wheel in a fresh environment; check both `marketpulse`
   and `mp`, and confirm `marketpulse --version` matches `__version__`. On
   macOS, also verify the companion from an editable checkout.
6. Merge the release PR to `main` (fast-forward or merge commit — no force-push).
7. On the release PR merge commit, create an annotated tag matching `__version__`
   and push it (example for 2.1.0). Do not tag whatever happens to be at the tip
   of `main` if other commits landed afterward:

   ```bash
   RELEASE_MERGE_SHA="REPLACE_WITH_RELEASE_PR_MERGE_SHA"
   git fetch origin main
   git checkout --detach "$RELEASE_MERGE_SHA"
   test "$(git rev-parse HEAD)" = "$RELEASE_MERGE_SHA"
   git tag -a v2.1.0 -m "MarketPulse 2.1.0"
   git push origin v2.1.0
   ```

   Pushing the tag starts the **Release** workflow
   ([`.github/workflows/release.yml`](.github/workflows/release.yml)). It fails
   early if the tag isn't `v` plus `__version__` or `CHANGELOG.md` has no section
   for the version. It then runs the CI checks, builds the wheel, sdist, and
   `MarketPulse.app` for arm64 and x86_64 (`scripts/build_app.py`), packages each
   app as a zip and a DMG, attaches `scripts/install.sh`, and writes `SHA256SUMS`
   (`scripts/release.py package`).
   `scripts/release.py verify` opens every artifact, checks that the app and the
   bundled backend both report the tag's version, the architecture, and the
   signature, and runs each app: arm64 on `macos-15`, x86_64 on `macos-15-intel`.
   Only then does it create a **draft** release whose notes are that version's
   CHANGELOG section plus download and checksum instructions.

8. Review the draft release on GitHub (assets, notes) and publish it. Re-running
   the workflow for the same tag replaces the draft's files; it refuses once the
   release is published.

9. Verify a fresh install from the tag reports the expected version (prefer the
   non-editable git-tag path from the README; editable clone is fine for the
   macOS companion):

   ```bash
   uv tool install --python 3.11 --reinstall git+https://github.com/BrendanH18/Marketpulse.git@v2.1.0
   marketpulse --version
   ```

   Download one of the release zips, check it against `SHA256SUMS`, and open the app.
   Run the one-line install from the [install guide](docs/install.md) on a fresh macOS
   user account ([QA item 16](docs/qa.md#checklist)); the `latest` URL only resolves
   once the release is published.

**Dry run.** Before tagging, run the workflow from **Actions › Release › Run
workflow** on the release branch (or `gh workflow run release.yml --ref <branch>`).
It builds and verifies the same artifacts and attaches them to the run as
`marketpulse-<version>`, but creates no release; a missing CHANGELOG section is
only a warning. Everything except the draft release can also be run locally:

```bash
uv build --no-sources --out-dir dist/python
uv run --locked python scripts/build_app.py --arch arm64 --arch x86_64 \
  --wheel dist/python/marketpulse-2.1.0-py3-none-any.whl
uv run --locked python scripts/release.py package --python-dist dist/python   # dist/release
uv run --locked python scripts/release.py verify dist/release
uv run --locked python scripts/release.py notes       # this version's release notes
```

The workflow doesn't publish to PyPI.

### Publishing to PyPI (follow-up)

Package metadata in `pyproject.toml` is ready for a wheel (`marketpulse` / `mp`
entry points, MIT license, classifiers). Publishing still needs a maintainer
action:

1. Create a PyPI project named `marketpulse` (or claim the name).
2. **Manual publish (API token):** create a PyPI API token, then after tagging a
   release run `uv build --no-sources` and `uv publish` (or
   `twine upload dist/*`) with that token.
3. **Trusted publisher (CI/OIDC only):** configure a PyPI trusted publisher for
   this repo’s release workflow when automating uploads from CI; do not combine
   that path with local `uv publish` / `twine` (those need a token).
4. Switch the README primary install to
   `uv tool install --python 3.11 marketpulse` and keep the git-tag commands as
   a fallback for pinned source installs.

Do not automate PyPI from CI until a tagged release path is stable and OIDC or
secrets are configured.
