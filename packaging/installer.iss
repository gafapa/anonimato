; Inno Setup script: per-user installation, no administrator rights.
#ifndef AppVersion
#define AppVersion "2.2.2"
#endif
#ifndef PayloadRoot
#define PayloadRoot "..\dist\Anonimato"
#endif

[Setup]
#ifdef QualificationBuild
AppId={{B0C7E153-8E93-41E4-95AC-021EE0D98621}
#else
AppId={{6B0E7C9E-4E2B-4C0B-9D1A-8E6A2D3F1A47}
#endif
#ifdef QualificationBuild
AppName=Anonimato Qualification
#else
AppName=Anonimato
#endif
AppVersion={#AppVersion}
AppPublisher=Anonimato
#ifdef QualificationBuild
DefaultDirName={localappdata}\Programs\AnonimatoQualification
#else
DefaultDirName={localappdata}\Programs\Anonimato
#endif
DefaultGroupName=Anonimato
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
#ifdef QualificationBuild
OutputBaseFilename=AnonimatoQualificationSetup-{#AppVersion}
#else
OutputBaseFilename=AnonimatoSetup-{#AppVersion}
#endif
Compression=lzma2/max
LZMAUseSeparateProcess=yes
SolidCompression=yes
LZMANumBlockThreads=2
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile=anonimato.ico
UninstallDisplayIcon={app}\Anonimato.exe
LicenseFile=..\LICENSE
MinVersion=10.0.17763

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "{#PayloadRoot}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2

[Icons]
#ifndef QualificationBuild
Name: "{autoprograms}\Anonimato"; Filename: "{app}\Anonimato.exe"
Name: "{autodesktop}\Anonimato"; Filename: "{app}\Anonimato.exe"; Tasks: desktopicon
#endif

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Instalando WebView2…"; Check: NeedsWebView2
#ifndef QualificationBuild
Filename: "{app}\Anonimato.exe"; Description: "Abrir Anonimato"; Flags: nowait postinstall skipifsilent
#endif

[UninstallDelete]
; AI models downloaded on first launch and on request (base, runtime and advanced) and the shader cache.
#ifdef QualificationBuild
Type: filesandordirs; Name: "{app}\qualification-profile\Anonimato"
#else
Type: filesandordirs; Name: "{localappdata}\Anonimato"
#endif

[Code]
function WebView2Installed(): Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
  Result := Result and (Version <> '') and (Version <> '0.0.0.0');
end;

function NeedsWebView2(): Boolean;
begin
#ifdef QualificationBuild
  Result := False;
#else
  Result := not WebView2Installed();
#endif
end;
