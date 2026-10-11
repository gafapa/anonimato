"""Detection evaluation (plan phase 4): recall and precision per category.

Builds a synthetic but varied Spanish corpus with ground truth (native PDFs and scanned
versions with noise and slight rotation), or uses your own annotated set:
  eval/docs/<name>.pdf + eval/docs/<name>.json  ->  [{"type": "dni", "value": "12345678Z"}, ...]

Recall  = share of ground-truth values that end up fully covered by an enabled finding.
Precision = share of findings that overlap some ground-truth value.
Usage: uv run python tools/evaluate_detection.py [--docs 40] [--scanned] [--advanced]
Private corpus: add --private --output tmp/private-evaluation.md (aggregate results only).
Results: docs/deteccion.md
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import random
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.engine import pipeline, rules  # noqa: E402
from app.engine.propagate import NormalizedText  # noqa: E402
from app.engine.rules import DNI_LETTERS  # noqa: E402
from app.engine.services import Services  # noqa: E402
from app.engine.types import Options  # noqa: E402

FIRST = ["Lucía", "Martín", "Uxía", "Iker", "Nerea", "Hugo", "Aitana", "Brais", "Leire", "Óscar", "Carmen", "Jordi",
         "Mireia", "Sergio", "Rocío", "Andrés", "Zuriñe", "Maialen", "Telmo", "Noa"]
RARE_FIRST = ["Aldara", "Iraitz", "Xiana", "Eneko", "Oihana", "Sheila", "Yeray", "Ximena", "Anxo", "Jaione"]
SURNAMES = ["García", "Fernández", "López", "Martínez", "Sánchez", "Pérez", "Gómez", "Díaz", "Rial", "Seoane",
            "Etxeberria", "Puig", "Castro", "Varela", "Iglesias", "Otero", "Bouzas", "Garmendia", "Soler", "Vidal"]
RARE_SURNAMES = ["Arrizabalaga", "Quintairos", "Villarrubia", "Eguzkitza", "Barreiro-Loureiro", "Sotomaior",
                 "Casteleiro", "Urquiola", "Mouriño", "Castrillón"]
STREETS = ["Calle Mayor", "C/ Real", "Avda. de la Constitución", "Rúa do Vilar", "Plaza de España", "Paseo de Gracia",
           "Calle San Roque", "Avenida de Madrid", "Rúa Nova", "Camino de Ronda"]
CITIES = [("15702", "Santiago de Compostela"), ("28013", "Madrid"), ("08007", "Barcelona"), ("41004", "Sevilla"),
          ("36201", "Vigo"), ("48001", "Bilbao"), ("46001", "Valencia"), ("33003", "Oviedo")]
CONDITIONS = ["diabetes tipo 2", "hipertensión arterial", "trastorno de ansiedad", "asma bronquial", "epilepsia"]


def dni(rng):
    number = rng.randint(10_000_000, 99_999_999)
    return f"{number}{DNI_LETTERS[number % 23]}"


def nie(rng):
    prefix = rng.choice("XYZ")
    number = rng.randint(1_000_000, 9_999_999)
    return f"{prefix}{number}{DNI_LETTERS[int(str('XYZ'.index(prefix)) + str(number)) % 23]}"


def iban(rng):
    bban = "".join(str(rng.randint(0, 9)) for _ in range(20))
    check = 98 - int(bban + "142800") % 97
    raw = f"ES{check:02d}{bban}"
    return " ".join(raw[i:i + 4] for i in range(0, 24, 4))


def nss(rng):
    province, middle = rng.randint(1, 52), rng.randint(10_000_000, 99_999_999)
    control = int(f"{province:02d}{middle}") % 97
    return f"{province:02d}/{middle}/{control:02d}"


def phone(rng):
    first = rng.choice("6789")
    digits = first + "".join(str(rng.randint(0, 9)) for _ in range(8))
    style = rng.randint(0, 2)
    if style == 0:
        return f"{digits[:3]} {digits[3:6]} {digits[6:]}"
    if style == 1:
        return f"{digits[:3]} {digits[3:5]} {digits[5:7]} {digits[7:]}"
    return f"+34 {digits}"


def person(rng):
    first = rng.choice(RARE_FIRST if rng.random() < 0.3 else FIRST)
    s1 = rng.choice(RARE_SURNAMES if rng.random() < 0.3 else SURNAMES)
    s2 = rng.choice(SURNAMES)
    return f"{first} {s1} {s2}"


def address(rng):
    postcode, city = rng.choice(CITIES)
    return f"{rng.choice(STREETS)} {rng.randint(1, 120)}, {rng.randint(1, 8)}º{rng.choice('ABCD')}, {postcode} {city}"


def document(rng, index: int) -> tuple[bytes, list[dict]]:
    p1, p2 = person(rng), person(rng)
    truth = []

    def use(kind, value):
        truth.append({"type": kind, "value": value})
        return value

    template = index % 6
    if template == 0:
        lines = [
            "CONTRATO DE ARRENDAMIENTO DE VIVIENDA",
            f"De una parte, D. {use('name', p1)}, con DNI {use('dni', dni(rng))} y domicilio en {use('address', address(rng))}.",
            f"De otra parte, Dña. {use('name', p2)}, con NIE {use('nie', nie(rng))}, teléfono {use('phone', phone(rng))}.",
            f"El pago se realizará en la cuenta {use('iban', iban(rng))}.",
            "Ambas partes se reconocen capacidad legal suficiente para obligarse.",
        ]
    elif template == 1:
        lines = [
            "INFORME CLÍNICO DE ALTA",
            f"Paciente: {use('name', p1)}    NSS: {use('nss', nss(rng))}",
            f"Fecha de nacimiento: {use('date', f'{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(1940, 2010)}')}",
            f"Diagnóstico principal: {use('health', rng.choice(CONDITIONS))}.",
            f"Contacto: {use('email', p1.split()[0].lower() + '.' + p1.split()[1].lower() + '@correo.es')}",
            "Se recomienda seguimiento en consultas externas en tres meses.",
        ]
    elif template == 2:
        lines = [
            "SOLICITUD DE MATRÍCULA",
            f"Apellidos y nombre: {use('name', p1)}",
            f"DNI/NIE: {use('dni', dni(rng))}",
            f"Domicilio: {use('address', address(rng))}",
            f"Teléfono móvil: {use('phone', phone(rng))}",
            "Curso solicitado: 2º de Bachillerato, modalidad de Ciencias.",
        ]
    elif template == 3:
        lines = [
            "Estimado cliente:",
            f"Le informamos de que el recibo asociado a {use('name', p1)} ha sido devuelto.",
            f"Puede contactarnos en el {use('phone', phone(rng))} o regularizar el pago en {use('iban', iban(rng))}.",
            f"Referencia del vehículo asegurado: matrícula {use('plate', f'{rng.randint(1000, 9999)} ' + ''.join(rng.choice('BCDFGHJKLMNPRSTVWXYZ') for _ in range(3)))}.",
            "Atentamente, el Departamento de Atención al Cliente.",
        ]
    elif template == 4:
        lines = [
            "RELACIÓN DE ASISTENTES",
            f"1. {use('name', p1)} — {use('dni', dni(rng))}",
            f"2. {use('name', p2)} — {use('dni', dni(rng))}",
            f"3. {use('name', person(rng))} — {use('nie', nie(rng))}",
            "Total de asistentes: 3",
        ]
    else:
        lines = [
            "ACTA DE LA REUNIÓN",
            f"Comparecen {use('name', p1)} y {use('name', p2)}, vecinos de {CITIES[index % len(CITIES)][1]}.",
            f"La Sra. {p2.split()[1]} expone que la tarjeta {use('card', '4111 1111 1111 1111')} fue utilizada sin permiso.",
            f"Se acuerda remitir copia al correo {use('email', 'vecinos' + str(index) + '@comunidad.org')}.",
        ]
        truth.append({"type": "name", "value": p2.split()[1], "partial": True})
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 90
    for line in lines:
        rect = pymupdf.Rect(60, y, 540, y + 60)
        page.insert_textbox(rect, line, fontsize=11 if not line.isupper() else 13, fontname="helv")
        y += 44
    return doc.tobytes(), truth


def scanned(data: bytes, rng, truth=None):
    page = pymupdf.open("pdf", data)[0]
    pix = page.get_pixmap(dpi=150)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    angle = rng.uniform(-1.2, 1.2)
    image = image.rotate(angle, expand=False, fillcolor="white", resample=Image.BICUBIC)
    noise = np.random.default_rng(rng.randint(0, 1000)).normal(0, 9, (image.height, image.width, 1))
    image = Image.fromarray(np.clip(np.asarray(image, dtype=np.float32) + noise, 0, 255).astype(np.uint8))
    image = image.filter(ImageFilter.GaussianBlur(0.5))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=70)
    out = pymupdf.open()
    target = out.new_page(width=595, height=842)
    target.insert_image(target.rect, stream=buffer.getvalue())
    if truth is not None:
        from tools.occurrence_evaluation import project
        return out.tobytes(), project(truth, page, target, image.size, angle=angle)
    return out.tobytes()


def covered(analysis: pipeline.Analysis, value: str) -> bool:
    """The whole value is inside the union of enabled findings, in some text source."""
    import regex as re
    words = NormalizedText(value).text.split()
    pattern = r"[\s,]*".join(re.escape(w) for w in words) if len(words) > 1 else re.escape(words[0])
    for page, sources in analysis.sources.items():
        for _, source in sources:
            norm = NormalizedText(source.text)
            for match in re.finditer(pattern, norm.text):
                begin, end = norm.span(match.start(), match.end())
                rects = source.rects_for(begin, end)
                if rects and all(_rect_covered(analysis, r, page) for r in rects):
                    return True
            if _span_covered(analysis, source, value, page):
                return True
    # OCR misreadings ("Vig0" for "Vigo"): a finding whose value is within 2 edits of the truth.
    from app.engine.verify import substring_distance
    target = " ".join(NormalizedText(value).text.split())
    for finding in analysis.findings:
        if finding.enabled and finding.value:
            found = " ".join(NormalizedText(finding.value).text.split())
            if len(found) >= len(target) - 2 and substring_distance(target, found) <= 2:
                return True
    return False


def _span_covered(analysis, source, value, page) -> bool:
    import regex as re
    pattern = r"[\s.\-/]?".join(re.escape(c) for c in re.sub(r"\W", "", value))
    for match in re.finditer(pattern, source.text):
        rects = source.rects_for(match.start(), match.end())
        if rects and all(_rect_covered(analysis, r, page) for r in rects):
            return True
    return False


def _rect_covered(analysis, rect, page) -> bool:
    x0, y0, x1, y1 = rect
    width = x1 - x0
    if width <= 0:
        return True
    parts = []
    for finding in analysis.findings:
        if not finding.enabled or finding.page != page:
            continue
        for fx0, fy0, fx1, fy1 in finding.rects:
            if min(y1, fy1) - max(y0, fy0) > 0.4 * (y1 - y0):
                parts.append((max(x0, fx0 - 1.5), min(x1, fx1 + 1.5)))
    parts.sort()
    reach = x0
    for a, b in parts:
        if a > reach + 0.5:
            break
        reach = max(reach, b)
    return reach >= x1 - 0.5


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", type=int, default=40)
    parser.add_argument("--scanned", action="store_true")
    parser.add_argument("--advanced", action="store_true")
    parser.add_argument("--private", action="store_true", help="Include local annotated documents; output is aggregate-only")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    output = args.output or ROOT / "docs" / "deteccion.md"
    if args.private and (args.output is None or not output.resolve().is_relative_to((ROOT / "tmp").resolve())):
        parser.error("Private evaluation requires --output inside ignored tmp/; no names or values are included")
    rng = random.Random(args.seed)
    services = Services()
    categories = set(rules.SELECTABLE) - rules.DEFAULT_OFF
    options = Options(categories=categories, handwriting=args.advanced, llm_review=args.advanced)
    corpus = []
    own = ROOT / "eval" / "docs"
    if args.private and own.exists():
        for index, pdf in enumerate(sorted(own.glob("*.pdf"))):
            truth = json.loads(pdf.with_suffix(".json").read_text("utf-8"))
            if not isinstance(truth, list) or any(not isinstance(item, dict) or not isinstance(item.get('type'), str)
                                                  or item.get('type') not in rules.CATEGORIES
                                                  or not isinstance(item.get('value'), str) for item in truth):
                parser.error('Private annotations require supported category keys and string values')
            corpus.append(("private", f"private-{index}", pdf.read_bytes(), truth))
    for index in range(args.docs):
        data, truth = document(rng, index)
        from tools.occurrence_evaluation import annotate
        truth = annotate(data, truth)
        corpus.append(("native", f"synthetic-{index}", data, truth))
        if args.scanned:
            scan, scan_truth = scanned(data, rng, truth)
            corpus.append(("scanned", f"synthetic-{index}", scan, scan_truth))
    from tools.evaluation_corpus import challenging_documents
    corpus.extend(challenging_documents(args.seed, include_scanned=args.scanned))
    stats: dict[tuple[str, str], list[int]] = {}
    occurrence_stats = {}
    unlocated = 0
    precision_hits = precision_total = 0
    misses = []
    positional_misses = []
    false_positives = []
    started = time.time()
    for kind, name, data, truth in corpus:
        analysis = pipeline.analyze(data, name + ".pdf", options, services)
        for item in truth:
            from tools.occurrence_evaluation import coverage
            hits, occurrences = coverage(analysis, item)
            positional = occurrence_stats.setdefault((kind, item["type"]), [0, 0])
            positional[0] += hits
            positional[1] += occurrences
            if kind != 'private' and hits != occurrences:
                from tools.occurrence_evaluation import rect_covered
                for index, occurrence in enumerate(item.get('occurrences', [])):
                    if not occurrence.get('rects') or not all(rect_covered(analysis, rect, occurrence['page'])
                                                            for rect in occurrence['rects']):
                        positional_misses.append(f"{kind} {name}: {item['type']}, occurrence {index + 1}, "
                                                 f"page {occurrence['page'] + 1}")
            unlocated += not occurrences
            ok = covered(analysis, item["value"])
            stats.setdefault((kind, item["type"]), [0, 0])
            stats[(kind, item["type"])][0] += ok
            stats[(kind, item["type"])][1] += 1
            if not ok:
                if kind != "private":
                    misses.append(f"{kind} {name}: {item['type']} «{item['value']}»")
        for finding in analysis.findings:
            if not finding.value or not finding.enabled:
                continue
            precision_total += 1
            value = " ".join(NormalizedText(finding.value).text.split())
            hit = any(value in " ".join(NormalizedText(t["value"]).text.split())
                      or " ".join(NormalizedText(t["value"]).text.split()) in value for t in truth)
            precision_hits += hit
            if not hit and kind != "private":
                false_positives.append(f"{kind} {name}: {finding.type} «{finding.value}» ({finding.source})")
    seconds = time.time() - started
    provenance = {"corpus": "synthetic-v3-positional", "seed": args.seed,
                  "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip(),
                  "dirty": bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()),
                  "hardware": {"platform": platform.platform(), "processor": platform.processor()},
                  "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
                  "manifest_sha256": hashlib.sha256((ROOT / "models/manifest.json").read_bytes()).hexdigest(),
                  "public_truth_sha256": hashlib.sha256(json.dumps([(kind, name, truth) for kind, name, _, truth in corpus
                                                                      if kind != "private"], sort_keys=True).encode()).hexdigest(),
                  "backends": services.status()["backends"]}
    lines = ["# Detection evaluation", "", "Provenance: " + json.dumps(provenance, sort_keys=True), "",
             f"Generated: {time.strftime('%Y-%m-%d %H:%M')} · {len(corpus)} documents · {seconds:.0f} s · "
             f"advanced AI: {'yes' if args.advanced else 'no'}", "",
             "Recall = ground-truth values fully covered by a finding. Targets: at least 98% for",
             "identifiers and 95% for printed names.", "",
             "This value-level metric accepts coverage in one occurrence; it does not measure every repeated occurrence,",
             "manual review effort, or handwriting accuracy on representative private documents.", "",
             "| Dataset | Category | Recall | Values |", "|---|---|---|---|"]
    category_labels = {
        "name": "Names", "dni": "DNI / NIF", "nie": "NIE", "cif": "CIF",
        "passport": "Passport", "nss": "Social Security number", "email": "Email",
        "phone": "Phone", "url": "URL", "ip": "IP address", "plate": "License plate",
        "date": "Date of birth", "address": "Address", "iban": "IBAN / account",
        "bic": "BIC / SWIFT", "card": "Payment card", "id_other": "Other identifiers",
        "health": "Health data", "org": "Organizations", "other": "Other personal data",
        "handwriting": "Handwriting", "signature": "Signature", "face": "Face",
    }
    for (kind, category), (hit, total) in sorted(stats.items()):
        lines.append(f"| {kind} | {category_labels.get(category, category)} | {100 * hit / total:.1f} % | {total} |")
    lines += ["", "## Complete positional occurrence coverage", "",
              "Every annotated occurrence requires 98% two-dimensional coverage of all its rectangles (1.5pt glyph tolerance).",
              "This conservative bounding-box diagnostic is separate from pixel-level leakage verification and final export checks.",
              "Original positions are extracted before detection and projected through the exact raster transforms.",
              "Private inputs need explicit occurrences with page and rects. Unlocated targets are never positional successes.", "",
              "| Dataset | Category | Covered | Occurrences | Recall |", "|---|---|---|---|---|"]
    for (kind, category), (hit, total) in sorted(occurrence_stats.items()):
        recall = f"{100 * hit / total:.1f}%" if total else "unlocated"
        lines.append(f"| {kind} | {category_labels.get(category, category)} | {hit} | {total} | {recall} |")
    lines += ["", f"Targets without positional annotations: {unlocated}; excluded from the positional denominator."]
    if positional_misses:
        lines += ['', '### Incompletely covered public occurrences', ''] + [f'- {miss}' for miss in positional_misses]
    lines += ["", f"Overall precision: {100 * precision_hits / max(1, precision_total):.1f} % "
                  f"({precision_hits}/{precision_total} findings with values).", ""]
    if misses:
        lines += ["## Uncovered values", ""] + [f"- {m}" for m in misses[:80]] + [""]
    if false_positives:
        lines += ["## Unmatched findings (possible false positives)", ""] + [f"- {m}" for m in false_positives[:80]]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
