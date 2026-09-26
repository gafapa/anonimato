#!/usr/bin/env bash
# macOS (Apple Silicon) build: dependencies -> models -> tests -> PyInstaller .app -> .dmg
# Optional signing/notarization when these variables are set:
#   MACOS_SIGN_IDENTITY  ("Developer ID Application: Nombre (TEAMID)")
#   APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD  (app-specific password for notarytool)
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
uv sync --frozen
uv run python tools/fetch_models.py base runtime
uv run python -m pytest tests/test_rules.py tests/test_models.py -q
[ -f packaging/anonimato.icns ] || uv run python packaging/make_icon.py

uv run pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/anonimato.spec
APP="dist/Anonimato.app"

if [ -n "${MACOS_SIGN_IDENTITY:-}" ]; then
  codesign --force --deep --options runtime --timestamp --sign "$MACOS_SIGN_IDENTITY" "$APP"
fi

DMG="dist/Anonimato-${VERSION}-macos-arm64.dmg"
rm -f "$DMG"
STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Aplicaciones"
hdiutil create -volname "Anonimato" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"

if [ -n "${MACOS_SIGN_IDENTITY:-}" ] && [ -n "${APPLE_ID:-}" ]; then
  codesign --force --timestamp --sign "$MACOS_SIGN_IDENTITY" "$DMG"
  xcrun notarytool submit "$DMG" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_PASSWORD" --wait
  xcrun stapler staple "$DMG"
fi

"$APP/Contents/MacOS/Anonimato" "--selftest=$(pwd)/dist/selftest-macos.json" || { cat dist/selftest-macos.json; exit 1; }
echo "Generado: $DMG"
