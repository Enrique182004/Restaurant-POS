"""Cart, coupon, held orders, and order-lifecycle routes."""
import json
import uuid
from datetime import datetime

from flask import render_template, request, redirect, url_for, session, flash, jsonify

from auth import login_required
from db import get_db_connection, get_item_price, get_menu_options, get_sushi_prep_prices
from business import money, format_num, apply_bxgy_promotion
from routes_customize import (_beverage_list, _calc_rice_ball_price, _calc_sushi_price,
                              _rice_template_ctx, _sushi_template_ctx)
from routes_payment import print_receipt_physical


# ── Coupon/promo helpers ───────────────────────────────────────────────────────

def _reset_cart_prices(cart):
    for item in cart:
        if 'original_price' in item:
            item['price'] = item['original_price']
        item.pop('original_price', None)
        item.pop('discount', None)


def _parse_applicable_items(promo):
    try:
        return json.loads(promo['applicable_items']) if promo['applicable_items'] else []
    except (json.JSONDecodeError, TypeError):
        return []


def _apply_promo_to_cart(cart, promo):
    _reset_cart_prices(cart)
    total_price = 0
    for item in cart:
        quantity = item.get('quantity', 1)
        if 'unit_price' not in item:
            item['unit_price'] = item['price'] / max(quantity, 1)
        total_price += item['price']

    if (promo['min_purchase'] or 0) > 0 and total_price < promo['min_purchase']:
        return False

    applicable_items = _parse_applicable_items(promo)

    if promo['type'] == 'bxgy':
        buy_qty = int(promo['value']) if promo['value'] else 2
        get_free = int(promo['get_free'] or 1)
        return apply_bxgy_promotion(cart, applicable_items, buy_qty, get_free)

    if promo['type'] == 'percentage':
        for item in cart:
            if not applicable_items or item['type'] in applicable_items:
                item['original_price'] = item['price']
                item['price'] = money(item['original_price'] * (1 - promo['value'] / 100))
                item['discount'] = f"{format_num(promo['value'])}% off"
        return True

    remaining = money(promo['value'] or 0)
    applicable = [i for i in cart if not applicable_items or i['type'] in applicable_items]
    applicable.sort(key=lambda i: i['price'], reverse=True)
    badge = f"${format_num(promo['value'])} off"
    for item in applicable:
        if remaining <= 0:
            break
        reduce_by = min(remaining, item['price'])
        if reduce_by <= 0:
            continue
        item['original_price'] = item['price']
        item['price'] = money(item['original_price'] - reduce_by)
        item['discount'] = badge
        remaining = money(remaining - reduce_by)
    return True


def reapply_active_coupon(cart):
    code = session.get('coupon_code')
    if not code:
        _reset_cart_prices(cart)
        return
    conn = get_db_connection()
    promo = conn.execute(
        'SELECT * FROM promotions WHERE name = ? AND active = 1', (code,)
    ).fetchone()
    if not promo or not _apply_promo_to_cart(cart, promo):
        _reset_cart_prices(cart)
        session.pop('coupon_code', None)


# ── Route registration ─────────────────────────────────────────────────────────

def register(app):
    @app.route('/cart')
    @login_required
    def view_cart():
        cart = session.get('cart', [])
        conn = get_db_connection()
        try:
            promotions = conn.execute('SELECT * FROM promotions WHERE active = 1').fetchall()
        except Exception as e:
            print(f"Error fetching promotions: {e}")
            promotions = []
        total_price = 0
        for item in cart:
            quantity = item.get('quantity', 1)
            if 'unit_price' not in item:
                item['unit_price'] = item['price'] / quantity
            total_price += item['price']
        total_price = money(total_price)
        applied_discount = next((item['discount'] for item in cart if item.get('discount')), '')
        return render_template('cart.html', cart=cart, total_price=total_price,
                               promotions=promotions,
                               order_id=session.get('order_id', ''),
                               applied_discount=applied_discount)

    @app.route('/update_quantity/<int:item_index>/<int:quantity>', methods=['POST'])
    @login_required
    def update_quantity(item_index, quantity):
        if quantity < 1:
            quantity = 1
        cart = session.get('cart', [])
        if item_index < len(cart):
            item = cart[item_index]
            current_quantity = item.get('quantity', 1)
            had_promo = 'original_price' in item
            if 'unit_price' not in item:
                base = item['original_price'] if had_promo else item['price']
                item['unit_price'] = base / max(current_quantity, 1)
            item['quantity'] = quantity
            item['price'] = money(item['unit_price'] * quantity)
            item.pop('original_price', None)
            item.pop('discount', None)
            reapply_active_coupon(cart)
            session['cart'] = cart
            session.modified = True
            new_total = money(sum(i['price'] for i in cart))
            return jsonify({
                'success': True,
                'new_item_price': cart[item_index]['price'],
                'new_total': new_total,
                'promo_cleared': had_promo and 'original_price' not in cart[item_index],
            })
        return jsonify({'success': False, 'error': 'Índice de producto inválido'})

    @app.route('/update_item/<int:item_index>', methods=['GET', 'POST'])
    @login_required
    def update_item(item_index):
        cart = session.get('cart', [])
        if item_index >= len(cart):
            flash('Producto no encontrado', 'error')
            return redirect(url_for('view_cart'))
        item = cart[item_index]

        if request.method == 'POST':
            if item['type'] == 'Bebida':
                item['beverage_type'] = request.form.get('beverage_type')
                item['notes'] = request.form.get('notes', '')
                new_price = get_item_price(item['beverage_type'])
                item['unit_price'] = new_price
                item['price'] = new_price * item.get('quantity', 1)

            elif item['type'] == 'Boneless':
                item['sauces'] = request.form.getlist('sauce')
                item['accompaniment'] = request.form.get('accompaniment')
                item['notes'] = request.form.get('notes', '')
                base_price = get_item_price('Boneless')
                item['unit_price'] = base_price
                item['price'] = base_price * item.get('quantity', 1)

            elif item['type'] == 'Complementos':
                sauces = request.form.getlist('sauces')
                item['sauces'] = sauces
                item['notes'] = request.form.get('notes', '')
                sauce_count = len(sauces)
                sauce_unit = get_item_price('Complementos')
                total_price = sauce_count * sauce_unit
                item['unit_price'] = total_price
                item['price'] = total_price * item.get('quantity', 1)
                item['sauce_count'] = sauce_count

            elif item['type'] == 'Bola de Arroz':
                ingredients = request.form.getlist('ingredients')
                regular_ingredients = [i for i in ingredients if i != 'Ostión']
                ostion_ingredients  = [i for i in ingredients if i == 'Ostión']

                if len(regular_ingredients) > 6:
                    flash('Máximo 6 ingredientes regulares permitidos', 'error')
                    return render_template('rice_ball.html', **_rice_template_ctx(item, item_index))
                if len(regular_ingredients) < 1:
                    flash('Selecciona al menos 1 ingrediente', 'error')
                    return render_template('rice_ball.html', **_rice_template_ctx(item, item_index))
                if len(ostion_ingredients) > 1:
                    flash('Solo puedes agregar un Ostión', 'error')
                    return render_template('rice_ball.html', **_rice_template_ctx(item, item_index))

                item['base'] = request.form.getlist('base')
                item['ingredients'] = ingredients
                item['style'] = request.form.get('style')
                item['sauce'] = request.form.get('sauce')
                item['toppings'] = request.form.getlist('toppings')
                item['notes'] = request.form.get('notes', '')
                base_price, ostion_price, total_price = _calc_rice_ball_price(ingredients)
                item['unit_price'] = total_price
                item['price'] = total_price * item.get('quantity', 1)
                item['ostion_cost'] = ostion_price

            elif item['type'] == 'Sushi':
                ingredients = request.form.getlist('ingredients')
                prepared = request.form.get('prepared')
                regular_ingredients = [i for i in ingredients if i != 'Ostión']
                ostion_ingredients  = [i for i in ingredients if i == 'Ostión']

                if len(regular_ingredients) > 3:
                    flash('Máximo 3 ingredientes regulares permitidos', 'error')
                    return render_template('sushi.html', **_sushi_template_ctx(item, item_index))
                if len(regular_ingredients) < 1:
                    flash('Selecciona al menos 1 ingrediente', 'error')
                    return render_template('sushi.html', **_sushi_template_ctx(item, item_index))
                if len(ostion_ingredients) > 1:
                    flash('Solo puedes agregar un Ostión', 'error')
                    return render_template('sushi.html', **_sushi_template_ctx(item, item_index))

                item['base'] = request.form.getlist('base')
                item['ingredients'] = ingredients
                item['style'] = request.form.get('style')
                item['prepared'] = prepared
                sauce = request.form.get('sauce') or prepared
                item['sauce'] = sauce
                item['toppings'] = request.form.getlist('toppings')
                item['notes'] = request.form.get('notes', '')
                base_price, ostion_price, total_price = _calc_sushi_price(ingredients, prepared)
                item['unit_price'] = total_price
                item['price'] = total_price * item.get('quantity', 1)
                item['ostion_cost'] = ostion_price

            item.pop('original_price', None)
            item.pop('discount', None)
            cart[item_index] = item
            reapply_active_coupon(cart)
            session['cart'] = cart
            session.modified = True
            flash('Item actualizado con éxito', 'success')
            return redirect(url_for('view_cart'))

        # GET — show edit form
        if item['type'] == 'Bebida':
            return render_template('beverages.html', item=item, item_index=item_index,
                                   beverages=_beverage_list())
        elif item['type'] == 'Boneless':
            return render_template('boneless.html', item=item, item_index=item_index,
                                   boneless_sauces=get_menu_options('boneless_sauce'))
        elif item['type'] == 'Complementos':
            return render_template('complementos.html', item=item, item_index=item_index,
                                   extra_sauces=get_menu_options('extra_sauce'),
                                   sauce_price=get_item_price('Complementos'))
        elif item['type'] == 'Bola de Arroz':
            return render_template('rice_ball.html', item=item, item_index=item_index,
                                   rice_ingredients=get_menu_options('rice_ingredient'),
                                   rice_sauces=get_menu_options('rice_sauce'),
                                   base_price=get_item_price('Bola de Arroz'),
                                   ostion_price=get_item_price('Ostión'))
        elif item['type'] == 'Sushi':
            return render_template('sushi.html', item=item, item_index=item_index,
                                   sushi_ingredients=get_menu_options('sushi_ingredient'),
                                   sushi_sauces=get_menu_options('sushi_sauce'),
                                   sushi_prep_prices=get_sushi_prep_prices(),
                                   ostion_price=get_item_price('Ostión'))

    @app.route('/remove_item/<int:item_index>', methods=['POST'])
    @login_required
    def remove_item(item_index):
        cart = session.get('cart', [])
        if item_index < len(cart):
            cart.pop(item_index)
            reapply_active_coupon(cart)
            session['cart'] = cart
            session.modified = True
            flash('Producto eliminado de la orden', 'success')
        return redirect(url_for('view_cart'))

    @app.route('/apply_coupon', methods=['POST'])
    @login_required
    def apply_coupon():
        coupon_code = request.form.get('coupon_code', '').strip().upper()
        if not coupon_code:
            flash('Por favor ingresa un código de promoción', 'error')
            return redirect(url_for('view_cart'))

        cart = session.get('cart', [])
        if any('discount' in item for item in cart):
            flash('Ya hay una promoción aplicada a esta orden. Para usar otro código, '
                  'elimina los artículos y agrégalos de nuevo.', 'error')
            return redirect(url_for('view_cart'))

        conn = get_db_connection()
        promo = conn.execute(
            'SELECT * FROM promotions WHERE name = ? AND active = 1', (coupon_code,)
        ).fetchone()
        if not promo:
            flash('Código de promoción inválido o expirado', 'error')
            return redirect(url_for('view_cart'))

        total_price = 0
        for item in cart:
            quantity = item.get('quantity', 1)
            if 'unit_price' not in item:
                item['unit_price'] = item['price'] / max(quantity, 1)
            total_price += item['price']

        if (promo['min_purchase'] or 0) > 0 and total_price < promo['min_purchase']:
            flash(f'Se requiere una compra mínima de ${promo["min_purchase"]} '
                  f'para aplicar esta promoción', 'error')
            return redirect(url_for('view_cart'))

        applied = _apply_promo_to_cart(cart, promo)
        if not applied:
            if promo['type'] == 'bxgy':
                buy_qty = int(promo['value']) if promo['value'] else 2
                get_free = int(promo['get_free'] or 1)
                applicable_items = _parse_applicable_items(promo)
                items_label = ', '.join(applicable_items) if applicable_items else 'productos'
                flash(f'Necesitas al menos {buy_qty + get_free} {items_label} '
                      f'para aplicar esta promoción', 'error')
            else:
                flash('No se pudo aplicar la promoción a esta orden', 'error')
            return redirect(url_for('view_cart'))

        session['coupon_code'] = promo['name']
        session['cart'] = cart
        session.modified = True
        flash(f'Promoción "{promo["description"] or promo["name"]}" aplicada con éxito', 'success')
        return redirect(url_for('view_cart'))

    @app.route('/remove_coupon', methods=['POST'])
    @login_required
    def remove_coupon():
        cart = session.get('cart', [])
        _reset_cart_prices(cart)
        session['cart'] = cart
        session.pop('coupon_code', None)
        session.modified = True
        flash('Promoción eliminada de la orden', 'success')
        return redirect(url_for('view_cart'))

    @app.route('/new_order', methods=['POST'])
    @login_required
    def new_order():
        session.pop('cart', None)
        session.pop('customer_name', None)
        session.pop('held_id', None)
        session['order_id'] = str(uuid.uuid4())[:8]
        session['cart'] = []
        session.modified = True
        return redirect(url_for('home'))

    @app.route('/hold_order', methods=['POST'])
    @login_required
    def hold_order():
        cart = session.get('cart', [])
        if not cart:
            flash('No hay items en la orden para retener.', 'error')
            return redirect(url_for('view_cart'))

        customer_name = session.get('customer_name', '') or 'Cliente'
        total = sum(item.get('price', 0) for item in cart)
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn = get_db_connection()
        prev_held = session.pop('held_id', None)
        if prev_held:
            conn.execute('DELETE FROM held_orders WHERE id = ?', (prev_held,))
        cursor = conn.execute(
            'INSERT INTO held_orders (order_ref, customer_name, cart_json, total, created_at) '
            'VALUES (?, ?, ?, ?, ?)',
            ('', customer_name, json.dumps(cart), total, created_at)
        )
        held_id = cursor.lastrowid
        order_ref = f'HOLD-{held_id:03d}'
        conn.execute('UPDATE held_orders SET order_ref = ? WHERE id = ?', (order_ref, held_id))
        conn.commit()

        try:
            _, receipt_text = print_receipt_physical(
                cart=cart, total=total, payment_method='PEDIDO EN ESPERA',
                order_id=order_ref, customer_name=customer_name)
            conn.execute(
                "INSERT OR IGNORE INTO print_jobs (id, receipt_content, status, created_at) "
                "VALUES (?, ?, 'pending', ?)",
                (order_ref, receipt_text, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
            conn.commit()
        except Exception as e:
            print(f"Error imprimiendo ticket retenido: {e}")

        session['cart'] = []
        session['customer_name'] = ''
        session['order_id'] = str(uuid.uuid4())[:8]
        session.modified = True
        flash(f'Orden retenida como {order_ref}. Ticket enviado a imprimir.', 'success')
        return redirect(url_for('home'))

    @app.route('/api/held_orders')
    @login_required
    def api_held_orders():
        conn = get_db_connection()
        rows = conn.execute('SELECT * FROM held_orders ORDER BY created_at DESC').fetchall()
        return jsonify({'held_orders': [dict(r) for r in rows]})

    @app.route('/resume_order/<int:held_id>', methods=['POST'])
    @login_required
    def resume_order(held_id):
        conn = get_db_connection()
        order = conn.execute('SELECT * FROM held_orders WHERE id = ?', (held_id,)).fetchone()
        if not order:
            flash('Orden no encontrada.', 'error')
            return redirect(url_for('home'))
        try:
            cart = json.loads(order['cart_json'])
        except (json.JSONDecodeError, TypeError):
            flash('La orden guardada está corrupta y no se puede cargar.', 'error')
            return redirect(url_for('home'))
        session['cart'] = cart
        session['customer_name'] = order['customer_name']
        session['order_id'] = str(uuid.uuid4())[:8]
        session['held_id'] = held_id
        session.modified = True
        flash(f'Orden {order["order_ref"]} cargada. Modifica si es necesario y procede al pago.',
              'success')
        return redirect(url_for('view_cart'))

    @app.route('/cancel_held_order/<int:held_id>', methods=['POST'])
    @login_required
    def cancel_held_order(held_id):
        conn = get_db_connection()
        order = conn.execute('SELECT order_ref FROM held_orders WHERE id = ?', (held_id,)).fetchone()
        if not order:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        conn.execute('DELETE FROM held_orders WHERE id = ?', (held_id,))
        conn.commit()
        return jsonify({'ok': True, 'ref': order['order_ref']})

    @app.route('/api/recent_customers')
    @login_required
    def recent_customers():
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT DISTINCT customer_name FROM orders "
            "WHERE customer_name IS NOT NULL AND customer_name != '' "
            "AND customer_name != 'Cliente' ORDER BY date DESC LIMIT 30"
        ).fetchall()
        names = list(dict.fromkeys(r['customer_name'] for r in rows))[:20]
        return jsonify(names)
