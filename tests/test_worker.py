"""Isolated engine process: a hostile document can crash, hang or exhaust memory without
taking the application down, and the engine recovers for the next document."""
import pytest

from app.engine.worker import EngineCrashed, EngineError, EngineProcess, EngineTimeout


@pytest.fixture
def light():
    engine = EngineProcess(with_models=False, use_gpu=False, memory_limit_mb=1024, stall_seconds=5)
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


def test_memory_limit(light):
    with pytest.raises(EngineError):
        light.call("_test_alloc", 3000)  # 3 GB with a 1 GB limit
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
