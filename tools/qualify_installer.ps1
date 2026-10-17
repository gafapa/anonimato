# Exercise an isolated Inno installation, upgrade/repair and removal using fictitious profile data.
param(
  [Parameter(Mandatory=$true)][string]$Installer,
  [string]$PreviousInstaller,
  [Parameter(Mandatory=$true)][string]$ExpectedVersion,
  [string]$PreviousVersion
)
$ErrorActionPreference = 'Stop'
$workspaceRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$evidenceRoot = Join-Path $workspaceRoot ('tmp\installer-qualification\' + [guid]::NewGuid().ToString())
$installRoot = Join-Path $evidenceRoot 'application'
if (-not $installRoot.StartsWith($workspaceRoot + '\tmp\', [StringComparison]::OrdinalIgnoreCase)) {
  throw 'Qualification target must stay inside workspace tmp'
}
$qaKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{B0C7E153-8E93-41E4-95AC-021EE0D98621}_is1'
$productionKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{6B0E7C9E-4E2B-4C0B-9D1A-8E6A2D3F1A47}_is1'
if (Test-Path -LiteralPath $qaKey) { throw 'An existing qualification installation must be reviewed first' }
function Read-ProductionRegistration {
  if (Test-Path -LiteralPath $productionKey) { return (Get-ItemProperty -LiteralPath $productionKey | ConvertTo-Json -Compress) }
  return 'absent'
}
$productionBefore = Read-ProductionRegistration
function Resolve-QualificationSetup([string]$Path) {
  $resolved = (Resolve-Path -LiteralPath $Path).Path
  if ([IO.Path]::GetFileName($resolved) -notmatch '^(Anonimato|Privelto)QualificationSetup-.*\.exe$') {
    throw 'Only explicitly compiled qualification installers are allowed'
  }
  return $resolved
}
$currentSetup = Resolve-QualificationSetup $Installer
if ($PreviousInstaller) { $oldSetup = Resolve-QualificationSetup $PreviousInstaller }
else { $oldSetup = $currentSetup; $PreviousVersion = $ExpectedVersion }
New-Item -ItemType Directory -Path $evidenceRoot | Out-Null
function Run-Checked([string]$Executable, [string[]]$Arguments) {
  $process = Start-Process -WindowStyle Hidden -FilePath $Executable -ArgumentList $Arguments -WindowStyle Hidden -PassThru
  if (-not $process.WaitForExit(1200000)) { $process.Kill(); throw 'Qualification process exceeded 20 minutes' }
  if ($process.ExitCode -ne 0) { throw "Qualification process failed with exit code $($process.ExitCode)" }
}
function Install-Checked([string]$Setup, [string]$Stage) {
  $logPath = Join-Path $evidenceRoot "$Stage-install.log"
  Run-Checked $Setup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/TASKS=""',
                       "/DIR=`"$installRoot`"", "/LOG=`"$logPath`"")
  $registration = Get-ItemProperty -LiteralPath $qaKey
  if ($registration.InstallLocation.TrimEnd('\') -ne $installRoot) { throw 'Unexpected qualification registration location' }
}
function SelfTest-Checked([string]$Version, [string]$Stage) {
  $binary = Join-Path $installRoot 'Privelto.exe'
  if (-not (Test-Path -LiteralPath $binary)) { $binary = Join-Path $installRoot 'Anonimato.exe' }
  if ((Get-Item -LiteralPath $binary).VersionInfo.ProductVersion -ne $Version) { throw 'Installed binary version mismatch' }
  $report = Join-Path $evidenceRoot "$Stage-selftest.json"
  Run-Checked $binary @("--selftest=`"$report`"")
  if (-not (Test-Path -LiteralPath $report)) { throw 'Installed self-test produced no evidence' }
  $selfTestResult = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
  if ($selfTestResult.ok -ne $true -or $selfTestResult.integrity -ne $true -or $selfTestResult.crash_recovery -ne $true) {
    throw 'Installed self-test did not verify integrity and crash recovery'
  }
}
$profileRoot = Join-Path $installRoot 'qualification-profile'
$previousLocalAppData = $env:LOCALAPPDATA
$previousCpu = $env:ANONIMATO_CPU
try {
  Install-Checked $oldSetup 'initial'
  $env:LOCALAPPDATA = $profileRoot
  $env:ANONIMATO_CPU = '1'
  SelfTest-Checked $PreviousVersion 'initial'
  $dataRoot = Join-Path $profileRoot 'Anonimato'
  New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
  $marker = Join-Path $dataRoot 'fictitious-profile-marker.txt'
  Set-Content -LiteralPath $marker -Value 'Fictitious qualification profile - no personal documents'
  Install-Checked $currentSetup 'upgrade'
  if (-not (Test-Path -LiteralPath $marker) -or
      (Get-Content -LiteralPath $marker -Raw).Trim() -ne 'Fictitious qualification profile - no personal documents') {
    throw 'Upgrade changed or lost the existing profile'
  }
  SelfTest-Checked $ExpectedVersion 'upgrade'
  $uninstaller = Join-Path $installRoot 'unins000.exe'
  Run-Checked $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                             "/LOG=`"$(Join-Path $evidenceRoot 'uninstall.log')`"")
  if ((Test-Path -LiteralPath (Join-Path $installRoot 'Privelto.exe')) -or
      (Test-Path -LiteralPath $dataRoot) -or (Test-Path -LiteralPath $qaKey)) {
    throw 'Qualification uninstall left application, profile data or registration behind'
  }
  $cleanupDeadline = [DateTime]::UtcNow.AddSeconds(30)
  do {
    $remainingFiles = @(Get-ChildItem -LiteralPath $installRoot -Recurse -File -ErrorAction SilentlyContinue)
    if ($remainingFiles.Count -eq 0) { break }
    Start-Sleep -Milliseconds 250
  } while ([DateTime]::UtcNow -lt $cleanupDeadline)
  if ($remainingFiles.Count) { throw 'Qualification uninstall left payload files behind' }
  if ((Read-ProductionRegistration) -ne $productionBefore) { throw 'Production registration was modified' }
  $result = [ordered]@{ ok=$true; previousVersion=$PreviousVersion; version=$ExpectedVersion;
                       profilePreserved=$true; uninstallVerified=$true; remainingPayloadFiles=0; productionRegistrationUnchanged=$true;
                       evidenceRoot=$evidenceRoot }
  $result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidenceRoot 'result.json') -Encoding utf8
  $result | ConvertTo-Json
} finally {
  $env:LOCALAPPDATA = $previousLocalAppData
  $env:ANONIMATO_CPU = $previousCpu
}
