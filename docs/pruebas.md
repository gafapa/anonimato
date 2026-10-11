# Features and tests

This document maps application behavior to automated tests. `uv run pytest` runs the full suite. The UI test opens a real window; set `ANONIMATO_SKIP_UI=1` to skip it. Coverage also includes isolated engine processes.

## Document input

| Feature | Test |
|---|---|
| PDFs, folders (including recursive input), and drag and drop | `test_units::test_api_file_pickers_and_queue`, `test_window_drop_handler`, `test_ui` |
| JPG, PNG, and multipage TIFF input; EXIF removed during conversion | `test_api::test_images_are_accepted`, `test_units::test_multipage_tiff_and_bad_inputs` |
| Perspective correction for phone photos | `test_api::test_phone_photo_perspective_is_corrected` |
| Password-protected PDFs; output is never encrypted | `test_api::test_password_protected_pdf`, `test_worker::test_wrong_password`, `test_ui` |
| Digitally signed PDFs; warning and signer-data removal | `test_api::test_digitally_signed_pdf_is_flagged`, `test_leaks[25]` |
| Invalid, damaged, and oversized files | `test_units::test_multipage_tiff_and_bad_inputs`, `test_page_limit`, `test_worker::test_damaged_pdf_reports_error_not_crash` |

## Detection

| Feature | Test |
|---|---|
| Validated rules for DNI, NIE, CIF, Social Security numbers, IBAN/CCC, cards, phones, addresses, passports, BIC, IPs, license plates, and other IDs | `test_rules` (30 cases) |
| Labelled, unlabelled, rare, uppercase, and line-spanning names | `test_rules` |
| GLiNER personal-data detection and false-positive filters | `test_leaks::test_residual_detection_uses_the_ai_model`, `test_units::test_combine_and_ai_filters` |
| Scanned-page OCR, orientation, and rereading of small images | `test_leaks[13,22,23,24]`, `test_units::test_small_images_are_re_read_at_higher_resolution` |
| Advanced handwriting detection and conservative covering of uncertain text | `test_advanced::test_handwritten_form_leaves_no_trace`, `test_units::test_doubtful_handwriting_next_to_a_label_is_covered` |
| Contextual AI review accepts only literal source fragments | `test_advanced::test_contextual_review_finds_indirect_identifiers`, `test_units::test_llm_review_only_accepts_literal_fragments` |
| Faces in small ID photos and handwritten signatures | `test_leaks[22,23]`, `test_advanced` |
| Repeated and variant values, initials, rare surnames, and shared replacement tokens | `test_units::test_propagation_finds_unlabelled_repeats_and_variants`, `test_partial_mentions_share_the_full_name_token`, `test_shared_surname_of_two_people_keeps_separate_tokens` |
| Optional model failures are reported | `test_units::test_failures_of_optional_models_are_reported_not_hidden`, `test_vlm_failure_during_handwriting_is_noted` |
| Measured recall and precision by category | `tools/evaluate_detection.py` → `docs/detection-evaluation-2.2.0.md` (current); `docs/deteccion.md` (historical); `tools/benchmark_handwriting.py` → `docs/benchmark.md` |

## Redaction, cleanup, and verification

| Feature | Test |
|---|---|
| 27 leak paths, including metadata, XMP, bookmarks, accessibility tags, inline and referenced ActualText, invisible/off-page/hidden-layer text, annotations, forms, shared XObjects, vector and image text, thumbnails, PieceInfo, EXIF, JPEG 2000, older revisions, attachments, JavaScript, proportional fonts, rotated pages, filenames, photos, handwriting, digital signatures, and layer settings | `test_leaks::test_no_trace_left[01…27]` with an independent scanner |
| Lossless JPEG metadata cleanup | `test_units::test_jpeg_metadata_segments_are_removed_losslessly` |
| Maximum-security rasterization and OCR text layer | `test_leaks::test_max_security_mode`, `test_ui` |
| Hiding the length of replaced values | `test_api::test_uniform_token_width_hides_length`, `test_uniform_width_is_quantised_but_never_eats_neighbours` |
| Verification blocks remaining traces across objects, encoded streams, text, page OCR, enlarged area OCR, and faces | `test_leaks::test_verifier_blocks_a_leaky_pdf`, `test_zoomed_ocr_catches_a_half_covered_value`, `test_face_left_visible_is_detected`, `test_units::test_verification_decodes_hidden_encodings` |
| Remaining traces are located on the page | `test_api::test_blocked_export_shows_where_the_leak_is`, `test_ui` |
| Values intentionally kept by the user are not treated as leaks | `test_leaks::test_user_can_keep_a_value`, `test_units::test_targets_skip_values_the_user_kept` |
| Neutral filenames or filenames with personal values replaced | `test_leaks::test_filename_keeps_non_personal_words`, `test_units::test_safe_filename_variants` |

## Application

Version 2.1.1 security regressions are covered by `test_review_fixes`: obsolete export rejection (including the save dialog), busy-state edit guards, preservation of batch reports, accurate partial-success reporting, repeated integrity checks, complete and bounded offline installation, corrupted-ZIP cleanup, rollback and retained recovery backups, resumed downloads, newly available untrusted GGUF rejection, private reports, large image streams, UTF-16LE, verification-limit failures, pointer-safe Job Object error handling, gated worker startup, cleanup after failed assignment, and explicit CPU selection for advanced AI. `test_ui` also checks disabled review controls during export. Tests have explicit time limits; advanced inference is executed through an isolated engine process.

| Feature | Test |
|---|---|
| Full UI flow: queue, analysis, cancellation, marked review, filters, include/exclude, shortcuts, pages, manual areas, warnings, residual highlights, saving, logs, batch output, and maximum-security preview | `test_ui::test_every_interface_feature` (real window) |
| CSV/JSON logs omit originals by default and escape spreadsheet formulas | `test_api::test_logs_exclude_originals_by_default`, `test_units::test_logs_escape_formulas_and_respect_privacy_options` |
| Isolated worker crash, hang, memory limit, recovery, and GPU-to-CPU fallback | `test_worker` |
| Analysis cancellation | `test_api::test_cancel_leaves_remaining_documents_pending` |
| Model and runtime integrity, foreign libraries, and fresh content hashes | `test_models`, `test_units::test_integrity_rehashes_models_instead_of_trusting_disk_metadata`, `test_services_integrity_gate_and_warmup_timeout` |
| Advanced AI download and import, hash checks, and resumption | `test_api::test_advanced_download_flow`, `test_models::test_offline_import_verifies_checksums`, `test_units::test_download_restarts_when_the_server_ignores_ranges`, `test_api_import_advanced_pack` |
| Platform-specific llama.cpp runtime | `test_units::test_extract_runtime_tar_strips_top_folder_and_keeps_links`, `test_platform_filter_of_runtime_entries`, `test_llm_server_device_selection` |
| Installed executable self-test | `test_units::test_selftest_of_the_application`; installer checked with `--selftest` |

## Security regressions

`tests/test_security.py` covers unavailable OCR and face verification, selected one-to-three-character names,
integrity exceptions and same-stat tampering, refusal to execute untrusted or incomplete runtimes,
bounded reads and queue memory, TIFF frame and image pixel limits, bounded maximum-security rasterization,
empty categories, invalid options and thread-start recovery, invalidated reports, atomic publication failures
and name collisions, log-coordinate privacy and variant mappings, build-tool checksum failures, and
local AI requests that bypass proxies and refuse redirects. `tests/test_ocr_runtime.py` checks explicit
CPU selection, mobile-model fallback, and omission of GPU shape compilation on CPU.

## Review and release improvements (2.2.0)

`tests/test_improvements.py` covers bounded Undo/Redo, invalidation, preserved manual areas, changed-source/geometry refusal,
selective processing, coordinate editing, close warnings, lazy service preparation, execution-time model selection,
bounded zoom previews, targeted batch retries and integrity-lock progress. `tests/test_evaluation_tools.py` covers
fictitious corpus variants, private-output restrictions, page-specific coverage and hashes/metadata in package inventories.
The real-window smoke adds Undo/Redo, keyboard coordinate creation, zoom overlays, per-file batch summaries and status semantics.

Fast CI excludes the model-dependent application self-test. Integration runs API, adversarial leak and desktop-window
checks, then the source self-test. Tagged/manual/scheduled advanced qualification installs a real pack and rejects skipped
tests. Package builds include actual payload inventories; unknown native versions/licenses remain explicit review limits.

CPU measurement: `uv run python tools/profile_pipeline.py --threads 4 --output tmp/profile-4.json`.
Compare sequential runs against `--threads 0` on the same machine. Concurrent workloads and integrity-lock waiting
confound timings. Private evaluation requires `--private --output tmp/private-evaluation.md`; default evaluation reads
only fictitious fixtures and records provenance. Value-level recall does not measure every occurrence or universal accuracy.
The separate positional metric now requires complete two-dimensional coverage of each independently annotated occurrence.

## Expanded regression coverage

`tests/test_review_coverage.py` exercises no-op saved-state preservation, rejected edits during processing/installation,
invalid page indices, independently checked geometry at 0/90/180/270 degrees, cancellation/error recovery,
distinct preserved manual identifiers, changed-source export refusal, mixed batch causes, aggregate history budgets,
preview resolution limits and cache invalidation after editing.

`tests/test_service_coverage.py` exercises concurrent single initialization, cached loader failure and recovery,
model-preference changes, idle release, bounded integrity-lock failure/retry, actual runtime model reselection,
explicit CPU selection, untrusted-model refusal, health timeout and termination escalation. Native process/network
boundaries are controlled test doubles here; real advanced inference remains a separate qualification lane.

`tests/test_package_coverage.py` checks actual bundled models versus optional catalog entries, missing/changed artifacts,
foreign-platform filtering, ZIP/TAR native hashes and links without extraction, and inventory self-exclusion.
All fixtures are fictitious, tiny and local. The new tests run in the fast CI lane without model downloads.

Measured evidence and reproduction instructions are in [the coverage report](test-coverage-2026-10-10.md).

## Stateful review and occurrence qualification

`tests/test_next_improvements.py` rejects invalid preview requests before native work, preserves the exact integrity cause,
checks repeated names on multiple pages, requires two-dimensional coverage, and checks transforms against independent geometry.
`tests/test_stateful_review.py` compares generated edit/undo/redo/reanalysis/cancel/save sequences with an independent model
(40 deterministic examples, up to 30 actions each). All documents are fictitious.

`tests/test_javascript_coverage.py` measures V8 blocks in a task-owned real WebView2 window with synthetic workers.
The denominator is the complete UTF-16 source length, including ranges not reported by V8. Startup is excluded from action
coverage; attachment waits for initialization. The report records raw ranges and the covered-function count.
The scenario covers cross-document gesture cancellation, batch write failure/retry, manual edits, history, enable/disable,
filters, zoom, view/panel switches, PDF/log publication and reanalysis. It does not certify accessibility or real AI inference.

`tools/check_coverage.py` rejects missing critical modules and coverage below their individual floors, counting statements
and branches. `tests/test_coverage_gate.py` proves that a good total cannot hide a missing or under-covered critical module.
The policy also requires at least 65% JavaScript action coverage. Node.js 22 or newer is needed for this Windows development test.

`tools/qualify_installer.ps1` installs a separately identified Inno qualification build, runs the installed self-test,
preserves a fictitious profile through upgrade/reinstallation, runs the new installed binary and uninstalls it.
It checks the QA application/profile/registry removal and unchanged production uninstall registration. Local qualification
can use a genuine older packaged payload with `-PreviousInstaller` and `-PreviousVersion`; CI qualifies same-version repair.
QA builds omit shortcuts and WebView2 installation, and target only their own profile for removal. Production package assembly
is shared; production AppId, shell shortcuts, bootstrapper installation and its profile-removal rule remain distinct boundaries.

`tools/qualify_unix_package.py` copies the mounted DMG app or extracts the AppImage into a private temporary installation,
runs the installed self-test, replaces it, checks a preserved external marker and removes the application.
CI runners are disposable: this does not establish old-release data migration, system integration, signing/notarization,
interactive desktop behavior or removal of a real user's profile. See [2.2.1 evidence](improvements-2.2.1.md).

## Remaining platform qualification

- macOS and Linux branches in `app/engine/system.py` are configured to run in GitHub Actions on those platforms; Windows-local evidence does not qualify them.
- The pywebview startup loop in `app/main.py` is represented by `tools/ui_smoke.py`, which mounts the same UI and API.
- Defensive branches for driver and operating-system failures are logged and reported, but cannot be triggered reliably in an automated test.
