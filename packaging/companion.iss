#ifndef SourceDir
  #define SourceDir "..\dist\companion\SubtitleD-Companion"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\companion"
#endif
[Setup]
AppId={{659DB2AB-998C-470B-B689-F47032A26B7D}
AppName=SubtitleD Companion
AppVersion=0.1.2
AppPublisher=SubtitleD
DefaultDirName={localappdata}\Programs\SubtitleD Companion
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=SubtitleD-Companion-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\SubtitleD-Companion.exe
CloseApplications=yes
[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "Install-Companion.cmd"
[Icons]
Name: "{autoprograms}\SubtitleD Companion"; Filename: "{app}\SubtitleD-Companion.exe"
[Registry]
Root: HKCU; Subkey: "Software\Classes\subtitled"; ValueType: string; ValueData: "URL:SubtitleD Companion"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\subtitled"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\subtitled\shell\open\command"; ValueType: string; ValueData: """{app}\SubtitleD-Companion.exe"" --url ""%1"""
[Run]
Filename: "{app}\SubtitleD-Companion.exe"; Description: "Open SubtitleD Companion"; Flags: nowait postinstall skipifsilent
; User models, projects, and settings in LocalAppData\SubtitleD are deliberately
; outside the install directory and are never deleted by the uninstaller.
