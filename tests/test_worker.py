"""Isolated engine process: a hostile document can crash, hang or exhaust memory without
taking the application down, and the engine recovers for the next document."""
import sys

import pytest

from app.engine.worker import EngineCrashed, EngineError, EngineProcess, EngineTimeout


@pytest.fixture
def light():
    engine = EngineProcess(with_models=False, use_gpu=False, memory_limit_mb=2048, stall_seconds=5)
    yield engine
    engine.stop()


def _blank_pdf() -> bytes:
    import pymupdf
    doc = pymupdf.open()
    doc.new_page()
    return doc.tobytes()


def test_crash_is_contained_and_recovered(light):
    first = light.call("ping")
    with pytest.raises(EngineCrashed):
        light.call("_test_crash")
    second = light.call("ping")
    assert second != first  # a fresh process
    assert light.call("page_png", _blank_pdf(), 0, 200)[:4] == b"\x89PNG"


def test_hang_is_stopped_by_the_watchdog(light):
    with pytest.raises(EngineTimeout):
        light.call("_test_hang", 60)
    assert light.call("ping") > 0


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS no aplica RLIMIT_AS; allí protege el vigilante de bloqueos")
def test_memory_limit(light):
    with pytest.raises(EngineError):
        light.call("_test_alloc", 4000)  # 4 GB with a 2 GB limit
    assert light.call("ping") > 0


def test_damaged_pdf_reports_error_not_crash(light):
    with pytest.raises(EngineError) as error:
        light.call("page_png", b"%PDF-1.7\n1 0 obj << /Type /Catalog >>\n%%EOF garbage", 0, 200)
    assert not isinstance(error.value, EngineTimeout)
    assert light.call("ping") > 0


def test_wrong_password(light):
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secreto")
    locked = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="clave")
    with pytest.raises(EngineError):
        light.call("unlock", locked, "mala")
    unlocked = light.call("unlock", locked, "clave")
    assert not pymupdf.open("pdf", unlocked).needs_pass


def test_gpu_hang_falls_back_to_cpu(monkeypatch):
    """If the engine stalls during an analysis on the GPU, it restarts on the CPU and retries."""
    engine = EngineProcess(with_models=False, use_gpu=True, stall_seconds=3)
    engine.with_models = True  # behave like the model engine for the fallback logic
    calls = []
    original = engine._call

    def fake(op, *args, **kwargs):
        calls.append(engine.use_gpu)
        if engine.use_gpu:
            raise EngineTimeout("sin respuesta")
        return original("ping")

    monkeypatch.setattr(engine, "_call", fake)
    try:
        assert engine.call("analyze", b"", "x.pdf", None) > 0
        assert calls == [True, False] and engine.gpu_disabled
    finally:
        engine.stop()
