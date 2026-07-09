"""Gestión de promociones (admin)."""
import csv
import io
import json
import os
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
    # ── Promotions toggle ─────────────────────────────────────────────────────────
    @app.route('/admin/promotions/add', methods=['POST'])
    @login_required
    @admin_required
    def add_promotion():
        name = request.form.get('name', '').strip().upper().replace(' ', '')
        description = request.form.get('description', '').strip()
        promo_type = request.form.get('type', 'percentage')
        value = request.form.get('value', '0')
        min_purchase = request.form.get('min_purchase', '0') or '0'
        applicable_items = request.form.getlist('applicable_items')

        if not name:
            flash('El código de promoción no puede estar vacío.', 'error')
            return redirect(url_for('manage_promotions'))
        if promo_type not in ('percentage', 'fixed', 'bxgy'):
            flash('Tipo de promoción inválido.', 'error')
            return redirect(url_for('manage_promotions'))

        get_free = 1
        try:
            min_purchase = float(min_purchase or '0')
            if promo_type == 'bxgy':
                buy_qty_str = request.form.get('buy_qty', '').strip()
                get_free_str = request.form.get('get_free', '1').strip() or '1'
                value = int(float(buy_qty_str)) if buy_qty_str else 0
                get_free = int(float(get_free_str))
                if value < 1 or get_free < 1:
                    raise ValueError('buy/free must be >= 1')
            else:
                value = float(value) if value.strip() else 0.0
        except (ValueError, AttributeError):
            flash('Valor inválido.', 'error')
            return redirect(url_for('manage_promotions'))

        if promo_type == 'percentage' and not (0 < value <= 100):
            flash('El porcentaje debe estar entre 1 y 100.', 'error')
            return redirect(url_for('manage_promotions'))
        if promo_type != 'bxgy' and value <= 0:
            flash('El valor debe ser mayor a 0.', 'error')
            return redirect(url_for('manage_promotions'))

        applicable_json = json.dumps(applicable_items) if applicable_items else '[]'

        conn = get_db_connection()
        existing = conn.execute('SELECT id FROM promotions WHERE name = ?', (name,)).fetchone()
        if existing:
            flash(f'Ya existe una promoción con el código "{name}".', 'error')
            return redirect(url_for('manage_promotions'))
        conn.execute(
            'INSERT INTO promotions (name, description, type, value, get_free, min_purchase, applicable_items, active) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, 1)',
            (name, description, promo_type, value, get_free, min_purchase, applicable_json)
        )
        conn.commit()
        flash(f'Promoción "{name}" creada.', 'success')
        return redirect(url_for('manage_promotions'))


    @app.route('/admin/promotions/delete/<int:promo_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_promotion(promo_id):
        conn = get_db_connection()
        promo = conn.execute('SELECT name FROM promotions WHERE id = ?', (promo_id,)).fetchone()
        if promo:
            conn.execute('DELETE FROM promotions WHERE id = ?', (promo_id,))
            conn.commit()
            flash(f'Promoción "{promo["name"]}" eliminada.', 'success')
        return redirect(url_for('manage_promotions'))


    @app.route('/admin/promotions/toggle/<int:promo_id>', methods=['POST'])
    @login_required
    @admin_required
    def toggle_promotion(promo_id):
        conn = get_db_connection()
        promo = conn.execute('SELECT active, name FROM promotions WHERE id = ?', (promo_id,)).fetchone()
        if promo:
            new_state = 0 if promo['active'] else 1
            conn.execute('UPDATE promotions SET active = ? WHERE id = ?', (new_state, promo_id))
            conn.commit()
            state_label = 'activada' if new_state else 'desactivada'
            flash(f'Promoción "{promo["name"]}" {state_label}.', 'success')
        return redirect(url_for('manage_promotions'))


    @app.route('/admin/promotions')
    @login_required
    @admin_required
    def manage_promotions():
        conn = get_db_connection()
        promotions = [dict(p) for p in conn.execute('SELECT * FROM promotions ORDER BY name').fetchall()]
        return render_template('promotions.html', promotions=promotions)
