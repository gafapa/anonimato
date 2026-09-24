# Build: dependencies -> models -> PyInstaller -> Inno Setup -> dist\AnonimatoSetup-x.y.z.exe
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

uv sync --frozen
uv run python tools/fetch_models.py base runtime
uv run python -m pytest tests/test_rules.py -q

$webview = Join-Path $PSScriptRoot 'MicrosoftEdgeWebview2Setup.exe'
if (-not (Test-Path $webview)) {
  Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $webview
}
if (-not (Test-Path (Join-Path $PSScriptRoot 'anonimato.ico'))) {
  uv run python packaging/make_icon.py
}

uv run pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/anonimato.spec

$iscc = @(
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 no está instalado (https://jrsoftware.org/isdl.php)' }
& $iscc packaging/installer.iss
Write-Host 'Instalador generado en dist\'
