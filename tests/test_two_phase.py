"""Batch analysis in two phases: base models document by document, then the advanced AI over the batch."""
from app.api import Api, Doc
from app.engine import pipeline
from app.engine.types import Options
from app.engine.worker import EngineError
from tests.test_security import pdf_with_text

OPTIONS = Options(categories={"name", "manual"}, ocr=False, ai=False, faces=False, signatures=False,
                  handwriting=False, llm_review=True)


class Engine:
    gpu_disabled = ""

    def __init__(self, advance=None):
        self.calls = []
        self._advance = advance

    def ensure_started(self):
        pass

    def stop(self):
        pass

    def call(self, op, *args, progress=None, **kwargs):
        if op == "advance":
            self.calls.append((op, args[0].filename, *args[2:]))
        else:
            self.calls.append((op, args[1], *args[3:]))
        if op == "analyze":
            return pipeline.analyze(args[0], args[1], args[2], defer_advanced=bool(args[3:] and args[3]))
        if op == "advance":
            analysis = args[0]
            if self._advance:
                self._advance(analysis)
            analysis.add(0, "name", "Lucía Ferreiro", [(10, 10, 80, 20)], 0.8, "llm", detail="propuesto por la revisión con IA")
            analysis.deferred, analysis.advanced_pending = [], False
            return analysis
        raise AssertionError(op)


def make_api(engine, names=("uno.pdf", "dos.pdf")):
    api = Api(engine=engine, light=Engine())
    api._status_cache = {"advanced": True}
    for index, name in enumerate(names, 1):
        data = pdf_with_text(f"FICTITIOUS DOCUMENT {index}")
        doc = Doc(f"d{index}", name, len(data), data)
        api._state.docs[doc.id] = doc
        api._state.order.append(doc.id)
    return api


def test_base_phase_for_every_document_then_advanced_phase_for_the_batch():
    engine = Engine()
    api = make_api(engine)
    api._run(["d1", "d2"], OPTIONS)
    assert [call[:2] for call in engine.calls] == [("analyze", "uno.pdf"), ("analyze", "dos.pdf"),
                                                   ("advance", "uno.pdf"), ("advance", "dos.pdf")]
    # The base models are released once, before the first document of the advanced phase.
    assert [call[2] for call in engine.calls if call[0] == "advance"] == [True, False]
    for doc in api._state.docs.values():
        assert doc.status == "ready" and doc.advanced == "" and not doc.analysis.advanced_pending
        added = [f for f in doc.analysis.findings if f.source == "llm"]
        assert len(added) == 1 and added[0].token.startswith("[NOMBRE")
        assert any("añadió 1 dato" in note for note in doc.analysis.notes)
    # One identifier for the same person in both documents of the session.
    tokens = {f.token for doc in api._state.docs.values() for f in doc.analysis.findings if f.source == "llm"}
    assert len(tokens) == 1


def test_without_the_advanced_ai_the_batch_is_analysed_in_one_pass():
    engine = Engine()
    api = make_api(engine)
    api._status_cache = {"advanced": False}
    api._run(["d1", "d2"], OPTIONS)
    assert [call[0] for call in engine.calls] == ["analyze", "analyze"] and all(len(call) == 2 for call in engine.calls)


def test_review_changes_made_during_the_advanced_phase_are_kept():
    api = None

    def user_edits(_snapshot):
        doc = api._state.docs["d1"]
        if doc.advanced == "running":
            doc.analysis.add(0, "manual", None, [(1, 1, 5, 5)], 1.0, "manual")   # new zone meanwhile
            doc.analysis.findings[0].enabled = False

    api = make_api(Engine(advance=user_edits), names=("uno.pdf",))
    api._run(["d1"], OPTIONS)
    findings = api._state.docs["d1"].analysis.findings
    assert any(f.type == "manual" for f in findings) and any(f.source == "llm" for f in findings)
    assert len({f.id for f in findings}) == len(findings)          # no identifier taken twice


def test_cancelling_the_advanced_phase_leaves_reviewable_documents_with_a_note():
    api = None

    def cancel(_snapshot):
        api._state.cancel = True
        raise pipeline.Cancelled()

    api = make_api(Engine(advance=cancel))
    api._run(["d1", "d2"], OPTIONS)
    for doc in api._state.docs.values():
        assert doc.status == "ready" and doc.advanced == "" and not doc.analysis.advanced_pending
        assert any("IA avanzada cancelada" in note for note in doc.analysis.notes)
    assert not api.poll()["busy"]


def test_an_advanced_phase_failure_is_reported_per_document():
    def fail(_snapshot):
        raise EngineError("servidor caído")

    api = make_api(Engine(advance=fail), names=("uno.pdf",))
    api._run(["d1"], OPTIONS)
    doc = api._state.docs["d1"]
    assert doc.status == "ready" and doc.advanced == ""
    assert any("IA avanzada no disponible: servidor caído" in note for note in doc.analysis.notes)
