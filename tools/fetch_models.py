"""Download model groups listed in models/manifest.json.

Usage: uv run python tools/fetch_models.py base runtime [advanced] [candidates] [--pin]
--pin records the SHA-256 of downloaded files that have no checksum yet.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine import models  # noqa: E402


def main() -> None:
    groups = [arg for arg in sys.argv[1:] if not arg.startswith("--")] or ["base", "runtime"]
    pin = "--pin" in sys.argv
    manifest = models.load_manifest()
    last = {}

    def progress(model_id: str, done: int, total: int) -> None:
        percent = int(done * 100 / total) if total else 0
        if last.get(model_id) != percent and percent % 10 == 0:
            last[model_id] = percent
            print(f"  {model_id}: {percent}% ({done >> 20} MB)", flush=True)

    for group in groups:
        for item in manifest[group]:
            print(f"[{group}] {item.id}", flush=True)
            models.download(item, progress)

    if pin:
        raw = json.loads(models.manifest_path().read_text(encoding="utf-8"))
        for group in groups:
            for entry in raw[group]:
                item = models.model(entry["id"])
                if not entry["sha256"] and item.path.exists():
                    entry["sha256"] = models.sha256_of(item.path)
        # Every llama.cpp file that the application ships is pinned too (checked at start-up).
        runtime = models.runtime_dir() / "llama"
        if runtime.exists():
            shipped = ("ggml", "llama-server", "llama.dll", "llama-common", "mtmd", "libomp")
            raw["runtime_files"] = {
                f"llama/{path.name}": models.sha256_of(path)
                for path in sorted(runtime.iterdir())
                if path.suffix in (".exe", ".dll") and path.name.startswith(shipped)
            }
        models.manifest_path().write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        print("Checksums pinned.")


if __name__ == "__main__":
    main()
