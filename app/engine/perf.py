"""Performance log: one JSON line per analysis or export, to find where the time goes.

Only timings and settings are written: never file names, document text or detected values.
The file lives in the user data folder and is rotated at ``MAX_BYTES``.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
_write_lock = threading.Lock()


def log_path() -> Path:
    """``ANONIMATO_PERF_LOG`` points the log elsewhere (the tests keep it out of the user profile)."""
    override = os.environ.get("ANONIMATO_PERF_LOG")
    if override:
        return Path(override)
    from .system import user_data_dir
    return user_data_dir() / "logs" / "rendimiento.jsonl"


class StageTimer:
    """Wall time per pipeline stage, measured between the progress events of one operation."""

    def __init__(self) -> None:
        self.started = time.perf_counter()
        self._last = self.started
        self._stage = "inicio"
        self.stages: dict[str, float] = {}
        self.pages = 0

    def event(self, event: dict) -> None:
        now = time.perf_counter()
        self.stages[self._stage] = self.stages.get(self._stage, 0.0) + now - self._last
        self._stage, self._last = str(event.get("stage") or "otro"), now
        self.pages = max(self.pages, int(event.get("total") or 0))

    def finish(self) -> dict:
        now = time.perf_counter()
        self.stages[self._stage] = self.stages.get(self._stage, 0.0) + now - self._last
        self._last = now
        ordered = sorted(self.stages.items(), key=lambda item: -item[1])
        return {"segundos": round(now - self.started, 3),
                "etapas": {name: round(seconds, 3) for name, seconds in ordered if seconds >= 0.001}}


def options_summary(options) -> dict:
    return {"ocr": options.ocr, "ia": options.ai, "manuscrito": options.handwriting, "revision_ia": options.llm_review,
            "rostros": options.faces, "firmas": options.signatures, "ppp": options.dpi, "modelo_avanzado": options.advanced_mode,
            "maxima_seguridad": options.max_security, "categorias": len(options.categories)}


def record(operation: str, timer: StageTimer, *, options=None, size_bytes: int = 0, pages: int = 0,
           engine: dict | None = None, error: BaseException | None = None, path: Path | None = None) -> None:
    """Append one entry. Logging must never interrupt the user's work, so failures are ignored."""
    entry = {"fecha": datetime.now(UTC).isoformat(timespec="seconds"), "operacion": operation,
             **timer.finish(), "paginas": pages or timer.pages, "tamano_mb": round(size_bytes / 1048576, 2),
             "resultado": type(error).__name__ if error else "ok"}
    if options is not None:
        entry["ajustes"] = options_summary(options)
    if isinstance(engine, dict):
        entry["motor"] = {key: engine[key] for key in ("gpu", "backends", "timings", "peak_memory_mb") if key in engine}
    target = path or log_path()
    try:
        with _write_lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.stat().st_size > MAX_BYTES:
                target.replace(target.with_suffix(".jsonl.1"))
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
