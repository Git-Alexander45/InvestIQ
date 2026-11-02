; Inno Setup script for InvestIQ-Setup.exe. Built by build.ps1 / the GitHub Actions workflow.
; Installs for the current user only (no administrator rights). The owner's data lives in
; %LOCALAPPDATA%\InvestIQ and is never removed by the uninstaller.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6E0B1E5A-4E33-4C6B-9C38-1C2E8E2B7A11}
AppName=InvestIQ
AppVersion={#AppVersion}
AppPublisher=InvestIQ (personal)
DefaultDirName={localappdata}\Programs\InvestIQ
DefaultGroupName=InvestIQ
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=InvestIQ-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=InvestIQ
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\InvestIQ\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\InvestIQ"; Filename: "{app}\InvestIQ.exe"; WorkingDir: "{app}"
Name: "{group}\InvestIQ keys and settings"; Filename: "{sys}\notepad.exe"; Parameters: """{localappdata}\InvestIQ\.env"""
Name: "{group}\InvestIQ data folder"; Filename: "{localappdata}\InvestIQ"
Name: "{group}\Uninstall InvestIQ"; Filename: "{uninstallexe}"
Name: "{userdesktop}\InvestIQ"; Filename: "{app}\InvestIQ.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\InvestIQ.exe"; Description: "Start InvestIQ now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /F /TN ""InvestIQ\Daily Research"""; Flags: runhidden; RunOnceId: "RemoveTask"
