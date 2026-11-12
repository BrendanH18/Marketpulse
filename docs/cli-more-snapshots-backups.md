# More snapshot and backup workflows (51–75)

[Issue #134](https://github.com/BrendanH18/Marketpulse/issues/134).
These additions inspect saved snapshots and backup file metadata offline. They
never calculate new financial values, open backup databases, restore files or
write snapshots. As with existing backup commands, opening the tracker may
first take the normal daily safety backup when one is due. Examples are fictional.

| # | Capability | Example |
| --- | --- | --- |
| 51 | Export snapshots as JSON Lines | `marketpulse snapshots --jsonl` |
| 52 | Print snapshot dates for scripts | `marketpulse snapshots --dates --weekdays-only` |
| 53 | Select and order snapshot export fields | `marketpulse snapshots --csv --fields date,currency,net_worth` |
| 54 | Exclude weekdays, repeatably | `marketpulse snapshots --exclude-weekday mon --exclude-weekday fri` |
| 55 | Select Monday through Friday snapshots | `marketpulse snapshots --weekdays-only` |
| 56 | Select Saturday and Sunday snapshots | `marketpulse snapshots --weekends-only` |
| 57 | Select first-of-month records | `marketpulse snapshots --month-start-only` |
| 58 | Select final-calendar-day-of-month records | `marketpulse snapshots --month-end-only` |
| 59 | Count snapshots by weekday | `marketpulse snapshots --summary weekday --json` |
| 60 | Count snapshots by recorded change direction | `marketpulse snapshots --summary change-direction --csv` |
| 61 | Export backup listings as JSON Lines | `marketpulse backup list --jsonl` |
| 62 | Print absolute backup paths for scripts | `marketpulse backup list --paths --reason manual` |
| 63 | Select and order backup listing export fields | `marketpulse backup list --json --fields file,size_bytes` |
| 64 | Exclude exact backup filenames, repeatably | `marketpulse backup list --exclude-file marketpulse-20240229-120000-manual.db` |
| 65 | Exclude backup dates, repeatably | `marketpulse backup list --exclude-date 2024-02-29` |
| 66 | Select backup weekdays, repeatably | `marketpulse backup list --weekday mon --weekday fri` |
| 67 | Select a backup calendar quarter | `marketpulse backup list --quarter 2024-Q1` |
| 68 | Select backups with or without recognized timestamps | `marketpulse backup list --no-timestamp` (or `--has-timestamp`) |
| 69 | Select a backup filename prefix | `marketpulse backup list --filename-prefix marketpulse-202403` |
| 70 | Select a backup filename suffix | `marketpulse backup list --filename-suffix=-manual.db` |
| 71 | Export inspected backup metadata as CSV | `marketpulse backup show marketpulse-20240229-120000-manual.db --csv` |
| 72 | Print one backup metadata field | `marketpulse backup show marketpulse-20240229-120000-manual.db --field path` |
| 73 | Inspect several backup files together | `marketpulse backup show fictional-one.db fictional-two.db --json` |
| 74 | Count backups by recorded date | `marketpulse backup list --summary date --json` |
| 75 | Count backups by weekday | `marketpulse backup list --summary weekday --csv` |

Calendar selections intersect all existing filters before counts, summaries,
single-record selection and pagination. Weekday names ignore case. Month-end
selection handles leap years and requires the final calendar day to have an
actual saved snapshot; it does not pick the latest available day in a month.
Change-direction groups are `increase`, `decrease`, `unchanged` and `unknown`.
They use the existing previous-recorded-snapshot comparison, including currency
switches, even when a filter removes the earlier record. These counts never
sum money across currencies.

`--fields` accepts distinct, comma-separated field names in the requested order
and requires JSON, CSV or JSON Lines output. Snapshot fields are `date`,
`net_worth`, `book`, `contributions`, `change`, and `currency`; backup fields are
`file`, `path`, `reason`, `size_bytes`, and `taken_at`. Field selection works with
existing JSON pagination envelopes and single-record options, and rejects
summaries. Empty CSV output retains the selected header; empty JSON Lines and
plain date/path outputs contain no lines. JSON Lines emits objects without a
pagination envelope and cannot combine with `--page-info`.

New formats are mutually exclusive with each other, existing JSON/CSV, and
counts. Summaries support the existing human/JSON/CSV formats and reject JSON
Lines and plain dates/paths. `--weekdays-only` conflicts with `--weekends-only`;
`--month-start-only` conflicts with `--month-end-only`. Human monetary output
continues to respect privacy masking. JSON, CSV and JSON Lines are raw exports.

Backup dates always come from filenames, never file modification times. Files
with unrecognized timestamps appear in date/weekday summaries as `unknown`.
They fail positive date, quarter and weekday filters, but remain eligible when
excluding dates. The startup safety-backup check ignores unrecognized timestamps
and uses the newest recognized backup, so these files do not prevent inspection.
Filename matching ignores case. `--exclude-file` takes exact
filenames without directory components; filename prefixes/suffixes cannot be
blank. These options never delete files.

`backup show` accepts the same full paths or filenames from `backup list` as
before, and now accepts several, validating every source before printing
results. One source retains its existing JSON object; multiple sources return
a JSON array in argument order, multiple CSV rows, or multiple human tables.
`--field` prints one raw value per source; a missing timestamp prints an empty
line. It is mutually exclusive with JSON and CSV. Existing default output
contracts are unchanged.
