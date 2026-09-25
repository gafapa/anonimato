"""Detection evaluation (plan phase 4): recall and precision per category.

Builds a synthetic but varied Spanish corpus with ground truth (native PDFs and scanned
versions with noise and slight rotation), or uses your own annotated set:
  eval/docs/<name>.pdf + eval/docs/<name>.json  ->  [{"type": "dni", "value": "12345678Z"}, ...]

Recall  = share of ground-truth values that end up fully covered by an enabled finding.
Precision = share of findings that overlap some ground-truth value.
Usage: uv run python tools/evaluate_detection.py [--docs 40] [--scanned] [--advanced]
Results: docs/deteccion.md
"""
from __future__ import annotations

import argparse
import io
import json
import random
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


def scanned(data: bytes, rng) -> bytes:
    page = pymupdf.open("pdf", data)[0]
    pix = page.get_pixmap(dpi=150)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    image = image.rotate(rng.uniform(-1.2, 1.2), expand=False, fillcolor="white", resample=Image.BICUBIC)
    noise = np.random.default_rng(rng.randint(0, 1000)).normal(0, 9, (image.height, image.width, 1))
    image = Image.fromarray(np.clip(np.asarray(image, dtype=np.float32) + noise, 0, 255).astype(np.uint8))
    image = image.filter(ImageFilter.GaussianBlur(0.5))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=70)
    out = pymupdf.open()
    target = out.new_page(width=595, height=842)
    target.insert_image(target.rect, stream=buffer.getvalue())
    return out.tobytes()


def covered(analysis: pipeline.Analysis, value: str) -> bool:
    """The whole value is inside the union of enabled findings, in some text source."""
    import regex as re
    words = NormalizedText(value).text.split()
    pattern = r"[\s,]*".join(re.escape(w) for w in words) if len(words) > 1 else re.escape(words[0])
    for sources in analysis.sources.values():
        for _, source in sources:
            norm = NormalizedText(source.text)
            for match in re.finditer(pattern, norm.text):
                begin, end = norm.span(match.start(), match.end())
                rects = source.rects_for(begin, end)
                if rects and all(_rect_covered(analysis, r) for r in rects):
                    return True
            if _span_covered(analysis, source, value):
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


def _span_covered(analysis, source, value) -> bool:
    import regex as re
    pattern = r"[\s.\-/]?".join(re.escape(c) for c in re.sub(r"\W", "", value))
    for match in re.finditer(pattern, source.text):
        rects = source.rects_for(match.start(), match.end())
        if rects and all(_rect_covered(analysis, r) for r in rects):
            return True
    return False


def _rect_covered(analysis, rect) -> bool:
    x0, y0, x1, y1 = rect
    width = x1 - x0
    if width <= 0:
        return True
    parts = []
    for finding in analysis.findings:
        if not finding.enabled:
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
    args = parser.parse_args()
    rng = random.Random(2026)
    services = Services()
    categories = set(rules.SELECTABLE) - rules.DEFAULT_OFF
    options = Options(categories=categories, handwriting=args.advanced, llm_review=args.advanced)
    corpus = []
    own = ROOT / "eval" / "docs"
    if own.exists():
        for pdf in sorted(own.glob("*.pdf")):
            corpus.append(("propio", pdf.name, pdf.read_bytes(), json.loads(pdf.with_suffix(".json").read_text("utf-8"))))
    for index in range(args.docs):
        data, truth = document(rng, index)
        corpus.append(("nativo", f"sint-{index}", data, truth))
        if args.scanned:
            corpus.append(("escaneado", f"sint-{index}", scanned(data, rng), truth))
    stats: dict[tuple[str, str], list[int]] = {}
    precision_hits = precision_total = 0
    misses = []
    false_positives = []
    started = time.time()
    for kind, name, data, truth in corpus:
        analysis = pipeline.analyze(data, name + ".pdf", options, services)
        for item in truth:
            ok = covered(analysis, item["value"])
            stats.setdefault((kind, item["type"]), [0, 0])
            stats[(kind, item["type"])][0] += ok
            stats[(kind, item["type"])][1] += 1
            if not ok:
                misses.append(f"{kind} {name}: {item['type']} «{item['value']}»")
        for finding in analysis.findings:
            if not finding.value:
                continue
            precision_total += 1
            value = " ".join(NormalizedText(finding.value).text.split())
            hit = any(value in " ".join(NormalizedText(t["value"]).text.split())
                      or " ".join(NormalizedText(t["value"]).text.split()) in value for t in truth)
            precision_hits += hit
            if not hit:
                false_positives.append(f"{kind} {name}: {finding.type} «{finding.value}» ({finding.source})")
    seconds = time.time() - started
    lines = ["# Evaluación de la detección", "",
             f"Generado: {time.strftime('%Y-%m-%d %H:%M')} · {len(corpus)} documentos · {seconds:.0f} s · "
             f"IA avanzada: {'sí' if args.advanced else 'no'}", "",
             "Recall = valores reales completamente cubiertos por un hallazgo. Objetivos del plan: ≥ 98 % en",
             "identificadores y ≥ 95 % en nombres impresos.", "",
             "| Conjunto | Categoría | Recall | Valores |", "|---|---|---|---|"]
    for (kind, category), (hit, total) in sorted(stats.items()):
        lines.append(f"| {kind} | {rules.CATEGORIES[category]['label']} | {100 * hit / total:.1f} % | {total} |")
    lines += ["", f"Precisión global: {100 * precision_hits / max(1, precision_total):.1f} % "
                  f"({precision_hits}/{precision_total} hallazgos con valor).", ""]
    if misses:
        lines += ["## Valores no cubiertos", ""] + [f"- {m}" for m in misses[:80]] + [""]
    if false_positives:
        lines += ["## Hallazgos sin correspondencia (posibles falsos positivos)", ""] + [f"- {m}" for m in false_positives[:80]]
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "deteccion.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
