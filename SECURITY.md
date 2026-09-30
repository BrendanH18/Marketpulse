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

## Data protection

MarketPulse stores financial data locally and does not encrypt it. Display
privacy mode does not redact machine-readable exports. See
[data and backups](docs/data.md) for storage, network behavior, and restoration.

Calculation discrepancies and ordinary import errors can be reported as bugs
using redacted examples, unless they expose private data or another vulnerability.
