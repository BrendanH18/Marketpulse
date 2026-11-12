# Offline maintenance and diagnostics

[User guide](usage.md) · [Issue #126](https://github.com/BrendanH18/Marketpulse/issues/126)

Thirty additions help you inspect backups, settings, the offline quote cache and
installation health without changing anything. Each guide numbers ten
capabilities and gives examples using fictional data.

| Improvements | Guide | Area |
| --- | --- | --- |
| 1–10 | [Backup inventory](cli-backup-inventory.md) | `backup list`, `backup show`, `backup verify` |
| 11–20 | [Configuration inspection](cli-config-inspection.md) | `config` and `theme` |
| 21–30 | [Quote cache and diagnostics](cli-quote-cache-diagnostics.md) | `quote --cached` and `doctor` |

These commands only read. Backup listings never open, restore or delete backup
files; configuration inspection never writes the configuration file and keeps
API keys redacted; cached quotes come only from the saved offline cache and stay
marked stale. No option adds a network call, and `doctor --offline` still skips
every network check. Defaults remain unchanged.
