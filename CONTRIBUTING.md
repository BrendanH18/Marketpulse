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
```

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

1. Run the checks above and confirm CI passes.
2. Update `__version__` in `src/marketpulse/__init__.py`; package metadata and
   the CLI use this single source. Refresh `uv.lock` if dependencies changed.
3. Review installation and upgrade instructions, migration backups, and any
   changed JSON fields used by the companion. Confirm the README git-tag
   examples match the tag you are about to publish (for example `v2.0.1`).
4. Build and install the wheel in a fresh environment; check both `marketpulse`
   and `mp`. On macOS, also verify the companion from an editable checkout.
5. Prepare release notes describing changes and any upgrade requirements.
6. Create an annotated git tag and GitHub Release. Verify a clean install:

   ```bash
   uv tool install --python 3.11 --reinstall git+https://github.com/BrendanH18/Marketpulse.git@vX.Y.Z
   marketpulse --version
   ```

The repository does not automatically publish packages or create releases.

### Publishing to PyPI (follow-up)

Package metadata in `pyproject.toml` is ready for a wheel (`marketpulse` / `mp`
entry points, MIT license, classifiers). Publishing still needs a maintainer
action:

1. Create a PyPI project named `marketpulse` (or claim the name) and a trusted
   publisher or API token.
2. After tagging a release: `uv build --no-sources` then
   `uv publish` (or `twine upload dist/*`) with the token.
3. Switch the README primary install to
   `uv tool install --python 3.11 marketpulse` and keep the git-tag commands as
   a fallback for pinned source installs.

Do not automate PyPI from CI until a tagged release path is stable and secrets
are configured.
