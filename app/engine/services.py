"""Lazily loaded AI services shared by the whole application."""
from __future__ import annotations

import threading
import time

from . import llm_server, models


class Services:
    def __init__(self, use_gpu: bool = True):
        self.use_gpu = use_gpu
        self._lock = threading.RLock()
        self._ocr = None
        self._pii = None
        self._faces = None
        self._llm = None
        self.errors: dict[str, str] = {}

    def _load(self, name: str, factory):
        with self._lock:
            current = getattr(self, f"_{name}")
            if current is None and name not in self.errors:
                try:
                    current = factory()
                    setattr(self, f"_{name}", current)
                except Exception as error:  # noqa: BLE001
                    self.errors[name] = str(error)
            return current

    def ocr(self):
        from .ocr.engine import OcrEngine
        return self._load("ocr", lambda: OcrEngine(self.use_gpu))

    def pii(self):
        from .pii_model import PiiModel
        return self._load("pii", lambda: PiiModel(self.use_gpu))

    def faces(self):
        from .faces import FaceDetector
        return self._load("faces", FaceDetector)

    def warm_up(self) -> None:
        """Load models and compile GPU graphs in the background so the first document is fast."""
        def run() -> None:
            self.check_integrity()
            engine = self.ocr()
            if engine is not None:
                try:
                    engine.warm_up()
                except Exception:  # noqa: BLE001
                    pass
            self.pii()
            self.faces()
        threading.Thread(target=run, daemon=True).start()

    def check_integrity(self) -> bool:
        """SHA-256 of every bundled and installed model against the pinned manifest."""
        bad = []
        for group in ("base", "advanced"):
            for item in models.load_manifest().get(group, []):
                if item.path.exists() and item.sha256 and models.sha256_of(item.path) != item.sha256:
                    bad.append(item.id)
        if bad:
            self.errors["integrity"] = "Modelos alterados o dañados: " + ", ".join(bad)
        return not bad

    def advanced_available(self) -> bool:
        return llm_server.available()

    def llm(self):
        if not self.advanced_available():
            return None
        return self._load("llm", llm_server.LlamaServer.default)

    def release_llm_if_idle(self, idle_seconds: float = 300) -> None:
        with self._lock:
            if self._llm is not None and self._llm.running() and time.time() - self._llm.last_used > idle_seconds:
                self._llm.stop()

    def shutdown(self) -> None:
        with self._lock:
            if self._llm is not None:
                self._llm.stop()

    def status(self) -> dict:
        from .onnx_runtime import gpu_active
        return {
            "base": models.group_installed("base"),
            "advanced": self.advanced_available(),
            "gpu": gpu_active(),
            "errors": dict(self.errors),
        }
