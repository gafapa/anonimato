"""Create an explicitly portable distribution from the platform's frozen application."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build() -> Path:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    platform = "windows-x64" if sys.platform == "win32" else "macos-arm64" if sys.platform == "darwin" else "linux-x86_64"
    suffix = ".tar.gz" if sys.platform == "linux" else ".zip"
    output = ROOT / "dist" / f"Privelto-{version}-{platform}-portable{suffix}"
    with tempfile.TemporaryDirectory(prefix="privelto-portable-", dir=ROOT / "build") as temporary:
        stage = Path(temporary) / "Privelto"
        source = ROOT / "dist" / ("Privelto.app" if sys.platform == "darwin" else "Privelto")
        if sys.platform == "darwin":
            stage.mkdir()
            shutil.copytree(source, stage / "Privelto.app", symlinks=True)
        else:
            shutil.copytree(source, stage, symlinks=True)
        (stage / "privelto-portable.json").write_text(json.dumps({"schema": 1}) + "\n", encoding="utf-8")
        (stage / "PORTABLE.txt").write_text(
            "Privelto portable\n\nExtract the entire archive into a writable folder before launching.\n"
            "Do not run the executable from inside the archive. Keep the marker beside the application.\n"
            "Application models, runtime, preferences and logs are stored in PriveltoData next to the application.\n"
            "The first launch downloads the required model/runtime pack; offline import is supported.\n"
            "Move the whole folder, including PriveltoData, to retain the portable profile.\n"
            "Operating-system and GPU-driver caches can still exist outside this folder.\n"
            "Windows requires Microsoft Edge WebView2 Runtime, installed separately when needed.\n",
            encoding="utf-8")
        if sys.platform == "darwin":
            subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(stage), str(output)], check=True)
        elif suffix == ".tar.gz":
            with tarfile.open(output, "w:gz") as archive:
                archive.add(stage, arcname="Privelto")
        else:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for path in stage.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(stage.parent))
    return output


if __name__ == "__main__":
    print(build())
