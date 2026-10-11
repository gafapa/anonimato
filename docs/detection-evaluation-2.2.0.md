# Detection evaluation

Provenance: {"backends": {"advanced": "Sin cargar", "faces": "CPU", "ocr": "GPU / reconocimiento CPU", "pii": "DmlExecutionProvider/CPUExecutionProvider"}, "commit": "3e2d18f168ad0b754f9bb11a3a83b7976510926e", "corpus": "synthetic-v2", "dirty": true, "hardware": {"platform": "Windows-11-10.0.26300-SP0", "processor": "Intel64 Family 6 Model 165 Stepping 2, GenuineIntel"}, "lock_sha256": "03d761d2084d2936db50a47be018d8c7d0807fe9450855f21a14c49345a2d161", "manifest_sha256": "72a9cab312edf04d19b5d99a2583038ecdf5d4819a267d8353a3c7d0888caa24", "public_truth_sha256": "3f7c114d555295370a07c88f3611f68a46937f430c279ff54c2c89e2df04f64d", "seed": 2027}

Generated: 2026-10-10 11:11 · 93 documents · 158 s · advanced AI: no

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

Overall precision: 98.3 % (459/467 findings with values).

## Unmatched findings (possible false positives)

- scanned synthetic-0: address «Plaza de España
88, 2ºC, 36201 Vig0» (ocr)
- scanned synthetic-26: plate «7231
SSX» (handwriting)
- low-resolution-photo galician-table-0: name «Uxia Mouriño Pial» (ocr)
- low-resolution-photo galician-table-0: name «Uxia Mouritto Blal» (handwriting)
- low-resolution-photo galician-table-0: name «Uxia Mouniñio Rial» (ocr)
- low-resolution-photo galician-table-0: name «Uxia Mourifio Rial» (ocr)
- low-resolution-photo galician-table-0: name «Uxia Mounidio Riar» (handwriting)
- low-resolution-photo galician-table-2: name «Ánsela Seoane Otero» (handwriting)
