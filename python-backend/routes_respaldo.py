"""Respaldo de la base de datos: exportar/importar para migrar de computadora."""
import csv
import io
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

from flask import (render_template, request, redirect, url_for, session,
                   flash, jsonify, Response, send_file)

from auth import login_required, admin_required
from db import (get_db_connection, log_activity, _get_db_path,
                backup_db_to_file, get_item_price, get_menu_options)
from business import (money, format_num, get_week_bounds, parse_scheduled_days,
                      resolve_employee_schedule, compute_employee_pay)


def register(app):
    # ── Respaldo de la base de datos ──────────────────────────────────────────────

    @app.route('/admin/respaldo')
    @login_required
    @admin_required
    def respaldo():
        conn = get_db_connection()
        total_ordenes = conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        db_size_kb = os.path.getsize(_get_db_path()) // 1024
        return render_template('respaldo.html', db_size_kb=db_size_kb, total_ordenes=total_ordenes)


    @app.route('/admin/respaldo/exportar')
    @login_required
    @admin_required
    def respaldo_exportar():
        # Snapshot a un tempfile que se borra de inmediato: el contenido viaja en
        # memoria para no acumular archivos huérfanos en el directorio temporal.
        fd, tmp_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        try:
            backup_db_to_file(_get_db_path(), tmp_path)
            with open(tmp_path, 'rb') as f:
                data = f.read()
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        log_activity('respaldo_exportado', 'Respaldo de la base de datos exportado')
        return send_file(io.BytesIO(data), as_attachment=True,
                         download_name=f'ebiball_respaldo_{datetime.now().strftime("%Y-%m-%d")}.db')


    @app.route('/admin/respaldo/importar', methods=['POST'])
    @login_required
    @admin_required
    def respaldo_importar():
        archivo = request.files.get('respaldo')
        if 'respaldo' not in request.files or not archivo or not archivo.filename:
            flash('Selecciona un archivo de respaldo.', 'error')
            return redirect(url_for('respaldo'))

        fd, tmp_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        try:
            archivo.save(tmp_path)

            # Validar: integridad SQLite + que contenga las tablas del sistema
            try:
                check = sqlite3.connect(tmp_path)
                try:
                    integridad = check.execute('PRAGMA integrity_check').fetchone()[0]
                    tablas = {row[0] for row in check.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                finally:
                    check.close()
                valido = integridad == 'ok' and {'orders', 'users', 'menu_prices'}.issubset(tablas)
            except sqlite3.Error:
                valido = False
            if not valido:
                flash('El archivo no es un respaldo válido del sistema.', 'error')
                return redirect(url_for('respaldo'))

            db_path = _get_db_path()

            # Respaldo de seguridad de la BD actual antes de sobreescribirla
            backups_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), 'backups')
            os.makedirs(backups_dir, exist_ok=True)
            pre_import_path = os.path.join(
                backups_dir, f'pre_import_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db')
            backup_db_to_file(db_path, pre_import_path)

            # Restaurar DENTRO del archivo existente (no reemplazar/mover el archivo:
            # el servicio Java de inventario mantiene handles abiertos; Windows los bloquea).
            backup_db_to_file(tmp_path, db_path)

            # log_activity antes de limpiar la sesión (lee el usuario de la sesión)
            log_activity('respaldo_importado', 'Base de datos restaurada desde un respaldo')
            session.clear()
            flash('Respaldo importado correctamente. Inicia sesión de nuevo.', 'success')
            return redirect(url_for('login'))
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
