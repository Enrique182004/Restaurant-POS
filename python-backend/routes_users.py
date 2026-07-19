"""Cuentas: recuperación/cambio de contraseña y gestión de usuarios (admin)."""
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
from werkzeug.security import generate_password_hash, check_password_hash


def register(app):
    # ── Forgot Password ───────────────────────────────────────────────────────────
    # SEGURIDAD (audit v2.1.1): antes esta ruta reseteaba la contraseña de
    # CUALQUIER usuario (admin incluido) sin verificar identidad. Como el
    # servidor escucha en 0.0.0.0, cualquiera en la Wi-Fi del local podía
    # tomar la cuenta admin. Ahora exige sesión admin: el restablecimiento de
    # cuentas ajenas es una tarea de administración (igual que reset_user_password).
    # Un usuario que olvidó su contraseña debe pedirle a un admin que la
    # restablezca; no hay auto-servicio sin verificación de identidad.
    @app.route('/forgot_password', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def forgot_password():
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            new_pw   = request.form.get('new_password', '')
            confirm  = request.form.get('confirm_password', '')

            if not username or not new_pw or not confirm:
                flash('Todos los campos son requeridos.', 'error')
                return render_template('forgot_password.html')

            if new_pw != confirm:
                flash('Las contraseñas no coinciden.', 'error')
                return render_template('forgot_password.html')

            if len(new_pw) < 6:
                flash('La contraseña debe tener al menos 6 caracteres.', 'error')
                return render_template('forgot_password.html')

            conn = get_db_connection()
            user = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
            if not user:
                flash('Usuario no encontrado.', 'error')
                return render_template('forgot_password.html')

            conn.execute('UPDATE users SET password = ? WHERE id = ?',
                         (generate_password_hash(new_pw), user['id']))
            conn.execute('UPDATE users SET password_changed = 1 WHERE id = ?', (user['id'],))
            conn.commit()
            flash('Contraseña actualizada. Ya puedes iniciar sesión.', 'success')
            return redirect(url_for('login'))

        return render_template('forgot_password.html')


    # ── Change Password ───────────────────────────────────────────────────────────
    @app.route('/change_password', methods=['GET', 'POST'])
    @login_required
    def change_password():
        if request.method == 'POST':
            current = request.form.get('current_password', '')
            new_pw  = request.form.get('new_password', '')
            confirm = request.form.get('confirm_password', '')

            if not current or not new_pw or not confirm:
                flash('Todos los campos son requeridos.', 'error')
                return render_template('change_password.html')

            if new_pw != confirm:
                flash('Las contraseñas nuevas no coinciden.', 'error')
                return render_template('change_password.html')

            if len(new_pw) < 6:
                flash('La contraseña debe tener al menos 6 caracteres.', 'error')
                return render_template('change_password.html')

            conn = get_db_connection()
            user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
            if not user or not check_password_hash(user['password'], current):
                flash('Contraseña actual incorrecta.', 'error')
                return render_template('change_password.html')

            conn.execute('UPDATE users SET password = ? WHERE id = ?',
                         (generate_password_hash(new_pw), session['user_id']))
            conn.execute('UPDATE users SET password_changed = 1 WHERE id = ?', (session['user_id'],))
            conn.commit()
            flash('Contraseña actualizada exitosamente.', 'success')
            return redirect(url_for('admin_dashboard') if session.get('role') == 'admin' else url_for('home'))

        return render_template('change_password.html')


    # ── User Management (admin only) ──────────────────────────────────────────────
    @app.route('/admin/users')
    @login_required
    @admin_required
    def manage_users():
        conn = get_db_connection()
        users = conn.execute('SELECT id, username, role, created_at FROM users ORDER BY role, username').fetchall()
        return render_template('users.html', users=[dict(u) for u in users])


    @app.route('/admin/users/add', methods=['POST'])
    @login_required
    @admin_required
    def add_user():
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role     = request.form.get('role', 'user')

        if not username or not password:
            flash('Usuario y contraseña son requeridos.', 'error')
            return redirect(url_for('manage_users'))
        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'error')
            return redirect(url_for('manage_users'))
        if role not in ('admin', 'user'):
            role = 'user'

        conn = get_db_connection()
        existing = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if existing:
            flash(f'El usuario "{username}" ya existe.', 'error')
            return redirect(url_for('manage_users'))

        conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                     (username, generate_password_hash(password), role))
        conn.commit()
        log_activity('usuario_creado', f'Usuario "{username}" ({role}) creado')
        flash(f'Usuario "{username}" creado exitosamente.', 'success')
        return redirect(url_for('manage_users'))


    @app.route('/admin/users/reset/<int:user_id>', methods=['POST'])
    @login_required
    @admin_required
    def reset_user_password(user_id):
        new_pw = request.form.get('new_password', '').strip()
        if len(new_pw) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'error')
            return redirect(url_for('manage_users'))

        conn = get_db_connection()
        user = conn.execute('SELECT username FROM users WHERE id = ?', (user_id,)).fetchone()
        if not user:
            flash('Usuario no encontrado.', 'error')
            return redirect(url_for('manage_users'))

        conn.execute('UPDATE users SET password = ? WHERE id = ?',
                     (generate_password_hash(new_pw), user_id))
        conn.execute('UPDATE users SET password_changed = 1 WHERE id = ?', (user_id,))
        conn.commit()
        log_activity('contraseña_restablecida', f'Contraseña de "{user["username"]}" restablecida')
        flash(f'Contraseña de "{user["username"]}" restablecida.', 'success')
        return redirect(url_for('manage_users'))


    @app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_user(user_id):
        if user_id == session.get('user_id'):
            flash('No puedes eliminar tu propia cuenta.', 'error')
            return redirect(url_for('manage_users'))

        conn = get_db_connection()
        user = conn.execute('SELECT username FROM users WHERE id = ?', (user_id,)).fetchone()
        if user:
            conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
            conn.commit()
            log_activity('usuario_eliminado', f'Usuario "{user["username"]}" eliminado')
            flash(f'Usuario "{user["username"]}" eliminado.', 'success')
        return redirect(url_for('manage_users'))
