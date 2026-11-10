# Inspect and arrange offline inventory

[Offline CLI workflows](cli-workflows.md) · [User guide](usage.md)

The second batch of offline CLI improvements is tracked in
[#106](https://github.com/BrendanH18/Marketpulse/issues/106). These ten additions
inspect configured metadata and arrange inventory without changing it.
Examples use fictional accounts and symbols.

| # | Improvement | Example |
| --- | --- | --- |
| 11 | Inspect one active account by ID, name or unique type, as a table or JSON | `marketpulse accounts show "Fictional TFSA" --json` |
| 12 | Inspect one configured asset, as a table or JSON | `marketpulse asset show FICTION-GIC --json` |
| 13 | Filter accounts by configured currency, ignoring case | `marketpulse accounts list --offline --currency CAD` |
| 14 | Filter accounts by cash tracking | `marketpulse accounts list --offline --cash` or `--no-cash` |
| 15 | Sort accounts by name, type, institution or currency | `marketpulse accounts list --offline --sort name` |
| 16 | Reverse account order | `marketpulse accounts list --offline --sort name --descending` |
| 17 | Sort assets by symbol, name, kind or currency | `marketpulse asset list --sort name` |
| 18 | Reverse asset order | `marketpulse asset list --sort name --descending` |
| 19 | Limit the number of matching assets | `marketpulse asset list --limit 10` |
| 20 | Skip matching assets for pagination | `marketpulse asset list --offset 10 --limit 10` |

Both `show` commands are offline. Missing accounts or asset definitions fail
with exit status 1; reads never create a default account or asset. Account
inspection hides archived accounts even when an archived ID or name is supplied.
Use `accounts list --archived` to explicitly include archived account metadata.
Asset inspection reads the configured definition, including market-symbol
classification overrides; it does not infer a definition for an unconfigured
market symbol or return holdings or financial values.

`accounts show --json` returns the same fields as one entry from
`accounts list --json`: `id`, `name`, `type`, `currency`, `institution`,
`track_cash`, `archived`, and `created_at`. `asset show --json` returns the same
fields as an entry from `asset list --json`, including the configured rate and
term dates. JSON contains raw, unmasked metadata even in privacy mode. The human
asset detail table masks its rate in privacy mode. These commands do not fetch
prices, record valuation snapshots, or change the desktop bridge.

Account filters compose with the existing type, institution and name filters.
Omitting both `--cash` and `--no-cash` leaves cash tracking unrestricted. Existing
priced account listings remain the default: add `--offline` for a metadata table,
or `--json` for raw metadata without pricing.

Sorting ignores case; equal account keys use account ID, and equal asset keys
use symbol. Without `--sort`, account ID order and stored asset order remain the
defaults. `--descending` reverses the entire selected order, including tie order.
Asset filters run first, sorting second, and pagination last. `--offset` defaults
to zero and must be nonnegative; `--limit` must be positive and is unlimited when
omitted. A page beyond the end returns `[]` in JSON. Pages reflect the inventory
at the time each command runs.
