# PyInstaller spec: one-folder build with the base models and the llama.cpp runtime of this platform.
# Windows → dist/Anonimato (then Inno Setup); macOS → dist/Anonimato.app (then .dmg); Linux → dist/Anonimato (then AppImage).
import json
import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = Path(SPECPATH).parent
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
SYSTEM = "windows" if sys.platform == "win32" else "macos" if sys.platform == "darwin" else "linux"
manifest = json.loads((ROOT / "models" / "manifest.json").read_text(encoding="utf-8"))

datas = [
    (str(ROOT / "app" / "ui"), "app/ui"),
    (str(ROOT / "models" / "manifest.json"), "models"),
    (str(ROOT / "models" / "base"), "models/base"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY.md"), "."),
]
# Preserve original bytes: PyInstaller rewrites and signs native files on macOS.
# The application verifies this archive before extracting it into its private runtime cache.
for item in manifest.get("runtime", []):
    if item.get("platform") == SYSTEM:
        source = (ROOT / "models" / item["file"]).resolve()
        datas.append((str(source), "runtime"))

binaries = []
hiddenimports = ["app.engine.ocr.handwriting", "app.engine.llm_review", "app.engine.worker", "yaml"]
if SYSTEM == "windows":
    hiddenimports += ["clr_loader", "pythonnet"]
packages = ["webview", "onnxruntime", "pymupdf", "pikepdf", "tokenizers", "rapidfuzz", "regex", "cv2"]
if SYSTEM == "linux":
    packages += ["PyQt6", "qtpy"]
for package in packages:
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

# Include runtime dependency metadata and license files for a reviewable package inventory.
for distribution in ("filelock", "PyMuPDF", "pikepdf", "pywebview", "numpy", "pillow", "opencv-python-headless",
                     "onnxruntime-directml" if SYSTEM == "windows" else "onnxruntime", "tokenizers", "rapidfuzz", "regex", "pyyaml"):
    datas += copy_metadata(distribution, recursive=True)

icon = {"windows": ROOT / "packaging" / "anonimato.ico", "macos": ROOT / "packaging" / "anonimato.icns"}.get(SYSTEM)

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "pandas", "pyarrow", "onnx", "pytest", "IPython", "scipy", "torch"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="Anonimato", icon=str(icon) if icon else None,
    console=False, upx=False, version=str(ROOT / "packaging" / "version.txt") if SYSTEM == "windows" else None,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Anonimato")
if SYSTEM == "macos":
    app = BUNDLE(
        coll, name="Anonimato.app", icon=str(icon), bundle_identifier="org.anonimato.desktop",
        info_plist={
            "CFBundleName": "Anonimato", "CFBundleDisplayName": "Anonimato",
            "CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "15.0", "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.productivity",
        },
    )
