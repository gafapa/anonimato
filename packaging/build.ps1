# Build: dependencies -> tests -> PyInstaller -> Inno Setup -> dist\PriveltoSetup-x.y.z.exe
# No model weights are packaged: the application downloads them on first launch.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Checked {
  param([string]$Command, [string[]]$Arguments)
  & $Command @Arguments
  if ($LASTEXITCODE -ne 0) { throw "$Command failed with exit code $LASTEXITCODE" }
}

Invoke-Checked uv @('sync', '--frozen')
Invoke-Checked uv @('run', 'python', '-m', 'pytest', 'tests/test_rules.py', '-q')

$webview = Join-Path $PSScriptRoot 'MicrosoftEdgeWebview2Setup.exe'
if (-not (Test-Path $webview)) {
  Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $webview
}
$signature = Get-AuthenticodeSignature -LiteralPath $webview
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation(?:,|$)') {
  throw 'WebView2 bootstrapper must have a valid Microsoft Authenticode signature'
}
if (-not (Test-Path (Join-Path $PSScriptRoot 'anonimato.ico'))) {
  Invoke-Checked uv @('run', 'python', 'packaging/make_icon.py')
}

Invoke-Checked uv @('run', 'pyinstaller', '--noconfirm', '--clean', '--distpath', 'dist', '--workpath', 'build', 'packaging/anonimato.spec')
Invoke-Checked uv @('run', 'python', 'tools/package_inventory.py', 'dist/Privelto')

$iscc = @(
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 no está instalado (https://jrsoftware.org/isdl.php)' }
& $iscc packaging/installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE" }
Write-Host 'Instalador generado en dist\'
