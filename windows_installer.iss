#ifndef AppVersion
  #error AppVersion must be provided by the build script
#endif

[Setup]
; A stable ID lets later versions upgrade the same per-user installation.
AppId={{396C7B60-3ED5-4EC1-AB5E-E9ADCD701538}
AppName=零号桌宠
AppVersion={#AppVersion}
AppPublisher=零号正在观察
AppPublisherURL=https://github.com/fuskhhh/zero
DefaultDirName={localappdata}\Programs\LinghaoPet
DefaultGroupName=零号桌宠
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=release
OutputBaseFilename=LinghaoPet-Windows-x64-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\LinghaoPet.exe
CloseApplications=yes
RestartApplications=no

[Languages]
; Vendored from jrsoftware/issrc, blob d0d44258f51aa3127fc0d1167a7c8be328a9bdcf.
Name: "chinesesimp"; MessagesFile: "installer\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "dist\LinghaoPet\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\零号桌宠"; Filename: "{app}\LinghaoPet.exe"
Name: "{autodesktop}\零号桌宠"; Filename: "{app}\LinghaoPet.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LinghaoPet.exe"; Description: "启动零号桌宠"; Flags: nowait postinstall skipifsilent
