# Anonimato 2.2.0 improvement implementation

The accepted scope is I1–I8 from `improvement-opportunities-2026-10-10.md`. The cancelled Lumen agent-configuration request remains excluded. Documents, private annotations and diagnostic inputs stay local. All validation uses fictitious documents.

## Implemented behavior

| Item | Result |
|---|---|
| I1 | Pending/failed, selected and all-document analysis scopes. Compatible reanalysis preserves manual rectangles and their enabled state. Source/geometry mismatch retains the prior review and blocks transfer. Per-document settings identify reviews that need reanalysis. |
| I2 | Startup checks integrity without eagerly initializing OCR/PII. Operations prepare required services; face verification loads only when face findings require it. Service-load timings, stage wall times and worker peak memory are available. `ANONIMATO_CPU_THREADS=0..64` supports local measurement; zero keeps the runtime default. |
| I3 | Actual advanced-model startup reevaluates installed variants against current free VRAM and available RAM. Automatic, accuracy and memory preferences are exposed. Loaded service backends are reported individually. |
| I4 | Memory-only Undo/Redo, bounded to 40 snapshots/4 MiB per document. History restoration invalidates verification and saving status. Closing, removing and clearing reviewed unsaved work require a discard decision. |
| I5 | Fit/100/150/200/300 percent page zoom, scrollable inspection, high-resolution bounded previews, keyboard creation/editing of rectangles through labelled percentage fields. Marks remain in page coordinates. |
| I6 | Individual Saved/Verification blocked/Processing error/Write error batch outcomes, report path, successful document badges and targeted retry. Verification uses a polite atomic status region. |
| I7 | Versioned fictitious Galician layouts, accents, tables, repeated names, marginal text, noisy scans, low-resolution photos and mixed print/handwriting. Private evaluation is explicit and aggregate-only, restricted to ignored `tmp/`. Page coverage cannot use another page's marks. Provenance records source state, dependency/model manifest hashes, corpus seed/digest and actual backends. |
| I8 | Fast regression/security, real integration/package and non-skippable advanced qualification CI lanes. Package inventories cover actual file hashes, native binaries, embedded Windows versions, Python metadata/license references and native files inside runtime archives. PLAN documentation reflects fresh hashes and lazy preparation. |

Verification remains fail-closed. Every analysis/export forces fresh model/runtime hashes. Waiting for another instance's model lock reports progress and has a bounded deadline; a timeout blocks work with a retry message instead of claiming that models are corrupt. Inventories do not certify the absence of native vulnerabilities; unknown versions/licenses remain explicit.

## Validation record

Fresh regression: 190 tests passed with no skips (`tmp/improvements-regression-final.xml`). All 53 API/independent-leak integration tests passed in the broader source run (`tmp/improvements-source-final.xml`). Both native-window tests then passed with no skips (`tmp/improvements-ui-final.xml`), including mixed-batch selective retry, stale pointer gestures, Undo/Redo, coordinate editing, zoom, saved status and a compact desktop check. The source self-test also passed in the 38-test unit/worker run (`tmp/improvements-remaining-final.xml`); those 37 other tests overlap the 190-test regression count. Both real advanced-model tests passed with no skips in 373.7 seconds (`tmp/improvements-advanced-final.xml`). The automatically selected runtime was the installed 4B pack on CPU, with both packs installed. The tests cover handwritten redaction plus an independent residue scan, and literal contextual detection of indirect identifiers/health data. Together the final evidence covers all 248 collected distinct tests: 190 regression, 53 API/leak integration, two native-window, one source self-test and two advanced tests. Counts from overlapping reruns are not added twice. The installed Python environment audit covered all 54 installed distributions with matching name/version coverage and no known vulnerabilities (`tmp/security-audit-2.2.0.json`). This does not cover unknown native vulnerabilities.

The Windows 2.2.0 executable passed a clean-local-profile self-test in 29.4 seconds: synthetic anonymization, verification, fresh integrity checks and crash recovery (`tmp/packaged-selftest-2.2.0.json`). The installer was built successfully, 720.58 MiB, SHA-256 `f83b7e7f2e5681029257cf62b5f174f98e41148c04d6e1ff31c834fe5c5fce38`; its companion `.sha256` is in `dist/`. This is packaged executable qualification, not an installation/upgrade test over an existing user application.

The actual inventory (`dist/Anonimato/component-inventory.json`) contains 1,135 payload files, 95 native files, 38 Python distributions, 10 bundled base/runtime model artifacts and 51 archived native files. The executable has embedded version 2.2.0.0. Optional advanced packs are catalogued separately and are not claimed as bundled. Unknown native versions/licenses require supplier review. Earlier 2.1.1 evidence remains in `review-2026-10-09.md`.

A 17-document expanded fictitious evaluation (`--docs 2 --scanned`, seed 2026) measured 100% value-level recall in its measured categories and 92.3% value-matching precision (72/78). Six OCR spelling variants in low-resolution photos were unmatched findings. This is a small diagnostic corpus, not representative qualification. The metric accepts coverage of one occurrence and does not demonstrate removal of every repeated occurrence or universal detection accuracy. Raw local evidence: `tmp/detection-improvements.md`.

A held-out seed (2027) then evaluated 93 fictitious documents (`--docs 40 --scanned`): 100% value-level recall in the measured categories and 98.3% value-matching precision (459/467), with eight unmatched findings. See `detection-evaluation-2.2.0.md` for category counts, examples and provenance. No detection thresholds were tuned against this seed. The earlier benchmark uses a different corpus and is not a controlled before/after comparison.

Sequential synthetic CPU measurements on Windows 11 with 12 logical CPUs retained the runtime-default thread count:

| Threads | Cold analysis/export | Warm analysis/export | Verification |
|---|---|---|---|
| Runtime default (0) | 74.371 / 37.261 s | 34.427 / 36.267 s | Both passed |
| 4 | 72.701 / 37.474 s | 34.497 / 36.575 s | Both passed |

These single cold/warm pairs do not demonstrate a useful four-thread gain. Warm totals differ by about 0.5%; changing the default is not justified. Fresh model/runtime hashes dominate wall time (about 34 seconds per operation on this machine). Startup/model-loading costs are included in the cold run; faces and advanced AI remained unloaded because this document did not require them. Peak worker memory was about 2.4 GiB. Evidence: `tmp/pipeline-profile-0-final.json` and `tmp/pipeline-profile-4-final.json`.

The earlier concurrently run four-thread profile is excluded: integration competed for the installation lock and confounded wall time. No verification checks were removed to improve speed.

Visual confirmation inspected the actual 1,480 × 940 and 980 × 640 native-window captures. The compact layout has no horizontal page overflow, both add buttons remain visible and long report paths wrap. Panels scroll to expose remaining actions. This is a bounded visual/functional check, not screen-reader or all-display-scale certification.

## Remaining qualification limits

Windows-local tests cannot certify macOS/Linux packages, remote GitHub Actions, upgrades over an existing user installation, all Windows display scales, screen-reader behavior or representative Spanish/Galician handwriting accuracy. No private user documents were used. The Impeccable detector runs in degraded regex mode because parser modules are unavailable; it cannot compute contrast or selector relationships. Dynamic preview images and a progress-width transition remain its known warnings.
