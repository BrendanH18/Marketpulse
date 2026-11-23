# ADR 0003 — Local portfolio data threat model

**Status:** Documented. Application encryption is deferred.
**Date:** 2026-11-23
**Issues:** [Threat model #224](https://github.com/BrendanH18/Marketpulse/issues/224) · [Encryption #25](https://github.com/BrendanH18/Marketpulse/issues/25)

## Decision

MarketPulse uses operating-system file permissions to isolate the ledger from
other ordinary users of the same machine. Use separate OS accounts on a shared
machine and an encrypted volume for protection if the device or drive is lost.
Protect backups and exports on their destination volumes as well. An optional
application vault would add a separate unlock boundary and needs its own design
review before implementation. [Data, backups, and privacy](../data.md)

## Trust boundary

The Mac app, Python engine, CLI, TUI, and scheduled jobs operate under the
portfolio owner's OS identity. The desktop bridge carries financial data for the
Mac app to render. This model assumes the OS and MarketPulse executable are
trusted and the owner controls which processes run in that account.

| Situation | Protection and exposure |
| --- | --- |
| Device powered off or volume locked | Properly configured volume encryption protects files on that volume while its key is unavailable. POSIX permissions rely on the operating system enforcing them. Unencrypted volumes and external copies remain readable from their storage. |
| Another ordinary OS account on a running machine | Owner-only modes protect the live database and managed backups under normal OS permission enforcement. Shared folders and files exported outside the managed directory depend on their own permissions. |
| Someone using the owner's signed-in session | That person can use the app or CLI to read or change the portfolio. Display privacy masks amounts on screen. A future separately locked vault could protect its encrypted files until an authorized unlock. |
| Compromised owner process, administrator, or OS | A process with the owner's access can read or modify today's ledger. During a future unlocked vault session, an attacker with sufficient access could also read plaintext data in use, capture input, or alter the software. Encryption alone cannot guarantee availability against deletion or distinguish a valid older encrypted backup from the latest state. |

FileVault on macOS and Linux block-device encryption such as LUKS with dm-crypt
protect data on the configured volume. An unlocked volume serves decrypted data
to processes with access. A locked screen can leave the volume mounted and
scheduled jobs running. [Apple Platform Security](https://support.apple.com/guide/security/volume-encryption-with-filevault-sec4c6dc1b6e/web) · [Linux kernel dm-crypt documentation](https://docs.kernel.org/admin-guide/device-mapper/dm-crypt.html)

## Where data goes today

| Data | What to protect |
| --- | --- |
| Live SQLite database | The data directory is `0700`. The database and existing `-wal`, `-shm`, and `-journal` sidecars are secured as `0600` on open. Treat the files as a unit. Use the backup command for a consistent copy of an open ledger. |
| Managed backups | The `backups/` directory is `0700` and managed copies are `0600`. They include ledger history, including data that may have changed or been removed in the live ledger. Startup logs a warning when it cannot secure an existing managed backup. |
| External backups and system snapshots | `backup now PATH` writes a SQLite copy to the chosen path. The destination's permissions, encryption, sync, and retention determine who can access that copy. System backups can retain earlier data even after it is removed from the live directory. |
| Temporary databases | Import preview, restore and backup verification stage plaintext copies inside private OS temporary directories. Normal cleanup removes those directories. Interrupted operations and retained storage snapshots can leave data behind. |
| Exports and diagnostics | CSV, JSON, the desktop bridge and redirected CLI output can contain raw values even with display privacy enabled. Copies in a spreadsheet, shared folder, terminal log, or clipboard inherit that destination's controls. |
| Config and legacy files | Configuration is separate from the ledger. Saving a quote API key uses an owner-only TOML file. A legacy JSON import leaves its original files in place. |

The WAL can hold committed changes that have yet to reach the main file. SQLite
integrity checks and restore previews assess whether a backup can be read and
restored, while its origin and custody determine whether to trust its contents.
[SQLite write-ahead logging](https://www.sqlite.org/wal.html) · [Restore workflow](../data.md#restore-a-database)

## Requirements for a future vault design

- Define who can unlock, when the key leaves memory, and how CLI, TUI, Mac app,
  and scheduled jobs behave while locked. A keychain could store the database
  key and require user presence for access. Automatic unlock makes the benefit
  depend on the OS session and the keychain's access policy. The keychain stores
  the key and the database storage layer encrypts the data. [Apple Keychain Services](https://developer.apple.com/documentation/security/keychain-services/) · [Keychain item access controls](https://developer.apple.com/documentation/Security/restricting-keychain-item-accessibility)
- Account for the live database, SQLite sidecars, temporary databases, and each
  backup path. Keep managed backups encrypted when the vault is enabled. Give
  external backups and plaintext CSV or JSON exports a clear format and
  disclosure so users can protect the destination.
- Make migration opt-in. Quiesce writers, create and verify the new store, and
  preserve a rollback copy until the new store can be reopened and reconciled.
  Document where older plaintext copies may survive, including snapshots and
  backups. Deleting a file has no guarantee of erasing those copies.
- Provide a recovery procedure that can restore an encrypted backup on a new
  machine even if the original keychain is lost. Keep recovery material separate
  from the backup. Test an interrupted migration, wrong or missing keys, locked
  automation, and restore to a fresh profile on fictional ledgers before shipping.
