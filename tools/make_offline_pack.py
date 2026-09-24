"""Build the offline advanced-AI pack (zip) for computers without Internet access.

Usage: uv run python tools/make_offline_pack.py [output.zip]
Import it from the app: «Importar paquete sin conexión (.zip)». Checksums are verified on import.
"""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine import models  # noqa: E402

target = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/Anonimato-IA-avanzada.zip")
target.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
    for item in models.load_manifest()["advanced"]:
        if not item.path.exists():
            raise SystemExit(f"Falta {item.id}: ejecuta tools/fetch_models.py advanced")
        archive.write(item.path, Path(item.file).name)
print(f"Paquete creado: {target}")
