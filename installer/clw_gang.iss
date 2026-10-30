; Instalador de NO LIMIT (antes CLW GANG) (Inno Setup 6). Se compila en GitHub Actions:
;   ISCC.exe /DAppVersion=1.0.0 installer\clw_gang.iss

#define AppName "NO LIMIT"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppExe "NO LIMIT.exe"

[Setup]
AppId={{5B7C2E1A-6F0D-4C9B-9E3A-2D8F4A1C7E55}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=NO LIMIT
AppPublisherURL=https://santiagoliftss-svj.github.io/NOT-LIMIT/
AppSupportURL=https://github.com/santiagoliftss-svj/NOT-LIMIT
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
OutputDir=..\salida
OutputBaseFilename=NO-LIMIT-Setup
SetupIconFile=..\app\assets\icono.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no
#if Ver >= EncodeVer(6, 6, 0)
WizardStyle=modern dark
#else
WizardStyle=modern
#endif
WizardImageFile=imagenes\lateral_100.bmp,imagenes\lateral_125.bmp,imagenes\lateral_150.bmp,imagenes\lateral_200.bmp
WizardSmallImageFile=imagenes\chico_100.bmp,imagenes\chico_125.bmp,imagenes\chico_150.bmp,imagenes\chico_200.bmp
WizardImageStretch=no
WizardImageBackColor=$000000

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Messages]
es.WelcomeLabel1=Bienvenido a [name]
es.WelcomeLabel2=Esto va a instalar [name/ver] en tu computadora.%n%nContesta preguntas de la pantalla con un Ctrl + clic.%n%nCierra otras apps antes de seguir.
es.FinishedHeadingLabel=[name] quedó instalado
es.FinishedLabel=Ya puedes abrir [name] desde el escritorio o el menú Inicio.

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\NO LIMIT\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: escritorio

[InstallDelete]
; lo de cuando se llamaba CLW GANG
Type: files; Name: "{app}\CLW GANG.exe"
Type: files; Name: "{autoprograms}\CLW GANG.lnk"
Type: files; Name: "{autodesktop}\CLW GANG.lnk"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir {#AppName}"; Flags: nowait postinstall skipifsilent
; actualizacion sola (la app corre esto con /VERYSILENT /RELANZAR=1): se vuelve a abrir al terminar
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: Relanzar

[UninstallRun]
; si quedo activa junto al reloj, se cierra antes de borrar sus archivos
Filename: "{sys}\taskkill.exe"; Parameters: "/IM ""{#AppExe}"" /F"; Flags: runhidden; RunOnceId: "CerrarNOLIMIT"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// cierra la version abierta (aunque este escondida junto al reloj, o sea la vieja CLW GANG) antes de instalar
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Codigo: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM "CLW GANG.exe" /F', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM "NO LIMIT.exe" /F', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
  Result := '';
end;

// /RELANZAR=1 lo pone la app cuando el usuario toca "Actualizar" (si se instala al cerrarla, no se vuelve a abrir)
function Relanzar(): Boolean;
begin
  Result := ExpandConstant('{param:RELANZAR|0}') = '1';
end;
