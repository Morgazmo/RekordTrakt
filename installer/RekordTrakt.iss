; RekordTrakt installer (Inno Setup 6). Built by installer/build.py, which assembles dist\RekordTrakt first.
; Per user, no administrator rights: installs to %LOCALAPPDATA%\Programs\RekordTrakt.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6C1E7C52-8B7A-4E0B-9F2D-5A3B1E6F2C41}
AppName=RekordTrakt
AppVersion={#AppVersion}
AppVerName=RekordTrakt {#AppVersion}
AppPublisher=Morgazmo
AppPublisherURL=https://github.com/Morgazmo/RekordTrakt
AppSupportURL=https://github.com/Morgazmo/RekordTrakt/issues
AppUpdatesURL=https://github.com/Morgazmo/RekordTrakt/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName=RekordTrakt
VersionInfoDescription=RekordTrakt setup
DefaultDirName={autopf}\RekordTrakt
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
DisableDirPage=auto
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=RekordTrakt-{#AppVersion}-setup
SetupIconFile=..\assets\icon\rekordtrakt.ico
UninstallDisplayIcon={app}\RekordTrakt.exe
UninstallDisplayName=RekordTrakt
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
WizardStyle=modern
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\RekordTrakt\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\RekordTrakt"; Filename: "{app}\RekordTrakt.exe"
Name: "{autodesktop}\RekordTrakt"; Filename: "{app}\RekordTrakt.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\RekordTrakt.exe"; Description: "Start RekordTrakt"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\runtime"

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

procedure QuitRunningCopy(Exe: String);
var
  Code: Integer;
begin
  { RekordTrakt releases everything it holds in Rekordbox and turns the controllers' LEDs off before it quits. }
  if FileExists(Exe) then
    Exec(Exe, '--quit', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  QuitRunningCopy(ExpandConstant('{app}\RekordTrakt.exe'));
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Exe: String;
  Code: Integer;
begin
  if CurUninstallStep <> usUninstall then
    exit;
  Exe := ExpandConstant('{app}\RekordTrakt.exe');
  QuitRunningCopy(Exe);
  { Put Rekordbox's MIDI mapping files back as they were. Rekordbox rewrites them when it quits, so it must be closed. }
  while Exec(Exe, '--restore-rekordbox', '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 2) do
  begin
    if UninstallSilent or (MsgBox('Rekordbox is running. Close it, then click OK so RekordTrakt can put back ' +
        'Rekordbox''s MIDI mapping files as they were. Cancel leaves them as they are.',
        mbInformation, MB_OKCANCEL) = IDCANCEL) then
      break;
  end;
  RegDeleteValue(HKEY_CURRENT_USER, RunKey, 'RekordTrakt');
end;
