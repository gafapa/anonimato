"""Build the offline advanced-AI pack (zip) for computers without Internet access.

Usage: uv run python tools/make_offline_pack.py [output.zip] [advanced|advanced_lite]
Import it from the app: «Importar paquete sin conexión (.zip)». Checksums are verified on import.
"""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine import models

target = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/Anonimato-IA-avanzada.zip")
group = sys.argv[2] if len(sys.argv) > 2 else "advanced"
target.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
    for item in models.load_manifest()[group]:
        if not item.path.exists():
            raise SystemExit(f"Falta {item.id}: ejecuta tools/fetch_models.py {group}")
        archive.write(item.path, item.file)
print(f"Paquete creado: {target}")
