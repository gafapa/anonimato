"""Lazily loaded AI services shared by the whole application."""
from __future__ import annotations

import threading
import time

from . import llm_server, models


class WarmupTimeout(RuntimeError):
    pass


class Services:
    def __init__(self, use_gpu: bool = True):
        self.use_gpu = use_gpu
        self._lock = threading.RLock()
        self._ocr = None
        self._pii = None
        self._faces = None
        self._llm = None
        self.errors: dict[str, str] = {}
        self._integrity_checked = threading.Event()
        self._ready = threading.Event()
        self._ready.set()  # only cleared while a warm-up is running

    def _load(self, name: str, factory):
        with self._lock:
            current = getattr(self, f"_{name}")
            if current is None and name not in self.errors:
                try:
                    current = factory()
                    setattr(self, f"_{name}", current)
                except Exception as error:
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
            try:
                if not self.check_integrity():
                    return
                engine = self.ocr()
                if engine is not None:
                    try:
                        engine.warm_up()
                    except Exception:
                        pass
                self.pii()
                self.faces()
            finally:
                self._ready.set()
        self._ready.clear()
        threading.Thread(target=run, daemon=True).start()

    def check_integrity(self, force: bool = False) -> bool:
        """SHA-256 of every model and runtime file against the pinned manifest.

        A failed or incomplete check blocks processing. Disk metadata is not proof of integrity.
        """
        try:
            bad = models.verify_all(force=force)
        except Exception as error:
            self.errors["integrity"] = f"No se pudo comprobar la integridad: {error}"
            return False
        finally:
            self._integrity_checked.set()
        if bad:
            self.errors["integrity"] = "Archivos alterados o dañados: " + ", ".join(bad)
        else:
            self.errors.pop("integrity", None)
        return not bad

    def require_integrity(self, progress=None, timeout: float = 300) -> None:
        """Block until the integrity check and the warm-up have run; refuse to work with altered models.

        (GPU sessions must not be used by the warm-up thread and an analysis at the same time.)
        If the warm-up does not finish in time (a GPU driver that stopped responding), a
        ``WarmupTimeout`` is raised so the engine can restart on the CPU."""
        waited = 0.0
        while not self._ready.wait(5):
            waited += 5
            if progress:
                progress({"stage": "prepare", "message": "Preparando los modelos de IA…"})
            if waited >= timeout:
                raise WarmupTimeout("La tarjeta gráfica no responde al preparar los modelos")
        if not self._integrity_checked.is_set():
            self.check_integrity()
        if "integrity" in self.errors:
            raise RuntimeError(self.errors["integrity"] + ". Reinstala la aplicación o la IA avanzada.")

    def reset_advanced(self) -> None:
        with self._lock:
            if self._llm is not None:
                self._llm.stop()
            self._llm = None
            self.errors.pop("llm", None)

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
        from .onnx_runtime import gpu_available
        return {
            "base": models.group_installed("base"),
            "advanced": self.advanced_available(),
            "gpu": gpu_available(self.use_gpu),
            "errors": dict(self.errors),
        }
