"""Replacement logs (CSV / JSON). Originals and coordinates are excluded unless requested."""
from __future__ import annotations

import csv
import copy
import io
import json
from datetime import datetime, UTC

from .rules import CATEGORIES
from .types import Finding


def _cell(value) -> str:
    text = "" if value is None else str(value)
    first = text.lstrip(" \t\r\n")[:1]
    return "'" + text if first in ("=", "+", "-", "@") or text[:1] in ("\t", "\r", "\n") else text


def private_report(report: dict | None, include_coords: bool = False) -> dict | None:
    report = copy.deepcopy(report)
    if report:
        for leak in report.get("leaks", []):
            if "value" in leak:
                leak["value"] = "…"
            if not include_coords:
                leak.pop("rects", None)
                leak.pop("view", None)
    return report


def build_csv(findings: list[Finding], include_originals: bool = False, include_coords: bool = False) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    head = ["página", "tipo", "confianza", "origen", "reemplazo"]
    if include_originals:
        head.insert(4, "valor original")
    if include_coords:
        head += ["x0", "y0", "x1", "y1"]
    writer.writerow(head)
    for f in findings:
        if not f.enabled:
            continue
        row = [f.page + 1, CATEGORIES[f.type]["label"], f"{round(f.confidence * 100)} %", f.source, f.token]
        if include_originals:
            row.insert(4, f.value or "")
        if include_coords and f.rects:
            row += [round(v, 1) for v in f.rects[0]]
        writer.writerow([_cell(v) for v in row])
    return "\ufeff" + buffer.getvalue()


def build_json(findings: list[Finding], pages: int, report: dict | None, include_originals: bool = False,
               include_coords: bool = False) -> str:
    enabled = [f for f in findings if f.enabled]
    mapping: dict[str, dict] = {}
    for f in enabled:
        entry = mapping.setdefault(f.token, {"tipo": CATEGORIES[f.type]["label"], "reemplazo": f.token, "ocurrencias": 0})
        entry["ocurrencias"] += 1
        if include_originals and f.value:
            entry["originales"] = sorted({f.value} | set(entry.get("originales", [])))
    report = private_report(report, include_coords)
    data = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "paginas": pages,
        "resumen": {"sustituciones": len(enabled), "valoresUnicos": len(mapping),
                    "rostros": sum(1 for f in enabled if f.type == "face")},
        "verificacion": report,
        "sustituciones": [
            {"pagina": f.page + 1, "tipo": CATEGORIES[f.type]["label"], "confianza": f.confidence, "origen": f.source,
             "reemplazo": f.token, **({"original": f.value} if include_originals else {}),
             **({"rect": [round(v, 1) for v in f.rects[0]]} if include_coords and f.rects else {})}
            for f in enabled
        ],
        "mapeo": list(mapping.values()),
    }
    return json.dumps(data, ensure_ascii=False, indent=2)
