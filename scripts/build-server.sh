#!/bin/bash
# Construye el servidor Flask como ejecutable standalone con PyInstaller.
# Ejecutar desde la raíz del proyecto: bash scripts/build-server.sh
set -e

echo "=== Construyendo servidor Flask con PyInstaller ==="
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/../python-backend"
cd "$BACKEND_DIR"

# Crear venv si no existe
if [ ! -d "venv" ]; then
    echo "Creando entorno virtual..."
    python3 -m venv venv
fi

PYTHON="venv/bin/python"
PIP="venv/bin/pip"

# Instalar/actualizar dependencias
echo "Instalando dependencias..."
"$PIP" install --upgrade pip --quiet
"$PIP" install -r requirements.txt --quiet

# Verificar PyInstaller
"$PYTHON" -c "import PyInstaller" 2>/dev/null || {
    echo "Error: PyInstaller no se instaló correctamente."
    exit 1
}

# Copiar site-packages a ruta fija (sin versión de Python)
# Esto permite que package.json use una ruta estable sin importar la versión de Python
SITE_PACKAGES="$("$PYTHON" -c "import sysconfig; print(sysconfig.get_path('purelib'))")"
echo "Copiando paquetes desde: $SITE_PACKAGES"
rm -rf bundled-packages
cp -r "$SITE_PACKAGES" bundled-packages
echo "Paquetes copiados a: $BACKEND_DIR/bundled-packages"

# Limpiar build anterior
rm -rf build/ dist/

# Construir servidor Flask
"$PYTHON" -m PyInstaller ebiball-server.spec --clean --noconfirm

# Construir bridge de impresión
"$PYTHON" -m PyInstaller print-bridge.spec --clean --noconfirm

echo ""
echo "=== Construcción completada ==="
echo "Servidor:      python-backend/dist/ebiball-server/"
echo "Print bridge:  python-backend/dist/print-bridge/"
echo ""
echo "Siguiente paso: npm run build-mac o npm run build-win"
