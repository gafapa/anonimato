#!/usr/bin/env bash
# Linux (x86-64) build: dependencies -> tests -> PyInstaller -> AppImage
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
uv sync --frozen
# No model weights are packaged: the application downloads them on first launch (the self-test below too).
uv run python -m pytest tests/test_rules.py tests/test_models.py -q -k "not test_base_models_match_their_checksums"
[ -f packaging/anonimato.png ] || uv run python packaging/make_icon.py

uv run pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/anonimato.spec
uv run python tools/package_inventory.py dist/Privelto

APPDIR="build/Privelto.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr"
cp -R dist/Privelto "$APPDIR/usr/anonimato"
cp packaging/anonimato.png "$APPDIR/anonimato.png"
cat > "$APPDIR/anonimato.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Privelto
Comment=Local document redaction and verification
Exec=anonimato
Icon=anonimato
Categories=Office;Utility;
EOF
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/anonimato/Privelto" "$@"
EOF
chmod +x "$APPDIR/AppRun"

TOOL="build/appimagetool-x86_64.AppImage"
uv run python tools/fetch_build_tool.py appimagetool "$TOOL"
chmod +x "$TOOL"
OUT="dist/Privelto-${VERSION}-linux-x86_64.AppImage"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUT"

QT_QPA_PLATFORM=offscreen dist/Privelto/Privelto "--selftest=$(pwd)/dist/selftest-linux.json" \
  || { cat dist/selftest-linux.json; exit 1; }
echo "Generado: $OUT"
