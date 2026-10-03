# Atlas v2 ATX00-3 — MT5 Evidence Acquisition Preparation

Owner: Ali Shariati
Status: CLOSED — read-only acquisition preparation implemented, independently reviewed, and dual-runtime validated; real account evidence still external
Research alias: ATX-00
Authority: READ-ONLY RAW EVIDENCE / NO ORDER

## Purpose

Prepare the shortest safe path from the current ATX00-2 replay boundary to real broker/account evidence without asking the owner to manually reconstruct data or exposing credentials in project artifacts.

## Current Mac inspection

Read-only inspection found a local MetaTrader 5 Wine installation and historical terminal data under the local MT5 data directory.

Observed:
- terminal executable and MetaEditor are installed;
- historical HCC/bar caches exist for several FX symbols;
- the inspected terminal log/config/cache does not expose a usable logged-in account history export;
- the local Python environment does not provide the `MetaTrader5` package;
- no suitable deal/fill statement, account-history export, or raw tick export was found in Atlas Project, Desktop, Downloads, Documents, or the inspected MT5 data tree.

Historical HCC/bar caches are **not** substituted for source-account execution evidence.

## Prepared acquisition path

Added `run_atx00_mt5_evidence_export.py`.

The exporter:
- imports MetaTrader5 lazily and is intended for an MT5 Python host where the terminal is already logged in;
- does not accept or persist an account password;
- calls only terminal/account/symbol/history/tick read surfaces;
- never calls order send, modify, close, or any execution method;
- exports raw deals and orders into compressed JSONL;
- optionally exports ticks in one-day chunks;
- preserves API return order with an explicit local export index without claiming it is broker chronology;
- hashes each artifact and the manifest;
- removes raw account login, account-holder name, and local terminal/data paths from the manifest;
- requires a non-secret local account alias instead of deriving a reversible fingerprint from the login;
- uses deterministic gzip headers so identical raw rows produce identical artifact hashes;
- records tick-chunk row counts/boundaries as **UNVERIFIED completeness** instead of treating an empty chunk as proof of no market activity;
- pads both history and tick acquisition windows by 36 hours around the requested UTC window so unresolved edge-time semantics cannot silently drop boundary evidence;
- labels ticks as `MT5_DOCUMENTED_UTC_UNVERIFIED`: the official Python documentation describes tick/bar time as UTC, but Atlas still requires broker/account-specific verification before normalization;
- keeps requested UTC coverage separate from raw query windows because deal/order time semantics still require explicit normalization;
- writes into a `.partial` directory and atomically renames it only after a complete manifest is written;
- refuses to overwrite existing evidence directories.

## What this does not decide

The raw export is evidence acquisition only. It does not:
- establish deal/order server-time semantics by assumption; official MetaTrader5 Python documentation describes tick/bar timestamps as UTC, while the history-deal/order documentation does not explicitly settle every normalization detail needed by Atlas;
- turn API row order into normalized source sequence;
- normalize broker-specific deal types/cost signs automatically;
- claim account-currency conversion evidence is complete;
- make ATX-00 confirmatory;
- authorize Demo/Live orders.

The resulting source pack must be archived byte-for-byte, hashed, reviewed, and mapped through the ATX00-2 normalized execution contract before replay.

## Review and validation

Independent final read-only review: **PASS** with no concrete blocker.

Validation:
- exporter-focused Python 3.14: **8/8 PASS**;
- exporter-focused Python 3.12: **8/8 PASS**;
- Atlas v2 + exporter Python 3.14: **255/255 PASS + 242 subtests**;
- Atlas v2 + exporter Python 3.12: **255/255 PASS + 242 subtests**;
- Python compile checks: PASS;
- `git diff --check`: PASS;
- execution/order authority introduced: **NO**.

Operator note: an interrupted export intentionally leaves only `<out>.partial` and blocks reuse until that incomplete directory is reviewed and deliberately removed. It must never be renamed or treated as complete evidence.

## Immediate external dependency

The next real-data step requires a MetaTrader 5 terminal logged into the account whose historical behavior should be used for Atlas research, or a broker-exported account/deal history file supplied by the owner.

Credentials should **not** be sent into chat or committed to the repository. The preferred owner action is simply to log the terminal into the intended account and confirm that it is connected; Atlas can then continue with read-only evidence collection.
