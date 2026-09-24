"""Handwriting transcription of single text lines with the local vision-language model.

The detector decides *where* the line is; the model only reads it. A hallucinated
transcription can never move a redaction box.
"""
from __future__ import annotations

import numpy as np

from ..llm_server import LlamaServer, image_part

PROMPT = (
    "Transcribe literalmente el texto de esta imagen (una sola línea, puede estar escrita a mano). "
    "No corrijas la ortografía, no completes palabras y no añadas nada. "
    "Si algún fragmento no se puede leer, escribe [ilegible] en su lugar. "
    "Responde únicamente con la transcripción."
)
ILLEGIBLE = "[ilegible]"


class HandwritingReader:
    def __init__(self, server: LlamaServer):
        self.server = server

    def read(self, crop: np.ndarray) -> str:
        h, w = crop.shape[:2]
        pad = max(4, h // 5)
        canvas = np.full((h + 2 * pad, w + 2 * pad, 3), 255, dtype=np.uint8)
        canvas[pad:pad + h, pad:pad + w] = crop
        if canvas.shape[0] < 64:  # tiny crops are enlarged for the vision encoder
            factor = 64 / canvas.shape[0]
            from PIL import Image
            canvas = np.asarray(Image.fromarray(canvas).resize((int(canvas.shape[1] * factor), 64)))
        text = self.server.chat([{"role": "user", "content": [image_part(canvas), {"type": "text", "text": PROMPT}]}],
                                max_tokens=160)
        text = text.strip().strip('"').strip()
        return " ".join(text.split())
