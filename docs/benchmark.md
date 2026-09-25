# Comparativa de OCR manuscrito

Generado: 2026-09-25 01:54 · equipo: RTX 2070 8 GB (Vulkan) · 60 líneas por conjunto.

CER = error por carácter (menor es mejor; en el censo, solo sobre los nombres). Exactas = líneas idénticas.
Datos personales = líneas cuyos datos personales siguen detectándose tras la transcripción (en el censo:
nombres y apellidos leídos con ≤ 15 % de error). Tiempo = mediana por línea.

## IAM (inglés)

| Motor | CER | Exactas | Datos personales | s/línea |
|---|---|---|---|---|
| ppocr | 20.5 % | 5 % | — | 0.04 |
| qwen3vl-4b | 7.0 % | 18 % | — | 0.51 |
| qwen3vl-8b | 5.6 % | 20 % | — | 0.77 |
| paddleocr-vl | 7.5 % | 15 % | — | 0.23 |

## Censo francés (nombres)

| Motor | CER | Exactas | Datos personales | s/línea |
|---|---|---|---|---|
| ppocr | 36.1 % | 0 % | 13 % | 0.06 |
| qwen3vl-4b | 23.7 % | 0 % | 35 % | 0.62 |
| qwen3vl-8b | 13.7 % | 0 % | 48 % | 1.01 |
| paddleocr-vl | 20.1 % | 0 % | 38 % | 0.26 |

## Sintético español con datos personales

| Motor | CER | Exactas | Datos personales | s/línea |
|---|---|---|---|---|
| ppocr | 5.0 % | 73 % | 89 % | 0.02 |
| qwen3vl-4b | 0.0 % | 100 % | 100 % | 0.36 |
| qwen3vl-8b | 0.2 % | 98 % | 100 % | 0.57 |
| paddleocr-vl | 1.3 % | 90 % | 100 % | 0.18 |
