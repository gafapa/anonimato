# Anonimato

Aplicación de escritorio para Windows que elimina datos personales, rostros y firmas de documentos PDF,
fotos y escaneos **sin que quede rastro**, ni visible ni recuperable. Todo se procesa en el equipo; no hay
servidor ni se envía ningún documento a ninguna parte.

## Instalación

1. Ejecuta `AnonimatoSetup-2.1.0.exe` (≈ 710 MB). No pide permisos de administrador ni necesita Python ni CUDA.
2. Abre **Anonimato** desde el menú Inicio.
3. (Opcional) En la barra lateral pulsa **Descargar IA avanzada** para leer texto manuscrito y hacer una revisión
   contextual: Qwen3-VL-8B (≈ 5,5 GB) si la tarjeta gráfica tiene ≥ 7 GB libres, o Qwen3-VL-4B (≈ 2,8 GB) si no. Es la única conexión que realiza la aplicación: descarga modelos desde su origen
   oficial y comprueba su SHA-256. En equipos sin Internet usa **Importar paquete sin conexión (.zip)**.

Sin certificado de firma de código, Windows puede mostrar «Windows protegió su PC» la primera vez:
pulsa **Más información → Ejecutar de todas formas**.

## Uso

1. Añade archivos o carpetas (PDF, JPG, PNG, TIFF…) o suéltalos en la ventana.
2. Elige qué anonimizar y pulsa **Analizar documentos**.
3. Revisa cada página: a la izquierda el original con los hallazgos marcados, en el centro el resultado real,
   a la derecha la lista (atajos: ← → páginas, J/K hallazgos, Espacio incluir/excluir, M ocultar zona).
4. **Guardar PDF verificado**: el archivo solo se escribe si la verificación final no encuentra ningún resto.
5. Si vas a compartir el documento fuera, activa **Voy a compartir este documento fuera** (máxima seguridad).

## Cómo garantiza que no queda rastro

- **Detección en capas:** reglas con validación (DNI/NIE/CIF, IBAN y CCC, tarjetas, NSS, teléfonos,
  direcciones, pasaportes, IP…), IA de datos personales (GLiNER-PII), OCR (PP-OCRv5), lectura de manuscritos
  y revisión contextual con un modelo local (Qwen3-VL), rostros (YuNet) y firmas. Cada dato encontrado se
  busca después en todo el documento con sus variantes.
- **Borrado destructivo:** MuPDF elimina el texto, los píxeles de imagen y el dibujo vectorial bajo cada zona;
  se elimina también todo lo que queda fuera de la zona visible de la página.
- **Limpieza estructural:** metadatos (Info y XMP en cualquier objeto), marcadores, etiquetas de accesibilidad
  y textos alternativos, miniaturas, adjuntos, JavaScript, formularios, anotaciones, datos privados de
  aplicaciones, EXIF/XMP dentro de JPEG, revisiones anteriores y objetos huérfanos.
- **Modo máxima seguridad:** cada página se convierte en imagen tras tachar; opcionalmente se añade una capa de
  texto buscable generada por OCR sobre el resultado ya anonimizado.
- **Verificación obligatoria:** sobre los mismos bytes que se guardan: estructura, todos los objetos y flujos
  (varias codificaciones), texto de cada página (incluido invisible, fuera de caja y capas ocultas), OCR de la
  página renderizada y OCR ampliado de cada zona tachada (con relectura por IA de las zonas manuscritas), rostros,
  y detección residual con reglas e IA. Si algo falla, no se guarda nada y el resto se marca en rojo sobre la página.
- **Aislamiento:** cada documento se analiza en un proceso separado con límite de memoria y vigilancia de bloqueos.
  Un PDF dañado o malicioso no puede cerrar ni colgar la aplicación; el motor se reinicia solo.
- **Integridad:** los modelos y el motor de IA se comprueban con SHA-256 al arrancar; si algo está alterado, el
  procesamiento se bloquea y se avisa.
- **PDF con contraseña** (se pide al abrirlos; la salida nunca va cifrada) y **PDF con firma digital** (se avisa de
  que la firma no puede conservarse y se eliminan los datos del firmante).
- **Nombre del archivo:** por defecto `documento-N_anonimizado.pdf`.
- **Registros:** CSV/JSON sin valores originales ni coordenadas salvo que se pidan expresamente.

**Límite honesto:** la garantía es completa sobre lo que se marca y sobre todo lo no visible (modo máxima
seguridad). Lo que ni la detección ni la persona que revisa marcan sigue visible: la revisión página a página
sigue siendo obligatoria.

## Plataformas

Windows es la plataforma principal (instalador probado de principio a fin). macOS y Linux usan el mismo código con
las piezas nativas de cada sistema; sus paquetes se compilan y prueban en GitHub Actions (`.github/workflows/build.yml`).

| | Windows 10/11 x64 | macOS 12+ (Apple Silicon) | Linux x86-64 |
|---|---|---|---|
| Paquete | `AnonimatoSetup-x.y.z.exe` (Inno Setup, sin administrador) | `.dmg` con `Anonimato.app` | `.AppImage` |
| Aceleración de modelos | DirectML (cualquier GPU) | CoreML | CUDA/ROCm si se instala `onnxruntime-gpu`; si no, CPU |
| IA avanzada (llama.cpp) | Vulkan | Metal | Vulkan |
| Límite de memoria del motor aislado | Job Object (motor y llama-server) | vigilante de bloqueos (macOS no aplica límites de memoria por proceso) | `RLIMIT_AS` en el proceso ligero |
| Firma | opcional (aviso SmartScreen) | recomendable: sin firma y notarización hay que abrirla con clic derecho → Abrir | no necesaria |

Compilación local: `packaging/build.ps1` (Windows), `bash packaging/build_macos.sh` (macOS; firma y notarización si
se definen `MACOS_SIGN_IDENTITY`, `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD`), `bash packaging/build_linux.sh` (Linux).

## Desarrollo

Requisitos: [uv](https://docs.astral.sh/uv/) y Python 3.12 (uv lo instala), en Windows, macOS o Linux.

```powershell
uv sync
uv run python tools/fetch_models.py base runtime          # modelos base + llama.cpp (Vulkan)
uv run python tools/fetch_models.py advanced              # IA avanzada (opcional)
uv run python -m tests.fixtures.generate                  # corpus adversarial en tests/fixtures/out
uv run pytest                                             # reglas, fugas, verificación
uv run python -m app                                      # abrir la aplicación
```

- Comparativa de OCR manuscrito: `uv run python tools/benchmark_handwriting.py` → `docs/benchmark.md`.
- Evaluación de la detección (recall/precisión por categoría): `uv run python tools/evaluate_detection.py --scanned`
  → `docs/deteccion.md`. Añade tus documentos anotados en `eval/docs/*.pdf` + `*.json` (no se versionan).
- Prueba de la interfaz real: `uv run python tools/ui_smoke.py`. Autocomprobación del ejecutable:
  `Anonimato.exe --selftest=informe.json`.
  Añade tus propias líneas en `eval/own/*.png` + `eval/own/labels.json` (no se versionan).
- Paquete de IA sin conexión: `uv run python tools/make_offline_pack.py`.
- Instalador: `powershell -File packaging/build.ps1` → `dist/AnonimatoSetup-2.1.0.exe` (requiere Inno Setup 6).

Estructura: `app/engine` (motor), `app/ui` (interfaz), `app/api.py` (puente), `models/manifest.json`
(modelos con SHA-256), `tests/` (corpus adversarial y tests), `packaging/` (PyInstaller + Inno Setup).

## Licencia

GNU Affero General Public License v3.0 o posterior (`AGPL-3.0-or-later`). Ver `LICENSE` y `THIRD_PARTY.md`.
