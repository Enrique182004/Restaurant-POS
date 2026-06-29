#!/usr/bin/env python3
"""
Thermal Printer Bridge — Ebi Ball POS
Detecta la impresora automáticamente, la habilita si está desactivada,
y reintenta cuando se reconecta. No requiere configuración manual.
"""

import os
import time
import subprocess
import platform
import tempfile
import requests

# ── Configuración ─────────────────────────────────────────────────────────────
SERVER_URL    = os.environ.get('POS_SERVER_URL', 'http://localhost:5001')
PRINTER_NAME  = os.environ.get('POS_PRINTER_NAME', 'Printer_POS_80')
POLL_INTERVAL = 2    # segundos entre revisiones de la cola
MAX_WIDTH     = 42   # chars por línea para papel 80mm (deja margen derecho para evitar borrosidad)
LEFT_MARGIN   = 6    # margen izquierdo (evita corte y zona gris del cabezal)
MAX_RETRIES   = 5    # abandonar job después de N fallos consecutivos
FALLOS_ANTES_REDETECTAR = 3   # re-detectar impresora tras N fallos seguidos
VERIFICAR_IMPRESORA_CADA = 30 # revisar estado de impresora cada N ciclos (60s)

# Palabras clave para identificar impresoras POS/térmicas automáticamente
KEYWORDS_POS = [
    'pos', 'thermal', 'termica', 'receipt', 'ticket',
    '80', 'tm-', 'tsp', 'mr', 'boss', 'citizen', 'bixolon',
    'star', 'sewoo', 'xprinter', 'rongta', 'printer_pos',
]
# ─────────────────────────────────────────────────────────────────────────────


class ThermalPrintBridge:

    def __init__(self):
        self._fallos = {}           # job_id → nº de fallos consecutivos
        self._fallos_globales = 0   # fallos seguidos para disparar re-detección
        self._printer_name = self._leer_impresora()
        self._printer_name = self._verificar_y_activar(self._printer_name)
        print(f"Server URL:  {SERVER_URL}")
        print(f"Impresora:   {self._printer_name}")
        print(f"OS:          {platform.system()}")

    # ── Detección y activación de impresora ───────────────────────────────────

    def _leer_impresora(self):
        """Lee el nombre guardado en la BD del servidor; usa env var como fallback."""
        try:
            resp = requests.get(f'{SERVER_URL}/api/config', timeout=3)
            if resp.status_code == 200:
                nombre = resp.json().get('printer_name', '').strip()
                if nombre:
                    return nombre
        except Exception:
            pass
        return PRINTER_NAME

    def _guardar_impresora(self, nombre):
        """Guarda el nombre detectado en la BD vía API para que persista."""
        try:
            requests.post(
                f'{SERVER_URL}/api/config/printer',
                json={'printer_name': nombre},
                timeout=3,
            )
        except Exception:
            pass

    def _listar_impresoras_cups(self):
        """Devuelve lista de dicts {name, disabled} con todas las impresoras CUPS."""
        try:
            r = subprocess.run(
                ['lpstat', '-p'], capture_output=True, text=True, timeout=5
            )
            impresoras = []
            for line in r.stdout.splitlines():
                if line.startswith('printer '):
                    parts = line.split()
                    if len(parts) >= 2:
                        impresoras.append({
                            'name': parts[1],
                            'disabled': 'disabled' in line,
                        })
            return impresoras
        except Exception:
            return []

    def _listar_impresoras_windows(self):
        """Devuelve lista de nombres de impresoras en Windows."""
        try:
            r = subprocess.run(
                ['wmic', 'printer', 'get', 'name'],
                capture_output=True, text=True, timeout=5,
            )
            nombres = [
                l.strip() for l in r.stdout.splitlines()
                if l.strip() and l.strip().lower() != 'name'
            ]
            return [{'name': n, 'disabled': False} for n in nombres]
        except Exception:
            return []

    def _habilitar_cups(self, nombre):
        """Habilita una impresora desactivada en CUPS."""
        try:
            subprocess.run(['cupsenable', nombre], capture_output=True, timeout=5)
            print(f"[Impresora] '{nombre}' reactivada automáticamente.")
            return True
        except Exception:
            return False

    def _es_pos(self, nombre):
        """Devuelve True si el nombre de la impresora parece ser POS/térmica."""
        nombre_lower = nombre.lower()
        return any(kw in nombre_lower for kw in KEYWORDS_POS)

    def _verificar_y_activar(self, nombre_deseado):
        """
        1. Si el nombre configurado existe en el sistema, lo activa si está deshabilitado.
        2. Si no existe, busca cualquier impresora POS/térmica disponible.
        3. Guarda el nombre encontrado en la BD para la próxima vez.
        Devuelve el nombre de la impresora a usar.
        """
        # Rutas UNC (\\host\share) son configuración manual explícita para que
        # el comando `print` de Windows funcione — no aparecen en `wmic printer
        # get name` (que solo lista nombres locales), así que no se pueden
        # verificar contra esa lista. Sin este atajo, la auto-detección las
        # confundía con "no encontrada" y las sobrescribía con el nombre local
        # plano en cada reinicio, rompiendo la impresión de nuevo.
        if nombre_deseado.startswith('\\\\'):
            return nombre_deseado

        system = platform.system()

        if system in ('Darwin', 'Linux'):
            impresoras = self._listar_impresoras_cups()
        elif system == 'Windows':
            impresoras = self._listar_impresoras_windows()
        else:
            return nombre_deseado  # OS no soportado, usar el configurado

        nombres = {p['name'] for p in impresoras}

        # 1. La impresora configurada existe → habilitarla si está desactivada
        if nombre_deseado in nombres:
            for p in impresoras:
                if p['name'] == nombre_deseado and p['disabled']:
                    self._habilitar_cups(nombre_deseado)
            return nombre_deseado

        # 2. No encontrada → buscar cualquier POS/térmica
        print(f"[Impresora] '{nombre_deseado}' no encontrada. Buscando impresora POS...")
        for p in impresoras:
            if self._es_pos(p['name']):
                if p.get('disabled'):
                    self._habilitar_cups(p['name'])
                print(f"[Impresora] Detectada automáticamente: '{p['name']}'")
                self._guardar_impresora(p['name'])
                return p['name']

        # 3. No hay ninguna impresora POS → usar la configurada (fallback)
        print(f"[Impresora] No se encontró impresora POS. Usando '{nombre_deseado}' como fallback.")
        return nombre_deseado

    def redetectar(self):
        """Vuelve a buscar la impresora. Llama cuando hay fallos consecutivos."""
        print("[Impresora] Re-detectando impresora...")
        nuevo = self._verificar_y_activar(self._printer_name)
        if nuevo != self._printer_name:
            print(f"[Impresora] Cambiada a '{nuevo}'")
            self._printer_name = nuevo
            self._guardar_impresora(nuevo)

    # ── Helpers de texto ──────────────────────────────────────────────────────

    def clean_text(self, text):
        """Reemplaza caracteres que las impresoras térmicas no soportan."""
        reemplazos = {
            'ñ': 'n', 'Ñ': 'N',
            'á': 'a', 'à': 'a', 'ä': 'a', 'â': 'a',
            'é': 'e', 'è': 'e', 'ë': 'e', 'ê': 'e',
            'í': 'i', 'ì': 'i', 'ï': 'i', 'î': 'i',
            'ó': 'o', 'ò': 'o', 'ö': 'o', 'ô': 'o',
            'ú': 'u', 'ù': 'u', 'ü': 'u', 'û': 'u',
            'Á': 'A', 'À': 'A', 'Ä': 'A', 'Â': 'A',
            'É': 'E', 'È': 'E', 'Ë': 'E', 'Ê': 'E',
            'Í': 'I', 'Ì': 'I', 'Ï': 'I', 'Î': 'I',
            'Ó': 'O', 'Ò': 'O', 'Ö': 'O', 'Ô': 'O',
            'Ú': 'U', 'Ù': 'U', 'Ü': 'U', 'Û': 'U',
            '¡': '!', '¿': '?', '°': ' grados',
            '€': 'EUR', '¢': 'c', '£': 'GBP',
            '‘': "'", '’': "'",
            '“': '"', '”': '"',
            '…': '...', '–': '-', '—': '-',
        }
        for viejo, nuevo in reemplazos.items():
            text = text.replace(viejo, nuevo)
        return text

    def add_left_margin(self, text):
        """Agrega margen izquierdo y trunca al ancho máximo del papel."""
        margin = ' ' * LEFT_MARGIN
        result = []
        for line in text.split('\n'):
            margined = margin + line
            if len(margined) > MAX_WIDTH:
                margined = margined[:MAX_WIDTH]
            result.append(margined)
        return '\n'.join(result)

    def format_for_printer(self, receipt_content):
        """
        Limpia y aplica margen. Las líneas marcadas con \\x02 al inicio
        se imprimen en fuente doble-altura (ESC/POS) para que los nombres
        de artículos sean más fáciles de leer.
        Devuelve bytes listos para enviar a la impresora.
        """
        ESC_INIT         = b'\x1b\x40'       # Inicializar impresora
        ESC_DOBLE_ALTO   = b'\x1b\x21\x10'  # Fuente doble altura
        ESC_NORMAL       = b'\x1b\x21\x00'  # Fuente normal

        margin = ' ' * LEFT_MARGIN
        cleaned = self.clean_text(receipt_content)
        result = bytearray(ESC_INIT)

        # Margen amplio de papel en blanco al final: el corte es manual (sin
        # cuchilla automática), así que hace falta suficiente espacio para
        # que el corte no se lleve contenido del ticket.
        for line in ('\n' + cleaned + '\n' * 8).split('\n'):
            if line.startswith('\x02'):
                # Línea de nombre de artículo — doble altura
                contenido = line[1:]
                margined = margin + contenido
                if len(margined) > MAX_WIDTH:
                    margined = margined[:MAX_WIDTH]
                result += ESC_DOBLE_ALTO
                result += margined.encode('ascii', errors='replace') + b'\n'
                result += ESC_NORMAL
            else:
                margined = margin + line
                if len(margined) > MAX_WIDTH:
                    margined = margined[:MAX_WIDTH]
                result += margined.encode('ascii', errors='replace') + b'\n'

        return bytes(result)

    # ── Comunicación con la API ───────────────────────────────────────────────

    def get_pending_jobs(self):
        try:
            resp = requests.get(f'{SERVER_URL}/api/print_queue', timeout=5)
            if resp.status_code == 200:
                return resp.json().get('jobs', [])
        except requests.exceptions.RequestException as e:
            print(f"Sin conexión al servidor: {e}")
        return []

    def mark_job_printed(self, job_id):
        try:
            requests.post(f'{SERVER_URL}/api/mark_printed/{job_id}', timeout=5)
        except requests.exceptions.RequestException as e:
            print(f"No se pudo marcar job {job_id}: {e}")

    # ── Impresión ─────────────────────────────────────────────────────────────

    def send_to_printer(self, formatted_text):
        system = platform.system()

        if system == 'Windows':
            tmp_path = None
            try:
                raw_data = formatted_text if isinstance(formatted_text, bytes) else formatted_text.encode('ascii', errors='replace')
                with tempfile.NamedTemporaryFile(
                    mode='wb', suffix='.bin', delete=False,
                ) as tmp:
                    tmp.write(raw_data)
                    tmp_path = tmp.name
                result = subprocess.run(
                    ['print', f'/D:{self._printer_name}', tmp_path],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    print(f"Error de impresión Windows: {result.stderr}")
                return result.returncode == 0
            except Exception as e:
                print(f"Error Windows: {e}")
                return False
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

        elif system in ('Darwin', 'Linux'):
            try:
                # Enviar como bytes (necesario para comandos ESC/POS binarios)
                raw_data = formatted_text if isinstance(formatted_text, bytes) else formatted_text.encode('ascii', errors='replace')
                result = subprocess.run(
                    ['lpr', '-P', self._printer_name, '-o', 'raw'],
                    input=raw_data,
                    capture_output=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    print(f"lpr error: {result.stderr}")
                return result.returncode == 0
            except Exception as e:
                print(f"Error Unix: {e}")
                return False

        else:
            print(f"OS no soportado: {system}")
            return False

    def print_job(self, job):
        receipt_content = job.get('receipt_content', '')
        if not receipt_content:
            print(f"Job {job.get('id')} sin contenido — omitiendo")
            return False
        return self.send_to_printer(self.format_for_printer(receipt_content))

    # ── Loop principal ────────────────────────────────────────────────────────

    def run(self):
        print("Print Bridge iniciado")
        print(f"Servidor: {SERVER_URL}  |  Revisión cada {POLL_INTERVAL}s")
        print(f"Impresora activa: {self._printer_name}")
        print('-' * 50)

        ciclos_sin_verificar = 0

        try:
            while True:
                # Verificar proactivamente que la impresora sigue habilitada
                # aunque no haya jobs — evita que CUPS la deje desactivada silenciosamente
                ciclos_sin_verificar += 1
                if ciclos_sin_verificar >= VERIFICAR_IMPRESORA_CADA:
                    self._verificar_y_activar(self._printer_name)
                    ciclos_sin_verificar = 0

                jobs = self.get_pending_jobs()
                for job in jobs:
                    job_id = job.get('id', '?')
                    fallos = self._fallos.get(job_id, 0)

                    # Abandonar job si superó el límite de reintentos
                    if fallos >= MAX_RETRIES:
                        print(f"Job {job_id}: {MAX_RETRIES} fallos — abandonando.")
                        self.mark_job_printed(job_id)
                        self._fallos.pop(job_id, None)
                        continue

                    intento = f" (reintento {fallos + 1})" if fallos else ""
                    print(f"Imprimiendo job {job_id}{intento}...")
                    success = self.print_job(job)

                    if success:
                        print(f"  OK — impreso correctamente.")
                        self.mark_job_printed(job_id)
                        self._fallos.pop(job_id, None)
                        self._fallos_globales = 0
                    else:
                        self._fallos[job_id] = fallos + 1
                        self._fallos_globales += 1
                        restantes = MAX_RETRIES - (fallos + 1)
                        print(f"  FALLO — {restantes} intentos restantes para este job.")

                        # Re-detectar impresora tras varios fallos consecutivos
                        if self._fallos_globales >= FALLOS_ANTES_REDETECTAR:
                            self.redetectar()
                            self._fallos_globales = 0

                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\nPrint bridge detenido.")
        except Exception as e:
            print(f"Error en bridge: {e}")


if __name__ == '__main__':
    bridge = ThermalPrintBridge()
    bridge.run()
