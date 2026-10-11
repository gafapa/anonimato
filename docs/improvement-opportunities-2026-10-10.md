# Improvement opportunities — 2026-10-10

Scope: current Anonimato 2.1.1 working tree, Python processing/verification, the desktop WebView interface, model selection, evaluation, and CI. This is a prioritized improvement review; application behavior and dependencies were not changed. The cancelled Lumen agent-configuration request is excluded.

## Evidence and limits

The existing final reports record 161 regression/unit tests, 54 integration tests (including the real window), and two advanced-model tests passing. The packaged self-test also passed. Those tests were not rerun wholesale for this review. Fresh synthetic probes exercised reanalysis and model preference. Source inspection and official technical documentation support the recommendations below; expected performance gains are not measured production guarantees.

## Prioritized opportunities

| ID | Priority | Improvement | Expected benefit | Effort |
|---|---|---|---|---|
| I1 | High | Preserve manual review when reanalyzing; target pending/failed documents | Avoid lost work and repeated processing | Medium |
| I2 | High | Prepare only required services and measure CPU thread budgets | Reduce first-use latency and unnecessary memory use | Medium |
| I3 | High | Select the advanced model at execution time and report actual backends | Avoid unnecessarily running 8B on CPU when a suitable 4B pack is available | Medium |
| I4 | Medium | Add undo/redo and close-with-unsaved-review protection | Recover accidental edits without writing sensitive session data to disk | Medium |
| I5 | Medium | Add document zoom and keyboard-accessible manual rectangles | Improve review of small text and make manual redaction accessible | Medium |
| I6 | Medium | Present per-file batch outcomes and accessible verification status | Distinguish verification, engine, disk, and report failures | Small |
| I7 | Medium | Broaden local detection evaluation and version its evidence | Measure failure modes beyond the synthetic benchmark | Medium |
| I8 | Medium | Separate CI feedback lanes and inventory shipped native components | Faster routine feedback and more complete release assurance | Medium |

### I1 — Preserve work and support selective reanalysis

Evidence: `app/api.py:254` supports an `only` document list, but `app/ui/app.js:259` passes `null`. The default backend selection includes every unlocked document, including already reviewed ones. `_run()` clears the analysis at `app/api.py:288` and rebuilds findings.

Fresh synthetic reproduction: one manually added rectangle became zero rectangles after reanalysis (`tmp/improvement-probes.json`). This is confirmed behavior, not evidence of an export bypass.

Recommendation: expose “Analyze pending”, “Retry failed”, and “Reanalyze selected”. Preserve manual rectangles when the source hash and page geometry match; prompt before replacing reviewed findings. Keep automatic findings subject to the new detection options rather than silently retaining stale detection results.

Acceptance: reanalyzing a selected file leaves other files and their edits untouched; manual geometry survives compatible reanalysis; changed source/page geometry requires an explicit review decision.

### I2 — Prepare services on demand and benchmark CPU settings

Evidence: `app/engine/services.py:50` warms OCR, GLiNER, and face detection unconditionally. `require_integrity()` waits for that preparation before analysis/export. `app/engine/onnx_runtime.py` already disables idle thread spinning, but does not configure an explicit CPU thread budget.

Recommendation: separate the integrity gate from model preparation; prepare only services needed by the selected operation, including mandatory output verification and residual detection. A text-only initial analysis with AI disabled should not wait for unused face/PII models. Benchmark model initialization, integrity hashing, OCR, GLiNER, and stream scanning separately before changing thread settings. Continue hashing at processing gates; do not reintroduce a writable integrity cache.

The [official ONNX Runtime threading guide](https://onnxruntime.ai/docs/performance/tune-performance/threading.html) documents per-session defaults and thread-count controls. A lower thread count is a candidate to measure, not an automatic improvement.

Historical synthetic integration timings: initial processing 173 s; three-file batch export 444 s; the complete UI scenario 977 s. These are test-scenario durations on this machine, with concurrent workloads, not clean per-operation benchmarks.

Acceptance: report cold/warm stage timings and peak memory on identical inputs and hardware; pass the current verification suite; preserve required verification when optional analysis methods are disabled.

### I3 — Choose a suitable installed variant for the actual execution device

Evidence: `app/engine/llm_server.py:50` prefers the full advanced pack whenever both packs are installed. `LlamaServer.default()` follows that preference. Later startup requires approximately 7 GB free GPU memory for the larger file and otherwise selects CPU; it does not try the installed lighter pack first. The synthetic probe confirms that both installed packs resolve to `advanced`.

Recommendation: offer Auto / Higher accuracy / Lower memory. Auto should consider available VRAM, RAM, explicit CPU selection, installed packs, and measured runtime capabilities immediately before launch. If 8B cannot fit but 4B can, suggest/use 4B with a visible quality tradeoff. Allow a deliberate 8B CPU choice. Preserve the larger model's measured handwriting advantage rather than forcing a smaller model for every user.

Show the chosen model and actual CPU/GPU backend for OCR, PII, and advanced inference. The current global “GPU active” indicator is not proof that every service runs on GPU.

Acceptance: cover both installed variants, changing free VRAM, CPU-only execution, unavailable runtime backends, and explicit user overrides.

### I4 — Undo/redo and protection against losing unsaved review

Evidence: toggles, manual additions, and deletions directly modify findings; the UI has no undo/redo history, and `app/main.py` closes through shutdown without a review-loss confirmation.

Recommendation: keep a bounded in-memory history of review commands, including document identity and revision; add Undo/Redo and warn when closing with reviewed work that has not been exported. Invalidate verification after every undo/redo mutation. Avoid automatic disk persistence of original text, findings, or document contents.

Acceptance: recover a deleted rectangle and a bulk inclusion change; revisions/reports remain coherent; saving, processing, and installation cannot race with history operations.

### I5 — Better document inspection and accessible manual redaction

Evidence: previews are fit-to-window raster images; there are no document zoom/pan controls. Manual creation uses pointer handlers at `app/ui/app.js:530`; the M shortcut activates pointer selection but does not provide a keyboard rectangle editor.

Recommendation: add zoom presets, fit-width, pan, and higher-resolution rendering on demand. Provide keyboard-operable rectangle creation/resizing or a labelled coordinate editor, with page-bound validation. Keep stored marks in page coordinates regardless of zoom.

Acceptance: marking the same region at different zoom levels produces equivalent page geometry; the entire manual-redaction operation can be completed with keyboard input; inspect narrow desktop windows and Windows display scaling. No full accessibility compliance claim is made from static inspection.

### I6 — Explain batch results and announce verification changes

Evidence: the backend returns individual batch results and a report path. `app/ui/app.js:644` shows aggregate counts and describes every failed file as blocked by verification, although engine and write errors also produce failed results. The `verifyCard` at `app/ui/index.html:127` is not a live/status region, while progress and engine errors already have appropriate announcements.

Recommendation: show a per-file summary with Saved / Verification blocked / Processing error / Write error, plus the report location and a retry action for eligible failures. Update saved badges for successfully exported documents. Announce the final verification state through a concise status region without exposing original values.

The [W3C status-message guidance](https://www.w3.org/WAI/WCAG22/Techniques/aria/ARIA22.html) supports announcing changed status without moving focus. Existing progress/status semantics should be preserved rather than making every UI change announce repeatedly.

Acceptance: a mixed batch with one verified PDF and one disk error displays the correct saved count and distinct cause; report-writing failure preserves saved success; assistive technology receives the final verification outcome.

### I7 — Versioned, representative local evaluation

Evidence: `docs/deteccion.md` records an 80-document evaluation dated 2026-09-25; `tools/evaluate_detection.py` generates synthetic native/scanned documents and supports locally annotated inputs. Handwriting evaluation uses English IAM, French census names, and synthetic Spanish lines; it does not establish general Spanish/Galician handwriting accuracy.

Recommendation: expand synthetic/public fixtures with accents, Galician names, low-resolution phone images, small text, tables, repeated values, marginal notes, and mixed printed/handwritten text. Where private evaluation is appropriate, keep input and labels entirely local and out of version control. Record commit, dependency lock hash, model hashes, hardware/backend, corpus version, category counts, recall/precision, and review effort. Separate synthetic and representative results.

Acceptance: compare candidate changes against a held-out corpus; report missed values and false positives by category/layout; do not publish sensitive examples or imply that 100% synthetic recall means universal detection.

### I8 — CI lanes, native component inventory, and current documentation

Evidence: `.github/workflows/build.yml` runs all tests inside each OS build job. Advanced-model tests skip when the optional pack is absent. The current dependency audit covers Python distributions; it does not inventory all libraries bundled by PyInstaller and llama.cpp. `PLAN.md` still describes a size/time integrity cache that the current implementation intentionally removed.

Recommendation: run a fast regression/lint/audit lane on each PR, keep leak/real-window/package tests as required release validation, and schedule a dedicated advanced-model qualification lane with its pack installed. Generate a release inventory/SBOM containing actual native files, versions, hashes, and licenses; review native advisories against that inventory. Reconcile PLAN.md with the current fail-closed checks and verified 2.1.1 results. Do not skip critical verification merely to shorten CI.

Acceptance: PRs receive quick deterministic feedback; required release gates still run; advanced-model qualification cannot appear green through skipping; the release inventory matches packaged bytes.

## UI audit observations

Scope is code-level desktop inspection; no new live-window visual, contrast, screen-reader, or DPI audit was run. An overall accessibility/design score would therefore be misleading. Static evidence covers all five audit dimensions: accessibility gaps are I5/I6; expensive processing is I2; native minimum size is 980 × 640 and narrower CSS fallbacks should be checked under display scaling; CSS tokens and focus styles provide an existing visual system; safe DOM construction and a restrictive CSP are worth preserving.

The Impeccable detector ran in degraded regex mode because its HTML/CSS parser modules were unavailable (`tmp/improvement-ui-detector.json`): it could not compute contrast or selector relationships. Its two “broken image” warnings are false positives for previews populated dynamically inside hidden review content. Its width-transition warning concerns a small progress bar and is low priority, not evidence of a severe performance problem. There is no basis for a redesign from these findings.

Useful follow-up UI passes: `$impeccable harden` for I4/I6, `$impeccable adapt` for I5 and scaling, then `$impeccable polish` after functional fixes.

## Candidate rejected after measurement

A blanket replacement of `no_accents()` with Unicode normalization plus `str.translate()` did not improve the measured mixed-Unicode sample: current 0.4953 s/call versus candidate 0.5293 s/call, three repetitions over 994,000 synthetic characters (`tmp/improvement-normalization-benchmark.json`). The implementations matched over the Unicode code-point range. These are microbenchmark observations, not an application speed assessment; the candidate is not recommended on that evidence.

## Suggested implementation order

I1 first to protect review work, I2/I3 next for responsiveness and hardware suitability, then I5/I6 for safer inspection and clearer results. Add I4 alongside those review changes. Run I7/I8 continuously as validation and release maintenance. Each item should be implemented as a separately reviewable change with its acceptance checks.
