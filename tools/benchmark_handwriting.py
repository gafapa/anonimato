"""Handwriting OCR benchmark (plan phase 4.0).

Compares the printed-text recogniser with the candidate vision-language models on:
  * IAM-line (English handwriting, MIT on Hugging Face, Teklia/IAM-line, test split)
  * FrenchCensus handwritten texts (names, Latin script, MIT, agomberto/..., test split)
  * Synthetic Spanish lines with personal data written in handwriting-style fonts
  * Your own annotated lines, if present: eval/own/*.png + eval/own/labels.json {"file.png": "text"}

Metrics: character error rate (CER), exact-line accuracy, personal-data recall (synthetic/own:
share of lines whose personal data is still detected after transcription) and seconds per line.
Results: docs/benchmark.md. Data is cached under eval/ (ignored by git).

Usage: uv run python tools/benchmark_handwriting.py [--n 60] [--models ppocr,qwen3vl-4b,qwen3vl-8b,paddleocr-vl]
"""
from __future__ import annotations

import argparse
import io
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.engine import models, rules  # noqa: E402
from app.engine.system import font as system_font  # noqa: E402
from app.engine.llm_server import LlamaServer, image_part  # noqa: E402
from app.engine.ocr.handwriting import PROMPT  # noqa: E402

EVAL = ROOT / "eval"
CANDIDATES = {
    "qwen3vl-4b": ("vlm", "vlm-mmproj", PROMPT),
    "qwen3vl-8b": ("qwen3vl-8b", "qwen3vl-8b-mmproj", PROMPT),
    "paddleocr-vl": ("paddleocr-vl", "paddleocr-vl-mmproj", "OCR:"),
}


PARQUET = {
    "iam": ("https://huggingface.co/datasets/Teklia/IAM-line/resolve/main/data/test.parquet", "iam_test.parquet"),
    "census": ("https://huggingface.co/datasets/agomberto/FrenchCensus-handwritten-texts/resolve/main/data/"
               "test-00000-of-00001.parquet", "census_test.parquet"),
}


def fetch_rows(key: str, n: int, seed: int = 7) -> list[tuple[Image.Image, str]]:
    import pyarrow.parquet as pq
    url, name = PARQUET[key]
    path = EVAL / "hw" / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, path)
    table = pq.read_table(path).to_pylist()
    picks = sorted(random.Random(seed).sample(range(len(table)), min(n, len(table))))
    return [(Image.open(io.BytesIO(table[i]["image"]["bytes"])).convert("RGB"), table[i]["text"]) for i in picks]


SYNTH_LINES = [
    "Juan García Pérez", "DNI 12345678Z", "Xabier Etxeberria Goikoetxea", "Tel. 612 345 678",
    "C/ Mayor 5, 3ºA, Madrid", "María del Carmen Rodríguez", "X1234567L", "Rúa do Franco 14, Santiago",
    "Uxía Rial Lorenzo", "maria.lopez@correo.es", "ES91 2100 0418 4502 0005 1332", "Avda. de América 12",
    "Nacido el 3 de marzo de 1990", "Aaliyah Kuznetsova", "Plaza de España 3, Sevilla", "91 234 56 78",
]
SYNTH_FONTS = ["hand", "hand2", "hand3", "comic"]


def synthetic(n: int, seed: int = 11) -> list[tuple[Image.Image, str]]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        text = SYNTH_LINES[i % len(SYNTH_LINES)]
        font = ImageFont.truetype(system_font(SYNTH_FONTS[(i // len(SYNTH_LINES)) % len(SYNTH_FONTS)]), rng.randint(30, 44))
        width = int(font.getlength(text)) + 40
        image = Image.new("RGB", (width, 80), (rng.randint(235, 255),) * 3)
        ImageDraw.Draw(image).text((20, 12), text, fill=(rng.randint(10, 60), rng.randint(10, 60), rng.randint(60, 140)), font=font)
        image = image.rotate(rng.uniform(-2.5, 2.5), expand=True, fillcolor=(250, 250, 250))
        if rng.random() < 0.5:
            image = image.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.9)))
        out.append((image, text))
    return out


def own() -> list[tuple[Image.Image, str]]:
    folder = EVAL / "own"
    labels = folder / "labels.json"
    if not labels.exists():
        return []
    data = json.loads(labels.read_text(encoding="utf-8"))
    return [(Image.open(folder / name).convert("RGB"), text) for name, text in data.items()]


def norm(text: str) -> str:
    return " ".join(text.replace("|", " ").replace("/", " ").replace("¤", " ").split())


def census_names(truth: str) -> list[str]:
    fields = [f.strip() for f in truth.split("/")[:2]]
    return [w for f in fields if f and f != "¤" for w in f.split()]


def pii_kept(truth: str, reading: str, names: list[str] | None = None) -> bool | None:
    """True if every personal datum of the truth line is still detected in the reading."""
    if names is not None:
        from rapidfuzz import fuzz
        if not names:
            return None
        return all(fuzz.partial_ratio(n.lower(), reading.lower()) >= 85 for n in names)
    wanted = {m.type for m in rules.detect_all(truth)}
    if not wanted:
        return None
    got = {m.type for m in rules.detect_all(reading)}
    return wanted <= got


def run_engine(name: str, samples: list[tuple[Image.Image, str]]) -> list[tuple[str, float]]:
    readings = []
    if name == "ppocr":
        from app.engine.ocr.printed import Recognizer
        recognizer = Recognizer(False)
        for image, _ in samples:
            started = time.time()
            text = recognizer.recognize([np.asarray(image)])[0][0]
            readings.append((text, time.time() - started))
        return readings
    model_id, mmproj_id, prompt = CANDIDATES[name]
    server = LlamaServer(str(models.model(model_id).path), str(models.model(mmproj_id).path))
    server.start()
    try:
        for image, _ in samples:
            started = time.time()
            try:
                text = server.chat([{"role": "user", "content": [image_part(np.asarray(image)), {"type": "text", "text": prompt}]}],
                                   max_tokens=160)
            except Exception as error:  # noqa: BLE001
                text = f"<error {error}>"
            readings.append((norm(text), time.time() - started))
    finally:
        server.stop()
    return readings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=60)
    parser.add_argument("--models", default="ppocr,qwen3vl-4b,qwen3vl-8b,paddleocr-vl")
    args = parser.parse_args()
    sets = {
        "IAM (inglés)": fetch_rows("iam", args.n),
        "Censo francés (nombres)": fetch_rows("census", args.n),
        "Sintético español con datos personales": synthetic(args.n),
    }
    mine = own()
    if mine:
        sets["Tus documentos"] = mine
    engines = [m for m in args.models.split(",") if m == "ppocr" or models.model(CANDIDATES[m][0]).path.exists()]
    results: dict[str, dict[str, dict]] = {}
    for engine in engines:
        print(f"== {engine}", flush=True)
        for set_name, samples in sets.items():
            readings = run_engine(engine, samples)
            cers, exact, kept, seconds = [], 0, [], []
            census = set_name.startswith("Censo")
            for (image, truth), (reading, secs) in zip(samples, readings):
                truth_n, reading_n = norm(truth), norm(reading)
                if census:
                    # Table rows with empty cells and abbreviations: measure the error on the names only.
                    from app.engine.verify import substring_distance
                    names = census_names(truth)
                    if names:
                        total = sum(len(n) for n in names)
                        cers.append(sum(substring_distance(n.lower(), reading_n.lower()) for n in names) / total)
                else:
                    cers.append(Levenshtein.distance(truth_n, reading_n) / max(1, len(truth_n)))
                exact += truth_n == reading_n
                seconds.append(secs)
                flag = pii_kept(truth_n, reading_n, census_names(truth) if set_name.startswith("Censo") else None)
                if flag is not None:
                    kept.append(flag)
            results.setdefault(set_name, {})[engine] = {
                "cer": float(np.mean(cers)), "exact": exact / len(samples),
                "pii": (sum(kept) / len(kept)) if kept else None, "seconds": float(np.median(seconds)),
            }
            print(f"   {set_name}: {results[set_name][engine]}", flush=True)
    lines = ["# Comparativa de OCR manuscrito", "",
             f"Generado: {time.strftime('%Y-%m-%d %H:%M')} · equipo: RTX 2070 8 GB (Vulkan) · {args.n} líneas por conjunto.", "",
             "CER = error por carácter (menor es mejor; en el censo, solo sobre los nombres). Exactas = líneas idénticas.",
             "Datos personales = líneas cuyos datos personales siguen detectándose tras la transcripción (en el censo:",
             "nombres y apellidos leídos con ≤ 15 % de error). Tiempo = mediana por línea.", ""]
    for set_name, per_engine in results.items():
        lines += [f"## {set_name}", "", "| Motor | CER | Exactas | Datos personales | s/línea |", "|---|---|---|---|---|"]
        for engine, r in per_engine.items():
            pii = "—" if r["pii"] is None else f"{r['pii'] * 100:.0f} %"
            lines.append(f"| {engine} | {r['cer'] * 100:.1f} % | {r['exact'] * 100:.0f} % | {pii} | {r['seconds']:.2f} |")
        lines.append("")
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "benchmark.md").write_text("\n".join(lines), encoding="utf-8")
    (EVAL / "benchmark.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
