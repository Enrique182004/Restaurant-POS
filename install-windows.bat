@echo off
REM Ebi Ball POS — Instalacion y compilacion para Windows
REM Haz doble clic en este archivo para construir la aplicacion.

chcp 65001 >nul 2>&1
title Ebi Ball POS — Instalacion

cls
echo ╔══════════════════════════════════════════╗
echo ║       Ebi Ball POS — Instalacion         ║
echo ╚══════════════════════════════════════════╝
echo.

cd /d "%~dp0"

REM ── Paso 1: Node.js ──────────────────────────────────────────────────────────
echo [1/4] Verificando Node.js...
where node >nul 2>&1
if errorlevel 1 (
    echo   Node.js no encontrado. Instalando con winget...
    winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo.
        echo   winget no disponible. Descarga Node.js manualmente desde:
        echo   https://nodejs.org  ^(elige la version LTS^)
        echo.
        echo   Instala Node.js y vuelve a ejecutar este archivo.
        pause
        exit /b 1
    )
    REM Recargar PATH para que node este disponible
    for /f "tokens=*" %%i in ('where node 2^>nul') do set NODE_PATH=%%i
    if not defined NODE_PATH (
        echo   Reinicia la terminal y vuelve a ejecutar este archivo.
        pause
        exit /b 1
    )
)
for /f "tokens=*" %%v in ('node --version') do echo   ✓ Node.js %%v

REM ── Paso 2: Python 3 ─────────────────────────────────────────────────────────
echo.
echo [2/4] Verificando Python 3...
where python >nul 2>&1
if errorlevel 1 (
    echo   Python no encontrado. Instalando con winget...
    winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo.
        echo   winget no disponible. Descarga Python manualmente desde:
        echo   https://www.python.org/downloads/
        echo.
        echo   IMPORTANTE: marca "Add Python to PATH" durante la instalacion.
        echo   Luego reinicia y vuelve a ejecutar este archivo.
        pause
        exit /b 1
    )
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo   ✓ %%v

REM ── Paso 3: Dependencias Node ─────────────────────────────────────────────────
echo.
echo [3/4] Instalando dependencias de Node...
call npm install
if errorlevel 1 (
    echo.
    echo   ✗ ERROR: npm install fallo.
    pause
    exit /b 1
)
echo   ✓ Dependencias instaladas

REM ── Paso 4: Compilar ─────────────────────────────────────────────────────────
echo.
echo [4/4] Compilando Ebi Ball POS...
echo.
echo   → Compilando servidor Flask y bridge de impresion...
call scripts\build-server.bat
if errorlevel 1 (
    echo.
    echo   ✗ ERROR: build-server.bat fallo.
    pause
    exit /b 1
)

echo.
echo   → Empaquetando aplicacion para Windows...
call npm run build-win
if errorlevel 1 (
    echo.
    echo   ✗ ERROR: electron-builder fallo.
    pause
    exit /b 1
)

REM ── Resultado ─────────────────────────────────────────────────────────────────
echo.
echo ╔══════════════════════════════════════════╗
echo ║            ¡Compilacion lista!           ║
echo ╚══════════════════════════════════════════╝
echo.
echo   El ejecutable se encuentra en la carpeta dist\
echo.
for %%f in (dist\*.exe) do (
    echo   Archivo: %%f
)
echo.
echo   Para instalar: haz doble clic en el archivo EbiBall-POS-Portable.exe
echo.
explorer dist
pause
