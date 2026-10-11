"""Lazily loaded AI services shared by the whole application."""
from __future__ import annotations

import threading
import time
from filelock import Timeout

from . import llm_server, models

MAX_INTEGRITY_WAIT_SECONDS = 300


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
        self.advanced_mode = "auto"
        self.timings: dict[str, float] = {}
        self.errors: dict[str, str] = {}
        self._integrity_checked = threading.Event()
        self._ready = threading.Event()
        self._ready.set()  # only cleared while a warm-up is running

    def _load(self, name: str, factory):
        with self._lock:
            current = getattr(self, f"_{name}")
            if current is None and name not in self.errors:
                try:
                    started = time.perf_counter()
                    current = factory()
                    setattr(self, f"_{name}", current)
                    self.timings[f"load_{name}"] = round(time.perf_counter() - started, 4)
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
        """Check startup integrity without loading services that the next operation may not need."""
        def run() -> None:
            try:
                if not self.check_integrity():
                    return
            finally:
                self._ready.set()
        self._ready.clear()
        threading.Thread(target=run, daemon=True).start()

    def prepare(self, options, *, export: bool = False) -> None:
        if self.advanced_mode != options.advanced_mode:
            self.reset_advanced()
            self.advanced_mode = options.advanced_mode
        if export or options.ocr:
            self.ocr()
        if export or options.ai:
            self.pii()
        if options.faces and not export:
            self.faces()

    def check_integrity(self, force: bool = False, progress=None) -> bool:
        """SHA-256 of every model and runtime file against the pinned manifest.

        A failed or incomplete check blocks processing. Disk metadata is not proof of integrity.
        """
        started = time.perf_counter()
        try:
            lock = models.installation_lock()
            while True:
                try:
                    guard = lock.acquire(timeout=1)
                    break
                except Timeout:
                    if time.perf_counter() - started >= MAX_INTEGRITY_WAIT_SECONDS:
                        raise
                    if progress:
                        progress({"stage": "prepare", "message": "Esperando a que termine otra comprobación o instalación de modelos…"})
            with guard:
                bad = models.verify_all(force=force)
        except Timeout:
            self.errors["integrity"] = "Otro proceso sigue utilizando los modelos. Espera a que termine y vuelve a intentarlo"
            return False
        except Exception as error:
            self.errors["integrity"] = f"No se pudo comprobar la integridad: {error}"
            return False
        finally:
            self._integrity_checked.set()
            self.timings["integrity"] = round(time.perf_counter() - started, 4)
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
        if progress:
            progress({"stage": "prepare", "message": "Comprobando la integridad de los modelos…"})
        self.check_integrity(force=True, progress=progress)
        if "integrity" in self.errors:
            raise RuntimeError(self.errors["integrity"] + ". Procesamiento bloqueado hasta completar la comprobación de integridad.")

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
        return self._load("llm", lambda: llm_server.LlamaServer.default(use_gpu=self.use_gpu, mode=self.advanced_mode))

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
            "timings": dict(self.timings),
            "backends": {
                "ocr": ("GPU / reconocimiento CPU" if self._ocr.detector.on_gpu else "CPU") if self._ocr else "Sin cargar",
                "pii": "/".join(self._pii.session.get_providers()) if self._pii else "Sin cargar",
                "faces": "CPU" if self._faces else "Sin cargar",
                "advanced": self._llm.execution_status() if self._llm else "Sin cargar",
            },
        }
