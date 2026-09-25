"""ONNX Runtime sessions with DirectML (any Windows GPU) and CPU fallback."""
from __future__ import annotations

import threading

import onnxruntime as ort

ort.set_default_logger_severity(3)
_lock = threading.Lock()
_gpu_ok: bool | None = None


def session(path: str, use_gpu: bool = True, cpu_basic: bool = False) -> ort.InferenceSession:
    global _gpu_ok
    options = ort.SessionOptions()
    options.log_severity_level = 3
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    providers = ["CPUExecutionProvider"]
    with _lock:
        want_gpu = use_gpu and _gpu_ok is not False and "DmlExecutionProvider" in ort.get_available_providers()
    if want_gpu:
        try:
            options.enable_mem_pattern = False
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            created = ort.InferenceSession(path, sess_options=options, providers=["DmlExecutionProvider", "CPUExecutionProvider"])
            with _lock:
                _gpu_ok = True
            return created
        except Exception:  # noqa: BLE001 - driver problems: fall back to CPU for the rest of the session
            with _lock:
                _gpu_ok = False
    if cpu_basic:
        # Some fp16 graphs break under the full CPU optimiser.
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    return ort.InferenceSession(path, sess_options=options, providers=providers)


def gpu_active() -> bool:
    return bool(_gpu_ok)


def gpu_available(use_gpu: bool = True) -> bool:
    """GPU in use, or usable and not yet tried."""
    if _gpu_ok is not None:
        return _gpu_ok
    return use_gpu and "DmlExecutionProvider" in ort.get_available_providers()
