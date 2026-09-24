# Componentes de terceros

Todos los componentes se ejecutan localmente. Los modelos se descargan solo desde su origen oficial
y se comprueban con SHA-256 fijados en `models/manifest.json` (también al arrancar la aplicación).

| Componente | Uso | Licencia | Origen |
|---|---|---|---|
| PyMuPDF / MuPDF | lectura, extracción, tachado destructivo, renderizado | AGPL-3.0 | pypi `pymupdf` |
| pikepdf / qpdf | limpieza estructural y verificación objeto a objeto | MPL-2.0 / Apache-2.0 | pypi `pikepdf` |
| pywebview + WebView2 | ventana nativa | BSD-3 / Microsoft | pypi `pywebview` |
| ONNX Runtime (DirectML) | inferencia en GPU sin CUDA | MIT | pypi `onnxruntime-directml` |
| OpenCV | detección de rostros (YuNet), imagen | Apache-2.0 | pypi `opencv-python-headless` |
| tokenizers, regex, rapidfuzz, NumPy, Pillow, PyYAML | utilidades | Apache-2.0 / Apache-2.0 / MIT / BSD / HPND / MIT | pypi |
| llama.cpp (build Vulkan b11166) | motor de la IA avanzada | MIT | github.com/ggml-org/llama.cpp |
| PP-OCRv5 server det, PP-OCRv5 mobile det, latin PP-OCRv5 mobile rec, PP-LCNet doc orientation | OCR | Apache-2.0 | huggingface.co/PaddlePaddle |
| GLiNER multi PII v1 (ONNX fp16) | IA de datos personales | Apache-2.0 | huggingface.co/onnx-community/gliner_multi_pii-v1 (base: urchade/gliner_multi_pii-v1) |
| YuNet 2023mar | rostros | MIT | github.com/opencv/opencv_zoo |
| Qwen3-VL-4B-Instruct (GGUF Q4_K_M + mmproj Q8_0) | manuscritos y revisión contextual (paquete avanzado) | Apache-2.0 | huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF |

Modelos evaluados y no incluidos por defecto (ver `docs/benchmark.md`): Qwen3-VL-8B-Instruct (Apache-2.0),
PaddleOCR-VL 1.6 (Apache-2.0).

Datos de evaluación (no se distribuyen): Teklia/IAM-line (MIT en Hugging Face; datos IAM con licencia de
investigación), agomberto/FrenchCensus-handwritten-texts (MIT). Imágenes de prueba de caras:
OpenCV `samples/data` (lena.jpg), solo para tests.
