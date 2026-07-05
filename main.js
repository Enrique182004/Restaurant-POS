"use strict";

const {
  app,
  BrowserWindow,
  Tray,
  Menu,
  nativeImage,
  dialog,
  ipcMain,
} = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const { version: APP_VERSION } = require("./package.json");
const { autoUpdater } = require("electron-updater");

// ── Actualizaciones automáticas ───────────────────────────────────────────────
let updateDownloaded = false;

function _sendUpdateStatus(state) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("update-status", { state });
  }
}

autoUpdater.on("update-available", () => {
  console.log(
    "[Updater] Actualización disponible — descargando en segundo plano...",
  );
  _sendUpdateStatus("downloading");
});

autoUpdater.on("update-not-available", () => {
  _sendUpdateStatus("up-to-date");
});

autoUpdater.on("update-downloaded", () => {
  updateDownloaded = true;
  _sendUpdateStatus("ready");
  // Notify the renderer — it shows a non-blocking banner instead of a dialog
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("update-ready");
  }
});

autoUpdater.on("error", (err) => {
  console.error("[Updater] Error:", err.message);
  _sendUpdateStatus("error");
});

ipcMain.on("install-update", () => {
  isQuitting = true;
  // Snapshot the DB right before applying the update so there is always a
  // point-in-time restore available even if today's daily backup is hours old.
  if (app.isPackaged && resolvedDbPath && fs.existsSync(resolvedDbPath)) {
    try {
      const backupsDir = path.join(app.getPath("userData"), "backups");
      fs.mkdirSync(backupsDir, { recursive: true });
      const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      const dest = path.join(backupsDir, `restaurant_preupdate_${ts}.db`);
      fs.copyFileSync(resolvedDbPath, dest);
      console.log("[DB] Backup pre-actualización creado:", dest);
    } catch (e) {
      console.error("[DB] Error en backup pre-actualización:", e.message);
    }
  }
  autoUpdater.quitAndInstall(false, true);
});

// Renderer can poll this on page load to catch updates downloaded before the page was ready
ipcMain.handle("get-update-ready", () => updateDownloaded);

ipcMain.handle("check-for-updates-now", () => {
  if (updateDownloaded) return { state: "ready" };
  autoUpdater
    .checkForUpdatesAndNotify()
    .catch(() => _sendUpdateStatus("error"));
  return { state: "checking" };
});

// ── Estado global ─────────────────────────────────────────────────────────────
let mainWindow = null;
let tray = null;
let flaskProcess = null;
let printBridgeProcess = null;
let inventoryServiceProcess = null;
let isQuitting = false;
let resolvedDbPath = null; // set once DB path is known, used for pre-update backup
let flaskRestarts = 0;
const MAX_FLASK_RESTARTS = 3;
let printBridgeRestarts = 0;
const MAX_PRINT_BRIDGE_RESTARTS = 5;
let inventoryServiceRestarts = 0;
const MAX_INVENTORY_SERVICE_RESTARTS = 5;
const FLASK_PORT = 5001;
const FLASK_URL = `http://localhost:${FLASK_PORT}`;

// ── Persistencia del estado de ventana ────────────────────────────────────────
function windowStateFile() {
  return path.join(app.getPath("userData"), "window-state.json");
}

function cargarEstadoVentana() {
  try {
    const data = JSON.parse(fs.readFileSync(windowStateFile(), "utf8"));
    if (data && data.width >= 1024 && data.height >= 600) {
      // Validar que la posición guardada sea visible en alguna pantalla
      // (evita ventana invisible al cambiar de monitor o resolución)
      if (data.x !== undefined && data.y !== undefined) {
        const { screen } = require("electron");
        const displays = screen.getAllDisplays();
        const enPantalla = displays.some((d) => {
          return (
            data.x >= d.bounds.x - 50 &&
            data.y >= d.bounds.y - 50 &&
            data.x < d.bounds.x + d.bounds.width &&
            data.y < d.bounds.y + d.bounds.height
          );
        });
        if (!enPantalla) {
          // Posición fuera de pantalla — ignorar x/y pero conservar tamaño
          return {
            width: data.width,
            height: data.height,
            maximized: data.maximized,
          };
        }
      }
      return data;
    }
  } catch (_) {}
  // Primera vez: maximizado por defecto (mejor para laptop)
  return { width: 1280, height: 800, maximized: true };
}

function guardarEstadoVentana() {
  if (!mainWindow) return;
  try {
    const maximized = mainWindow.isMaximized();
    // Guardar bounds normales (no maximizados) para poder restaurarlos
    const bounds = maximized
      ? mainWindow.getNormalBounds()
      : mainWindow.getBounds();
    fs.writeFileSync(
      windowStateFile(),
      JSON.stringify({ ...bounds, maximized }),
    );
  } catch (_) {}
}

// ── Ícono de la app ───────────────────────────────────────────────────────────
// Preferir PNG (mejor soporte en empaquetado), luego JPEG/JPG como fallback
const ICON_PATH =
  [
    path.join(__dirname, "assets", "icon.png"),
    path.join(__dirname, "assets", "icon.jpeg"),
    path.join(__dirname, "assets", "icon.jpg"),
  ].find(fs.existsSync) || path.join(__dirname, "assets", "icon.png");

function cargarIcono() {
  if (fs.existsSync(ICON_PATH)) {
    return nativeImage.createFromPath(ICON_PATH);
  }
  // Fallback: círculo naranja generado si el archivo aún no existe
  const size = 22;
  const bitmap = Buffer.alloc(size * size * 4, 0);
  const cx = size / 2,
    cy = size / 2,
    r = size / 2 - 1;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = (y * size + x) * 4;
      if (Math.sqrt((x - cx) ** 2 + (y - cy) ** 2) <= r) {
        bitmap[i] = 255;
        bitmap[i + 1] = 152;
        bitmap[i + 2] = 0;
        bitmap[i + 3] = 255;
      }
    }
  }
  return nativeImage.createFromBitmap(bitmap, { width: size, height: size });
}

// ── Bandeja del sistema ───────────────────────────────────────────────────────
function configurarBandeja() {
  const icono = cargarIcono();
  tray = new Tray(icono);
  tray.setToolTip("Ebi Ball POS");

  const menu = Menu.buildFromTemplate([
    {
      label: "Mostrar aplicación",
      click: () => mostrarVentana(),
    },
    {
      label: "Ir al menú principal",
      click: () => {
        mostrarVentana();
        if (mainWindow) mainWindow.loadURL(FLASK_URL);
      },
    },
    { type: "separator" },
    {
      label: "Salir",
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(menu);

  tray.on("double-click", () => mostrarVentana());
  // En Windows un solo clic también muestra la ventana
  if (process.platform === "win32") {
    tray.on("click", () => mostrarVentana());
  }
}

function mostrarVentana() {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

// ── Pantalla de carga: actualizar progreso ────────────────────────────────────
async function setLoadingStatus(msg) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  try {
    await mainWindow.webContents.executeJavaScript(
      `typeof setStatus==='function' && setStatus(${JSON.stringify(msg)})`,
    );
  } catch (_) {}
}

async function setLoadingProgress(pct) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  try {
    await mainWindow.webContents.executeJavaScript(
      `typeof setProgress==='function' && setProgress(${Number(pct)})`,
    );
  } catch (_) {}
}

// ── Creación de la ventana principal ─────────────────────────────────────────
function crearVentana() {
  const estado = cargarEstadoVentana();

  mainWindow = new BrowserWindow({
    width: estado.width,
    height: estado.height,
    x: estado.x,
    y: estado.y,
    minWidth: 960,
    minHeight: 620,
    show: false,
    backgroundColor: "#121212",
    icon: fs.existsSync(ICON_PATH) ? ICON_PATH : undefined,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      devTools: !app.isPackaged,
      preload: path.join(__dirname, "preload.js"),
    },
    title: "Ebi Ball POS",
  });

  mainWindow.setMenuBarVisibility(false);

  // Guardar posición/tamaño/estado al mover, redimensionar o cambiar maximizado
  mainWindow.on("moved", guardarEstadoVentana);
  mainWindow.on("resized", guardarEstadoVentana);
  mainWindow.on("maximize", guardarEstadoVentana);
  mainWindow.on("unmaximize", guardarEstadoVentana);

  // Minimizar a bandeja en vez de cerrar
  mainWindow.on("close", (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
      if (tray && process.platform === "win32") {
        tray.displayBalloon({
          title: "Ebi Ball POS",
          content: "La aplicación sigue corriendo en segundo plano.",
          iconType: "info",
        });
      }
    }
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  // Mostrar ventana sólo cuando esté lista (evita el flash blanco)
  // En laptops iniciamos maximizado por defecto para usar toda la pantalla
  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    const estado = cargarEstadoVentana();
    if (estado.maximized !== false) mainWindow.maximize();
  });

  return mainWindow;
}

// ── Servidor Flask ────────────────────────────────────────────────────────────
function iniciarFlask(backendDir, dbPath) {
  return new Promise((resolve) => {
    const resourcesPath = process.resourcesPath || __dirname;

    // Buscar Python: primero el venv local (desarrollo), luego sistema
    const isWindows = process.platform === "win32";
    const venvPython = isWindows
      ? path.join(__dirname, "python-backend", "venv", "Scripts", "python.exe")
      : path.join(__dirname, "python-backend", "venv", "bin", "python");

    let pythonBin;
    if (fs.existsSync(venvPython)) {
      pythonBin = venvPython; // desarrollo local con venv
    } else if (isWindows) {
      // En Windows: intentar 'python' (más común que 'python3')
      pythonBin = "python";
    } else {
      pythonBin = "python3";
    }

    const pythonScript = path.join(backendDir, "app.py");

    // Paquetes bundleados (extraResources en la app empaquetada)
    const bundledPackages = path.join(resourcesPath, "python-packages");
    const existingPythonPath = process.env.PYTHONPATH || "";
    const sep = path.delimiter; // ':' en Unix, ';' en Windows
    const pythonPath = fs.existsSync(bundledPackages)
      ? existingPythonPath
        ? `${bundledPackages}${sep}${existingPythonPath}`
        : bundledPackages
      : existingPythonPath;

    const env = {
      ...process.env,
      PYTHONPATH: pythonPath,
      RESTAURANT_DB_PATH: dbPath || "",
    };

    // Buscar el servidor bundleado (PyInstaller) primero — no requiere Python instalado
    const serverName = isWindows ? "ebiball-server.exe" : "ebiball-server";
    const bundledServer = path.join(resourcesPath, "server", serverName);

    let args, bin;
    if (fs.existsSync(bundledServer)) {
      // Producción: usar ejecutable standalone
      bin = bundledServer;
      args = [];
      env.FLASK_APP_DIR = backendDir; // indica dónde están templates/ y static/
      console.log(`[Flask] Usando servidor bundleado: ${bundledServer}`);
    } else {
      // Desarrollo: verificar que Python exista antes de intentar lanzarlo
      const { spawnSync } = require("child_process");
      const pythonCheck = spawnSync(pythonBin, ["--version"], {
        timeout: 5000,
        stdio: "ignore",
      });
      if (pythonCheck.error) {
        const { dialog } = require("electron");
        dialog.showErrorBox(
          "Python no encontrado",
          isWindows
            ? "Esta aplicación requiere Python 3.x.\n\nDescárgalo desde https://www.python.org e instálalo marcando 'Add Python to PATH'.\nLuego reinicia la aplicación."
            : "Esta aplicación requiere Python 3.\n\nInstálalo con:\n  brew install python3\nLuego reinicia la aplicación.",
        );
        return resolve();
      }
      bin = pythonBin;
      args = [pythonScript];
      console.log(`[Flask] Iniciando con Python: ${pythonBin} ${pythonScript}`);
    }

    flaskProcess = spawn(bin, args, { cwd: backendDir, env });

    let resuelto = false;
    const doResolve = () => {
      if (!resuelto) {
        resuelto = true;
        resolve();
      }
    };

    flaskProcess.stdout.on("data", (d) => {
      const text = d.toString();
      console.log(`[Flask] ${text.trim()}`);
      if (text.includes("Running on")) {
        flaskRestarts = 0; // resetear contador al arrancar exitosamente
        doResolve();
      }
    });

    flaskProcess.stderr.on("data", (d) => {
      const text = d.toString();
      console.error(`[Flask] ${text.trim()}`);
      if (text.includes("Running on")) {
        flaskRestarts = 0; // resetear contador al arrancar exitosamente
        doResolve();
      }
    });

    flaskProcess.on("close", (code) => {
      console.log(`[Flask] Proceso terminó con código ${code}`);
      flaskProcess = null;
      doResolve(); // asegura que la promesa se resuelva

      // Watchdog: reiniciar automáticamente si fue un crash (no un cierre intencional)
      if (!isQuitting && flaskRestarts < MAX_FLASK_RESTARTS) {
        flaskRestarts++;
        console.log(
          `[Flask] Reiniciando automáticamente (intento ${flaskRestarts}/${MAX_FLASK_RESTARTS})...`,
        );

        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents
            .executeJavaScript(`document.title = 'Reconectando...'`)
            .catch(() => {});
        }

        setTimeout(async () => {
          liberarPuerto(FLASK_PORT);
          await iniciarFlask(backendDir, dbPath);
          cargarAppConReintentos();
        }, 2000);
      } else if (!isQuitting) {
        // Se agotaron los reintentos — mostrar error al usuario
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow
            .loadURL(
              "data:text/html," +
                encodeURIComponent(
                  '<!doctype html><html lang="es"><head><meta charset="UTF-8">' +
                    "<style>body{background:#121212;color:#f5f5f5;font-family:sans-serif;" +
                    "display:flex;flex-direction:column;align-items:center;justify-content:center;" +
                    "height:100vh;margin:0;text-align:center;gap:16px;}" +
                    "h2{color:#ff9800;}p{color:#888;max-width:400px;}" +
                    "button{background:#ff9800;color:#121212;border:none;padding:12px 28px;" +
                    "border-radius:10px;font-size:1rem;font-weight:700;cursor:pointer;}</style></head>" +
                    "<body><h2>&#9888;&#65039; Error del servidor</h2>" +
                    "<p>El servidor de la aplicaci&#243;n no pudo reiniciarse autom&#225;ticamente.</p>" +
                    '<button onclick="location.reload()">Reintentar</button>' +
                    "</body></html>",
                ),
            )
            .catch(() => {});
        }
      }
    });

    // Fallback de seguridad: continuar después de 22 segundos
    setTimeout(doResolve, 22000);
  });
}

// ── Bridge de impresión ───────────────────────────────────────────────────────
function iniciarPrintBridge(backendDir) {
  const resourcesPath = process.resourcesPath || __dirname;
  const isWin = process.platform === "win32";

  // Prefer bundled PyInstaller executable; fall back to Python script in dev
  const bundledName = isWin ? "print-bridge.exe" : "print-bridge";
  const bundledExe = path.join(resourcesPath, "print-bridge", bundledName);

  let bin, args;
  if (fs.existsSync(bundledExe)) {
    bin = bundledExe;
    args = [];
    console.log("[PrintBridge] Usando ejecutable bundled.");
  } else {
    const bridgeScript = path.join(backendDir, "print_bridge.py");
    if (!fs.existsSync(bridgeScript)) {
      console.warn("[PrintBridge] print_bridge.py no encontrado — omitiendo.");
      return;
    }
    const venvPython = isWin
      ? path.join(__dirname, "python-backend", "venv", "Scripts", "python.exe")
      : path.join(__dirname, "python-backend", "venv", "bin", "python");
    bin = fs.existsSync(venvPython) ? venvPython : isWin ? "python" : "python3";
    args = [bridgeScript];
    console.log("[PrintBridge] Usando script Python (modo dev).");
  }

  const env = {
    ...process.env,
    POS_SERVER_URL: FLASK_URL,
  };

  console.log("[PrintBridge] Iniciando bridge de impresión...");
  printBridgeProcess = spawn(bin, args, {
    cwd: backendDir,
    env,
  });

  printBridgeProcess.stdout.on("data", (d) =>
    console.log(`[PrintBridge] ${d.toString().trim()}`),
  );
  printBridgeProcess.stderr.on("data", (d) =>
    console.error(`[PrintBridge] ${d.toString().trim()}`),
  );

  printBridgeProcess.on("close", (code) => {
    console.log(`[PrintBridge] Proceso terminó con código ${code}`);
    printBridgeProcess = null;
    // Reiniciar el bridge si fue un crash, con límite de intentos
    if (
      !isQuitting &&
      code !== 0 &&
      printBridgeRestarts < MAX_PRINT_BRIDGE_RESTARTS
    ) {
      printBridgeRestarts++;
      console.log(
        `[PrintBridge] Reiniciando en 5 segundos (intento ${printBridgeRestarts}/${MAX_PRINT_BRIDGE_RESTARTS})...`,
      );
      setTimeout(() => iniciarPrintBridge(backendDir), 5000);
    } else if (!isQuitting && code !== 0) {
      console.warn(
        "[PrintBridge] Se agotaron los reintentos. La impresora no está disponible.",
      );
    }
  });
}

// Mata cualquier proceso que esté ocupando el puerto para evitar que el
// restart loop se dispare cuando queda un proceso huérfano de una sesión
// anterior (antes de que el SIGTERM handler existiera).
function liberarPuerto(port) {
  const { spawnSync } = require("child_process");
  const isWin = process.platform === "win32";
  try {
    if (isWin) {
      const r = spawnSync("netstat", ["-ano"], {
        encoding: "utf8",
        timeout: 5000,
      });
      if (!r.stdout) return;
      const pids = new Set();
      for (const line of r.stdout.split("\n")) {
        if (line.includes(`:${port}`) && line.includes("LISTENING")) {
          const parts = line.trim().split(/\s+/);
          const pid = parts[parts.length - 1];
          if (pid && /^\d+$/.test(pid) && pid !== "0") pids.add(pid);
        }
      }
      for (const pid of pids) {
        console.log(
          `[InventoryService] Puerto ${port} ocupado — terminando PID ${pid}`,
        );
        spawnSync("taskkill", ["/F", "/PID", pid], { timeout: 5000 });
      }
    } else {
      const r = spawnSync("lsof", ["-ti", `:${port}`], {
        encoding: "utf8",
        timeout: 5000,
      });
      if (!r.stdout) return;
      for (const pid of r.stdout.trim().split("\n").filter(Boolean)) {
        console.log(
          `[InventoryService] Puerto ${port} ocupado — terminando PID ${pid}`,
        );
        spawnSync("kill", ["-9", pid], { timeout: 5000 });
      }
    }
  } catch (e) {
    console.warn(`[InventoryService] liberarPuerto(${port}) falló:`, e.message);
  }
}

// ── Servicio de inventario (Java) ─────────────────────────────────────────────
// Mismo patrón que iniciarPrintBridge: preferir un JRE bundleado (futuro paso
// de build con jlink/jpackage), si no existe usar 'java' del sistema + el jar.
// Si ninguno está disponible, omitir — Flask ya degrada con gracia (lista
// vacía) cuando el servicio de inventario no responde.
function iniciarInventoryService(dbPath) {
  liberarPuerto(8081);
  const resourcesPath = process.resourcesPath || __dirname;
  const isWin = process.platform === "win32";

  const jarName = "inventory-service-1.0.0.jar";
  const bundledJar = path.join(resourcesPath, "inventory-service", jarName);
  const devJar = path.join(
    __dirname,
    "java-services",
    "inventory-service",
    "target",
    jarName,
  );
  const jarPath = fs.existsSync(bundledJar) ? bundledJar : devJar;

  if (!fs.existsSync(jarPath)) {
    console.warn(
      "[InventoryService] jar no encontrado — omitiendo (la página de inventario mostrará una lista vacía).",
    );
    return;
  }

  // JRE bundleado (cuando exista): resourcesPath/inventory-service/jre/bin/java[.exe]
  const bundledJre = path.join(
    resourcesPath,
    "inventory-service",
    "jre",
    "bin",
    isWin ? "java.exe" : "java",
  );
  const javaBin = fs.existsSync(bundledJre) ? bundledJre : "java";

  if (javaBin === "java") {
    const { spawnSync } = require("child_process");
    const javaCheck = spawnSync(javaBin, ["-version"], {
      timeout: 5000,
      stdio: "ignore",
    });
    if (javaCheck.error) {
      console.warn(
        "[InventoryService] No se encontró un Java instalado en el sistema — omitiendo (la página de inventario mostrará una lista vacía).",
      );
      return;
    }
  }

  console.log(`[InventoryService] Iniciando con: ${javaBin} -jar ${jarPath}`);
  inventoryServiceProcess = spawn(
    javaBin,
    [`-Dapp.db.path=${dbPath}`, "-jar", jarPath],
    { env: process.env },
  );

  inventoryServiceProcess.stdout.on("data", (d) =>
    console.log(`[InventoryService] ${d.toString().trim()}`),
  );
  inventoryServiceProcess.stderr.on("data", (d) =>
    console.error(`[InventoryService] ${d.toString().trim()}`),
  );

  inventoryServiceProcess.on("close", (code) => {
    console.log(`[InventoryService] Proceso terminó con código ${code}`);
    inventoryServiceProcess = null;
    if (
      !isQuitting &&
      code !== 0 &&
      inventoryServiceRestarts < MAX_INVENTORY_SERVICE_RESTARTS
    ) {
      inventoryServiceRestarts++;
      console.log(
        `[InventoryService] Reiniciando en 5 segundos (intento ${inventoryServiceRestarts}/${MAX_INVENTORY_SERVICE_RESTARTS})...`,
      );
      setTimeout(() => iniciarInventoryService(dbPath), 5000);
    } else if (!isQuitting && code !== 0) {
      console.warn(
        "[InventoryService] Se agotaron los reintentos. El inventario no estará disponible.",
      );
    }
  });
}

// ── Cargar la app Flask con reintentos ────────────────────────────────────────
function cargarAppConReintentos() {
  if (!mainWindow || mainWindow.isDestroyed()) return;

  let intentos = 0;
  const MAX_INTENTOS = 20;

  function intentar() {
    if (!mainWindow || mainWindow.isDestroyed()) return;

    mainWindow.loadURL(FLASK_URL).catch(() => {
      if (intentos < MAX_INTENTOS) {
        intentos++;
        setTimeout(intentar, 1000);
      } else {
        // La app sigue sin responder después de 20 segundos — mostrar error
        mainWindow.loadURL(
          "data:text/html," +
            encodeURIComponent(
              '<!doctype html><html lang="es"><head><meta charset="UTF-8">' +
                "<style>body{background:#121212;color:#f5f5f5;font-family:sans-serif;" +
                "display:flex;flex-direction:column;align-items:center;justify-content:center;" +
                "height:100vh;margin:0;text-align:center;gap:16px;}" +
                "h2{color:#ff9800;}p{color:#888;max-width:400px;}" +
                "button{background:#ff9800;color:#121212;border:none;padding:12px 28px;" +
                "border-radius:10px;font-size:1rem;font-weight:700;cursor:pointer;}</style></head>" +
                "<body><h2>⚠️ Error al iniciar</h2>" +
                "<p>El servidor tardó demasiado en responder. Cierra y vuelve a abrir la aplicación.</p>" +
                '<button onclick="location.reload()">Reintentar</button>' +
                "</body></html>",
            ),
        );
      }
    });
  }

  intentar();
}

// ── Flujo principal de arranque ───────────────────────────────────────────────
app.on("ready", async () => {
  crearVentana();

  // Mostrar pantalla de carga inmediatamente
  mainWindow.loadFile(path.join(__dirname, "loading.html"));

  // Esperar a que la pantalla de carga esté lista antes de enviar mensajes
  await new Promise((resolve) => {
    mainWindow.webContents.once("did-finish-load", resolve);
  });

  // Mostrar versión en pantalla de carga
  try {
    await mainWindow.webContents.executeJavaScript(
      `typeof setVersion==='function' && setVersion(${JSON.stringify(APP_VERSION)})`,
    );
  } catch (_) {}

  // Configurar bandeja del sistema
  configurarBandeja();

  // Determinar directorio del backend (dev vs. app empaquetada)
  const resourcesPath = process.resourcesPath || __dirname;
  const backendDir = fs.existsSync(
    path.join(resourcesPath, "python-backend", "app.py"),
  )
    ? path.join(resourcesPath, "python-backend")
    : path.join(__dirname, "python-backend");

  // ── Base de datos ────────────────────────────────────────────────────────────
  // Dev: usar restaurant.db junto al código para que todo quede en el proyecto.
  // Producción: usar userData (directorio escribible fuera del bundle).
  const dbPath = app.isPackaged
    ? path.join(app.getPath("userData"), "restaurant.db")
    : path.join(__dirname, "python-backend", "restaurant.db");

  if (app.isPackaged) {
    // Primera vez en producción: copiar BD base desde recursos si existe
    if (!fs.existsSync(dbPath)) {
      const dbEnResources = path.join(backendDir, "restaurant.db");
      if (fs.existsSync(dbEnResources)) {
        fs.copyFileSync(dbEnResources, dbPath);
        console.log("[DB] Base de datos migrada a userData:", dbPath);
      } else {
        console.log("[DB] Nueva instalación — Flask creará la BD en:", dbPath);
      }
    }

    // Backup diario (máximo 7 días)
    try {
      const backupsDir = path.join(app.getPath("userData"), "backups");
      fs.mkdirSync(backupsDir, { recursive: true });
      const fechaHoy = new Date().toISOString().slice(0, 10);
      const backupPath = path.join(backupsDir, `restaurant_${fechaHoy}.db`);
      if (fs.existsSync(dbPath) && !fs.existsSync(backupPath)) {
        fs.copyFileSync(dbPath, backupPath);
        console.log("[DB] Backup creado:", backupPath);
      }
      const backups = fs
        .readdirSync(backupsDir)
        .filter((f) => f.endsWith(".db"))
        .sort()
        .reverse();
      backups.slice(7).forEach((b) => {
        fs.unlinkSync(path.join(backupsDir, b));
        console.log("[DB] Backup antiguo eliminado:", b);
      });
    } catch (e) {
      console.error("[DB] Error en backup:", e.message);
    }
  }

  resolvedDbPath = dbPath;
  console.log("[DB] Usando base de datos en:", dbPath);

  // ── Paso 1: Flask ─────────────────────────────────────────────────────────
  await setLoadingStatus("Iniciando servidor de la aplicación...");
  await setLoadingProgress(20);
  await iniciarFlask(backendDir, dbPath);
  await setLoadingProgress(70);

  // ── Paso 2: Print bridge (no bloqueante) ─────────────────────────────────
  await setLoadingStatus("Iniciando bridge de impresión...");
  iniciarPrintBridge(backendDir); // fire and forget
  await setLoadingProgress(80);

  // ── Paso 2b: Servicio de inventario (no bloqueante) ──────────────────────
  await setLoadingStatus("Iniciando servicio de inventario...");
  iniciarInventoryService(dbPath); // fire and forget
  await setLoadingProgress(85);

  // ── Paso 3: Cargar la app ─────────────────────────────────────────────────
  await setLoadingStatus("Cargando aplicación...");
  await setLoadingProgress(95);

  cargarAppConReintentos();

  // ── Verificar actualizaciones (5 seg después de cargar, luego cada 30 min) ──
  const checkForUpdates = () =>
    autoUpdater.checkForUpdatesAndNotify().catch(() => {});
  setTimeout(checkForUpdates, 5000);
  const updaterInterval = setInterval(checkForUpdates, 30 * 60 * 1000);
  app.once("before-quit", () => clearInterval(updaterInterval));
});

// ── Gestión del ciclo de vida de la app ──────────────────────────────────────

// Mantener la app viva aunque se cierren todas las ventanas (el tray la sigue corriendo)
app.on("window-all-closed", () => {
  // Deliberadamente no llamamos app.quit() aquí para que el tray siga activo
});

// En macOS: mostrar la ventana cuando el usuario hace clic en el ícono del Dock
app.on("activate", () => {
  if (mainWindow) {
    mostrarVentana();
  }
});

// Marcar intento de cierre para que los handlers de 'close' no prevengan el cierre
app.on("before-quit", () => {
  isQuitting = true;
});

// Asegurar limpieza si el proceso recibe SIGTERM/SIGINT (kill externo, gestor
// de procesos, etc.) en vez de cerrarse desde la UI normal — sin esto, Flask,
// el print bridge y el servicio de inventario quedan huérfanos corriendo en
// segundo plano (incluyendo ocupando sus puertos en el siguiente arranque).
function terminarPorSenal() {
  isQuitting = true;
  app.quit();
}
process.on("SIGTERM", terminarPorSenal);
process.on("SIGINT", terminarPorSenal);

// Terminar procesos hijos al salir
app.on("quit", () => {
  console.log("[App] Cerrando procesos hijos...");

  if (tray) {
    tray.destroy();
    tray = null;
  }
  if (flaskProcess) {
    flaskProcess.kill("SIGKILL");
    console.log("[App] Flask terminado.");
  }
  if (printBridgeProcess) {
    printBridgeProcess.kill("SIGKILL");
    console.log("[App] PrintBridge terminado.");
  }
  if (inventoryServiceProcess) {
    inventoryServiceProcess.kill("SIGKILL");
    console.log("[App] InventoryService terminado.");
  }
});
