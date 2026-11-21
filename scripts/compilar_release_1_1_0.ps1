<#
.SYNOPSIS
    Compila los paquetes distribuibles de escritorio de IdentIA Release 1.1.0 para Windows.
.DESCRIPTION
    1. Compila el frontend React/Vite hacia frontend/dist.
    2. Verifica la existencia offline de los modelos YuNet y SFace ONNX en backend/models.
    3. Genera la carpeta portable (--onedir) y su archivo comprimido ZIP.
    4. Genera el ejecutable único todo-en-uno (--onefile) IdentIA-1.1.0.exe.
    5. Reporta las rutas finales y tamaños exactos en MB dentro de release/.
#>

$ErrorActionPreference = "Stop"

$RaizProyecto = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DirectorioFrontend = Join-Path $RaizProyecto "frontend"
$DirectorioBackend = Join-Path $RaizProyecto "backend"
$DirectorioRelease = Join-Path $RaizProyecto "release"
$PythonVenv = Join-Path $DirectorioBackend ".venv\Scripts\python.exe"
$PyInstallerExe = Join-Path $DirectorioBackend ".venv\Scripts\pyinstaller.exe"

if (-not (Test-Path $PythonVenv)) {
    throw "No se encontró el entorno virtual Python en $PythonVenv"
}
if (-not (Test-Path $PyInstallerExe)) {
    throw "No se encontró PyInstaller en $PyInstallerExe. Instálalo con pip install pyinstaller."
}

Write-Host "`n[1/5] Compilando frontend React (npm run build)..." -ForegroundColor Cyan
Push-Location $DirectorioFrontend
try {
    npm run build
    if ($LASTEXITCODE -ne 0) {
        throw "Falló la compilación del frontend."
    }
}
finally {
    Pop-Location
}

Write-Host "`n[2/5] Verificando modelos ONNX locales..." -ForegroundColor Cyan
Push-Location $DirectorioBackend
try {
    & $PythonVenv -c "from pathlib import Path; from app.vision.models_loader import asegurar_modelos; y, s = asegurar_modelos(Path('models')); print('YuNet:', y); print('SFace:', s)"
    if ($LASTEXITCODE -ne 0) {
        throw "No fue posible verificar o preparar los modelos ONNX."
    }
}
finally {
    Pop-Location
}

Write-Host "`n[3/5] Limpiando artefactos de compilación previos..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $DirectorioRelease | Out-Null
$RutasLimpieza = @(
    (Join-Path $DirectorioBackend "build"),
    (Join-Path $DirectorioBackend "dist"),
    (Join-Path $DirectorioRelease "IdentIA-1.1.0-portable"),
    (Join-Path $DirectorioRelease "IdentIA-1.1.0-portable.zip"),
    (Join-Path $DirectorioRelease "IdentIA-1.1.0.exe")
)
foreach ($Ruta in $RutasLimpieza) {
    if (Test-Path $Ruta) {
        Remove-Item -Recurse -Force $Ruta
    }
}

Push-Location $DirectorioBackend
try {
    Write-Host "`n[4/5] Compilando versión portable (--onedir) con PyInstaller..." -ForegroundColor Cyan
    & $PyInstallerExe --noconfirm --clean "identia_portable.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "Falló PyInstaller para identia_portable.spec."
    }

    $OrigenPortable = Join-Path $DirectorioBackend "dist\IdentIA-1.1.0-portable"
    $DestinoPortable = Join-Path $DirectorioRelease "IdentIA-1.1.0-portable"
    $DestinoZip = Join-Path $DirectorioRelease "IdentIA-1.1.0-portable.zip"
    Move-Item -Path $OrigenPortable -Destination $DestinoPortable
    Compress-Archive -Path "$DestinoPortable\*" -DestinationPath $DestinoZip -CompressionLevel Optimal

    Write-Host "`n[5/5] Compilando ejecutable único (--onefile) con PyInstaller..." -ForegroundColor Cyan
    & $PyInstallerExe --noconfirm --clean "identia_unico.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "Falló PyInstaller para identia_unico.spec."
    }

    $OrigenUnico = Join-Path $DirectorioBackend "dist\IdentIA-1.1.0.exe"
    $DestinoUnico = Join-Path $DirectorioRelease "IdentIA-1.1.0.exe"
    Copy-Item -Path $OrigenUnico -Destination $DestinoUnico -Force
}
finally {
    Pop-Location
}

$TamanoZipMb = [math]::Round((Get-Item (Join-Path $DirectorioRelease "IdentIA-1.1.0-portable.zip")).Length / 1MB, 2)
$TamanoExeMb = [math]::Round((Get-Item (Join-Path $DirectorioRelease "IdentIA-1.1.0.exe")).Length / 1MB, 2)

Write-Host "`n================ RESUMEN RELEASE 1.1.0 ================" -ForegroundColor Green
Write-Host "Carpeta portable : $DirectorioRelease\IdentIA-1.1.0-portable"
Write-Host "Archivo ZIP      : $DirectorioRelease\IdentIA-1.1.0-portable.zip ($TamanoZipMb MB)"
Write-Host "Ejecutable único : $DirectorioRelease\IdentIA-1.1.0.exe ($TamanoExeMb MB)"
Write-Host "=======================================================" -ForegroundColor Green
