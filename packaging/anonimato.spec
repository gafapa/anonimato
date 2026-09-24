# PyInstaller spec: one-folder build with the base models and the llama.cpp (Vulkan) runtime.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
LLAMA_KEEP = ("llama-server.exe", "llama-server-impl.dll", "llama.dll", "llama-common.dll", "mtmd.dll", "libomp.dll",
              "LICENSE-LLVM-OpenMP")

datas = [
    (str(ROOT / "app" / "ui"), "app/ui"),
    (str(ROOT / "models" / "manifest.json"), "models"),
    (str(ROOT / "models" / "base"), "models/base"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY.md"), "."),
]
for item in (ROOT / "runtime" / "llama").iterdir():
    if item.name in LLAMA_KEEP or (item.name.startswith("ggml") and item.suffix == ".dll"):
        datas.append((str(item), "runtime/llama"))

binaries = []
hiddenimports = ["app.engine.ocr.handwriting", "app.engine.llm_review", "yaml", "clr_loader", "pythonnet"]
for package in ("webview", "onnxruntime", "pymupdf", "pikepdf", "tokenizers", "rapidfuzz", "regex", "cv2"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

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
    pyz, a.scripts, [], exclude_binaries=True, name="Anonimato", icon=str(ROOT / "packaging" / "anonimato.ico"),
    console=False, upx=False, version=str(ROOT / "packaging" / "version.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Anonimato")
