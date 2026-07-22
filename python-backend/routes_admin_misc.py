"""Miscellaneous admin routes: changelog, activity log, config update, config API."""
import json
import os

from flask import render_template, request, redirect, url_for, flash, jsonify

from auth import login_required, admin_required
from db import get_db_connection, log_activity
from routes_payment import _api_autorizada

_APP_DIR = os.environ.get('FLASK_APP_DIR') or os.path.dirname(os.path.abspath(__file__))


def register(app, csrf):
    @app.route('/admin/changelog')
    @login_required
    @admin_required
    def changelog():
        releases_path = os.path.join(_APP_DIR, 'releases.json')
        try:
            with open(releases_path, 'r', encoding='utf-8') as f:
                releases = json.load(f)
        except Exception:
            releases = []
        current = releases[0]['version'] if releases else '—'
        return render_template('changelog.html', releases=releases, current=current)

    @app.route('/admin/activity')
    @login_required
    @admin_required
    def activity_log_view():
        conn = get_db_connection()
        logs = conn.execute(
            'SELECT * FROM activity_log ORDER BY timestamp DESC LIMIT 200'
        ).fetchall()
        return render_template('activity_log.html', logs=[dict(l) for l in logs])

    @app.route('/admin/config/update', methods=['POST'])
    @login_required
    @admin_required
    def update_config():
        conn = get_db_connection()
        if 'usd_rate' in request.form:
            raw = request.form.get('usd_rate', '').strip()
            try:
                rate = float(raw)
            except ValueError:
                rate = 0
            if rate <= 0:
                flash('El tipo de cambio debe ser un número mayor a 0.', 'error')
                return redirect(url_for('admin_dashboard'))
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES ('usd_rate', ?)",
                (f'{rate:.2f}',)
            )
            conn.commit()
            log_activity('config', f'Tipo de cambio USD actualizado a ${rate:.2f} MXN')
            flash(f'Tipo de cambio guardado: 1 USD = ${rate:.2f} MXN.', 'success')
            return redirect(url_for('admin_dashboard'))

        printer_name = request.form.get('printer_name', '').strip()
        if not printer_name:
            flash('El nombre de la impresora no puede estar vacío.', 'error')
            return redirect(url_for('admin_dashboard'))
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES ('printer_name', ?)",
            (printer_name,)
        )
        conn.commit()
        flash(f'Impresora configurada como "{printer_name}".', 'success')
        return redirect(url_for('admin_dashboard'))

    @app.route('/api/config')
    @csrf.exempt
    def get_config_api():
        if not _api_autorizada():
            return jsonify({'error': 'No autorizado'}), 401
        conn = get_db_connection()
        rows = conn.execute('SELECT key, value FROM config').fetchall()
        return jsonify({r['key']: r['value'] for r in rows})
