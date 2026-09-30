"""Regression checks for CPU selection and GPU fallback without loading models."""
from types import SimpleNamespace
from unittest.mock import Mock

from app.engine import onnx_runtime
from app.engine.ocr import detect
from app.engine.ocr.engine import OcrEngine


def test_explicit_cpu_overrides_cached_gpu(monkeypatch):
    monkeypatch.setattr(onnx_runtime, "_gpu_ok", True)
    assert not onnx_runtime.gpu_available(False)
    monkeypatch.setenv("ANONIMATO_CPU", "1")
    assert not onnx_runtime.gpu_available(True)


def test_cpu_warmup_does_not_run_gpu_shapes():
    engine = OcrEngine.__new__(OcrEngine)
    run = Mock()
    engine.detector = SimpleNamespace(on_gpu=False, session=SimpleNamespace(run=run))
    engine.warm_up()
    run.assert_not_called()


def test_cpu_detector_loads_only_mobile_model(monkeypatch):
    monkeypatch.setattr(onnx_runtime, "_gpu_ok", True)
    model = Mock(side_effect=lambda name: SimpleNamespace(path=name))
    runtime = Mock(return_value=SimpleNamespace(get_inputs=lambda: [SimpleNamespace(name="input")],
                                               get_providers=lambda: ["CPUExecutionProvider"]))
    monkeypatch.setattr(detect.models, "model", model)
    monkeypatch.setattr(detect, "session", runtime)
    detector = detect.LineDetector(use_gpu=False)
    model.assert_called_once_with("ocr-det-mobile")
    runtime.assert_called_once_with("ocr-det-mobile", False)
    assert not detector.on_gpu
    assert detector.max_side == 1600


def test_unavailable_gpu_session_falls_back_to_mobile(monkeypatch):
    monkeypatch.setattr(onnx_runtime, "gpu_available", lambda use_gpu: True)
    monkeypatch.setattr(detect.models, "model", lambda name: SimpleNamespace(path=name))
    runtime = Mock(return_value=SimpleNamespace(get_inputs=lambda: [SimpleNamespace(name="input")],
                                               get_providers=lambda: ["CPUExecutionProvider"]))
    monkeypatch.setattr(detect, "session", runtime)
    detector = detect.LineDetector(use_gpu=True)
    assert runtime.call_args_list[0].args == ("ocr-det", True)
    assert runtime.call_args_list[1].args == ("ocr-det-mobile", False)
    assert not detector.on_gpu
    assert detector.max_side == 1600
