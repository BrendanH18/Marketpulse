# Security policy

## Report a vulnerability

Please report security issues privately. Use
[GitHub's private vulnerability reporting](https://github.com/BrendanH18/Marketpulse/security/advisories/new)
if it is available, or email the maintainer at **brendan.hallas@hey.com**.
Do not include exploit details or personal financial records in a public issue.

Include the affected version or commit, operating system, reproduction steps,
potential impact, and a minimal example using fictional data. Screenshots,
logs, CSV files, and status JSON can contain private amounts and account names;
redact them before sharing.

The maintainer will review reports as availability allows and coordinate a fix
and disclosure where appropriate. This project does not offer a guaranteed
response time or a bug bounty.

## Supported code

Security fixes target the current code on `main`. Older releases do not have
a separate maintenance or backport commitment; update to the current version
after making a database backup.

## Releases and verifying downloads

MarketPulse's macOS app is ad-hoc signed and not notarized: the project has no
paid Apple Developer ID, by decision ([app plan](docs/app-plan.md#decisions)).
The signature shows that the app hasn't changed since it was built, not who built it.
Trust comes from how releases are produced instead:

- **Built only by CI, from a tag.** Pushing a `v*` tag runs the
  [release workflow](.github/workflows/release.yml) on GitHub-hosted runners. It
  refuses a tag that doesn't match the package version, runs the full CI checks,
  builds the wheel, sdist, and the arm64 and x86_64 apps from the tagged commit, and
  writes `SHA256SUMS`. Release builds don't use caches from other builds, and the
  workflow's third-party actions are pinned to commit SHAs.
- **Checked before release.** `scripts/release.py verify` checks every file against
  `SHA256SUMS`, opens each zip and DMG, checks the app's version, architecture,
  bundled engine, and signature, and runs each app on a Mac of that architecture.
  Only then does the workflow create a *draft* release, which the maintainer
  reviews and publishes. The workflow won't replace the files of a published release.
- **Verified on install.** [`scripts/install.sh`](scripts/install.sh), attached to
  each release, downloads with `curl` and installs nothing unless the zip matches
  `SHA256SUMS` and the app inside has MarketPulse's bundle ID, the requested
  version, and a valid signature (`codesign --verify --deep --strict`).

To verify a download yourself, run `shasum -a 256 -c SHA256SUMS --ignore-missing`
in the download folder ([install guide](docs/install.md#verify-a-download)).
`SHA256SUMS` is published on the same release as the files it covers, so it detects
damaged or truncated downloads and files altered on their own, but not someone who
can replace both: a compromised GitHub account or release, or a mirror you download
both from (`install.sh --base-url`). To check a mirrored file, take `SHA256SUMS` from
the GitHub release itself. If that is your concern, build the app from the tag with
`scripts/build_app.py` ([build guide](docs/desktop.md#build-the-standalone-app)).
Builds aren't guaranteed to be bit-for-bit reproducible, so compare behaviour and source, not hashes.

Report a suspected tampered release privately, as described above.

## Data protection

MarketPulse stores financial data locally and does not encrypt it. Display
privacy mode does not redact machine-readable exports. See
[data and backups](docs/data.md) for storage, network behavior, and restoration.

Calculation discrepancies and ordinary import errors can be reported as bugs
using redacted examples, unless they expose private data or another vulnerability.
