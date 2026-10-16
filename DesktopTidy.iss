; DesktopTidy 安装包脚本(Inno Setup 6)
; 构建方法:安装 Inno Setup 后,右键本文件 → Compile,或运行:
;   ISCC.exe DesktopTidy.iss
; 产物在 dist\installer\ 下

[Setup]
AppName=桌面整理助手
AppVersion=1.0.0
AppPublisher=DesktopTidy
DefaultDirName={autopf}\DesktopTidy
DefaultGroupName=桌面整理助手
OutputDir=dist\installer
OutputBaseFilename=DesktopTidy-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
; 普通用户也能安装到自己的 AppData(不需要管理员权限时可用 PrivilegesRequired=lowest 配合 {userpf})
PrivilegesRequired=admin
UninstallDisplayIcon={app}\DesktopTidy.exe

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式(&D)"; GroupDescription: "附加任务:"

[Files]
Source: "dist\DesktopTidy.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\DesktopTidyCLI.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\桌面整理助手"; Filename: "{app}\DesktopTidy.exe"
Name: "{group}\桌面整理助手(命令行)"; Filename: "{app}\DesktopTidyCLI.exe"
Name: "{autodesktop}\桌面整理助手"; Filename: "{app}\DesktopTidy.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DesktopTidy.exe"; Description: "立即运行桌面整理助手"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 用户数据(日志/配置)存放在 %LOCALAPPDATA% 与 %APPDATA%,卸载时默认保留
Type: none; Name: "{app}"
