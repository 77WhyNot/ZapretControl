; Установщик Zapret Control (Inno Setup 6)
; Сборка: build\build.ps1 — он подставит версию и запустит ISCC.

#define AppName "Zapret Control"
#define AppExeName "ZapretControl.exe"
#define AppPublisher "Ivan Milyaev (ketamine)"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
; Адрес репозитория: показывается в «Программы и компоненты» как ссылка
; на страницу поддержки.
#define AppUrl "https://github.com/77WhyNot/ZapretControl"

[Setup]
AppId={{8F3C1D42-6B7E-4B9A-9E2C-5A1F7D0C3E88}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
#ifdef AppUrl
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
#endif
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} — обход блокировок

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no
AllowNoIcons=yes

; Приложению нужны права администратора: WinDivert грузит драйвер ядра,
; а служба zapret создаётся в системе.
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

OutputDir=..\dist
OutputBaseFilename=ZapretControl-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4

WizardStyle=modern
WizardSizePercent=110
SetupIconFile=..\app\resources\icon.ico
WizardImageFile=art\wizard-banner.bmp
WizardSmallImageFile=art\wizard-small.bmp
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

; Закрываем работающую копию перед заменой файлов.
CloseApplications=yes
RestartApplications=no
SetupMutex=ZapretControlSetupMutex

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; \
    GroupDescription: "Ярлыки:"
Name: "autostart"; Description: "Запускать программу вместе с Windows"; \
    GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
; Само приложение. Папку core исключаем — она ставится отдельным правилом.
Source: "..\dist\ZapretControl\*"; DestDir: "{app}"; \
    Excludes: "core"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; Ядро zapret. onlyifdoesntexist бережёт пользовательские списки и то ядро,
; которое программа уже обновила сама из GitHub. Пропавшие файлы (например,
; удалённые антивирусом) при этом восстанавливаются.
Source: "..\payload\zapret\*"; DestDir: "{app}\core"; \
    Flags: onlyifdoesntexist recursesubdirs createallsubdirs uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{sys}\schtasks.exe"; \
    Parameters: "/create /f /tn ""ZapretControl Autostart"" /tr ""\""{app}\{#AppExeName}\"" --tray"" /sc onlogon /rl highest"; \
    Flags: runhidden; Tasks: autostart
; shellexec обязателен: postinstall-запуск идёт от обычного пользователя,
; а у программы манифест requireAdministrator. CreateProcess в такой ситуации
; падает с ошибкой 740, а ShellExecute корректно поднимает права.
Filename: "{app}\{#AppExeName}"; Description: "Запустить {#AppName}"; \
    Flags: nowait postinstall skipifsilent shellexec

[UninstallRun]
; Порядок важен: сначала снимаем службу и процесс, потом удаляем файлы.
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#AppExeName}"; \
    Flags: runhidden; RunOnceId: "killapp"
Filename: "{sys}\sc.exe"; Parameters: "stop zapret"; \
    Flags: runhidden; RunOnceId: "stopsvc"
Filename: "{sys}\sc.exe"; Parameters: "delete zapret"; \
    Flags: runhidden; RunOnceId: "delsvc"
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im winws.exe"; \
    Flags: runhidden; RunOnceId: "killwinws"
Filename: "{sys}\sc.exe"; Parameters: "stop WinDivert"; \
    Flags: runhidden; RunOnceId: "stopwd"
Filename: "{sys}\sc.exe"; Parameters: "delete WinDivert"; \
    Flags: runhidden; RunOnceId: "delwd"
Filename: "{sys}\schtasks.exe"; Parameters: "/delete /f /tn ""ZapretControl Autostart"""; \
    Flags: runhidden; RunOnceId: "deltask"

[UninstallDelete]
; Файлы, появившиеся после установки (обновления ядра, кэш).
Type: filesandordirs; Name: "{app}\core"
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"

[Code]

function IsAppRunning(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('cmd.exe',
    '/c tasklist /fi "IMAGENAME eq {#AppExeName}" | find /i "{#AppExeName}"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  Internal: String;
begin
  NeedsRestart := False;
  { Программа могла сама запустить установщик при автообновлении — тогда она
    уже закрылась. На всякий случай снимаем процесс, иначе файлы заняты. }
  if IsAppRunning() then
  begin
    Exec('taskkill.exe', '/f /im {#AppExeName}', '', SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
    Sleep(1200);
  end;

  { При обновлении чистим _internal целиком: библиотеки Qt между версиями
    меняются, и файлы от старой сборки иначе остались бы навсегда.
    Папку core не трогаем — там ядро и списки пользователя. }
  Internal := ExpandConstant('{app}\_internal');
  if DirExists(Internal) then
    DelTree(Internal, True, True, True);

  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  { В тихом режиме (автообновление) кнопки «Запустить» нет — стартуем сами.
    Только ShellExec: программе нужны права администратора. }
  if (CurStep = ssPostInstall) and WizardSilent() then
    ShellExec('open', ExpandConstant('{app}\{#AppExeName}'), '',
              ExpandConstant('{app}'), SW_SHOW, ewNoWait, ResultCode);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\ZapretControl');
    if DirExists(DataDir) then
    begin
      if MsgBox('Удалить настройки программы и журнал?' + #13#10 +
                'Списки доменов и резервные копии тоже будут удалены.',
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
