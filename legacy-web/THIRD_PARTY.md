# Third-party runtime assets

The files under `vendor/` are served locally so documents never require a third-party runtime connection.

| Component | Version | Source |
| --- | --- | --- |
| PDF.js | 6.3.289 | `pdfjs-dist` npm package |
| pdf-lib | 1.17.1 | `pdf-lib` npm package |
| MediaPipe Tasks Vision | 1.0.1 | `@mediapipe/tasks-vision` npm package |
| Tesseract.js | 7.0.0 | `tesseract.js` npm package |
| Spanish OCR data | 1.0.0 | `@tesseract.js-data/spa` npm package |
| English OCR data | 1.0.0 | `@tesseract.js-data/eng` npm package |
| MuPDF.js | 1.28.1 | `mupdf` npm package, AGPL-3.0-or-later |
| BlazeFace short-range model | MediaPipe asset | `https://storage.googleapis.com/mediapipe-assets/blaze_face_short_range.tflite` |

The SHA-256 checksum of `vendor/mediapipe/blaze_face_short_range.tflite` is:

```text
B4578F35940BF5A1A655214A1CCE5CAB13EBA73C1297CD78E1A04C2380B0152F
```

Review upstream licenses and release notes before redistributing or updating these assets.
