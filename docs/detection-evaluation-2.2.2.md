# Detection evaluation

Provenance: {"backends": {"advanced": "Sin cargar", "faces": "CPU", "ocr": "CPU", "pii": "CPUExecutionProvider"}, "commit": "a81bc4be6cdbb3dbfe37afefc7309b8a9eb83f36", "corpus": "synthetic-v3-positional", "dirty": true, "hardware": {"platform": "Windows-11-10.0.26300-SP0", "processor": "Intel64 Family 6 Model 165 Stepping 2, GenuineIntel"}, "lock_sha256": "a950ac46b02ed9ec185a0c07551930cbb1d2453b16e2bbff4fa4591c5ada2573", "manifest_sha256": "72a9cab312edf04d19b5d99a2583038ecdf5d4819a267d8353a3c7d0888caa24", "public_truth_sha256": "54152db44e08c9a57b438c997f541e938047363541e86981f89e32175ed2b611", "seed": 2028}

Generated: 2026-10-15 20:43 · 93 documents · 255 s · advanced AI: no

Recall = ground-truth values fully covered by a finding. Targets: at least 98% for
identifiers and 95% for printed names.

This value-level metric accepts coverage in one occurrence; it does not measure every repeated occurrence,
manual review effort, or handwriting accuracy on representative private documents.

| Dataset | Category | Recall | Values |
|---|---|---|---|
| layout | Names | 100.0 % | 4 |
| low-resolution-photo | Names | 100.0 % | 4 |
| native | Address | 100.0 % | 14 |
| native | Payment card | 100.0 % | 6 |
| native | Date of birth | 100.0 % | 7 |
| native | DNI / NIF | 100.0 % | 26 |
| native | Email | 100.0 % | 13 |
| native | Health data | 100.0 % | 7 |
| native | IBAN / account | 100.0 % | 14 |
| native | Names | 100.0 % | 71 |
| native | NIE | 100.0 % | 13 |
| native | Social Security number | 100.0 % | 7 |
| native | Phone | 100.0 % | 21 |
| native | License plate | 100.0 % | 7 |
| noisy-layout | Names | 100.0 % | 4 |
| scanned | Address | 100.0 % | 14 |
| scanned | Payment card | 100.0 % | 6 |
| scanned | Date of birth | 100.0 % | 7 |
| scanned | DNI / NIF | 100.0 % | 26 |
| scanned | Email | 100.0 % | 13 |
| scanned | Health data | 100.0 % | 7 |
| scanned | IBAN / account | 100.0 % | 14 |
| scanned | Names | 100.0 % | 71 |
| scanned | NIE | 100.0 % | 13 |
| scanned | Social Security number | 100.0 % | 7 |
| scanned | Phone | 100.0 % | 21 |
| scanned | License plate | 100.0 % | 7 |
| synthetic-handwriting | DNI / NIF | 100.0 % | 1 |
| synthetic-handwriting | Names | 100.0 % | 1 |

## Complete positional occurrence coverage

Every annotated occurrence requires 98% two-dimensional coverage of all its rectangles (1.5pt glyph tolerance).
This conservative bounding-box diagnostic is separate from pixel-level leakage verification and final export checks.
Original positions are extracted before detection and projected through the exact raster transforms.
Private inputs need explicit occurrences with page and rects. Unlocated targets are never positional successes.

| Dataset | Category | Covered | Occurrences | Recall |
|---|---|---|---|---|
| layout | Names | 20 | 20 | 100.0% |
| low-resolution-photo | Names | 20 | 20 | 100.0% |
| native | Address | 14 | 14 | 100.0% |
| native | Payment card | 6 | 6 | 100.0% |
| native | Date of birth | 7 | 7 | 100.0% |
| native | DNI / NIF | 26 | 26 | 100.0% |
| native | Email | 13 | 13 | 100.0% |
| native | Health data | 7 | 7 | 100.0% |
| native | IBAN / account | 14 | 14 | 100.0% |
| native | Names | 77 | 77 | 100.0% |
| native | NIE | 13 | 13 | 100.0% |
| native | Social Security number | 7 | 7 | 100.0% |
| native | Phone | 21 | 21 | 100.0% |
| native | License plate | 7 | 7 | 100.0% |
| noisy-layout | Names | 20 | 20 | 100.0% |
| scanned | Address | 14 | 14 | 100.0% |
| scanned | Payment card | 6 | 6 | 100.0% |
| scanned | Date of birth | 7 | 7 | 100.0% |
| scanned | DNI / NIF | 26 | 26 | 100.0% |
| scanned | Email | 13 | 13 | 100.0% |
| scanned | Health data | 7 | 7 | 100.0% |
| scanned | IBAN / account | 14 | 14 | 100.0% |
| scanned | Names | 74 | 77 | 96.1% |
| scanned | NIE | 13 | 13 | 100.0% |
| scanned | Social Security number | 7 | 7 | 100.0% |
| scanned | Phone | 21 | 21 | 100.0% |
| scanned | License plate | 7 | 7 | 100.0% |
| synthetic-handwriting | DNI / NIF | 1 | 1 | 100.0% |
| synthetic-handwriting | Names | 1 | 1 | 100.0% |

Targets without positional annotations: 0; excluded from the positional denominator.

### Incompletely covered public occurrences

- scanned synthetic-5: name, occurrence 2, page 1
- scanned synthetic-17: name, occurrence 2, page 1
- scanned synthetic-23: name, occurrence 2, page 1

Overall precision: 98.5 % (459/466 findings with values).

## Unmatched findings (possible false positives)

- scanned synthetic-21: name «Anxo FernándezMartínez» (ocr)
- low-resolution-photo galician-table-0: name «Uxia Mouriñio Pial» (ocr)
- low-resolution-photo galician-table-0: name «Uxia Mouriñio Rial» (ocr)
- low-resolution-photo galician-table-0: name «Uxia Mouniño Rial» (ocr)
- low-resolution-photo galician-table-0: name «Uxia Mourifio Fial» (handwriting)
- low-resolution-photo galician-table-0: name «Uxia Mouniio Rial» (handwriting)
- low-resolution-photo galician-table-2: name «Ánsela Secane Otero» (ocr)
