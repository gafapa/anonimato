# Anonimato desktop plan and implementation record

## Goal and limits

Build a locally running desktop application that removes marked personal data from PDFs and images, verifies the exact output bytes, and blocks export if a trace remains. The Windows installer runs without administrator rights, Python, or CUDA. Reference hardware: Windows 11, RTX 2070 with 8 GB VRAM, and 32 GB RAM.

The guarantee covers marked content and, in maximum-security mode, non-visible document content. Data that neither the detectors nor a human reviewer marks can remain visible. The interface therefore requires page-by-page review before sharing.

## Architecture

```text
Native window (pywebview + WebView2)
  └─ HTML/CSS/JavaScript interface
       └─ direct JavaScript–Python bridge; no application HTTP server
            └─ isolated Python document engine
                 ├─ PyMuPDF: reading, exact character positions, rendering, redaction
                 ├─ pikepdf: structural cleanup and object-level verification
                 ├─ PP-OCRv5: text-line boxes and printed text
                 ├─ Qwen3-VL via llama.cpp: optional handwriting and contextual review
                 ├─ GLiNER-PII and validated rules: personal-data detection
                 ├─ YuNet: faces
                 └─ ONNX Runtime: DirectML/CoreML/CPU inference
```

OCR uses two stages because a vision-language model can transcribe handwriting but does not provide reliable redaction coordinates. A conventional detector supplies the text-line boxes; the VLM reads their contents. Uncertain handwriting next to personal-data labels is proposed for full-line redaction. Large models are loaded in sequence to fit an 8 GB GPU.

`llama-server` is the only local socket: it binds to `127.0.0.1` with a random port and session key, then closes with the application. The document engine is isolated from the window and restarts after a crash or hang.

## Design decisions

| Component | Reason |
|---|---|
| pywebview + WebView2 | Reuses the local HTML interface without shipping Chromium; no application port is exposed. |
| PyMuPDF | Provides exact character quads, rendering, redaction, and PDF text operations. |
| pikepdf / qpdf | Provides low-level access for structural cleanup and inspection of decoded streams. |
| PP-OCRv5 | Finds precise text-line boxes and reads printed text quickly. |
| Qwen3-VL | Reads Spanish handwriting and performs contextual review with one optional local model. |
| GLiNER-PII | Multilingual, configurable personal-data detection without retraining. |
| llama.cpp with Vulkan or Metal | Runs quantized advanced models locally without CUDA or PyTorch. |
| DirectML | Accelerates ONNX models on the reference Windows GPU without a CUDA installation. |
| YuNet | Detects small faces, including ID photos embedded in a page. |
| PyInstaller and Inno Setup | Produce a per-user Windows installer and uninstaller. |

The base installer includes the lighter models. The optional advanced package downloads official model files with resumption and SHA-256 verification, or imports an offline ZIP. The original 250 MB installer estimate was revised to about 710 MB because the measured GLiNER fp16 model is about 550 MB and is needed for detection quality.

## Implementation phases

### 0. Skeleton and adversarial corpus

Pin Python 3.12 and dependencies with uv, create the desktop shell, and generate one PDF per leak path with canary values (`Juan García Pérez`, `12345678Z`). The corpus covers Info and XMP metadata, bookmarks and names, accessibility tags and ActualText, invisible/off-page/hidden-layer text, white text, annotations and forms, shared XObjects, vector and raster text, thumbnails and PieceInfo, JPEG EXIF/XMP, incremental revisions, attachments and JavaScript, proportional fonts, rotated pages, filenames, scans with small ID photos, and later extensions. Port and extend the rule detector with matching tests.

### 1. Destructive redaction and cleanup

Bake annotations and widgets before detection, extract exact character quads, redact text/images/vector graphics, and insert replacement tokens as real page text. Remove metadata, catalog and page structures, ActualText and related tags, JPEG APP segments, content outside the CropBox, and orphaned objects. Save a full non-incremental rewrite with a fresh PDF ID. Use a neutral output filename by default. Faces receive opaque coverage; the old pixelation option was removed.

### 2. Mandatory verification

Verify the same bytes that would be written. Check page text, all decoded PDF objects and streams, forbidden structures, rendered-page OCR, enlarged OCR around redacted zones, faces, and residual rule/AI findings. Search original values and variants across encodings and typography. If verification fails, do not save; show the page and location of the remaining trace.

### 3. Maximum-security output

After redaction, rasterize each page and rebuild the PDF from images. Optionally add searchable OCR text derived from the anonymized output. Allow replacement-token widths to be uniform so the original length is not revealed. Enable this mode when the user selects the external-sharing option.

### 4. Detection quality

Measure recall, precision, and time per page on printed pages, poor scans, handwriting, signatures, and marginal notes. Keep private evaluation documents outside the repository. PP-OCRv5 detects text lines; low-confidence or handwritten lines go to Qwen3-VL for literal transcription. GLiNER-PII analyzes native and OCR text. Validated rules take precedence for IDs and accounts; a contextual local model proposes only literal fragments found on the page. Search detected values and variants throughout the document. YuNet scans full pages and overlapping image tiles at multiple scales.

The baseline must remain useful without the advanced package: validated rules, GLiNER, and printed OCR remain available. Initial targets were at least 98% recall for identifiers and 95% for printed names; handwriting targets must be set from measured data.

### 5. Interface

Provide native file and folder pickers, drag and drop, a document queue with background progress, actual-output previews, editable findings, manual redactions, verification results, keyboard shortcuts, and batch export. Support JPG, PNG, multipage TIFF, and mobile photos with perspective correction. Keep logs free of document text and detected values. CSV/JSON exports omit original values and coordinates by default and warn before including them. The sidebar presents the essential choices first and folds detailed detection and output settings away until needed.

### 6. Packaging

Build a PyInstaller directory and Inno Setup installer. Install per user without administrator rights; provide a Start-menu shortcut and clean uninstall. Check WebView2, verify bundled and downloaded model hashes, and fall back to CPU if DirectML fails. Code signing remains optional; without a certificate, Windows may show SmartScreen on first launch.

### 7. Remove the old web version

Remove the obsolete web app after desktop feature parity, keep generated artifacts out of Git, and document the current project structure.

## Historical implementation record (2026-09-26)

| Phase | Status and evidence |
|---|---|
| 0 | Complete: adversarial fixtures and expanded rules in `tests/fixtures/generate.py` and `app/engine/rules.py`. |
| 1 | Complete: exact redaction, annotation baking, CropBox cleanup, XMP/Info/ActualText removal, JPEG/JPX handling, neutral filenames. |
| 2 | Complete: structural, text, encoded-stream, OCR, face, and residual checks in `verify.py`; failed exports are blocked. |
| 3 | Complete: page rasterization, optional output OCR layer, and uniform token widths. |
| 4 | Complete: PP-OCRv5, orientation and small-image rereading, GLiNER fp16, Qwen3-VL, YuNet, signatures, and propagation. See `docs/benchmark.md` and `docs/deteccion.md`. |
| 5 | Complete: file/folder/image input, review, shortcuts, manual redaction, batch output, privacy-preserving logs, and a simplified settings sidebar. See `tools/ui_smoke.py`. |
| 6 | Complete: Windows installer and installed-program `--selftest` tested with silent install and uninstall. |
| 7 | Complete: legacy web project removed. |

The model benchmark selected Qwen3-VL-8B as the standard advanced package (13.7% character error on the tested handwritten census names versus 23.7% for 4B). Qwen3-VL-4B is selected on GPUs with less than 7 GB free. PaddleOCR-VL was faster but could not perform contextual review. A VLM threshold of 0.985 captures almost all uncertain handwriting in the measured set. GLiNER uses fp16 because the published int8 variant failed detection in testing. The OCR line recognizer runs on CPU because DirectML was slower for its changing input sizes.

The evaluation used public IAM and French census data plus synthetic documents with fictitious personal data. The recorded 80-document native/scanned evaluation reported 100% recall in every measured category, 99.8% precision without advanced AI, and 99.5% with it. These results do not establish performance on every real-world document. Add representative private documents to `eval/own` and `eval/docs` for local measurement.

## Second review and remaining work

- Hostile PDFs run in separate workers. Windows Job Objects limit memory (including `llama-server`); hangs and crashes trigger recovery. The window never opens a PDF directly. `tests/test_worker.py` covers crashes, hangs, memory, damaged files, and passwords.
- Integrity verification covers base, advanced, and lightweight models plus the llama.cpp runtime. Processing and export force fresh content hashes and are blocked on altered files. Disk size and timestamps are not accepted as proof of integrity. The UI reports integrity failures.
- Optional model failures are reported in UI status and document notes; GLiNER retries on CPU after GPU failure. Startup checks integrity; each operation prepares only its required services. Detector access is locked to avoid concurrent DirectML use.
- Verification rereads covered handwriting with AI when available and uses GLiNER on output text and OCR. Remaining traces carry page and box coordinates, appear in red, and show progress while saving.
- Further test coverage includes cancellation, passwords, digital signatures, uniform token lengths, advanced-model downloads, JPEG 2000, and residual leak localization.

Outstanding external inputs are representative user documents for private evaluation and a paid certificate if signed Windows installers are required.

## Improvements in 2.2.0 (2026-10-10)

Compatible reanalysis preserves manual areas, including disabled areas. Pending/failed, selected, and all-document scopes avoid repeating unrelated work. Changed source bytes or page geometry block manual-area transfer and retain the previous review. Undo/Redo stores at most 40 snapshots and 4 MiB in memory; edits and history restoration invalidate verification. Closing warns about active work or reviewed revisions not yet saved.

The UI provides scrollable zoom, a keyboard coordinate editor, individual batch outcomes, report locations and targeted retry. Model startup selects installed 8B/4B variants using current free GPU memory and available RAM; explicit accuracy/memory preferences are available. Service status reports actual loaded backends. CPU thread counts can be profiled with `tools/profile_pipeline.py`; settings must be justified by measurements on the target machine.

Evaluation adds fictitious Galician tables, accents, repeated values, small marginal text, noisy scans, low-resolution images, and mixed print/handwriting. Private annotations are opt-in and produce aggregate-only reports inside ignored `tmp/`. Recorded historical recall is not a universal detection guarantee.

CI separates fast regression/security, real integration and packaging, and scheduled/manual/tagged advanced-model qualification. Release jobs require successful qualification when requested; advanced tests cannot silently skip. Package inventories hash actual files and archived native libraries and include Python distribution metadata and license references. They are not a complete native vulnerability assessment. See `docs/improvement-opportunities-2026-10-10.md` and the final implementation report for current evidence and remaining qualification limits.
