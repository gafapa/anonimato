"""Build an offline model pack (zip) for computers without Internet access.

Usage: uv run python tools/make_offline_pack.py [output.zip] [base|advanced|advanced_lite]
"base" holds the base models and this platform's llama.cpp runtime, which the application otherwise downloads
on first launch. Import it from the app: «Importar paquete sin conexión (.zip)». Checksums are verified on import.
"""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine import models

target = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/Anonimato-IA-avanzada.zip")
group = sys.argv[2] if len(sys.argv) > 2 else "advanced"
target.parent.mkdir(parents=True, exist_ok=True)
manifest = models.load_manifest()
items = manifest["base"] + models.for_this_platform(manifest["runtime"]) if group == "base" else manifest[group]
with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
    for item in items:
        if not item.path.exists():
            raise SystemExit(f"Falta {item.id}: ejecuta tools/fetch_models.py {item.group}")
        archive.write(item.path, models.pack_name(item))
print(f"Paquete creado: {target}")
