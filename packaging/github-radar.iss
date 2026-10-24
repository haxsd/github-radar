; GitHub 中文雷达 · Inno Setup 安装脚本
; 构建：先用 build_app.bat 生成 dist\StarScout，再运行 build_installer.bat

#define MyAppName "GitHub 中文雷达"
#define MyAppVersion "0.7.3"
#define MyAppPublisher "GitHub Radar contributors"
#define MyAppURL "https://github.com/haxsd/github-radar"
#define MyAppExeName "StarScout.exe"
#define MyDataDir "{localappdata}\GitHubRadar"

[Setup]
AppId={{8F4A2C1E-6D7B-4E3A-9C2F-1B5D8E7A4C30}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\GitHubRadar
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=GitHubRadar-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
MinVersion=10.0

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式:"; Flags: checkedonce
Name: "autostart"; Description: "开机自动启动（托盘后台运行）"; GroupDescription: "启动选项:"; Flags: unchecked

[Files]
Source: "..\dist\StarScout\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 说明文档放到程序根目录，开始菜单「使用说明」直接打开
Source: "..\packaging\使用说明.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README-EN.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\.env.example"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\使用说明"; Filename: "{app}\使用说明.txt"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "GitHubRadar"; ValueData: """{app}\{#MyAppExeName}"" --minimized"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
const
  UNINSTALL_TASKKILL = 'taskkill.exe';
  DATA_DIR = '{#MyDataDir}';

function KillRunningApp(): Boolean;
var
  ResultCode: Integer;
begin
  { 升级/卸载时先结束托盘进程，避免文件被占用 }
  Exec(UNINSTALL_TASKKILL, '/F /IM {#MyAppExeName}', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

function InitializeSetup(): Boolean;
begin
  KillRunningApp();
  Result := True;
end;

function InitializeUninstall(): Boolean;
begin
  KillRunningApp();
  Result := True;
end;

function SilentMode(): Boolean;
var
  Cmd: String;
begin
  Cmd := LowerCase(GetCmdTail);
  Result := (Pos('/silent', Cmd) > 0) or (Pos('/verysilent', Cmd) > 0);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Msg: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { 静默卸载不弹窗，默认保留数据，避免自动化任务卡住 }
    if DirExists(ExpandConstant(DATA_DIR)) and not SilentMode() then
    begin
      Msg := '是否同时删除本地数据？' + #13#10 + #13#10 +
             '数据目录：' + ExpandConstant(DATA_DIR) + #13#10 +
             '包含数据库、预览图缓存和 .env 配置。' + #13#10 + #13#10 +
             '选择「否」会保留数据，方便以后重新安装继续使用。';
      if MsgBox(Msg, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(ExpandConstant(DATA_DIR), True, True, True);
    end;
  end;
end;
