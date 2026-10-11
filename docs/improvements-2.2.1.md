# 2.2.1 verification and review improvements

All project documentation, identifiers and comments are maintained in English. No real personal documents were used.

## Changes

- Analysis displays the actual integrity error. Temporary lock contention and unavailable checks no longer suggest reinstalling.
- Preview resolution, page and view are validated before generating output or invoking a native renderer; invalid inputs do not mutate caches.
- Detection evaluation annotates every occurrence independently before detection, projects positions through raster rotation/skew/image placement,
  and requires complete two-dimensional coverage on the correct page. Repeated values cannot pass from one occurrence alone.
  Handwritten fixture positions come from the independent drawing font and coordinates. Private reports remain aggregate-only; category keys are validated before parsing so arbitrary labels cannot expose a private value.
  The five evaluation-tool regressions passed after that additional guard.
- Hypothesis compares 40 deterministic sequences of up to 30 review actions with an independent model: edits, no-ops, history,
  cancellation/errors, successful reanalysis, busy rejection and saved-state invalidation.
- CI requires minimum combined statement/branch coverage for each critical module and a separate real-window V8 action threshold.
  Missing modules fail. The JavaScript denominator is the whole UTF-16 source, including unreported ranges; profiling starts after initialization.
- Windows qualification installs genuine packaged payloads with a separate Inno application identity and fictitious data directory,
  exercises upgrade/repair and removal, and checks that production uninstall registration stays unchanged.
  Unix CI additionally installs from the actual DMG/AppImage, runs the installed binary, replaces and removes it.
- Integration and source self-test are separate CI steps so a later success cannot hide an earlier regression.

## Source coverage and regressions

The fast lane passed **270 tests**, with zero failures and zero skips (193.5 seconds).
Compared with the preceding expansion, this adds 24 cases and generated stateful action sequences.
Python coverage applies to `app/`, not tools, tests or JavaScript. Model-dependent integration and application self-test are excluded.

- Combined Python statements/branches: **72.3%** (previous comparable fast result: 71.6%).
- Statements: **75.0%**; branches: **64.8%**.
- JavaScript real-window action coverage: **67.45%**, 30,280 / 44,891 UTF-16 source units, 81 / 106 reported functions called.
- JavaScript floor: **65%**. This uses fictitious workers; it does not qualify AI inference or certify accessibility.

| Critical module | Measured combined coverage | Required floor |
|---|---|---|
| `app/api.py` | 85.5% | 80% |
| `app/engine/review.py` | 100.0% | 100% |
| `app/engine/services.py` | 87.5% | 85% |
| `app/engine/llm_server.py` | 92.2% | 90% |
| `app/engine/verify.py` | 83.6% | 80% |
| `app/engine/models.py` | 81.1% | 78% |
| `app/engine/worker.py` | 77.2% | 70% |

Local evidence: `tmp/startup-final-fast-tests.xml`, `tmp/startup-final-python-coverage.json`, `tmp/startup-final-python-coverage.xml`,
`tmp/startup-final-javascript-coverage.json`. Raw coverage data is isolated in `tmp/coverage-runs/startup-final/`.
CI uploads the corresponding reports even if the fast lane fails.

## Positional detection evidence

The [held-out fictitious evaluation](detection-evaluation-2.2.1.md) uses seed 2028 and 93 documents (364 seconds),
including native, noisy scanned, repeated Galician table names, low-resolution/skewed photos and mixed handwriting.
All targets have positional annotations. Value-level precision is 98.3% (457 / 465 findings with values).

The positional metric reveals incomplete coverage: native names cover 76 / 77 occurrences (98.7%),
scanned names 74 / 77 (96.1%), scanned DNI 13 / 26 (50.0%), and scanned NIE 7 / 13 (53.8%).
The public report lists every incompletely covered occurrence and page. These are conservative bounding-box diagnostics,
not proof of readable exported leakage; export verification remains independent and mandatory.
Manual review of every page, especially scanned identifiers and handwriting, remains necessary.
Advanced-model evaluation and representative private handwriting accuracy are not established by this corpus.

## Windows startup regression found during qualification

The first upgrade trial exposed an invalid synchronization handle in a frozen Windows child. Because windowed executables
have no stderr, multiprocessing's error reporting raised a second exception and opened a blocking native dialog.
The source now retains the parent's startup synchronization object until the child stops, reports gate failures before loading
models or parsing documents, and provides writable null streams during frozen bootstrap.
`tests/test_worker_startup.py` reproduces resource lifetime loss, rejected/timed-out protection and missing-stream reporting.
The worker/security subset passed 54 tests. The source application self-test passed after this fix (233.6 seconds),
including actual detection, verified export, integrity checking and recovery after a deliberately terminated worker.
The API/adversarial leak suite passed 53 tests (2,138 seconds); its parent engine was started before the final lifetime adjustment.
The complete real-window UI suite passed 2 tests (1,110 seconds); it ran with the corrected preview/integrity API and before
this final worker lifetime adjustment. The final fast suite covers the worker adjustment and the task-owned real-window action scenario.

The final real advanced-model suite also passed **2 tests with zero skips** (408.0 seconds),
covering the handwritten form, independently checked exported traces and contextual indirect identifiers.
Evidence: `tmp/startup-final-advanced-tests.xml`. This is a narrow fictitious regression, not a representative handwriting benchmark.

## Security and packaging

`tmp/security-audit-2.2.1.json` covers exactly the 56 installed Python distributions, including the two new test-only dependencies
(Hypothesis and sortedcontainers), with zero known vulnerabilities at audit time. The audited name/version set was compared
with installed metadata. This does not certify bundled native DLLs or AI runtime archives against every CVE.

The production Windows installer is `dist/AnonimatoSetup-2.2.1.exe`, 755,623,894 bytes, with companion `.exe.sha256`.
SHA-256: `c9b6a83aeed2bfc1dbd3bdea48bc796c2ecd14f27906d8b3f5c73e07a03ac572`.
The package includes an actual payload component inventory. Code signing remains outside this local qualification.

## Qualification boundaries

Qualification installers are explicitly named `AnonimatoQualificationSetup-*`, use a separate registry identity/default
installation directory, omit shortcuts and automatic startup, do not install WebView2, and only remove their own qualification
profile. The harness always supplies an isolated workspace `tmp/` destination. These are development artifacts, excluded
from uploaded release installers. Production AppId, shortcuts, WebView2 installation and profile cleanup are distinct boundaries.

The final Windows upgrade qualification passed with genuine 2.2.0 and corrected 2.2.1 payloads:
initial install, both installed self-tests, unchanged fictitious marker after upgrade, uninstall, zero remaining payload files,
removed QA data/registration and unchanged production registration. Evidence:
`tmp/installer-qualification/494b1429-8699-4503-9322-b92db64f684c/result.json` and adjacent installation/self-test logs. Same-version Windows reinstall/repair also passed with the corrected 2.2.1 package, including both installed self-tests,
preserved fictitious data, complete removal and unchanged production registration. Evidence:
`tmp/installer-qualification/c7400b3c-c6f3-4f91-b31e-f4e4fb246c4f/result.json`.
CI performs same-version reinstall/repair unless an actual
previous installer is provided; this is not presented as an old-release migration.
The Unix helper checks private application copy/extraction, installed self-test, same-version replacement and removal,
and preserves an external fictitious marker. It does not qualify system-wide integration or a real user's data migration.
macOS/Linux jobs and remote CI results have not been executed from this Windows workstation.
