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
AppMutex=Local\RootDetector-C4886A85-376C-4C2A-BD59-956A8A3CA12F
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
CloseApplications=no
RestartApplications=no

[InstallDelete]
; AppMutex refuses upgrades while RootDetector is running. Replace only the
; packaged DLL set so obsolete CPU/CUDA files cannot survive an upgrade and
; conflict with the new runtime manifest. User models/cache are outside {app}.
Type: filesandordirs; Name: "{app}\main\torch\lib"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\RootDetector"; Filename: "{app}\main\main.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\RootDetector"; Filename: "{app}\main\main.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\main\main.exe"; Description: "Start RootDetector"; Flags: nowait postinstall skipifsilent

[Code]
var
  LifecycleHandle: THandle;
  LifecycleAcquired: Boolean;

function OpenLifecycleFile(FileName: String; DesiredAccess, ShareMode: DWORD;
  SecurityAttributes: NativeUInt; CreationDisposition, FlagsAndAttributes: DWORD;
  TemplateFile: THandle): THandle;
  external 'CreateFileW@kernel32.dll stdcall';

function CloseLifecycleHandle(Handle: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';

function AcquireLifecycleLock: String;
var
  DataDirectory: String;
  ErrorCode: DWORD;
begin
  Result := '';
  if LifecycleAcquired then
    Exit;
  DataDirectory := ExpandConstant('{localappdata}\RootDetector');
  if not ForceDirectories(DataDirectory) then begin
    Result := 'Cannot access the RootDetector user-data directory. Check folder permissions and retry.';
    Exit;
  end;
  { Deny sharing for the same file the app keeps open throughout its lifetime.
    File sharing applies across Windows sessions, unlike the Local AppMutex.
    OPEN_ALWAYS preserves existing bytes; no models/settings/cache are changed. }
  LifecycleHandle := OpenLifecycleFile(DataDirectory + '\.instance.lock',
    $C0000000, 0, 0, 4, $80, 0);
  LifecycleAcquired := LifecycleHandle <> THandle(-1);
  if not LifecycleAcquired then begin
    ErrorCode := DLLGetLastError;
    Result := 'RootDetector user data is in use or unavailable. Close RootDetector in all Windows sessions and retry. ' +
      'If no copy is running, check access to the user-data folder. Windows error: ' + IntToStr(ErrorCode);
    Log(Result);
  end;
end;

procedure ReleaseLifecycleLock;
begin
  if LifecycleAcquired then begin
    CloseLifecycleHandle(LifecycleHandle);
    LifecycleAcquired := False;
  end;
end;

function InitializeSetup: Boolean;
var
  LockError: String;
begin
  LockError := AcquireLifecycleLock;
  Result := LockError = '';
  if not Result then
    SuppressibleMsgBox(LockError, mbError, MB_OK, IDOK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { All install mutations are complete. Release before the flagged postinstall
    [Run] entry launches the app on the Completed page. }
  if CurStep = ssPostInstall then
    ReleaseLifecycleLock;
end;

procedure DeinitializeSetup;
begin
  { Also releases after cancellation or failed installation. }
  ReleaseLifecycleLock;
end;

function InitializeUninstall: Boolean;
var
  LockError: String;
begin
  LockError := AcquireLifecycleLock;
  Result := LockError = '';
  if not Result then
    SuppressibleMsgBox(LockError, mbError, MB_OK, IDOK);
end;

procedure DeinitializeUninstall;
begin
  ReleaseLifecycleLock;
end;
