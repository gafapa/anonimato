"""Performance log: stage timings without names or content."""
import json

from app.engine import perf
from app.engine.types import Options


def test_entries_time_each_stage_without_document_names(tmp_path):
    log = tmp_path / "logs" / "rendimiento.jsonl"
    timer = perf.StageTimer()
    timer.event({"stage": "prepare", "message": "Comprobando la integridad de los modelos…"})
    timer.event({"stage": "page", "page": 1, "total": 3, "message": "Página 1 de 3: nombre-secreto.pdf"})
    perf.record("analisis", timer, options=Options(categories={"name"}), size_bytes=2 * 1048576,
                engine={"gpu": True, "timings": {"integrity": 19.5}, "secret": "x"}, path=log)
    entry = json.loads(log.read_text(encoding="utf-8"))
    assert entry["operacion"] == "analisis" and entry["resultado"] == "ok"
    assert set(entry["etapas"]) <= {"inicio", "prepare", "page"} and entry["paginas"] == 3 and entry["tamano_mb"] == 2.0
    assert entry["ajustes"]["categorias"] == 1 and entry["motor"] == {"gpu": True, "timings": {"integrity": 19.5}}
    assert "secreto" not in log.read_text(encoding="utf-8")


def test_log_rotates_and_never_raises(tmp_path, monkeypatch):
    log = tmp_path / "rendimiento.jsonl"
    log.write_text("x" * 64, encoding="utf-8")
    monkeypatch.setattr(perf, "MAX_BYTES", 10)
    perf.record("guardado", perf.StageTimer(), error=RuntimeError("caído"), path=log)
    assert (tmp_path / "rendimiento.jsonl.1").read_text(encoding="utf-8") == "x" * 64
    assert json.loads(log.read_text(encoding="utf-8"))["resultado"] == "RuntimeError"
    (tmp_path / "file.txt").write_text("", encoding="utf-8")
    perf.record("guardado", perf.StageTimer(), path=tmp_path / "file.txt" / "inside")  # parent is a file: ignored


def test_api_logs_each_analysis(tmp_path, monkeypatch):
    from app.api import Api, Doc
    from tests.test_security import pdf_with_text
    from app.engine import pipeline

    log = tmp_path / "perf.jsonl"
    monkeypatch.setenv("ANONIMATO_PERF_LOG", str(log))
    options = Options(categories={"manual"}, ocr=False, ai=False, faces=False, signatures=False)

    class Engine:
        gpu_disabled = ""

        def ensure_started(self):
            pass

        def stop(self):
            pass

        def call(self, op, *args, progress=None, **kwargs):
            progress({"stage": "page", "page": 1, "total": 1})
            return pipeline.analyze(args[0], args[1], options)

    api = Api(engine=Engine(), light=Engine())
    data = pdf_with_text("FICTITIOUS PERFORMANCE FIXTURE")
    api._state.docs["d1"] = Doc("d1", "privado.pdf", len(data), data)
    api._state.order.append("d1")
    api._status_cache = {"gpu": False, "timings": {"integrity": 0.1}}
    api._run(["d1"], options)
    entry = json.loads(log.read_text(encoding="utf-8"))
    assert entry["operacion"] == "analisis" and entry["paginas"] == 1 and entry["motor"]["timings"]["integrity"] == 0.1
    assert "privado" not in log.read_text(encoding="utf-8")
