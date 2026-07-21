"""Opciones del menú — ingredientes y salsas administrables (admin)."""
from flask import render_template, request, redirect, url_for, flash, jsonify

from auth import login_required, admin_required
from db import get_db_connection, log_activity, get_menu_options


def register(app):
    @app.route('/admin/menu-options/add', methods=['POST'])
    @login_required
    @admin_required
    def add_menu_option():
        category = request.form.get('category', '').strip()
        name = request.form.get('name', '').strip()
        icon = request.form.get('icon', '🍽️').strip() or '🍽️'
        try:
            price = float(request.form.get('price', 0) or 0)
        except ValueError:
            price = 0.0

        if not name or not category:
            flash('Nombre y categoría son requeridos', 'error')
            return redirect(url_for('manage_menu_options'))

        conn = get_db_connection()
        existing = conn.execute(
            'SELECT id FROM menu_options WHERE category=? AND name=?', (category, name)
        ).fetchone()
        if existing:
            # Reactiva y aplica el precio/icono enviados (antes se ignoraban al re-agregar).
            conn.execute('UPDATE menu_options SET active=1, price=?, icon=? WHERE id=?',
                         (price, icon, existing['id']))
            if category == 'beverage':
                conn.execute(
                    'INSERT OR REPLACE INTO menu_prices (key, label, price) VALUES (?, ?, ?)',
                    (name, name, price)
                )
        else:
            max_sort = conn.execute(
                'SELECT COALESCE(MAX(sort_order),0) FROM menu_options WHERE category=?', (category,)
            ).fetchone()[0]
            conn.execute(
                'INSERT INTO menu_options (category, name, icon, price, sort_order) VALUES (?, ?, ?, ?, ?)',
                (category, name, icon, price, max_sort + 1)
            )
            # Sync new beverages to menu_prices so get_item_price works immediately
            if category == 'beverage':
                conn.execute(
                    'INSERT OR IGNORE INTO menu_prices (key, label, price) VALUES (?, ?, ?)',
                    (name, name, price)
                )
        conn.commit()
        flash(f'"{name}" agregado al menú', 'success')
        return redirect(url_for('manage_menu_options'))


    @app.route('/admin/menu-options/update/<int:option_id>', methods=['POST'])
    @login_required
    @admin_required
    def update_menu_option(option_id):
        conn = get_db_connection()
        option = conn.execute('SELECT * FROM menu_options WHERE id=?', (option_id,)).fetchone()
        if not option:
            flash('Opción no encontrada', 'error')
            return redirect(url_for('manage_menu_options'))

        name = request.form.get('name', '').strip()
        icon = request.form.get('icon', '').strip() or option['icon']
        try:
            price = float(request.form.get('price', option['price']) or 0)
        except ValueError:
            price = option['price']

        if not name:
            flash('El nombre no puede quedar vacío', 'error')
            return redirect(url_for('manage_menu_options'))

        duplicate = conn.execute(
            'SELECT id FROM menu_options WHERE category=? AND name=? AND id!=?',
            (option['category'], name, option_id)
        ).fetchone()
        if duplicate:
            flash(f'Ya existe "{name}" en esta categoría', 'error')
            return redirect(url_for('manage_menu_options'))

        # Bebidas cobran por nombre vía menu_prices (key es PRIMARY KEY). Renombrar a
        # un nombre que ya tiene fila en menu_prices reventaba con IntegrityError (500):
        # detecta la colisión ANTES de escribir y aborta con un mensaje claro.
        if option['category'] == 'beverage' and name != option['name']:
            clash = conn.execute('SELECT 1 FROM menu_prices WHERE key=?', (name,)).fetchone()
            if clash:
                flash(f'Ya existe un precio registrado para "{name}". Elige otro nombre.', 'error')
                return redirect(url_for('manage_menu_options'))

        conn.execute('UPDATE menu_options SET name=?, icon=?, price=? WHERE id=?',
                     (name, icon, price, option_id))
        # Las bebidas cobran por nombre vía menu_prices: mantenerlo en sincronía
        if option['category'] == 'beverage':
            conn.execute('UPDATE menu_prices SET key=?, label=?, price=? WHERE key=?',
                         (name, name, price, option['name']))
        conn.commit()
        log_activity('menu_opcion_editada',
                     f'"{option["name"]}" → "{name}" (${price:g}) en {option["category"]}')
        flash(f'"{name}" actualizado', 'success')
        return redirect(url_for('manage_menu_options'))


    @app.route('/admin/menu-options/reorder', methods=['POST'])
    @login_required
    @admin_required
    def reorder_menu_options():
        """Persiste el orden de las opciones tras un drag & drop en el admin."""
        data = request.get_json(silent=True) or {}
        ids = data.get('ids', [])
        if not ids or not all(isinstance(i, int) for i in ids):
            return jsonify({'ok': False, 'error': 'ids inválidos'}), 400
        conn = get_db_connection()
        for pos, option_id in enumerate(ids):
            conn.execute('UPDATE menu_options SET sort_order=? WHERE id=?', (pos, option_id))
        conn.commit()
        return jsonify({'ok': True})


    @app.route('/admin/menu-options/delete/<int:option_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_menu_option(option_id):
        conn = get_db_connection()
        option = conn.execute('SELECT * FROM menu_options WHERE id=?', (option_id,)).fetchone()
        if option:
            conn.execute('DELETE FROM menu_options WHERE id=?', (option_id,))
            # Bebidas: borra también su fila en menu_prices para no dejar un precio
            # huérfano (seguiría siendo cobrable y provocaba colisiones al renombrar).
            if option['category'] == 'beverage':
                conn.execute('DELETE FROM menu_prices WHERE key=?', (option['name'],))
            conn.commit()
            flash(f'"{option["name"]}" eliminado del menú', 'success')
        return redirect(url_for('manage_menu_options'))


    @app.route('/admin/menu-options/toggle/<int:option_id>', methods=['POST'])
    @login_required
    @admin_required
    def toggle_menu_option(option_id):
        conn = get_db_connection()
        option = conn.execute('SELECT * FROM menu_options WHERE id=?', (option_id,)).fetchone()
        if option:
            new_active = 0 if option['active'] else 1
            conn.execute('UPDATE menu_options SET active=? WHERE id=?', (new_active, option_id))
            conn.commit()
            status = 'activado' if new_active else 'desactivado'
            flash(f'"{option["name"]}" {status}', 'success')
        return redirect(url_for('manage_menu_options'))


    @app.route('/admin/menu-options')
    @login_required
    @admin_required
    def manage_menu_options():
        conn = get_db_connection()
        categories = ['beverage', 'boneless_sauce', 'extra_sauce', 'rice_ingredient', 'rice_sauce', 'sushi_ingredient', 'sushi_sauce']
        menu_opts = {}
        for cat in categories:
            rows = conn.execute(
                'SELECT * FROM menu_options WHERE category=? ORDER BY active DESC, sort_order, name',
                (cat,)
            ).fetchall()
            opts = [dict(r) for r in rows]
            if cat == 'beverage':
                for opt in opts:
                    mp = conn.execute('SELECT price FROM menu_prices WHERE key=?', (opt['name'],)).fetchone()
                    if mp:
                        opt['price'] = mp['price']
            menu_opts[cat] = opts
        return render_template('menu_options.html', menu_opts=menu_opts)
