@echo off
REM Construye el servidor Flask como ejecutable standalone con PyInstaller.
REM Ejecutar desde la raiz del proyecto: scripts\build-server.bat

echo === Construyendo servidor Flask con PyInstaller ===
cd /d "%~dp0\..\python-backend"

REM Crear venv si no existe
if not exist "venv" (
    echo Creando entorno virtual...
    python -m venv venv
    if errorlevel 1 (
        echo Error: No se pudo crear el entorno virtual. Asegurate de tener Python 3 instalado.
        exit /b 1
    )
)

set PYTHON=venv\Scripts\python.exe
set PIP=venv\Scripts\pip.exe

REM Instalar/actualizar dependencias
echo Instalando dependencias...
"%PIP%" install --upgrade pip --quiet
"%PIP%" install -r requirements.txt --quiet

REM Verificar PyInstaller
"%PYTHON%" -c "import PyInstaller" >nul 2>&1 || (
    echo Error: PyInstaller no se instalo correctamente.
    exit /b 1
)

REM Copiar site-packages a ruta fija (sin version de Python)
echo Copiando paquetes a ruta fija...
for /f "delims=" %%i in ('"%PYTHON%" -c "import sysconfig; print(sysconfig.get_path('purelib'))"') do set SITE_PACKAGES=%%i
if exist bundled-packages rmdir /s /q bundled-packages
xcopy /e /i /q "%SITE_PACKAGES%" bundled-packages >nul
echo Paquetes copiados.

REM Limpiar build anterior
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM Construir servidor Flask
"%PYTHON%" -m PyInstaller ebiball-server.spec --clean --noconfirm

REM Construir bridge de impresion
"%PYTHON%" -m PyInstaller print-bridge.spec --clean --noconfirm

echo.
echo === Construccion completada ===
echo Servidor:      python-backend\dist\ebiball-server\
echo Print bridge:  python-backend\dist\print-bridge\
echo.
echo Siguiente paso: npm run build-win
