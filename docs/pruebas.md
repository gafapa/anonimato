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
| Measured recall and precision by category | `tools/evaluate_detection.py` → `docs/deteccion*.md`; `tools/benchmark_handwriting.py` → `docs/benchmark.md` |

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

## Not automatically exercised on Windows

- macOS and Linux branches in `app/engine/system.py` run in GitHub Actions on those platforms.
- The pywebview startup loop in `app/main.py` is represented by `tools/ui_smoke.py`, which mounts the same UI and API.
- Defensive branches for driver and operating-system failures are logged and reported, but cannot be triggered reliably in an automated test.
