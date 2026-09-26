#!/usr/bin/env bash
# Linux (x86-64) build: dependencies -> models -> tests -> PyInstaller -> AppImage
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
uv sync --frozen
uv run python tools/fetch_models.py base runtime
uv run python -m pytest tests/test_rules.py tests/test_models.py -q
[ -f packaging/anonimato.png ] || uv run python packaging/make_icon.py

uv run pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/anonimato.spec

APPDIR="build/Anonimato.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr"
cp -R dist/Anonimato "$APPDIR/usr/anonimato"
cp packaging/anonimato.png "$APPDIR/anonimato.png"
cat > "$APPDIR/anonimato.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Anonimato
Comment=Anonimización local de documentos, sin rastro
Exec=anonimato
Icon=anonimato
Categories=Office;Utility;
EOF
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/anonimato/Anonimato" "$@"
EOF
chmod +x "$APPDIR/AppRun"

TOOL="build/appimagetool-x86_64.AppImage"
if [ ! -x "$TOOL" ]; then
  curl -sSL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "$TOOL"
fi
OUT="dist/Anonimato-${VERSION}-linux-x86_64.AppImage"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUT"

QT_QPA_PLATFORM=offscreen dist/Anonimato/Anonimato "--selftest=$(pwd)/dist/selftest-linux.json" \
  || { cat dist/selftest-linux.json; exit 1; }
echo "Generado: $OUT"
