# Evaluación de la detección

Generado: 2026-09-25 03:10 · 80 documentos · 1806 s · IA avanzada: sí

Recall = valores reales completamente cubiertos por un hallazgo. Objetivos del plan: ≥ 98 % en
identificadores y ≥ 95 % en nombres impresos.

| Conjunto | Categoría | Recall | Valores |
|---|---|---|---|
| escaneado | Dirección | 100.0 % | 14 |
| escaneado | Tarjeta bancaria | 100.0 % | 6 |
| escaneado | Fecha nacimiento | 100.0 % | 7 |
| escaneado | DNI / NIF | 100.0 % | 26 |
| escaneado | Email | 100.0 % | 13 |
| escaneado | Datos de salud | 100.0 % | 7 |
| escaneado | IBAN / cuenta | 100.0 % | 14 |
| escaneado | Nombres | 100.0 % | 71 |
| escaneado | NIE | 100.0 % | 13 |
| escaneado | N.º Seg. Social | 100.0 % | 7 |
| escaneado | Teléfono | 100.0 % | 21 |
| escaneado | Matrícula | 100.0 % | 7 |
| nativo | Dirección | 100.0 % | 14 |
| nativo | Tarjeta bancaria | 100.0 % | 6 |
| nativo | Fecha nacimiento | 100.0 % | 7 |
| nativo | DNI / NIF | 100.0 % | 26 |
| nativo | Email | 100.0 % | 13 |
| nativo | Datos de salud | 100.0 % | 7 |
| nativo | IBAN / cuenta | 100.0 % | 14 |
| nativo | Nombres | 100.0 % | 71 |
| nativo | NIE | 100.0 % | 13 |
| nativo | N.º Seg. Social | 100.0 % | 7 |
| nativo | Teléfono | 100.0 % | 21 |
| nativo | Matrícula | 100.0 % | 7 |

Precisión global: 99.5 % (411/413 hallazgos con valor).

## Hallazgos sin correspondencia (posibles falsos positivos)

- escaneado sint-1: id_other «NSS» (llm)
- escaneado sint-36: address «Avenida de Madrid
95, 7ºD, 36201 Vig0» (ocr)
