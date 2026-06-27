# Cómo hacer actualizaciones — Ebi Ball POS

## ¿Qué pasa con la base de datos durante una actualización?

**La base de datos NO se pierde.** Está guardada en la carpeta de datos del usuario del sistema operativo:

- **macOS:** `~/Library/Application Support/ebi-ball-pos/restaurant.db`
- **Windows:** `%APPDATA%\ebi-ball-pos\restaurant.db`

Esta carpeta nunca se toca al instalar o actualizar la app. También se hace un **backup automático diario** en la carpeta `backups/` del mismo directorio.

---

## Flujo de actualización (automático vía GitHub)

### Configuración inicial (una sola vez)

1. Crear repositorio en GitHub llamado `ebi-ball-pos`
2. En package.json, cambiar `"owner": "GITHUB_USERNAME"` por tu usuario de GitHub
3. En GitHub → Settings → Secrets → Actions, agregar:
   - `GH_TOKEN` = tu Personal Access Token con permisos de `write:packages` y `repo`
4. Subir el código inicial: `git init && git add . && git commit -m "Initial commit" && git push`

### Para publicar una actualización

1. Hacer los cambios en el código en tu laptop de desarrollo
2. Actualizar la versión en `package.json`: `"version": "1.0.1"` (o la versión siguiente)
3. Hacer commit y crear un tag con esa versión:
   ```bash
   git add .
   git commit -m "Versión 1.0.1 — descripción del cambio"
   git tag v1.0.1
   git push && git push --tags
   ```
4. GitHub Actions construirá automáticamente el instalador (.dmg para Mac, .exe para Windows)
5. La app en el restaurante detectará la actualización en los próximos minutos y mostrará un aviso

### ¿Qué ve el personal del restaurante?

Un mensaje dice: _"¡Hay una nueva versión de Ebi Ball POS lista para instalar!"_  
Con dos botones: **Instalar ahora** o **Más tarde**.  
Si eligen "Instalar ahora", la app se cierra, instala la actualización, y vuelve a abrir.  
La base de datos queda intacta.

---

## Actualizaciones manuales (sin GitHub)

Si prefieres no usar GitHub:

1. Construir el instalador manualmente:
   ```bash
   npm run build-mac   # Para macOS → genera dist/Ebi Ball POS.dmg
   npm run build-win   # Para Windows → genera dist/Ebi Ball POS Setup.exe
   ```
2. Copiar el archivo generado en `dist/` a una USB o Google Drive
3. En el restaurante: abrir el instalador y seguir los pasos (doble clic)
4. La base de datos se preserva automáticamente

---

## Recuperar la base de datos desde un backup

Si por alguna razón se necesita restaurar:

**macOS/Linux:**

```bash
cp "~/Library/Application Support/ebi-ball-pos/backups/restaurant_2025-05-17.db" \
   "~/Library/Application Support/ebi-ball-pos/restaurant.db"
```

**Windows (PowerShell):**

```powershell
Copy-Item "$env:APPDATA\ebi-ball-pos\backups\restaurant_2025-05-17.db" `
          "$env:APPDATA\ebi-ball-pos\restaurant.db"
```

Luego reiniciar la app.

---

## Cambios en la base de datos (nuevas tablas o columnas)

Los cambios de estructura se hacen automáticamente al abrir la app. El archivo `app.py` contiene la función `init_db()` que detecta si faltan columnas o tablas y las agrega sin borrar los datos existentes.
