; ==============================================================================
; tunemusic Pro - Roteiro de Compilação de Instalador Oficial (Inno Setup 6)
; ==============================================================================

#define MyAppName "tunemusic Pro"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "tunemusic"
#define MyAppURL "https://tunemusic.com.br"
#define MyAppExeName "tunemusic.exe"

[Setup]
AppId={{48C37C51-248E-454B-BF45-7BC5A18C61E8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=LICENCA_TERMOS.txt
OutputDir=..\dist_installer
OutputBaseFilename=tunemusic_Pro_v1.0_Instalador
SetupIconFile=..\app_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=commandline dialog
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
CloseApplicationsFilter=*.exe
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion=1.0.0.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} - Teleprompter ao Vivo e Estúdio Vocal com IA
VersionInfoCopyright=Copyright (C) 2026 {#MyAppPublisher}. Todos os direitos reservados.
VersionInfoProductName={#MyAppName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "quicklaunchicon"; Description: "Criar atalho na Barra de Tarefas"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Dirs]
Name: "{app}\uploads"; Permissions: users-modify
Name: "{app}\outputs"; Permissions: users-modify
Name: "{app}\data"; Permissions: users-modify
Name: "{app}\data\stageprompter"; Permissions: users-modify

[Files]
; 1. Executável Principal do tunemusic (Launcher Nativo Windows com ícone oficial embutido)
Source: "..\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; 2. Ícones e Identidade Visual
Source: "..\app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

; 3. Servidor Backend e Motores IA
Source: "..\server.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\license_engine.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\stageprompter_engine.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\modal_separator.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\vocal_tuner.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion

; 4. Binários de Áudio (FFmpeg essencial para decodificação/recodificação sem dependências de sistema)
Source: "..\bin\ffmpeg.exe"; DestDir: "{app}\bin"; Flags: ignoreversion

; 5. Interface Web Desktop (HTML, CSS, JS, Logos, Fontes)
Source: "..\static\*"; DestDir: "{app}\static"; Flags: ignoreversion recursesubdirs createallsubdirs

; 6. Configurações Iniciais Limpas (Repertório Padrão)
Source: "..\data\stageprompter\repertorio.json"; DestDir: "{app}\data\stageprompter"; Flags: ignoreversion onlyifdoesntexist

; [NOTA PARA DISTRIBUIÇÃO COM RUNTIME EMBUTIDO]:
; Quando for distribuir o pacote 100% autônomo (Offline Full), basta desmarcar a linha abaixo
; que conterá o Python 3.12 portátil com PyTorch e Demucs:
; Source: "..\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"; Tasks: desktopicon

[Run]
; Configurar exceção no Firewall do Windows automaticamente (evita avisos assustadores do Windows Defender)
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""tunemusic Pro Local Server"" dir=in action=allow protocol=TCP localport=8000"; Flags: runhidden; StatusMsg: "Configurando permissões do sistema..."
; Iniciar tunemusic Pro opcionalmente após instalação
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Remover regra do Firewall ao desinstalar
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""tunemusic Pro Local Server"""; Flags: runhidden

[Code]
// Procedimento de verificação antes da instalação
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
