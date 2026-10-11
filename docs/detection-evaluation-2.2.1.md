# Detection evaluation

Provenance: {"backends": {"advanced": "Sin cargar", "faces": "CPU", "ocr": "GPU / reconocimiento CPU", "pii": "DmlExecutionProvider/CPUExecutionProvider"}, "commit": "3e2d18f168ad0b754f9bb11a3a83b7976510926e", "corpus": "synthetic-v3-positional", "dirty": true, "hardware": {"platform": "Windows-11-10.0.26300-SP0", "processor": "Intel64 Family 6 Model 165 Stepping 2, GenuineIntel"}, "lock_sha256": "62528d2d5537537edaad61c53e94cd0de3bde8a64c0890c4169b93d9b02eba5e", "manifest_sha256": "72a9cab312edf04d19b5d99a2583038ecdf5d4819a267d8353a3c7d0888caa24", "public_truth_sha256": "54152db44e08c9a57b438c997f541e938047363541e86981f89e32175ed2b611", "seed": 2028}

Generated: 2026-10-11 13:41 · 93 documents · 364 s · advanced AI: no

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
| native | Names | 98.6 % | 71 |
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
| scanned | Names | 98.6 % | 71 |
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
| native | Names | 76 | 77 | 98.7% |
| native | NIE | 13 | 13 | 100.0% |
| native | Social Security number | 7 | 7 | 100.0% |
| native | Phone | 21 | 21 | 100.0% |
| native | License plate | 7 | 7 | 100.0% |
| noisy-layout | Names | 20 | 20 | 100.0% |
| scanned | Address | 14 | 14 | 100.0% |
| scanned | Payment card | 6 | 6 | 100.0% |
| scanned | Date of birth | 6 | 7 | 85.7% |
| scanned | DNI / NIF | 13 | 26 | 50.0% |
| scanned | Email | 13 | 13 | 100.0% |
| scanned | Health data | 7 | 7 | 100.0% |
| scanned | IBAN / account | 14 | 14 | 100.0% |
| scanned | Names | 74 | 77 | 96.1% |
| scanned | NIE | 7 | 13 | 53.8% |
| scanned | Social Security number | 7 | 7 | 100.0% |
| scanned | Phone | 21 | 21 | 100.0% |
| scanned | License plate | 6 | 7 | 85.7% |
| synthetic-handwriting | DNI / NIF | 1 | 1 | 100.0% |
| synthetic-handwriting | Names | 0 | 1 | 0.0% |

Targets without positional annotations: 0; excluded from the positional denominator.

### Incompletely covered public occurrences

- scanned synthetic-0: nie, occurrence 1, page 1
- scanned synthetic-5: name, occurrence 2, page 1
- scanned synthetic-6: nie, occurrence 1, page 1
- scanned synthetic-8: dni, occurrence 1, page 1
- scanned synthetic-10: dni, occurrence 1, page 1
- scanned synthetic-11: name, occurrence 2, page 1
- scanned synthetic-14: dni, occurrence 1, page 1
- scanned synthetic-16: dni, occurrence 1, page 1
- scanned synthetic-16: nie, occurrence 1, page 1
- scanned synthetic-18: dni, occurrence 1, page 1
- scanned synthetic-18: nie, occurrence 1, page 1
- scanned synthetic-20: dni, occurrence 1, page 1
- scanned synthetic-22: dni, occurrence 1, page 1
- scanned synthetic-22: nie, occurrence 1, page 1
- scanned synthetic-24: dni, occurrence 1, page 1
- scanned synthetic-27: plate, occurrence 1, page 1
- scanned synthetic-28: dni, occurrence 1, page 1
- scanned synthetic-31: date, occurrence 1, page 1
- scanned synthetic-32: dni, occurrence 1, page 1
- scanned synthetic-34: dni, occurrence 1, page 1
- scanned synthetic-34: dni, occurrence 1, page 1
- scanned synthetic-34: nie, occurrence 1, page 1
- native synthetic-35: name, occurrence 1, page 1
- scanned synthetic-35: name, occurrence 1, page 1
- scanned synthetic-36: dni, occurrence 1, page 1
- synthetic-handwriting mixed-print-handwriting: name, occurrence 1, page 1

Overall precision: 98.3 % (457/465 findings with values).

## Uncovered values

- native synthetic-35: name «Jaione Villarrubia Varela»
- scanned synthetic-35: name «Jaione Villarrubia Varela»

## Unmatched findings (possible false positives)

- scanned synthetic-18: address «Camino de Ronda
111, 2ºB, 48001 Bilba0» (ocr)
- scanned synthetic-36: nss «20E
93
2SS» (handwriting)
- low-resolution-photo galician-table-0: name «Uxia Mouriño Pial» (ocr)
- low-resolution-photo galician-table-0: name «Uxia Mouritto Blal» (handwriting)
- low-resolution-photo galician-table-0: name «Uxia Mouniñio Rial» (ocr)
- low-resolution-photo galician-table-0: name «Uxia Mourifio Rial» (ocr)
- low-resolution-photo galician-table-0: name «Uxia Mounidio Riar» (handwriting)
- low-resolution-photo galician-table-2: name «Ánsela Seoane Otero» (handwriting)
