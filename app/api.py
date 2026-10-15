"""Bridge between the window (JavaScript) and the engine.

The window process never parses a document: analysis, export and previews run in
isolated engine processes (see engine/worker.py). Everything stays in memory; the only
files written are the ones the user saves.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import math
import json
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import __version__
from .engine import document, llm_server, logs, models, pipeline, review, rules
from .engine.types import Options
from .engine.worker import EngineError, EngineProcess

VERSION = __version__


@dataclass
class Doc:
    id: str
    name: str
    size: int
    data: bytes
    status: str = "pending"          # pending | processing | ready | failed | locked
    error: str = ""
    analysis: pipeline.Analysis | None = None
    preview_key: str = ""
    preview_bytes: bytes | None = None
    report: dict | None = None
    revision: int = 0
    analysis_hash: str = ""
    history: review.ReviewHistory = field(default_factory=review.ReviewHistory)
    reviewed: bool = False
    saved_revision: int | None = None
    analysis_settings: dict = field(default_factory=dict)


@dataclass
class State:
    docs: dict[str, Doc] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    busy: bool = False
    cancel: bool = False
    progress: dict = field(default_factory=dict)
    install: dict = field(default_factory=dict)
    setup: dict = field(default_factory=dict)    # first-launch download of the required models
    counter: int = 0


def _options(raw: dict) -> Options:
    if not isinstance(raw, dict):
        raise ValueError("Opciones de procesamiento no válidas")
    selected = raw.get("categories")
    if selected is None:
        categories = set(rules.SELECTABLE) - rules.DEFAULT_OFF
    else:
        if not isinstance(selected, (list, set, tuple)) or any(
            not isinstance(key, str) or key not in rules.CATEGORIES for key in selected
        ):
            raise ValueError("Categorías no válidas")
        categories = set(selected)
    mode = raw.get("mode", "label")
    if mode not in ("label", "blank"):
        raise ValueError("Modo de salida no válido")
    dpi = raw.get("dpi", 200)
    if isinstance(dpi, bool) or not isinstance(dpi, (int, float)) or not 50 <= dpi <= 1200 or int(dpi) != dpi:
        raise ValueError("La resolución debe ser un entero entre 50 y 1200 ppp")
    categories |= {"manual"}
    advanced_mode = raw.get("advancedMode", "auto")
    if advanced_mode not in ("auto", "accuracy", "memory"):
        raise ValueError("Modo de IA avanzada no válido")
    return Options(
        categories=categories,
        ocr=bool(raw.get("ocr", True)),
        handwriting=bool(raw.get("handwriting", True)),
        ai=bool(raw.get("ai", True)),
        llm_review=bool(raw.get("llmReview", True)),
        faces=bool(raw.get("faces", True)),
        signatures=bool(raw.get("signatures", True)),
        propagate=bool(raw.get("propagate", True)),
        mode=mode,
        max_security=bool(raw.get("maxSecurity", False)),
        ocr_text_layer=bool(raw.get("textLayer", True)),
        uniform_tokens=bool(raw.get("uniform", False)),
        dpi=int(dpi),
        advanced_mode=advanced_mode,
    )


def _transform(matrix: tuple, rect) -> tuple[float, float, float, float]:
    a, b, c, d, e, f = matrix
    xs, ys = [], []
    for x, y in ((rect[0], rect[1]), (rect[2], rect[1]), (rect[0], rect[3]), (rect[2], rect[3])):
        xs.append(a * x + c * y + e)
        ys.append(b * x + d * y + f)
    return min(xs), min(ys), max(xs), max(ys)


def _invert(matrix: tuple) -> tuple:
    a, b, c, d, e, f = matrix
    det = a * d - b * c
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return ia, ib, ic, id_, -(e * ia + f * ic), -(e * ib + f * id_)


class Api:
    def __init__(self, use_gpu: bool = True, engine: EngineProcess | None = None, light: EngineProcess | None = None,
                 fetch_models: bool = False):
        self._engine = engine or EngineProcess(with_models=True, use_gpu=use_gpu)
        self._light = light or EngineProcess(with_models=False, use_gpu=False, stall_seconds=180)
        self._state = State()
        self._lock = threading.RLock()
        self._window = None
        self._status_cache: dict | None = None
        threading.Thread(target=self._engine.ensure_started, daemon=True).start()
        threading.Thread(target=self._light.ensure_started, daemon=True).start()
        if fetch_models:
            self.install_required()

    def attach(self, window) -> None:
        self._window = window

    def shutdown(self) -> None:
        self._engine.stop()
        self._light.stop()

    def confirm_close(self) -> bool:
        with self._lock:
            pending = self._state.busy or self._state.install.get("running") or any(
                doc.reviewed and doc.saved_revision != doc.revision for doc in self._state.docs.values())
        if not pending:
            return True
        return bool(self._window.create_confirmation_dialog(
            "Cerrar Anonimato", "Hay una operación en curso o una revisión sin guardar. ¿Quieres cerrar y descartarla?"))

    # ------------------------------------------------------------ status
    def _engine_status(self) -> dict:
        if self._state.busy and self._status_cache is not None:
            return self._status_cache
        try:
            status = self._engine.call("status", stall_seconds=600)
        except EngineError as error:
            status = {"base": False, "advanced": False, "gpu": False, "errors": {"engine": str(error)}}
        if self._engine.gpu_disabled:
            status = {**status, "gpu": False, "errors": {**status.get("errors", {}), "gpu": self._engine.gpu_disabled}}
        self._status_cache = status
        return status

    def status(self) -> dict:
        services = self._engine_status()
        variant = llm_server.installed_variant()
        if variant is None:
            try:
                variant = "advanced_lite" if "integrity" in services.get("errors", {}) else llm_server.recommended_variant()
            except (RuntimeError, OSError, ValueError) as error:
                services = {**services, "errors": {**services.get("errors", {}), "integrity": str(error)}}
                variant = "advanced_lite"
        missing = bool(services.get("missing"))
        return {
            "version": VERSION,
            "services": services,
            "errors": services.get("errors", {}),
            "blocked": "integrity" in services.get("errors", {}) or missing,
            "modelsMissing": missing,
            "setup": dict(self._state.setup),
            "advancedInstalled": llm_server.available(),
            "advancedVariant": variant,
            "advancedLabel": "Qwen3-VL 8B · ≈ 5,5 GB" if variant == "advanced" else "Qwen3-VL 4B · ≈ 2,8 GB",
            "categories": [
                {"key": key, "label": value["label"], "token": value["token"], "default": key not in rules.DEFAULT_OFF}
                for key, value in rules.CATEGORIES.items() if key in rules.SELECTABLE
            ],
        }

    def recheck_integrity(self) -> bool:
        """Retry a temporary integrity failure without restarting or changing review state."""
        if not self._begin():
            return False
        self._state.progress = {"message": "Comprobando la integridad de los modelos…", "percent": 0}
        def run() -> None:
            try:
                self._engine.call("integrity", progress=self._state.progress.update)
            except EngineError as error:
                self._state.progress = {"message": str(error), "percent": 0}
            finally:
                self._status_cache = None
                self._end()
        try:
            threading.Thread(target=run, daemon=True).start()
        except Exception:
            self._end()
            raise
        return True

    # ------------------------------------------------------------ documents
    def _add_path(self, path: Path) -> dict | None:
        suffix = path.suffix.lower()
        if suffix != ".pdf" and suffix not in document.IMAGE_SUFFIXES:
            return None
        with self._lock:
            size = path.stat().st_size
            queued = sum(doc.size for doc in self._state.docs.values())
            if size > document.LIMITS["max_bytes"]:
                raise document.DocumentError(f"El archivo supera {document.LIMITS['max_bytes'] >> 20} MB")
            if queued + size > document.LIMITS["max_queue_bytes"]:
                raise document.DocumentError("La cola supera el límite de memoria; quita documentos antes de añadir más")
            # Bound the read as well: the file may grow after stat(). Reserve no unbounded input buffer.
            available = min(document.LIMITS["max_bytes"], document.LIMITS["max_queue_bytes"] - queued)
            with path.open("rb") as handle:
                data = handle.read(available + 1)
            if len(data) > available:
                raise document.DocumentError("El archivo supera el límite de memoria de entrada")
            self._state.counter += 1
            doc = Doc(id=f"d{self._state.counter}", name=path.name, size=len(data), data=data)
            self._state.docs[doc.id] = doc
            self._state.order.append(doc.id)
        return self._doc_summary(doc)

    def pick_files(self) -> list[dict]:
        import webview
        paths = self._window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True,
            file_types=("Documentos (*.pdf;*.jpg;*.jpeg;*.png;*.tif;*.tiff;*.bmp;*.webp)", "Todos los archivos (*.*)"))
        return [s for s in (self._add_path(Path(p)) for p in (paths or [])) if s]

    def pick_folder(self, recursive: bool = False) -> list[dict]:
        import webview
        folders = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not folders:
            return []
        root = Path(folders[0])
        items = root.rglob("*") if recursive else root.glob("*")
        return [s for s in (self._add_path(p) for p in sorted(items) if p.is_file()) if s]

    def add_paths(self, paths: list[str]) -> list[dict]:
        out = []
        for raw in paths or []:
            path = Path(raw)
            if path.is_dir():
                out += [s for s in (self._add_path(p) for p in sorted(path.glob("*")) if p.is_file()) if s]
            elif path.is_file():
                summary = self._add_path(path)
                if summary:
                    out.append(summary)
        return out

    def remove(self, doc_id: str) -> bool:
        with self._lock:
            if self._state.busy:
                return False
            self._state.docs.pop(doc_id, None)
            if doc_id in self._state.order:
                self._state.order.remove(doc_id)
        return True

    def clear(self) -> bool:
        with self._lock:
            if self._state.busy:
                return False
            self._state.docs.clear()
            self._state.order.clear()
        return True

    def _doc_summary(self, doc: Doc) -> dict:
        analysis = doc.analysis
        return {
            "id": doc.id, "name": doc.name, "size": doc.size, "status": doc.status, "error": doc.error,
            "pages": len(analysis.pages) if analysis else None,
            "findings": len(analysis.findings) if analysis else None,
            "saved": doc.saved_revision == doc.revision,
            "reviewed": doc.reviewed,
            "analysisSettings": doc.analysis_settings,
        }

    def documents(self) -> list[dict]:
        with self._lock:
            return [self._doc_summary(self._state.docs[i]) for i in self._state.order]

    def unlock(self, doc_id: str, password: str) -> dict:
        """Decrypt a password-protected PDF (in the isolated process); the output is never encrypted."""
        doc = self._state.docs[doc_id]
        try:
            unlocked = self._light.call("unlock", doc.data, password)
        except EngineError as error:
            return {"ok": False, "message": str(error)}
        with self._lock:
            queued = sum(item.size for item in self._state.docs.values() if item.id != doc_id)
            if len(unlocked) > document.LIMITS["max_bytes"] or queued + len(unlocked) > document.LIMITS["max_queue_bytes"]:
                return {"ok": False, "message": "El documento descifrado supera el límite de memoria de entrada"}
            doc.data = unlocked
            doc.status, doc.error, doc.size = "pending", "", len(doc.data)
        return {"ok": True}

    # ------------------------------------------------------------ processing
    def process(self, raw_options: dict, only: list[str] | None = None) -> bool:
        options = _options(raw_options)
        status = self.status()
        if status.get("modelsMissing"):
            self._state.progress = {"message": "Faltan los modelos de IA necesarios. Espera a que termine la descarga",
                                    "percent": 0}
            return False
        if status.get("blocked"):
            self._state.progress = {"message": status.get("errors", {}).get(
                "integrity", "No se pudo comprobar la integridad. Vuelve a intentarlo"), "percent": 0}
            return False
        with self._lock:
            if self._state.busy or self._state.install.get("running"):
                return False
            self._state.busy = True
            self._state.cancel = False
            self._state.progress = {"message": "Preparando…", "percent": 0}
        try:
            self._engine.cancel.clear()
            targets = list(dict.fromkeys(only)) if only is not None else [
                i for i in self._state.order if self._state.docs[i].status in ("pending", "failed")]
            if any(i not in self._state.docs or self._state.docs[i].status == "locked" for i in targets):
                raise ValueError("La selección contiene documentos no disponibles")
            threading.Thread(target=self._run, args=(targets, options), daemon=True).start()
        except Exception:
            self._end()
            raise
        return True

    def cancel(self) -> None:
        self._state.cancel = True
        self._engine.cancel.set()

    def _run(self, targets: list[str], options: Options) -> None:
        try:
            total = len(targets)
            for position, doc_id in enumerate(targets):
                doc = self._state.docs.get(doc_id)
                if doc is None:
                    continue
                if self._state.cancel:
                    break
                doc.status, doc.error = "processing", ""
                previous = doc.analysis
                doc.preview_bytes, doc.preview_key, doc.report = None, "", None

                def progress(event: dict, position=position, doc=doc) -> None:
                    page, pages = event.get("page"), event.get("total")
                    fraction = (page - 0.5) / pages if page and pages else 0.0
                    self._state.progress = {
                        "doc": doc.id, "name": doc.name, "message": event.get("message", ""),
                        "percent": round(100 * (position + min(1.0, fraction)) / max(1, total), 1),
                    }

                try:
                    analyzed = self._engine.call("analyze", doc.data, doc.name, options, progress=progress)
                    digest = hashlib.sha256(doc.data).hexdigest()
                    manual = [f for f in previous.findings if f.type == "manual"] if previous else []
                    if manual and ((doc.analysis_hash and digest != doc.analysis_hash) or previous.pages != analyzed.pages):
                        raise EngineError("El documento o sus páginas han cambiado. Conserva la revisión anterior y añade el archivo como un documento nuevo.")
                    for finding in manual:
                        kept = copy.deepcopy(finding)
                        kept.id = analyzed.new_id(kept.page)
                        kept.key = kept.id
                        analyzed.findings.append(kept)
                    if manual:
                        analyzed.notes.append(f"Se conservaron {len(manual)} zonas manuales de la revisión anterior.")
                    with self._lock:
                        doc.analysis = analyzed
                        doc.analysis_hash = digest
                        doc.analysis_settings = {
                            "categories": sorted(options.categories), "ocr": options.ocr, "ai": options.ai,
                            "handwriting": options.handwriting, "llmReview": options.llm_review,
                            "faces": options.faces, "signatures": options.signatures, "propagate": options.propagate,
                            "dpi": options.dpi, "advancedMode": options.advanced_mode,
                        }
                        doc.history.clear()
                        doc.revision += 1
                    doc.status = "ready"
                except pipeline.Cancelled:
                    doc.status, doc.error = ("ready" if previous else "pending"), ""
                except EngineError as error:
                    if error.kind == "PasswordRequired":
                        doc.status, doc.error = "locked", "Protegido con contraseña"
                    else:
                        doc.status, doc.error = ("ready" if previous else "failed"), str(error)
        finally:
            with self._lock:
                self._state.busy = False
                self._state.progress = {"message": "", "percent": 100}

    def poll(self) -> dict:
        return {"busy": self._state.busy, "progress": self._state.progress, "documents": self.documents(),
                "install": self._state.install, "setup": self._state.setup}

    # ------------------------------------------------------------ review
    def _analysis(self, doc_id: str) -> tuple[Doc, pipeline.Analysis]:
        doc = self._state.docs[doc_id]
        if doc.analysis is None:
            raise ValueError("El documento no está analizado")
        return doc, doc.analysis

    def _view_rects(self, analysis: pipeline.Analysis, page: int, rects) -> list[list[float]]:
        """Unrotated page rects -> normalised rects on the displayed (rotated) page."""
        info = analysis.pages[page]
        out = []
        for rect in rects:
            x0, y0, x1, y1 = _transform(info.matrix, rect)
            out.append([x0 / info.width, y0 / info.height, x1 / info.width, y1 / info.height])
        return out

    def _report_view(self, analysis: pipeline.Analysis, report: dict | None) -> dict | None:
        if not report:
            return report
        for leak in report.get("leaks", []):
            page = leak.get("page")
            if page is not None and 0 <= page < len(analysis.pages):
                leak["view"] = self._view_rects(analysis, page, leak.get("rects", []))
            leak.pop("rects", None)
        return report

    def details(self, doc_id: str) -> dict:
        doc, analysis = self._analysis(doc_id)
        doc.reviewed = True
        findings = []
        for f in analysis.findings:
            data = f.to_json()
            data["label"] = rules.CATEGORIES[f.type]["label"]
            data["view"] = self._view_rects(analysis, f.page, f.rects)
            del data["rects"]
            findings.append(data)
        return {
            "id": doc.id, "name": doc.name, "pages": [{"width": p.width, "height": p.height} for p in analysis.pages],
            "findings": findings, "notes": analysis.notes, "seconds": analysis.seconds,
            "nativeChars": analysis.native_chars, "report": doc.report, "signed": analysis.signed,
            "history": {"undo": bool(doc.history.undo), "redo": bool(doc.history.redo)},
            "saved": doc.saved_revision == doc.revision,
        }

    def set_enabled(self, doc_id: str, finding_ids: list[str], enabled: bool) -> int:
        with self._lock:
            self._require_editable()
            doc, analysis = self._analysis(doc_id)
            wanted = set(finding_ids)
            changed = any(f.id in wanted and f.enabled != bool(enabled) for f in analysis.findings)
            if changed:
                doc.history.record(analysis.findings)
            count = 0
            for f in analysis.findings:
                if f.id in wanted:
                    f.enabled = bool(enabled)
                    count += 1
            if changed:
                self.invalidate_report(doc_id)
            return count

    def add_manual(self, doc_id: str, page: int, view_rect: list[float]) -> dict:
        with self._lock:
            self._require_editable()
            doc, analysis = self._analysis(doc_id)
            self._validate_manual(analysis, page, view_rect)
            doc.history.record(analysis.findings)
            info = analysis.pages[page]
            shown = (view_rect[0] * info.width, view_rect[1] * info.height, view_rect[2] * info.width, view_rect[3] * info.height)
            finding = pipeline.add_manual(analysis, page, _transform(_invert(info.matrix), shown))
            self.invalidate_report(doc_id)
        data = finding.to_json()
        data["label"] = rules.CATEGORIES["manual"]["label"]
        data["view"] = self._view_rects(analysis, page, finding.rects)
        del data["rects"]
        return data

    def remove_manual(self, doc_id: str, finding_id: str) -> bool:
        with self._lock:
            self._require_editable()
            doc, analysis = self._analysis(doc_id)
            before = len(analysis.findings)
            if any(f.id == finding_id and f.type == "manual" for f in analysis.findings):
                doc.history.record(analysis.findings)
            analysis.findings = [f for f in analysis.findings if not (f.id == finding_id and f.type == "manual")]
            if len(analysis.findings) < before:
                self.invalidate_report(doc_id)
            return len(analysis.findings) < before

    def invalidate_report(self, doc_id: str) -> None:
        with self._lock:
            doc = self._state.docs[doc_id]
            doc.report = None
            doc.revision += 1
            doc.reviewed = True

    @staticmethod
    def _validate_manual(analysis, page, rect) -> None:
        if (isinstance(page, bool) or not isinstance(page, int) or not 0 <= page < len(analysis.pages)
                or not isinstance(rect, (list, tuple)) or len(rect) != 4
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in rect)
                or rect[0] >= rect[2] or rect[1] >= rect[3]):
            raise ValueError("La zona debe estar dentro de la página y tener ancho y alto positivos")

    def update_manual(self, doc_id: str, finding_id: str, page: int, view_rect: list[float]) -> dict:
        with self._lock:
            self._require_editable()
            doc, analysis = self._analysis(doc_id)
            self._validate_manual(analysis, page, view_rect)
            finding = next((f for f in analysis.findings if f.id == finding_id and f.type == "manual"), None)
            if finding is None:
                raise ValueError("La zona manual ya no existe")
            doc.history.record(analysis.findings)
            info = analysis.pages[page]
            shown = (view_rect[0] * info.width, view_rect[1] * info.height, view_rect[2] * info.width, view_rect[3] * info.height)
            finding.page, finding.rects = page, [_transform(_invert(info.matrix), shown)]
            self.invalidate_report(doc_id)
        return self.details(doc_id)

    def restore_review(self, doc_id: str, redo: bool = False) -> dict:
        with self._lock:
            self._require_editable()
            doc, analysis = self._analysis(doc_id)
            restored = doc.history.restore(analysis.findings, redo=redo)
            if restored is not None:
                analysis.findings = restored
                self.invalidate_report(doc_id)
        return self.details(doc_id)

    def _require_editable(self) -> None:
        if self._state.busy or self._state.install.get("running"):
            raise ValueError("Espera a que termine el procesamiento antes de modificar las marcas")

    # ------------------------------------------------------------ previews
    def _state_key(self, analysis: pipeline.Analysis, options: Options) -> str:
        enabled = ",".join(sorted(f.id + str(f.rects) for f in analysis.findings if f.enabled))
        return f"{options.mode}|{options.max_security}|{options.uniform_tokens}|{enabled}"

    def page_image(self, doc_id: str, page: int, which: str, raw_options: dict) -> str:
        doc, analysis = self._analysis(doc_id)
        width = raw_options.get("previewWidth", 1100)
        if (isinstance(width, bool) or not isinstance(width, int) or not 600 <= width <= 3300
                or isinstance(page, bool) or not isinstance(page, int) or not 0 <= page < len(analysis.pages)
                or which not in ("original", "result")):
            raise ValueError("Resolución, página o tipo de vista previa no válidos")
        if which == "original":
            data = analysis.working
        else:
            options = _options(raw_options)
            # The key must describe exactly the findings that are rendered. Engine calls run one at a time, so
            # the review can change while this request waits; render a snapshot taken with its key.
            with self._lock:
                snapshot = replace(analysis, findings=copy.deepcopy(analysis.findings), sources={})
                key = self._state_key(snapshot, options)
                data = doc.preview_bytes if doc.preview_key == key else None
            if data is None:
                # Exactly the pipeline used for saving, minus the (slow) verification.
                data = self._light.call("build_preview", snapshot, options)
                with self._lock:
                    if doc.analysis is analysis:
                        doc.preview_bytes, doc.preview_key = data, key
        png = self._light.call("page_png", data, page, width)
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")

    # ------------------------------------------------------------ export
    def _export(self, doc: Doc, options: Options, index: int, keep_name: bool, share: tuple[int, int] = (0, 1)):
        def progress(event: dict) -> None:
            page, pages = event.get("page"), event.get("total")
            fraction = page / pages if page and pages else 0.0
            self._state.progress = {"message": f"{doc.name}: {event.get('message', '')}",
                                    "percent": round(100 * (share[0] + fraction) / max(1, share[1]), 1)}

        with self._lock:
            if doc.analysis_hash and hashlib.sha256(doc.data).hexdigest() != doc.analysis_hash:
                raise EngineError("El archivo de origen cambió; revisa el documento antes de guardar")
            revision = doc.revision
            snapshot = replace(doc.analysis, findings=copy.deepcopy(doc.analysis.findings), sources={})
        result = self._engine.call("export", snapshot, options, index, keep_name, progress=progress)
        with self._lock:
            if doc.revision != revision:
                doc.report = None
                raise EngineError("El documento cambió durante la exportación; vuelve a guardar")
            result.revision = revision
            doc.report = self._report_view(snapshot, result.report.to_json())
        return result

    def _publish_export(self, doc: Doc, result: pipeline.ExportResult, path: Path, overwrite: bool = True) -> None:
        from .engine.files import atomic_write
        # Keep the revision check and publication together, including after the native save dialog.
        with self._lock:
            if self._state.docs.get(doc.id) is not doc or doc.revision != result.revision or not result.report.ok:
                raise EngineError("El documento cambió durante la exportación; vuelve a guardar")
            atomic_write(path, result.data, overwrite=overwrite)
            doc.saved_revision = doc.revision

    def _begin(self) -> bool:
        with self._lock:
            if self._state.busy or self._state.install.get("running"):
                return False
            self._state.busy = True
            self._state.progress = {"message": "Generando y verificando…", "percent": 0}
            return True

    def _end(self) -> None:
        with self._lock:
            self._state.busy = False
            self._state.progress = {"message": "", "percent": 100}

    def save_pdf(self, doc_id: str, raw_options: dict) -> dict:
        import webview
        doc, _ = self._analysis(doc_id)
        options = _options(raw_options)
        keep = bool(raw_options.get("keepName", False))
        index = self._state.order.index(doc_id) + 1
        if not self._begin():
            return {"ok": False, "message": "Hay un proceso en curso"}
        try:
            try:
                result = self._export(doc, options, index, keep)
            except EngineError as error:
                return {"ok": False, "message": f"No se pudo generar el PDF: {error}"}
            if not result.report.ok:
                return {"ok": False, "report": doc.report,
                        "message": "La verificación ha encontrado restos del dato original. No se ha guardado nada."}
            target = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=result.filename,
                                                     file_types=("PDF (*.pdf)",))
            if not target:
                return {"ok": True, "saved": False, "report": doc.report}
            path = Path(target if isinstance(target, str) else target[0])
            try:
                self._publish_export(doc, result, path)
            except (OSError, EngineError) as error:
                return {"ok": False, "message": f"No se pudo guardar el PDF: {error}", "report": doc.report}
            return {"ok": True, "saved": True, "path": str(path), "report": doc.report}
        finally:
            self._end()

    def save_all(self, raw_options: dict) -> dict:
        import webview
        folders = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not folders:
            return {"ok": True, "saved": 0, "results": []}
        return self.export_folder(folders[0], raw_options)

    def export_folder(self, folder: str, raw_options: dict, only: list[str] | None = None) -> dict:
        options = _options(raw_options)
        keep = bool(raw_options.get("keepName", False))
        root = Path(folder)
        results = []
        if not self._begin():
            return {"ok": False, "message": "Hay un proceso en curso"}
        try:
            if only is not None and any(i not in self._state.docs for i in only):
                raise EngineError("Documento no disponible para reintentar")
            ready = [self._state.docs[i] for i in self._state.order
                     if self._state.docs[i].status == "ready" and (only is None or i in only)]
            for position, doc in enumerate(ready):
                number = self._state.order.index(doc.id) + 1
                entry = {"documento": f"documento-{number}", "id": doc.id, "status": "verification_blocked"}
                try:
                    result = self._export(doc, options, number, keep, share=(position, len(ready)))
                except EngineError as error:
                    entry.update(ok=False, error=str(error), status="processing_error")
                    results.append(entry)
                    continue
                entry.update(ok=result.report.ok, verificacion=logs.private_report(doc.report))
                if result.report.ok:
                    counter = 1
                    try:
                        while True:
                            name = result.filename if counter == 1 else result.filename.replace(
                                "_anonimizado.pdf", f"_anonimizado_{counter}.pdf")
                            path = root / name
                            try:
                                self._publish_export(doc, result, path, overwrite=False)
                                break
                            except FileExistsError:
                                counter += 1
                        entry["archivo"] = path.name
                        entry["status"] = "saved"
                    except (OSError, EngineError) as error:
                        entry.update(ok=False, error=f"No se pudo guardar el PDF: {error}", status="write_error")
                results.append(entry)
            from .engine.files import atomic_write
            summary = {"ok": all(r["ok"] for r in results), "saved": sum("archivo" in r for r in results),
                       "failed": sum(not r["ok"] for r in results), "folder": str(root), "results": results}
            if not results:
                return summary
            report_text = json.dumps({"generado": time.strftime("%Y-%m-%d %H:%M:%S"), "documentos": results},
                                     ensure_ascii=False, indent=2)
            counter = 1
            try:
                while True:
                    report_path = root / ("informe_verificacion.json" if counter == 1 else f"informe_verificacion_{counter}.json")
                    try:
                        atomic_write(report_path, report_text, encoding="utf-8", overwrite=False)
                        break
                    except FileExistsError:
                        counter += 1
                summary["reportPath"] = str(report_path)
            except OSError as error:
                summary.update(ok=False, reportError=str(error),
                               message=f"Se guardaron {summary['saved']} PDF, pero no se pudo guardar el informe: {error}")
            return summary
        finally:
            self._end()

    def save_log(self, doc_id: str, fmt: str, include_originals: bool, include_coords: bool) -> dict:
        import webview
        doc, analysis = self._analysis(doc_id)
        index = self._state.order.index(doc_id) + 1
        if fmt == "csv":
            content = logs.build_csv(analysis.findings, include_originals, include_coords)
            name, types = f"documento-{index}_registro.csv", ("CSV (*.csv)",)
        else:
            content = logs.build_json(analysis.findings, len(analysis.pages), doc.report, include_originals, include_coords)
            name, types = f"documento-{index}_registro.json", ("JSON (*.json)",)
        target = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name, file_types=types)
        if not target:
            return {"saved": False}
        path = Path(target if isinstance(target, str) else target[0])
        from .engine.files import atomic_write
        atomic_write(path, content, encoding="utf-8")
        return {"saved": True, "path": str(path)}

    # ------------------------------------------------------------ required models (first launch)
    def install_required(self) -> bool:
        """Download the base models and runtime that installed builds do not ship (first launch, or a retry)."""
        with self._lock:
            if self._state.setup.get("running") or not models.required_missing():
                return False
            self._state.setup = {"running": True, "percent": 0, "message": "Preparando la descarga de los modelos de IA…"}
            try:
                threading.Thread(target=self._install_required, daemon=True).start()
            except Exception:
                self._state.setup = {}
                raise
        return True

    def _install_required(self) -> None:
        try:
            total = sum(item.size or 0 for item in models.required_missing()) or 1
            received: dict[str, int] = {}

            def progress(model_id: str, done: int, _total: int) -> None:
                received[model_id] = done
                got = min(sum(received.values()), total)
                self._state.setup = {"running": True, "percent": round(100 * got / total, 1),
                                     "message": f"Descargando los modelos de IA ({got >> 20} de {total >> 20} MB)…"}

            models.install_required(progress)
            self._engine.call("reload_models")
            self._status_cache = None
            self._state.setup = {"running": False, "done": True, "percent": 100, "message": "Modelos de IA instalados"}
        except Exception as error:
            self._state.setup = {"running": False, "error": str(error),
                                 "message": f"No se pudieron descargar los modelos de IA: {error}"}

    # ------------------------------------------------------------ advanced models
    def install_advanced(self) -> bool:
        with self._lock:
            if self._state.install.get("running") or self._state.busy:
                return False
            self._state.install = {"running": True, "message": "Descargando…", "percent": 0}
            try:
                threading.Thread(target=self._install, daemon=True).start()
            except Exception:
                self._state.install = {"running": False}
                raise
        return True

    def _install(self, group: str | None = None) -> None:
        try:
            items = models.load_manifest()[group or llm_server.recommended_variant()]
            sizes: dict[str, tuple[int, int]] = {}

            def progress(model_id: str, done: int, total: int) -> None:
                sizes[model_id] = (done, total)
                got = sum(d for d, _ in sizes.values())
                tot = sum(t for _, t in sizes.values()) or 1
                self._state.install = {"running": True, "percent": round(100 * got / tot, 1),
                                       "message": f"Descargando modelos de IA ({got >> 20} MB)"}

            self._engine.call("release_advanced")
            models.download_group(items, progress)
            self._engine.call("reload_models")
            self._status_cache = None
            self._state.install = {"running": False, "done": True, "percent": 100, "message": "IA avanzada instalada"}
        except Exception as error:
            self._state.install = {"running": False, "error": str(error), "message": f"Error: {error}"}

    def import_advanced(self) -> dict:
        import webview
        paths = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("Paquete de IA (*.zip)",))
        if not paths:
            return {"ok": False}
        with self._lock:
            if self._state.install.get("running") or self._state.busy:
                return {"ok": False, "message": "Hay un proceso en curso"}
            self._state.install = {"running": True, "message": "Importando modelos…", "percent": 0}
        try:
            self._engine.call("release_advanced")
            models.import_zip(Path(paths[0]))
            self._engine.call("reload_models")
            self._status_cache = None
            return {"ok": True}
        except Exception as error:
            return {"ok": False, "message": str(error)}
        finally:
            self._state.install = {"running": False}
