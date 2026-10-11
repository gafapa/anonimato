"""Measure cold/warm local synthetic processing. Never reads user documents."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.engine.worker import EngineProcess  # noqa: E402
from app.engine.types import Options  # noqa: E402
from tools.evaluate_detection import document  # noqa: E402


def main() -> None:
    import random

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, choices=range(65), default=0)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/pipeline-profile.json")
    args = parser.parse_args()
    os.environ["ANONIMATO_CPU_THREADS"] = str(args.threads)
    os.environ["ANONIMATO_CPU"] = "1"
    data, _ = document(random.Random(2026), 2)
    options = Options(categories={"name", "dni", "phone", "address"}, handwriting=False, llm_review=False, faces=False)
    engine = EngineProcess(use_gpu=False)
    runs = []
    try:
        for label in ("cold", "warm"):
            stages: dict[str, float] = {}
            last = time.perf_counter()
            stage = "startup"

            def progress(event, stages=stages):
                nonlocal last, stage
                now = time.perf_counter()
                stages[stage] = stages.get(stage, 0) + now - last
                stage, last = event.get("stage", "other"), now

            started = time.perf_counter()
            analysis = engine.call("analyze", data, "synthetic.pdf", options, progress=progress)
            analyzed = time.perf_counter()
            result = engine.call("export", analysis, options, 1, False, progress=progress)
            finished = time.perf_counter()
            stages[stage] = stages.get(stage, 0) + finished - last
            runs.append({"run": label, "analysis_seconds": round(analyzed - started, 3),
                         "export_seconds": round(finished - analyzed, 3), "verified": result.report.ok,
                         "stages_seconds": {key: round(value, 3) for key, value in stages.items()},
                         "services": engine.call("status")})
            print(f"{label}: analysis {analyzed - started:.3f}s; export {finished - analyzed:.3f}s", flush=True)
    finally:
        engine.stop()
    report = {"platform": platform.platform(), "cpu_count": os.cpu_count(), "threads": args.threads,
              "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(), "runs": runs,
              "measurement": "Wall time between progress events includes loading; no document values are logged."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(args.output)
    if not all(run["verified"] for run in runs):
        raise SystemExit("Synthetic export verification failed")


if __name__ == "__main__":
    main()
