"""Precios del menú — edición por el admin."""
from flask import render_template, request, redirect, url_for, flash

from auth import login_required, admin_required
from db import get_db_connection, log_activity


def register(app):
    @app.route('/admin/prices/update', methods=['POST'])
    @login_required
    @admin_required
    def update_prices():
        conn = get_db_connection()
        for key, value in request.form.items():
            try:
                conn.execute('UPDATE menu_prices SET price = ? WHERE key = ?', (float(value), key))
            except (ValueError, sqlite3.Error):
                pass
        conn.commit()
        log_activity('precios_actualizados', 'Precios del menú actualizados')
        flash('Precios actualizados correctamente.', 'success')
        return redirect(url_for('manage_prices'))


    @app.route('/admin/prices')
    @login_required
    @admin_required
    def manage_prices():
        conn = get_db_connection()
        prices = conn.execute('SELECT * FROM menu_prices ORDER BY label').fetchall()
        return render_template('prices.html', prices=prices)
