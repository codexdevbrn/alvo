; Instalador do Prisma (Inno Setup 6).
;
; Compilado por build.ps1, que passa a versão e a pasta do pacote como
; /D<define> — nada de número de versão escrito aqui, para não divergir de
; backend/versao.py, que é a fonte única.
;
; Compilar na mão (raro):
;   ISCC.exe /DVersaoApp=1.0.0 /DPastaPacote=..\dist_pyinstaller\Prisma instalador\prisma.iss

#ifndef VersaoApp
  #error Defina VersaoApp (ex.: ISCC /DVersaoApp=1.0.0)
#endif
#ifndef PastaPacote
  #error Defina PastaPacote (pasta gerada pelo PyInstaller)
#endif

#define NomeApp "Prisma"
#define Publicador "2D Consultores | Monitores"
#define ExeApp "Prisma.exe"

[Setup]
; AppId fixo: é por ele que o Inno reconhece uma instalação existente e trata a
; próxima como atualização em vez de segunda cópia. Nunca mudar.
AppId={{8E1C4B3A-2D5F-4A77-9C10-PRISMA000001}
AppName={#NomeApp}
AppVersion={#VersaoApp}
AppPublisher={#Publicador}
VersionInfoVersion={#VersaoApp}

; %LOCALAPPDATA% e não Program Files: instalar em Program Files exigiria elevação
; a cada atualização automática, e o atualizador roda sem UAC.
DefaultDirName={localappdata}\{#NomeApp}
DefaultGroupName={#NomeApp}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
DisableDirPage=no

OutputDir=..\dist_release
OutputBaseFilename=Prisma-{#VersaoApp}-instalador
SetupIconFile=..\backend\engine\assets\logo_2d.ico
UninstallDisplayIcon={app}\{#ExeApp}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "atalhodesktop"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
; O pacote inteiro do PyInstaller (Prisma.exe + _internal + atualizador.exe).
Source: "{#PastaPacote}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Dados que ficam AO LADO do executável, não dentro do bundle: mudam sem release
; e precisam sobreviver às atualizações (o atualizador os preserva por nome).
;
; summary.json é o retrato do modo estático do Dashboard (~20 MB). Sem ele a
; primeira tela numa máquina nova é um erro, porque o seletor abre em
; "Dados padrão". onlyifdoesntexist: uma reinstalação não pode sobrescrever um
; summary mais novo que já esteja na máquina.
Source: "..\dashboard\public\data\summary.json"; DestDir: "{app}\data"; Flags: ignoreversion onlyifdoesntexist skipifsourcedoesntexist
Source: "..\base_de_dados.xlsx"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist skipifsourcedoesntexist

[Icons]
Name: "{group}\{#NomeApp}"; Filename: "{app}\{#ExeApp}"
Name: "{group}\Desinstalar o {#NomeApp}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#NomeApp}"; Filename: "{app}\{#ExeApp}"; Tasks: atalhodesktop

[Run]
Filename: "{app}\{#ExeApp}"; Description: "Abrir o {#NomeApp} agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Restos que o app cria em execução e que o [Files] não conhece.
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
{ dados_locais/ sobrevive à desinstalação porque nunca é declarado em [Files]:
  quem o cria é o app, em execução, e o Inno só remove o que instalou. É de
  propósito — o app.db guarda o login e os caminhos fonte/trabalho, e quem
  desinstala costuma estar reinstalando ou trocando de máquina; apagar a
  configuração transformaria isso em retrabalho.

  data/summary.json, ao contrário, VAI embora: está em [Files], então o Inno o
  rastreia e remove. Correto — é um artefato da release, não dado do usuário, e a
  reinstalação traz outro. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  PastaDados: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    PastaDados := ExpandConstant('{app}\dados_locais');
    if DirExists(PastaDados) then
      MsgBox('Suas configurações foram mantidas em:' + #13#10 + PastaDados + #13#10#13#10 +
             'Apague essa pasta manualmente se quiser remover login e caminhos salvos.',
             mbInformation, MB_OK);
  end;
end;
