; Instalador de CLW GANG (Inno Setup 6). Se compila en GitHub Actions:
;   ISCC.exe /DAppVersion=1.0.0 installer\clw_gang.iss

#define AppName "CLW GANG"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppExe "CLW GANG.exe"

[Setup]
AppId={{5B7C2E1A-6F0D-4C9B-9E3A-2D8F4A1C7E55}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=CLW GANG
AppPublisherURL=https://santiagoliftss-svj.github.io/clw-gang/
AppSupportURL=https://github.com/santiagoliftss-svj/clw-gang
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
OutputDir=..\salida
OutputBaseFilename=CLW-GANG-Setup
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
Source: "..\dist\CLW GANG\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: escritorio

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
