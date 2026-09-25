; Inno Setup script: per-user installation, no administrator rights.
#define AppVersion "2.0.0"

[Setup]
AppId={{6B0E7C9E-4E2B-4C0B-9D1A-8E6A2D3F1A47}
AppName=Anonimato
AppVersion={#AppVersion}
AppPublisher=Anonimato
DefaultDirName={localappdata}\Programs\Anonimato
DefaultGroupName=Anonimato
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=AnonimatoSetup-{#AppVersion}
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
Source: "..\dist\Anonimato\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2

[Icons]
Name: "{autoprograms}\Anonimato"; Filename: "{app}\Anonimato.exe"
Name: "{autodesktop}\Anonimato"; Filename: "{app}\Anonimato.exe"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Instalando WebView2…"; Check: NeedsWebView2
Filename: "{app}\Anonimato.exe"; Description: "Abrir Anonimato"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Advanced AI models downloaded after installation (several GB) and the shader cache.
Type: filesandordirs; Name: "{localappdata}\Anonimato"

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
  Result := not WebView2Installed();
end;
