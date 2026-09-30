# Handwriting OCR benchmark

Generated: 2026-09-25 01:54 · hardware: RTX 2070 8 GB (Vulkan) · 60 lines per dataset.

CER = character error rate (lower is better; census CER covers names only). Exact = identical lines.
Personal data = lines where personal data remains detectable after transcription (for the census:
first and last names read with at most 15% error). Time = median per line.

## IAM (English)

| Engine | CER | Exact | Personal data | s/line |
|---|---|---|---|---|
| ppocr | 20.5 % | 5 % | — | 0.04 |
| qwen3vl-4b | 7.0 % | 18 % | — | 0.51 |
| qwen3vl-8b | 5.6 % | 20 % | — | 0.77 |
| paddleocr-vl | 7.5 % | 15 % | — | 0.23 |

## French census (names)

| Engine | CER | Exact | Personal data | s/line |
|---|---|---|---|---|
| ppocr | 36.1 % | 0 % | 13 % | 0.06 |
| qwen3vl-4b | 23.7 % | 0 % | 35 % | 0.62 |
| qwen3vl-8b | 13.7 % | 0 % | 48 % | 1.01 |
| paddleocr-vl | 20.1 % | 0 % | 38 % | 0.26 |

## Synthetic Spanish personal data

| Engine | CER | Exact | Personal data | s/line |
|---|---|---|---|---|
| ppocr | 5.0 % | 73 % | 89 % | 0.02 |
| qwen3vl-4b | 0.0 % | 100 % | 100 % | 0.36 |
| qwen3vl-8b | 0.2 % | 98 % | 100 % | 0.57 |
| paddleocr-vl | 1.3 % | 90 % | 100 % | 0.18 |
