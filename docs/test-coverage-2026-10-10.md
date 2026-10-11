# Regression coverage expansion — 2026-10-10

Added 56 regression cases: 33 review/preview cases, 15 service/runtime cases and eight package-inventory cases.
All fixtures are fictitious and local. No application behavior, dependency versions or coverage exclusions were changed.

## Measured results

The same fast-lane selection was measured before and after on Windows with branch coverage and subprocess/thread
instrumentation enabled. The baseline passed 190 tests; the expanded selection passed 246, with zero skips/failures
and one intentionally deselected model-dependent source self-test. The complete suite now collects 304 cases.
The remaining model-dependent API/leak/window/advanced/self-test lanes were validated during the preceding 2.2.0
implementation, not rerun for this test-only expansion.

| Scope | Before | After |
|---|---|---|
| Application (fast lane) | 69.9% | 71.6% |
| API | 76.2% | 82.4% |
| Review history | 94.4% | 100.0% |
| Services | 71.2% | 86.9% |
| Advanced runtime | 77.6% | 92.2% |

The combined score counts executable statements and branches. Statement coverage improved from 72.7% to 74.3%;
branch coverage improved from 62.2% to 64.3%. The expanded run covered 68 additional statements and 32 additional
branches in aggregate. Conditional OS/model-presence paths and terminated workers may produce small run-to-run
variations. This is Python application coverage from the fast lane; it does not measure JavaScript, native libraries,
all supported platforms or real model accuracy. OCR/PII/face inference is deliberately handled by the integration lanes.
Coverage.py automatically collects and combines child-process evidence; report files live outside the data-file glob.

## New behavioral checks

- Preserve verification and saved revisions for no-op toggle/delete/Undo/Redo.
- Reject history and coordinate edits during processing or model installation without mutating review state.
- Validate page indices; compare rotated rectangle geometry against independent MuPDF matrices at four rotations.
- Retain manual history and the previous analysis after cancellation or engine failure.
- Keep preserved manual identifiers separate from freshly detected findings.
- Refuse changed-source export before invoking the engine; distinguish saved, verification-blocked and engine-error batch entries.
- Keep original values out of mixed-batch verification reports and enforce the combined Undo/Redo byte budget.
- Reject invalid preview resolutions; reuse redacted bytes when only zoom changes and rebuild them after an edit.
- Initialize a shared service once under concurrent requests; cache load failures and recover after reset.
- Stop the previous model when preference changes; release only genuinely idle servers.
- Bound integrity-lock waiting, block hashing on timeout and allow a successful retry.
- Reselect and verify model files immediately before native startup; honor CPU-only mode and loopback/authentication options.
- Refuse untrusted models before process launch; terminate unresponsive startup and escalate failed termination to kill.
- Verify actual bundled artifacts, foreign-platform filtering, required-artifact absence and altered model/runtime bytes.
- Hash native ZIP/TAR members and symbolic links without extraction; exclude the inventory from its own hashes.

Native process/HTTP boundaries are test doubles in the fast lane. Real advanced inference remains in the required
manual/scheduled/tagged qualification lane and cannot pass through missing-model skips.

## Continuous integration

The Windows fast lane now runs Coverage.py and fails below 70% combined statement/branch coverage.
This gate is below the measured 71.6% result to allow limited environment variation; it is a regression floor,
not a claim that 70% is sufficient for release. JUnit, JSON and Cobertura XML evidence is uploaded even if a gate fails.
Ruff, dependency audit, integration, package and advanced qualification lanes remain enabled.
Remote GitHub Actions has not been executed from this local workspace.

## Reproduction

Use a separate directory for coverage data; do not put JSON/XML/text report files beside data with the same prefix.

```powershell
$env:COVERAGE_FILE = Join-Path (Get-Location) 'tmp/coverage-runs/local/.coverage'
New-Item -ItemType Directory -Force -Path (Split-Path $env:COVERAGE_FILE) | Out-Null
uv run coverage run -m pytest tests --ignore=tests/test_api.py --ignore=tests/test_leaks.py --ignore=tests/test_ui.py --ignore=tests/test_advanced.py -k "not test_selftest_of_the_application" --junitxml=tmp/fast-tests.xml
uv run coverage combine
uv run coverage json -o tmp/fast-coverage.json
uv run coverage xml -o tmp/fast-coverage.xml
uv run coverage html -d tmp/fast-coverage-html
uv run coverage report --fail-under=70
```

Local evidence: `tmp/testcoverage-before.json`, `tmp/testcoverage-after.json`, `tmp/coverage-before-tests.xml`,
`tmp/coverage-after-tests.xml`, `tmp/testcoverage-after.xml` and `tmp/testcoverage-html/index.html`.
Static validation: Ruff and `git diff --check` passed. The installer produced before this expansion remains unchanged;
the new tests and CI measurement do not require rebuilding the application payload.
