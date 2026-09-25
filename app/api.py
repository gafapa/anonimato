"""Bridge between the window (JavaScript) and the engine.

Everything stays in memory; the only files written are the ones the user saves.
"""
from __future__ import annotations

import base64
import json
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .engine import document, logs, models, pipeline, rules
from .engine.services import Services
from .engine.types import Options

VERSION = "2.0.0"
SUPPORTED = ("*.pdf", "*.jpg", "*.jpeg", "*.png", "*.tif", "*.tiff", "*.bmp", "*.webp")


@dataclass
class Doc:
    id: str
    name: str
    size: int
    data: bytes
    status: str = "pending"          # pending | processing | ready | failed
    error: str = ""
    analysis: pipeline.Analysis | None = None
    preview_key: str = ""
    preview_bytes: bytes | None = None
    report: dict | None = None
    report_key: str = ""


@dataclass
class State:
    docs: dict[str, Doc] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    busy: bool = False
    cancel: bool = False
    progress: dict = field(default_factory=dict)
    install: dict = field(default_factory=dict)
    counter: int = 0


def _options(raw: dict) -> Options:
    categories = set(raw.get("categories") or (set(rules.SELECTABLE) - rules.DEFAULT_OFF))
    categories |= {"manual"}
    return Options(
        categories=categories,
        ocr=bool(raw.get("ocr", True)),
        handwriting=bool(raw.get("handwriting", True)),
        ai=bool(raw.get("ai", True)),
        llm_review=bool(raw.get("llmReview", True)),
        faces=bool(raw.get("faces", True)),
        signatures=bool(raw.get("signatures", True)),
        propagate=bool(raw.get("propagate", True)),
        mode=raw.get("mode", "label"),
        max_security=bool(raw.get("maxSecurity", False)),
        ocr_text_layer=bool(raw.get("textLayer", True)),
        uniform_tokens=bool(raw.get("uniform", False)),
        dpi=int(raw.get("dpi", 200)),
    )


class Api:
    def __init__(self, services: Services | None = None):
        self._services = services or Services()
        self._state = State()
        self._lock = threading.RLock()
        self._window = None

    def attach(self, window) -> None:
        self._window = window

    # ------------------------------------------------------------ status
    def status(self) -> dict:
        from .engine import llm_server
        variant = llm_server.installed_variant() or llm_server.recommended_variant()
        return {
            "version": VERSION,
            "services": self._services.status(),
            "advancedInstalled": self._services.advanced_available(),
            "advancedVariant": variant,
            "advancedLabel": "Qwen3-VL 8B · ≈ 5,5 GB" if variant == "advanced" else "Qwen3-VL 4B · ≈ 2,8 GB",
            "categories": [
                {"key": key, "label": value["label"], "token": value["token"], "default": key not in rules.DEFAULT_OFF}
                for key, value in rules.CATEGORIES.items() if key in rules.SELECTABLE
            ],
        }

    # ------------------------------------------------------------ documents
    def _add_path(self, path: Path) -> dict | None:
        suffix = path.suffix.lower()
        if suffix != ".pdf" and suffix not in document.IMAGE_SUFFIXES:
            return None
        data = path.read_bytes()
        with self._lock:
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
        }

    def documents(self) -> list[dict]:
        with self._lock:
            return [self._doc_summary(self._state.docs[i]) for i in self._state.order]

    # ------------------------------------------------------------ processing
    def process(self, raw_options: dict, only: list[str] | None = None) -> bool:
        with self._lock:
            if self._state.busy:
                return False
            self._state.busy = True
            self._state.cancel = False
            self._state.progress = {"message": "Preparando…", "percent": 0}
        options = _options(raw_options)
        targets = only or list(self._state.order)
        threading.Thread(target=self._run, args=(targets, options), daemon=True).start()
        return True

    def cancel(self) -> None:
        self._state.cancel = True

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
                doc.preview_bytes, doc.preview_key, doc.report = None, "", None

                def progress(event: dict, position=position, doc=doc) -> None:
                    page, pages = event.get("page"), event.get("total")
                    fraction = (page - 0.5) / pages if page and pages else 0.0
                    self._state.progress = {
                        "doc": doc.id, "name": doc.name, "message": event.get("message", ""),
                        "percent": round(100 * (position + min(1.0, fraction)) / max(1, total), 1),
                    }

                try:
                    doc.analysis = pipeline.analyze(doc.data, doc.name, options, self._services, progress,
                                                    lambda: self._state.cancel)
                    doc.status = "ready"
                except pipeline.Cancelled:
                    doc.status, doc.error = "pending", ""
                except Exception as error:  # noqa: BLE001
                    doc.status, doc.error = "failed", str(error) or error.__class__.__name__
                    traceback.print_exc()
        finally:
            with self._lock:
                self._state.busy = False
                self._state.progress = {"message": "", "percent": 100}
            self._services.release_llm_if_idle(0)

    def poll(self) -> dict:
        return {"busy": self._state.busy, "progress": self._state.progress, "documents": self.documents(),
                "install": self._state.install}

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
        matrix = _rotation_matrix(analysis, page)
        for rect in rects:
            r = pymupdf.Rect(rect) * matrix
            out.append([r.x0 / info.width, r.y0 / info.height, r.x1 / info.width, r.y1 / info.height])
        return out

    def details(self, doc_id: str) -> dict:
        doc, analysis = self._analysis(doc_id)
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
            "nativeChars": analysis.native_chars, "report": doc.report,
        }

    def set_enabled(self, doc_id: str, finding_ids: list[str], enabled: bool) -> int:
        _, analysis = self._analysis(doc_id)
        wanted = set(finding_ids)
        count = 0
        for f in analysis.findings:
            if f.id in wanted:
                f.enabled = bool(enabled)
                count += 1
        return count

    def add_manual(self, doc_id: str, page: int, view_rect: list[float]) -> dict:
        _, analysis = self._analysis(doc_id)
        info = analysis.pages[page]
        rect = pymupdf.Rect(view_rect[0] * info.width, view_rect[1] * info.height,
                            view_rect[2] * info.width, view_rect[3] * info.height)
        rect = rect * ~_rotation_matrix(analysis, page)
        finding = pipeline.add_manual(analysis, page, (rect.x0, rect.y0, rect.x1, rect.y1))
        data = finding.to_json()
        data["label"] = rules.CATEGORIES["manual"]["label"]
        data["view"] = self._view_rects(analysis, page, finding.rects)
        del data["rects"]
        return data

    def remove_manual(self, doc_id: str, finding_id: str) -> bool:
        _, analysis = self._analysis(doc_id)
        before = len(analysis.findings)
        analysis.findings = [f for f in analysis.findings if not (f.id == finding_id and f.type == "manual")]
        return len(analysis.findings) < before

    # ------------------------------------------------------------ previews
    def _state_key(self, analysis: pipeline.Analysis, options: Options) -> str:
        enabled = ",".join(sorted(f.id for f in analysis.findings if f.enabled))
        return f"{options.mode}|{options.max_security}|{options.uniform_tokens}|{enabled}"

    def page_image(self, doc_id: str, page: int, which: str, raw_options: dict) -> str:
        doc, analysis = self._analysis(doc_id)
        if which == "original":
            data = analysis.working
        else:
            options = _options(raw_options)
            key = self._state_key(analysis, options)
            if doc.preview_key != key or doc.preview_bytes is None:
                # Exactly the pipeline used for saving, minus the (slow) verification.
                doc_pdf = pymupdf.open("pdf", analysis.working)
                from .engine import rasterize, redact, sanitize
                redact.apply(doc_pdf, analysis.findings, options.mode, options.uniform_tokens)
                data = sanitize.sanitize(redact.render_output(doc_pdf.tobytes()))
                doc_pdf.close()
                if options.max_security:
                    data = sanitize.sanitize(rasterize.rasterize(data, options.raster_dpi, None))
                doc.preview_bytes, doc.preview_key = data, key
            data = doc.preview_bytes
        png = pipeline.preview(data, page, 1100)
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")

    # ------------------------------------------------------------ export
    def _export(self, doc: Doc, options: Options, index: int, keep_name: bool) -> pipeline.ExportResult:
        result = pipeline.export(doc.analysis, options, self._services, index=index, keep_name=keep_name,
                                 progress=lambda e: self._state.progress.update({"message": e.get("message", "")}))
        doc.report = result.report.to_json()
        doc.report_key = self._state_key(doc.analysis, options)
        return result

    def save_pdf(self, doc_id: str, raw_options: dict) -> dict:
        import webview
        doc, analysis = self._analysis(doc_id)
        options = _options(raw_options)
        keep = bool(raw_options.get("keepName", False))
        index = self._state.order.index(doc_id) + 1
        with self._lock:
            if self._state.busy:
                return {"ok": False, "message": "Hay un proceso en curso"}
            self._state.busy = True
        try:
            self._state.progress = {"message": "Generando y verificando…", "percent": 50}
            result = self._export(doc, options, index, keep)
            if not result.report.ok:
                return {"ok": False, "report": doc.report,
                        "message": "La verificación ha encontrado restos del dato original. No se ha guardado nada."}
            target = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=result.filename,
                                                     file_types=("PDF (*.pdf)",))
            if not target:
                return {"ok": True, "saved": False, "report": doc.report}
            path = Path(target if isinstance(target, str) else target[0])
            path.write_bytes(result.data)
            return {"ok": True, "saved": True, "path": str(path), "report": doc.report}
        finally:
            with self._lock:
                self._state.busy = False
                self._state.progress = {"message": "", "percent": 100}

    def save_all(self, raw_options: dict) -> dict:
        import webview
        folders = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not folders:
            return {"ok": True, "saved": 0, "results": []}
        return self.export_folder(folders[0], raw_options)

    def export_folder(self, folder: str, raw_options: dict) -> dict:
        options = _options(raw_options)
        keep = bool(raw_options.get("keepName", False))
        root = Path(folder)
        results = []
        with self._lock:
            if self._state.busy:
                return {"ok": False, "message": "Hay un proceso en curso"}
            self._state.busy = True
        try:
            ready = [self._state.docs[i] for i in self._state.order if self._state.docs[i].status == "ready"]
            for position, doc in enumerate(ready, start=1):
                self._state.progress = {"message": f"Exportando {position} de {len(ready)}",
                                        "percent": round(100 * (position - 1) / max(1, len(ready)))}
                result = self._export(doc, options, self._state.order.index(doc.id) + 1, keep)
                entry = {"documento": f"documento-{self._state.order.index(doc.id) + 1}", "ok": result.report.ok,
                         "verificacion": doc.report}
                if result.report.ok:
                    path = root / result.filename
                    counter = 2
                    while path.exists():
                        path = root / result.filename.replace("_anonimizado.pdf", f"_anonimizado_{counter}.pdf")
                        counter += 1
                    path.write_bytes(result.data)
                    entry["archivo"] = path.name
                results.append(entry)
            (root / "informe_verificacion.json").write_text(json.dumps(
                {"generado": time.strftime("%Y-%m-%d %H:%M:%S"), "documentos": results}, ensure_ascii=False, indent=2),
                encoding="utf-8")
            return {"ok": all(r["ok"] for r in results), "saved": sum(1 for r in results if r["ok"]),
                    "failed": sum(1 for r in results if not r["ok"]), "folder": str(root)}
        finally:
            with self._lock:
                self._state.busy = False
                self._state.progress = {"message": "", "percent": 100}

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
        path.write_text(content, encoding="utf-8")
        return {"saved": True, "path": str(path)}

    # ------------------------------------------------------------ advanced models
    def install_advanced(self) -> bool:
        if self._state.install.get("running"):
            return False
        self._state.install = {"running": True, "message": "Descargando…", "percent": 0}

        def run() -> None:
            try:
                from .engine import llm_server
                items = models.load_manifest()[llm_server.recommended_variant()]
                sizes = {}

                def progress(model_id: str, done: int, total: int) -> None:
                    sizes[model_id] = (done, total)
                    got = sum(d for d, _ in sizes.values())
                    tot = sum(t for _, t in sizes.values()) or 1
                    self._state.install = {"running": True, "percent": round(100 * got / tot, 1),
                                           "message": f"Descargando modelos de IA ({got >> 20} MB)"}

                for item in items:
                    models.download(item, progress)
                self._state.install = {"running": False, "done": True, "percent": 100,
                                       "message": "IA avanzada instalada"}
            except Exception as error:  # noqa: BLE001
                self._state.install = {"running": False, "error": str(error), "message": f"Error: {error}"}

        threading.Thread(target=run, daemon=True).start()
        return True

    def import_advanced(self) -> dict:
        import webview
        paths = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("Paquete de IA (*.zip)",))
        if not paths:
            return {"ok": False}
        try:
            models.import_zip(Path(paths[0]))
            self._services.errors.pop("llm", None)
            return {"ok": True}
        except Exception as error:  # noqa: BLE001
            return {"ok": False, "message": str(error)}


def _rotation_matrix(analysis: pipeline.Analysis, page: int) -> pymupdf.Matrix:
    cache = getattr(analysis, "_rotation_cache", None)
    if cache is None:
        doc = pymupdf.open("pdf", analysis.working)
        cache = [p.rotation_matrix for p in doc]
        doc.close()
        analysis._rotation_cache = cache  # type: ignore[attr-defined]
    return cache[page]
