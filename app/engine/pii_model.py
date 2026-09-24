"""GLiNER-PII (multilingual, zero-shot NER for personal data) running on ONNX Runtime.

Pre/post-processing re-implemented from the GLiNER span model ("markerV0") so that
no PyTorch is needed.
"""
from __future__ import annotations

import json

import numpy as np
import regex as re
from tokenizers import Tokenizer

from . import models
from .onnx_runtime import session
from .rules import Match

WORD_RE = re.compile(r"\w+(?:[-_’']\w+)*|\S")

# English labels (training language of the model) -> our categories.
LABELS = {
    "person": "name",
    "address": "address",
    "phone number": "phone",
    "email": "email",
    "passport number": "passport",
    "identity card number": "id_other",
    "social security number": "nss",
    "bank account number": "iban",
    "credit card number": "card",
    "date of birth": "date",
    "license plate number": "plate",
    "ip address": "ip",
    "medical condition": "health",
    "medication": "health",
    "health insurance id number": "id_other",
    "tax identification number": "id_other",
    "username": "other",
    "organization": "org",
}
MAX_WORDS = 180
OVERLAP = 30


class PiiModel:
    def __init__(self, use_gpu: bool = True, threshold: float = 0.5):
        config = json.loads(models.model("pii-config").path.read_text(encoding="utf-8"))
        self.max_width = int(config.get("max_width", 12))
        self.ent = config.get("ent_token", "<<ENT>>")
        self.sep = config.get("sep_token", "<<SEP>>")
        self.tokenizer = Tokenizer.from_file(str(models.model("pii-tokenizer").path))
        self.tokenizer.no_truncation()
        self.session = session(str(models.model("pii-model").path), use_gpu, cpu_basic=True)
        self.threshold = threshold
        self.labels = list(LABELS)
        prompt = []
        for label in self.labels:
            prompt += [self.ent, label]
        prompt.append(self.sep)
        self.prompt = prompt

    def _run(self, words: list[str]) -> list[tuple[int, int, str, float]]:
        encoding = self.tokenizer.encode(self.prompt + words, is_pretokenized=True)
        ids = np.array([encoding.ids], dtype=np.int64)
        attention = np.array([encoding.attention_mask], dtype=np.int64)
        words_mask = np.zeros_like(ids)
        prompt_len = len(self.prompt)
        seen = set()
        for position, word_id in enumerate(encoding.word_ids):
            if word_id is None or word_id < prompt_len or word_id in seen:
                continue
            seen.add(word_id)
            words_mask[0, position] = word_id - prompt_len + 1
        n = len(words)
        spans = np.array([[[i, i + j] for i in range(n) for j in range(self.max_width)]], dtype=np.int64)
        span_mask = spans[..., 1] < n
        spans = np.where(span_mask[..., None], spans, 0)
        logits = self.session.run(["logits"], {
            "input_ids": ids, "attention_mask": attention, "words_mask": words_mask,
            "text_lengths": np.array([[n]], dtype=np.int64), "span_idx": spans, "span_mask": span_mask,
        })[0][0]
        probs = 1 / (1 + np.exp(-logits))  # (n, max_width, classes)
        found = []
        for i, j, c in zip(*np.where(probs > self.threshold)):
            if i + j < n:
                found.append((int(i), int(i + j), self.labels[int(c)], float(probs[i, j, c])))
        found.sort(key=lambda item: -item[3])
        kept: list[tuple[int, int, str, float]] = []
        for item in found:
            if all(item[1] < k[0] or item[0] > k[1] for k in kept):
                kept.append(item)
        return kept

    def detect(self, text: str) -> list[Match]:
        tokens = [(m.start(), m.end(), m.group()) for m in WORD_RE.finditer(text)]
        results: dict[tuple[int, int], Match] = {}
        start = 0
        while start < len(tokens):
            window = tokens[start:start + MAX_WORDS]
            words = [w for _, _, w in window]
            for i, j, label, prob in self._run(words):
                begin, end = window[i][0], window[j][1]
                kind = LABELS[label]
                key = (begin, end)
                if key not in results or results[key].confidence < prob:
                    results[key] = Match(begin, end, kind, text[begin:end], round(min(0.95, prob), 3),
                                         prio=400, source="ai", extra={"label": label})
            if start + MAX_WORDS >= len(tokens):
                break
            start += MAX_WORDS - OVERLAP
        return sorted(results.values(), key=lambda m: m.start)
