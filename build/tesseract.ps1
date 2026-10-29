# Instala Tesseract en la maquina de compilacion y deja una copia minima en build\tesseract
# (tesseract.exe + DLLs + tessdata con espanol e ingles).
$ErrorActionPreference = "Stop"
$origen = "C:\Program Files\Tesseract-OCR"

if (-not (Test-Path "$origen\tesseract.exe")) {
    choco install tesseract -y --no-progress | Out-Host
}
if (-not (Test-Path "$origen\tesseract.exe")) {
    Write-Host "Chocolatey no lo instalo; se baja de UB Mannheim"
    gh release download -R UB-Mannheim/tesseract -p "*w64-setup*.exe" -D "$env:RUNNER_TEMP" --clobber
    $setup = Get-ChildItem "$env:RUNNER_TEMP\*w64-setup*.exe" | Select-Object -First 1
    Start-Process $setup.FullName -ArgumentList "/S" -Wait
}
if (-not (Test-Path "$origen\tesseract.exe")) { throw "No se pudo instalar Tesseract" }

& "$origen\tesseract.exe" --version | Out-Host

$destino = Join-Path $PSScriptRoot "tesseract"
if (Test-Path $destino) { Remove-Item $destino -Recurse -Force }
New-Item -ItemType Directory -Force "$destino\tessdata\configs" | Out-Null
Copy-Item "$origen\tesseract.exe" $destino
Copy-Item "$origen\*.dll" $destino
Copy-Item "$origen\tessdata\eng.traineddata" "$destino\tessdata"
Copy-Item "$origen\tessdata\osd.traineddata" "$destino\tessdata"
Copy-Item "$origen\tessdata\configs\*" "$destino\tessdata\configs"

$spa = "$destino\tessdata\spa.traineddata"
Invoke-WebRequest "https://github.com/tesseract-ocr/tessdata/raw/main/spa.traineddata" -OutFile $spa
if ((Get-Item $spa).Length -lt 1000000) { throw "spa.traineddata se bajo mal" }
Copy-Item $spa "$origen\tessdata\spa.traineddata" -Force

& "$destino\tesseract.exe" --list-langs | Out-Host
$tam = (Get-ChildItem $destino -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host ("Tesseract listo: {0:N1} MB" -f $tam)
