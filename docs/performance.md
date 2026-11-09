# Desktop refresh measurements

[Contributing](../CONTRIBUTING.md) · [App plan](app-plan.md) · [Issue #48](https://github.com/BrendanH18/Marketpulse/issues/48)

Issue #48 asks whether a persistent Python helper would make refreshes and edits
fast enough to justify its protocol, restart handling, and cross-process locking.
This benchmark measures the current engine first. It does not implement a helper
or change either desktop client.

## Repeat the benchmark

```bash
uv sync --locked --dev --python 3.11
uv run --locked python scripts/benchmark_desktop.py > /tmp/desktop-benchmark.json
```

On Windows, redirect to a writable scratch path instead of `/tmp`. The script
creates a temporary directory, overrides inherited `MARKETPULSE_DATA` and
`MARKETPULSE_CONFIG` in its workers, and removes its ledger afterwards. It never
opens your portfolio. All quotes are fixed fictional responses; no requests go
to Yahoo or any other service. Unexpected endpoints or symbols fail the run.
There are no provider keys or alerts in the fixture.

The default is seven repetitions with both zero delay and 100 ms of simulated
wait per quote request. `--samples N` changes the repetition count;
`--delay-ms N` changes the delayed scenario (0–1000 ms). The JSON includes raw
samples, medians, ranges, output sizes, request counts, and OS/Python metadata.
Run it alone, without tests or a profiler competing for CPU. Use the same host,
Python version, sample count, and delay when comparing a later change. These are
observations, not timing thresholds for CI.

## What is timed

The fixture has exactly 5,000 valid transactions: 1,250 each of deposits,
purchases, partial sales, and dividends, dated from January 2020 through June
2023. Four fictional cash-tracked accounts (two TFSA and two taxable) hold 12
positions, split between CAD and USD. Each sale follows an adequately funded
purchase. Seeding checks replay for issues; every measured snapshot checks its
activity/position counts, warnings, quote errors, and staleness.

An untimed initial snapshot creates the daily backup and today's snapshot.
Every measured case starts with a copy of that baseline. Backups, SQLite writes,
and today's snapshot upsert remain enabled. There is no long historical snapshot
series, watchlist, import, tax report, or app rendering in this workload.

| JSON timing | Boundary |
| --- | --- |
| `startup` | Fresh Python process running `desktop transaction-status` with an unused UUID. Includes imports, CLI initialization, opening SQLite, backup-age check, and the receipt lookup; no ledger replay or quote request. This is a readiness proxy, not pure interpreter startup. |
| `refresh` | Fresh process running the real `desktop snapshot` CLI, including full activity, revision hashes, replay, valuation, FX, maintenance, JSON encoding and stdout capture. |
| `edit` | Fresh process running `txn edit 2 --price 21`, including chronological replay validation. No quote lookup is needed. |
| `edit_refresh` | Sum of the edit and the immediately following refresh subprocess times. The edit is verified in the returned activity. These two processes share the edited scratch ledger; other samples start from the original 5,000 rows. Parent scheduling between the processes is excluded. |
| `reused_fresh` | One `snapshot(tracker, fresh=True)` plus JSON encoding on an already opened Tracker after an untimed snapshot. Measures `body_ms`, excluding worker startup and warm-up. Prices are fetched again; FX may remain in memory. |
| `reused_cached` | Same boundary, with the normal 15-second process quote cache enabled. Request counts show whether that cache was still usable. |

Subprocess times use a monotonic clock from launch to exit. Reused-Tracker times
exclude stdout printing; their samples also record the whole worker time as
`process_ms`, but summaries use only `body_ms`. None of these boundaries includes
native UI decoding or drawing. Imports/file pages may already be in the OS cache;
"fresh process" does not mean cold disk or a first launch after a reboot.

The fixture replaces only `CurlTransport.get_json` inside each worker. The real
quote parser, batching, caches, FX, SQLite, and financial engine still run. A new
process fetches prices even when a persisted quote cache exists. Normally the
fixture makes two serial requests (holdings and USD/CAD FX); reused fresh-price
runs make one and cached runs make none. This is not a model of Yahoo's latency,
retries, or outages. Requests can also be concurrent on larger symbol sets, so
summing request waits and subtracting them from elapsed time is invalid. Compare
the complete zero-delay and delayed cases instead.

## Baseline and recommendation

Measured 2026-11-09 on a Raspberry Pi 5 (Linux aarch64, Python 3.11.18),
against engine commit `3173c0e` (version 2.2.0), with seven samples per case.
[Raw JSON](benchmarks/desktop-refresh-linux-arm64.json) retains every sample.
Times below are median milliseconds, with the observed min–max in parentheses;
these host-specific numbers do not predict macOS or Windows app latency.


| Case | Zero delay, ms | 100 ms/request, ms | Requests, zero/delayed |
| --- | ---: | ---: | ---: |
| CLI readiness | 183 (181–232) | 184 (181–245) | 0/0 |
| Refresh | 1116 (1104–1156) | 1333 (1298–2134) | 2/2 |
| Edit | 324 (318–341) | 328 (323–774) | 0/0 |
| Edit + refresh | 1453 (1435–1518) | 1640 (1622–2346) | 2/2 |
| Reused Tracker, fresh prices | 954 (935–1069) | 1055 (1030–1090) | 1/1 |
| Reused Tracker, cached prices | 937 (925–969) | 950 (930–960) | 0/0 |

The refresh output is about 1.55 MB. The delayed scenario adds waiting without
changing the fixture or engine. Its ranges also show scheduling noise; the
largest samples should not be treated as a stable tail-latency estimate.

A separate `cProfile` diagnostic around a warmed, cached `snapshot(tracker)` and
`json.dumps` found eight `Store.transactions()` calls, three ledger replays,
10,000 transaction revision calls, and 15,015 `dataclasses.asdict()` calls in one
snapshot. Activity-row construction and `ledger_revision` both serialize every
transaction; those costs remain after a process is reused. Profiled timings
include profiler overhead and were not mixed into the benchmark samples.

**Recommendation:** investigate reducing repeated snapshot serialization and
ledger reads before committing to a persistent helper. A fresh-process refresh
still takes about 1.1 seconds locally, while a warmed cached snapshot body takes
about 0.94 seconds. That body cost remains without startup or network waiting.
Process reuse can help, but this experiment does not prove the benefit of a
server, and it omits the server protocol, crash recovery, locking, and UI costs.

No runtime optimization is part of this measurement PR. Keep #48 open and gated
on a maintainer decision. Repeat this baseline on target macOS and Windows
hardware before choosing a helper, and use the same harness for before/after
numbers if a later optimization is approved.
