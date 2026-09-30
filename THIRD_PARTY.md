# Third-party components

All components run locally. Models are downloaded only from their official sources and checked against the SHA-256 hashes in `models/manifest.json`, including at application startup.

| Component | Use | License | Source |
|---|---|---|---|
| PyMuPDF / MuPDF | PDF reading, text extraction, destructive redaction, rendering | AGPL-3.0 | PyPI `pymupdf` |
| pikepdf / qpdf | Structural cleanup and object-level verification | MPL-2.0 / Apache-2.0 | PyPI `pikepdf` |
| pywebview + WebView2 | Native application window | BSD-3 / Microsoft | PyPI `pywebview` |
| ONNX Runtime (DirectML) | GPU inference without CUDA | MIT | PyPI `onnxruntime-directml` |
| OpenCV | Face detection (YuNet) and image processing | Apache-2.0 | PyPI `opencv-python-headless` |
| tokenizers, regex, rapidfuzz, NumPy, Pillow, PyYAML | Utilities | Apache-2.0 / Apache-2.0 / MIT / BSD / HPND / MIT | PyPI |
| llama.cpp (Vulkan build b11166) | Advanced AI runtime | MIT | github.com/ggml-org/llama.cpp |
| PP-OCRv5 server det, PP-OCRv5 mobile det, Latin PP-OCRv5 mobile rec, PP-LCNet document orientation | OCR | Apache-2.0 | huggingface.co/PaddlePaddle |
| GLiNER multi PII v1 (ONNX fp16) | Personal-data detection | Apache-2.0 | huggingface.co/onnx-community/gliner_multi_pii-v1 (base: urchade/gliner_multi_pii-v1) |
| YuNet 2023mar | Face detection | MIT | github.com/opencv/opencv_zoo |
| Qwen3-VL-8B-Instruct (GGUF Q4_K_M + mmproj Q8_0) | Handwriting and contextual review (advanced package, GPU with at least 7 GB free) | Apache-2.0 | huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF |
| Qwen3-VL-4B-Instruct (GGUF Q4_K_M + mmproj Q8_0) | Smaller advanced package for lower-memory GPUs | Apache-2.0 | huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF |

Evaluated but not included (see [docs/benchmark.md](docs/benchmark.md)): PaddleOCR-VL 1.6 (Apache-2.0). It is the fastest option tested, but only performs OCR and reads handwritten names less accurately than Qwen3-VL-8B; it cannot perform contextual review.

Evaluation data is not distributed: Teklia/IAM-line (MIT on Hugging Face; IAM data has a research license) and agomberto/FrenchCensus-handwritten-texts (MIT). The OpenCV `samples/data/lena.jpg` face image is used only in tests.
