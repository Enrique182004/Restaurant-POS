#!/bin/bash
# Ebi Ball POS — Instalación y compilación para macOS
# Haz doble clic en este archivo para construir la aplicación.

# Abrir en la carpeta del proyecto (los .command se abren desde ~)
cd "$(dirname "$0")"

clear
echo "╔══════════════════════════════════════════╗"
echo "║       Ebi Ball POS — Instalación         ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Función de error ──────────────────────────────────────────────────────────
error() {
    echo ""
    echo "✗ ERROR: $1"
    echo ""
    read -rp "Presiona Enter para cerrar..."
    exit 1
}

ok() { echo "  ✓ $1"; }

# ── Paso 1: Xcode Command Line Tools ─────────────────────────────────────────
echo "[1/5] Verificando Xcode Command Line Tools..."
if ! xcode-select -p &>/dev/null; then
    echo "  Instalando Xcode Command Line Tools (requerido para compilar)..."
    xcode-select --install
    echo "  Espera a que termine la instalación y vuelve a ejecutar este archivo."
    read -rp "  Presiona Enter para cerrar..."
    exit 0
fi
ok "Xcode Command Line Tools"

# ── Paso 2: Homebrew ──────────────────────────────────────────────────────────
echo ""
echo "[2/5] Verificando Homebrew..."
if ! command -v brew &>/dev/null; then
    echo "  Instalando Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
        || error "No se pudo instalar Homebrew."
    # Agregar brew al PATH para Apple Silicon
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
fi
ok "Homebrew $(brew --version | head -1)"

# ── Paso 3: Node.js ───────────────────────────────────────────────────────────
echo ""
echo "[3/5] Verificando Node.js..."
if ! command -v node &>/dev/null; then
    echo "  Instalando Node.js..."
    brew install node || error "No se pudo instalar Node.js."
fi
ok "Node.js $(node --version)"

# ── Paso 4: Python 3 ─────────────────────────────────────────────────────────
echo ""
echo "[4/5] Verificando Python 3..."
if ! command -v python3 &>/dev/null; then
    echo "  Instalando Python 3..."
    brew install python3 || error "No se pudo instalar Python 3."
fi
ok "Python $(python3 --version)"

# ── Paso 5: Construir la aplicación ──────────────────────────────────────────
echo ""
echo "[5/5] Construyendo Ebi Ball POS..."
echo ""

echo "  → Instalando dependencias de Node..."
npm install || error "npm install falló."

echo ""
echo "  → Compilando servidor Flask y bridge de impresión..."
bash scripts/build-server.sh || error "build-server.sh falló."

echo ""
echo "  → Empaquetando aplicación para macOS..."
npm run build-mac || error "electron-builder falló."

# ── Resultado ─────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║            ¡Compilación lista!           ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  El instalador se encuentra en la carpeta dist/"
echo ""
DMG=$(ls dist/*.dmg 2>/dev/null | head -1)
if [[ -n "$DMG" ]]; then
    echo "  Archivo: $DMG"
    echo ""
    echo "  Para instalar: abre el .dmg y arrastra la app a Aplicaciones."
    open dist/
fi
echo ""
read -rp "Presiona Enter para cerrar..."
