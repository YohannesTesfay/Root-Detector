; Per-user Windows package. User data in LOCALAPPDATA\RootDetector is retained
; on upgrade and uninstall. Compile with ISCC.exe after build.py --installer-payload.
#ifndef SourceDir
  #define SourceDir "..\..\builds\RootDetector-Windows-installer-payload"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{C4886A85-376C-4C2A-BD59-956A8A3CA12F}
AppName=RootDetector
AppVersion={#AppVersion}
AppPublisher=Experimental Plant Ecology, University of Greifswald
DefaultDirName={localappdata}\Programs\RootDetector
DefaultGroupName=RootDetector
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\builds
OutputBaseFilename=RootDetector-Windows-Setup
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\main\main.exe
CloseApplications=yes

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\RootDetector"; Filename: "{app}\main\main.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\RootDetector"; Filename: "{app}\main\main.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\main\main.exe"; Description: "Start RootDetector"; Flags: nowait postinstall skipifsilent
