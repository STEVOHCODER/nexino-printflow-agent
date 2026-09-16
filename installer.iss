; Nexino Print Agent - Inno Setup Script
; Bundles Electron app + embedded Python + all dependencies

#define MyAppName "Nexino Print Agent"
#define MyAppPublisher "Nexino PrintFlow"
#define MyAppURL "https://github.com/STEVOHCODER/nexino-printflow-agent"
#define MyAppExeName "Nexino Print Agent.exe"

; These are passed via /D flags from build script
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

; Source directories (relative to ISS file location after build script copies them)
#define SrcDir "electron\\dist-installer\\inno-build"

[Setup]
AppId={{NEXINO-PRINT-AGENT-INSTALLER}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=electron\\dist-installer
OutputBaseFilename=NexinoPrintAgent-{#AppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
SetupIconFile=
UninstallDisplayIcon={app}\app\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Electron app with all resources
Source: "{#SrcDir}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
; Python embeddable runtime
Source: "{#SrcDir}\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs
; Agent code
Source: "{#SrcDir}\agent\*"; DestDir: "{app}\agent"; Flags: ignoreversion recursesubdirs createallsubdirs
; Config files
Source: "{#SrcDir}\.env"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\app\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\app\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
Filename: "{app}\app\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent
