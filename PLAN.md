# Plan: Anonimato de escritorio, sin rastro

**Objetivo:** una aplicación de Windows que se instala con un solo `AnonimatoSetup.exe` (sin permisos de administrador, sin Python ni CUDA), que funciona 100 % sin conexión y que **garantiza con una verificación automática** que en los archivos producidos (PDF, CSV, JSON, nombre de archivo) no queda ningún rastro de los datos anonimizados: ni visible ni recuperable.

Equipo de referencia: Windows 11, RTX 2070 8 GB, 32 GB RAM.

---

## 1. Arquitectura

```
┌───────────────── Ventana nativa (pywebview + WebView2) ─────────────────┐
│  UI actual (index.html / css / js) adaptada: cola, vista previa, tabla  │
│              │ llamadas directas JS ↔ Python (sin servidor HTTP)        │
└──────────────┼──────────────────────────────────────────────────────────┘
               ▼
        Motor Python (proceso local)
        ├─ PyMuPDF ........ lectura, texto con quad por carácter, render, redacción
        ├─ pikepdf ........ limpieza estructural y verificación objeto a objeto
        │
        ├─ OCR en dos etapas
        │   ├─ Localizar: detector de líneas de texto (PP-OCRv5 det, ONNX) → cajas exactas
        │   │             + clasificador impreso / manuscrito por línea
        │   ├─ Leer impreso:    PP-OCRv5 rec (rápido)
        │   └─ Leer manuscrito: modelo de visión-lenguaje (VLM) sobre cada recorte de línea
        │
        ├─ IA de detección de datos personales
        │   ├─ GLiNER-PII ...... NER multilingüe "zero-shot" (nombres, direcciones, etc.) en GPU
        │   ├─ Reglas + validación (DNI, IBAN, NSS…) ... precisión en identificadores
        │   └─ LLM local revisor ... segunda pasada contextual: identificadores indirectos
        │                            ("la hija del alcalde de Lalín"), datos de salud, etc.
        │
        ├─ OpenCV YuNet ... detección de rostros (ONNX, 300 KB)
        │
        └─ Runtimes
            ├─ llama.cpp (build Vulkan: funciona con el driver NVIDIA, sin CUDA) → VLM + LLM en GGUF
            └─ onnxruntime-directml → detector, OCR impreso, GLiNER, YuNet; CPU de reserva
```

**Por qué OCR en dos etapas:** los modelos de visión-lenguaje leen muy bien (incluida letra manuscrita), pero devuelven texto, no coordenadas fiables, y pueden "inventar" o corregir palabras. Para tachar hace falta saber *dónde* está cada dato. Por eso las cajas las pone siempre un detector clásico y el VLM solo lee el contenido de cada caja. Una alucinación del VLM no puede mover una caja; como mucho produce texto que no coincide con nada.

**Regla conservadora para manuscritos:** si una línea manuscrita no se puede leer con confianza suficiente, o está en una zona con contexto personal (junto a "Nombre", "Firma", "Domicilio"…), se propone **tachar la línea entera** para revisión. Ante la duda, se tapa.

**Memoria de GPU (8 GB):** los modelos grandes no caben a la vez. El motor los carga por turnos: primero OCR de todo el documento, luego detección y revisión LLM, y descarga cada modelo al terminar su fase.

**Decisiones y motivos**

| Decisión | Motivo |
|---|---|
| pywebview + WebView2 | Reutiliza la UI existente; WebView2 viene con Windows 11 (no hay que distribuir Chromium). Comunicación por `js_api`: **no se abre ningún puerto**, nada accesible desde la red. |
| PyMuPDF | Es el mismo MuPDF que ya se usa, con la API completa (quads por carácter, `search_for`, redacciones con todas las opciones, rasterizado). Licencia AGPL, compatible con el proyecto. |
| pikepdf (qpdf) | Acceso de bajo nivel a todos los objetos: borrar estructuras y escanear flujos descomprimidos en la verificación. |
| PP-OCRv5 det/rec (ONNX) | Localiza líneas (también manuscritas) con cajas precisas y lee texto impreso rápido; ~20 MB. |
| VLM para manuscritos | Único tipo de modelo local que lee letra manuscrita en español de forma útil. Candidatos a evaluar en la fase 4 (4-bit, caben en 8 GB): **Qwen3-VL 4B/8B**, **Qwen2.5-VL 3B/7B**, **PaddleOCR-VL**, y cualquier modelo OCR más reciente que salga en 2026. Se elige midiendo con documentos reales, no por reputación. |
| GLiNER-PII | Modelo de IA específico para datos personales, multilingüe, con tipos configurables sin reentrenar; mucho más preciso que spaCy y rápido en GPU. |
| LLM local revisor | Detecta lo que ni reglas ni NER ven: identificadores indirectos, datos de salud, relaciones familiares. Candidato: Qwen3 8B instruct (4-bit, ~5 GB). Sus hallazgos se localizan con `search_for` en el texto; nunca decide coordenadas. |
| llama.cpp Vulkan | Un solo runtime para VLM y LLM, sin CUDA ni Python pesado (sin PyTorch). Se ejecuta como proceso hijo `llama-server` escuchando solo en `127.0.0.1`, puerto aleatorio y clave aleatoria por sesión; se cierra con la app. Es el único socket local y no es accesible desde la red. |
| DirectML | Acelera los modelos ONNX en la RTX 2070 sin instalar CUDA/cuDNN. |
| YuNet | Detecta caras pequeñas (fotos de carnet dentro de un A4) mucho mejor que BlazeFace short-range. |
| PyInstaller (onedir) + Inno Setup | Instalador único, por usuario (`%LOCALAPPDATA%\Programs\Anonimato`), acceso directo en el menú Inicio, desinstalador. Modelos ligeros incluidos; el paquete avanzado se instala aparte (ver abajo). Ningún documento sale nunca del equipo. |

**Tamaño e instalación:** los modelos de IA ocupan 5–9 GB (VLM + LLM en 4-bit). Para que la instalación siga siendo fácil:
- `AnonimatoSetup.exe` (~250 MB) instala la app con los modelos ligeros (OCR impreso, GLiNER, caras): funciona desde el primer momento.
- En el primer arranque, un asistente ofrece descargar el **paquete de IA avanzada** (manuscritos + revisor LLM) con barra de progreso, comprobación SHA-256 y reanudación. Es la **única** conexión que hace la app, nunca envía documentos, y se puede hacer también desde un archivo descargado aparte (instalación sin conexión).
- Ajustes: "Calidad máxima (GPU)" / "Rápido (CPU)"; se detecta la GPU y la VRAM automáticamente.

**Estructura del repositorio**

```
app/
  main.py              arranque de la ventana
  api.py               puente JS ↔ Python (procesar, alternar filas, exportar)
  engine/
    document.py        abrir, bake, extraer caracteres con quads, render
    rules.py           reglas portadas de detectors.js + mejoras
    pii_model.py       GLiNER-PII
    llm_review.py      revisor LLM (llama.cpp)
    ocr/
      detect.py        cajas de línea + clasificador impreso/manuscrito
      printed.py       PP-OCRv5 rec
      handwriting.py   VLM por recorte de línea (llama.cpp)
    models.py          carga/descarga por turnos, VRAM, hashes, descarga del paquete avanzado
    faces.py           YuNet con mosaicos
    propagate.py       búsqueda global de valores y variantes
    redact.py          redacción y reemplazo por tokens
    sanitize.py        limpieza estructural (pikepdf)
    rasterize.py       modo máxima seguridad
    verify.py          verificación de ausencia (bloquea la exportación)
    logs.py            CSV/JSON
ui/                    index.html, css, js (adaptados a la API Python)
models/                ocr/, ner/, faces/  (con SHA-256 en THIRD_PARTY.md)
tests/
  fixtures/generate.py corpus adversarial
  test_rules.py  test_leaks.py  test_verify.py  test_e2e.py
packaging/
  anonimato.spec  installer.iss  build.ps1
legacy-web/            versión actual, congelada hasta alcanzar paridad; luego se elimina
```

---

## 2. Fases

### Fase 0 · Esqueleto y banco de pruebas adversarial
- Entorno con `uv` (Python 3.12 fijado), `pyproject.toml` con dependencias bloqueadas.
- `tests/fixtures/generate.py`: un PDF por vía de fuga, todos con el mismo dato canario (`Juan García Pérez`, `12345678Z`):
  1. Info dict completo, incluidas fechas y claves personalizadas.
  2. XMP en catálogo, página, imagen y fuente.
  3. Marcadores, `/PageLabels`, destinos con nombre, `/Names`.
  4. PDF etiquetado: `StructTreeRoot` con `/Alt`, `/ActualText`, `/T`, `/E`.
  5. `BDC /Span <</ActualText …>>` en el flujo de contenido.
  6. Texto invisible (modo 3, capa OCR de escáner).
  7. Texto fuera del CropBox.
  8. Texto en capa OCG oculta.
  9. Blanco sobre blanco y texto de 0,5 pt.
  10. Anotaciones FreeText, Stamp, Text/Popup con `/Contents`, Ink.
  11. AcroForm con valores y `/TU`.
  12. Form XObject compartido entre páginas.
  13. Texto convertido a trazados; dato rasterizado en imagen.
  14. Miniaturas `/Thumb`.
  15. `/PieceInfo`, `/Alternates`.
  16. JPEG con EXIF/XMP/miniatura en segmentos APP.
  17. Actualización incremental con el dato solo en la revisión anterior.
  18. Adjuntos, JavaScript, `OpenAction`.
  19. Fuente proporcional extrema (recorte parcial de caracteres).
  20. Página rotada 90° con CropBox desplazada.
  21. Nombre de archivo con el dato.
  22. Escaneo con foto de carnet pequeña.
- Mover la versión actual a `legacy-web/` (sigue funcionando mientras tanto).
- Portar `detectors.js` tal cual a `rules.py` y sus tests a `test_rules.py`, para tener un flujo completo desde el principio (las mejoras de reglas llegan en la fase 4).
- **Hecho cuando:** `pytest` genera el corpus, las reglas portadas pasan los mismos tests que en JS y la ventana vacía arranca con `python -m app`.

### Fase 1 · Motor de borrado y limpieza estructural
- `document.py`: abrir con PyMuPDF → `bake()` de anotaciones y widgets **antes** de detectar (así su texto se detecta como cualquier otro) → extraer caracteres con `rawdict` (quad exacto por carácter, incluido texto invisible y fuera del CropBox usando la MediaBox).
- `redact.py`: rectángulo = unión de quads exactos; `apply_redactions(images=PDF_REDACT_IMAGE_PIXELS, graphics=…, text=…)`; tokens insertados como texto real de página; clonar Form XObjects compartidos si hace falta (fixture 12).
- `sanitize.py` (pikepdf) antes de guardar:
  - Trailer `/Info` vacío.
  - Catálogo sin `Metadata, Outlines, PageLabels, Names, Dests, OpenAction, AA, AcroForm, StructTreeRoot, MarkInfo, Threads, PieceInfo, SpiderInfo, Collection, Perms, DSS, Legal, OCProperties`.
  - Páginas sin `Thumb, Metadata, PieceInfo, B, AA, StructParents, Annots`; `MediaBox := CropBox` y contenido recortado.
  - Recursos sin `Metadata, PieceInfo, Alternates, OPI` (recursivo).
  - `BDC` sin `/ActualText`, `/Alt`, `/E`.
  - JPEG recodificados sin segmentos APP.
  - Guardado completo (`garbage=4`, `clean`, `deflate`, nuevo `/ID`, sin incremental).
- Nombre de salida neutro por defecto (`documento-1_anonimizado.pdf`); opcional: nombre original con lo detectado sustituido.
- Rostros: solo cobertura opaca (se elimina "Pixelar").
- **Hecho cuando:** fixtures 1–5, 10, 11, 14–18, 20 y 21 pasan el escáner de fugas.

### Fase 2 · Verificación obligatoria (bloquea la exportación)
`verify.py` sobre **los mismos bytes** que se van a guardar; si falla, no se escribe el archivo y la UI muestra dónde está la fuga.
1. Texto completo de PyMuPDF (incluido invisible / fuera de caja) + `search_for` de cada valor.
2. Recorrido de todos los objetos con pikepdf: flujos descomprimidos y cadenas, buscando cada valor y sus variantes (sin tildes, sin separadores, mayúsculas, UTF‑16BE, hex, escapes octales, y texto decodificado vía `ToUnicode` para fuentes subset).
3. Afirmaciones estructurales (ninguna de las claves eliminadas en la fase 1 existe).
4. Render de cada página → OCR completo + OCR ampliado de las zonas tachadas (con el VLM en zonas manuscritas si el paquete avanzado está instalado); coincidencia difusa (distancia de edición ≤ 2) con cada original.
5. YuNet sobre el render de salida: cero rostros en zonas marcadas y aviso si aparecen nuevos.
6. Segunda pasada de reglas + GLiNER sobre el texto/OCR de salida → "posibles datos residuales" para revisar.
- Hasta que exista el OCR de la fase 4, los pasos 4–6 usan la extracción de texto y las reglas portadas; se refuerzan automáticamente cuando llegan los modelos.
- **Hecho cuando:** ningún fixture con fuga puede exportarse (aunque la detección o el borrado fallen).

### Fase 3 · Modo máxima seguridad
- Tras redactar: rasterizar cada página a 300 ppp y reconstruir el PDF solo con imágenes; capa de texto opcional generada por OCR **sobre el resultado ya anonimizado**.
- Opción "tamaño uniforme de token" para no revelar la longitud del dato.
- Activado por defecto al elegir "Voy a compartir este documento fuera".
- **Hecho cuando:** los 22 fixtures pasan en este modo, incluidos 6–9, 12, 13 y 19.

### Fase 4 · Detección con IA

**4.0 Conjunto de evaluación (antes de elegir modelos).** Reunir 30–50 páginas reales representativas (impresos, escaneos malos, formularios rellenados a mano, firmas, notas al margen), anotar a mano los datos personales y medir cada opción: *recall* (lo que no se escapa, prioritario), precisión y segundos por página en la RTX 2070. Los modelos se eligen con estos números. Se comprueba también la **licencia** de cada modelo (algunos tamaños de Qwen-VL no son Apache 2.0) y que funcione en llama.cpp Vulkan / ONNX DirectML. Script: `tests/benchmark.py`, reproducible, resultados en `docs/benchmark.md`. El conjunto real **no** se guarda en el repositorio.

- **OCR impreso** (`ocr/printed.py`): PP-OCRv5 en DirectML; páginas escaneadas y regiones de imagen (ampliadas si son pequeñas); detección de orientación; palabras de baja confianza se detectan igualmente con confianza reducida; ventanas de dos líneas.
- **OCR manuscrito** (`ocr/handwriting.py`):
  - El clasificador marca cada línea como impresa o manuscrita; las manuscritas (y las impresas de baja confianza) van al VLM recortadas con margen.
  - Instrucción al VLM: transcribir literalmente, sin corregir ni completar, y marcar `[ilegible]`.
  - La posición de cada palabra dentro de la línea se reparte por la caja del detector (o por sub-cajas si el detector las da); para manuscritos, el tachado cubre siempre la **línea completa** del dato.
  - Líneas ilegibles en contexto personal → tachado completo propuesto.
  - Firmas: detector de región de firma (trazos sin texto legible junto a "Firma/Fdo.") → tachado propuesto.
- **IA de datos personales** (`pii_model.py`): GLiNER-PII sobre texto nativo + OCR, con tipos: persona, dirección, teléfono, email, documento de identidad, cuenta bancaria, fecha de nacimiento, matrícula, organización (opcional), dato de salud. Fusión con reglas: la regla validada fija el tipo y da confianza alta; GLiNER amplía cobertura.
- **Revisor LLM** (`llm_review.py`, paquete avanzado): segunda pasada por página con el texto ya pseudonimizado alrededor; pide "lista literal de fragmentos que identifiquen a una persona y no estén ya marcados". Cada fragmento se busca en el texto; si no aparece literal, se descarta (evita alucinaciones). Los hallazgos entran con confianza media, para revisión.
- Todo configurable: "sin IA avanzada" sigue funcionando con reglas + GLiNER + OCR impreso.
- **Reglas** (`rules.py`), portadas y corregidas:
  - Direcciones abreviadas (`C/`, `Avda.`, `Pza.`, `Ctra.`…) + CP + piso/puerta; sin tachar la etiqueta.
  - Teléfonos 3-2-2-2, `(+34)`, `0034`, internacionales con etiqueta.
  - NSS con dígito de control; 12 dígitos sin validar solo con contexto.
  - Pasaporte, IBAN extranjero, BIC, CCC, IP, nº colegiado, historia clínica, expediente (con contexto).
  - Clave canónica de tokens (`12345678Z` = `12.345.678-Z`).
  - Diccionarios INE ampliados (incl. gallego, catalán, euskera) como apoyo al NER.
- **Propagación** (`propagate.py`): todo valor detectado se busca en todo el documento y en el OCR con sus variantes (sin tildes, solo apellidos, iniciales + apellido).
- **Rostros** (`faces.py`): YuNet sobre render completo y sobre cada imagen, en mosaicos con solape y varias escalas; NMS; margen amplio.
- **Hecho cuando:** los casos fallidos de la revisión pasan, fixtures 13 y 22 detectados, y en el conjunto de evaluación se alcanza un *recall* objetivo por categoría (propuesta: ≥ 98 % en identificadores, ≥ 95 % en nombres impresos, medir y fijar objetivo realista para manuscritos tras la primera ronda).

### Fase 5 · Interfaz
- Adaptar `ui/` al puente Python: seleccionar archivos o **carpetas** con diálogos nativos, cola con progreso por documento (procesado en segundo plano, UI siempre fluida), vista previa renderizada desde los bytes finales, tabla editable, ocultación manual, resultado de la verificación visible ("0 coincidencias en N objetos / M páginas").
- Sin vista previa del original en la columna anonimizada mientras carga.
- Registros CSV/JSON: sin originales ni coordenadas por defecto; advertencia explícita si se incluyen.
- Nada se escribe en disco salvo lo que el usuario exporta: temporales en memoria; si hacen falta ficheros temporales, en una carpeta propia que se borra al cerrar (y al arrancar, por si hubo un cierre brusco). Los registros de la app (logs) nunca contienen valores detectados ni texto de documentos.
- Estadísticas que se actualizan al marcar/desmarcar; atajos de teclado para revisar rápido (siguiente hallazgo, aceptar, descartar).
- Entrada también de imágenes (JPG, PNG, TIFF multipágina, fotos de móvil con corrección de perspectiva), convertidas a PDF internamente: los documentos manuscritos suelen llegar así.
- Exportación por lotes a una carpeta de destino, con informe de verificación por archivo.
- **Hecho cuando:** los e2e (pywebview en modo test o motor sin UI) cubren el flujo completo.

### Fase 6 · Empaquetado e instalación fácil
- `packaging/build.ps1`: `uv sync` → PyInstaller onedir (con modelos ligeros y `llama-server` Vulkan) → Inno Setup → `AnonimatoSetup-x.y.z.exe`.
- Paquete de IA avanzada: manifiesto firmado (URL + SHA-256 + licencia de cada GGUF), descarga desde el origen oficial de cada modelo (Hugging Face) con reanudación, o importación desde un `.zip` para equipos sin conexión.
- Instalación por usuario, sin admin; acceso directo; desinstalador limpio; comprobación de WebView2 (con instalador de arranque incluido por si falta).
- Arranque sin consola; si DirectML falla, CPU automáticamente.
- Opcional: firma de código (evita el aviso de SmartScreen); si no, documentar "Más información → Ejecutar de todas formas".
- THIRD_PARTY.md con versiones, licencias y SHA-256 de cada modelo; comprobación de hashes al arrancar.
- **Hecho cuando:** en una cuenta limpia de Windows, instalar → abrir → anonimizar → desinstalar funciona sin tocar nada más.

### Fase 7 · Retirada de la versión web
- Cuando haya paridad: eliminar `legacy-web/`, `vendor/`, `node_modules`, `package.json`, `start.ps1`.
- `git init`, `.gitignore` (`.venv/`, `build/`, `dist/`, `tmp/`, `opencode.json`), README nuevo.

---

## 3. Orden y criterio global

| # | Entrega | Resultado visible |
|---|---|---|
| 0 | Esqueleto + corpus | La app abre; los tests muestran las fugas actuales. |
| 1 | Borrado + limpieza | PDFs sin metadatos, estructuras ocultas ni anotaciones. |
| 2 | Verificación | Ningún PDF con fugas puede salir de la app. |
| 3 | Máxima seguridad | Garantía total sobre todo lo no visible. |
| 4 | Detección | Mejor OCR, NER, caras y reglas; métricas reales. |
| 5 | Interfaz | Uso diario cómodo, carpetas, procesado en segundo plano. |
| 6 | Instalador | `AnonimatoSetup.exe` de un clic. |
| 7 | Limpieza | Un solo proyecto, versionado en git. |

## 4. Hallazgos de la revisión inicial y dónde se resuelven

| Hallazgo en la versión web | Fase |
|---|---|
| XMP y fechas sobreviven (confirmado) | 1 |
| Opción "Pixelar" sin efecto en el PDF | 1 |
| Texto fuera del CropBox no se tacha | 1 (+3) |
| Cajas estimadas por nº de caracteres en fuentes proporcionales | 1 (quads exactos) |
| Anotaciones FreeText/Stamp/Ink nunca analizadas y luego integradas | 1 (bake antes de detectar) |
| Nombre del archivo de salida conserva el nombre original | 1 |
| Line art parcialmente cubierto no se borra | 3 |
| Direcciones abreviadas, teléfonos 3-2-2-2, NSS sin validar | 4 |
| Tokens distintos para el mismo DNI con distinto formato | 4 |
| BlazeFace pierde caras pequeñas | 4 |
| OCR descarta palabras de baja confianza y no cruza líneas | 4 |
| Vista previa muestra el original mientras carga; estadísticas no se actualizan | 5 |
| Código muerto, pdf-lib sin uso, LICENSE sobrescrito, README incoherente, sin git | 7 |

## 5. Decisiones pendientes y riesgos

- **Necesito de ti:** 30–50 páginas reales representativas para la fase 4.0 (se quedan en tu equipo, fuera del repositorio).
- **Modelos concretos** (VLM, LLM, GLiNER): se deciden con el benchmark, no antes.
- **Firma de código:** sin certificado, Windows muestra un aviso la primera vez. Un certificado cuesta dinero al año; opcional.
- **Riesgo – velocidad:** manuscritos con VLM ≈ 10–40 s/página (estimación, a medir). Mitigación: solo se envían al VLM las líneas manuscritas o dudosas.
- **Riesgo – manuscritos ilegibles:** ningún modelo los leerá todos. Mitigación: regla de tachado ante la duda.
- **Riesgo – soporte en llama.cpp/Vulkan** de un VLM concreto. Mitigación: el benchmark solo considera modelos que funcionen; alternativa ONNX si hiciera falta.
- **Riesgo – PDF hostiles** (el motor abre archivos no confiables). Mitigación: procesado en un proceso hijo con límites de memoria/tiempo, que se reinicia si falla.

**Límite honesto:** la garantía de "ni rastro" es absoluta sobre lo marcado (fases 1–2) y sobre todo lo no visible (fase 3). Lo que ninguna detección encuentre ni el usuario marque seguirá visible; la revisión humana página a página sigue siendo obligatoria y la UI la facilita, no la sustituye.
