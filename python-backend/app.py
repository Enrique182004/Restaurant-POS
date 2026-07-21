from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response, g, send_file
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import os
import uuid
from datetime import datetime, timedelta
import sqlite3
import json
import csv
import io
import tempfile
from functools import wraps
from db import (get_db_connection, _cerrar_db, get_item_price,
                get_sushi_prep_prices, get_menu_options, log_activity,
                _get_db_path, backup_db_to_file)
from business import (format_num, get_week_bounds, resolve_employee_schedule,
                      compute_employee_pay, parse_scheduled_days, apply_bxgy_promotion,
                      money)

# Soporte para modo PyInstaller (bundled) y desarrollo normal.
# FLASK_APP_DIR indica dónde están templates/ y static/ en producción.
_APP_DIR = os.environ.get('FLASK_APP_DIR') or os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(_APP_DIR, 'templates'),
    static_folder=os.path.join(_APP_DIR, 'static'),
)
csrf = CSRFProtect()

# Ruta de la base de datos: viene del env (Electron) o usa el directorio actual (desarrollo)
_DB_PATH = os.environ.get('RESTAURANT_DB_PATH') or 'restaurant.db'

# ── Restaurant configuration ──────────────────────────────────────────────────
RESTAURANT_NAME = os.environ.get('RESTAURANT_NAME', 'Ebi Ball')
JAVA_INVENTORY_SERVICE = os.environ.get('JAVA_SERVICE_URL', 'http://localhost:8081')
# ─────────────────────────────────────────────────────────────────────────────

# Store secret key persistently so sessions survive app restarts
_secret_key_file = os.path.join(os.path.dirname(__file__), '.secret_key')
if os.environ.get('SECRET_KEY'):
    SECRET_KEY = os.environ.get('SECRET_KEY').encode()
elif os.path.exists(_secret_key_file):
    with open(_secret_key_file, 'rb') as _f:
        SECRET_KEY = _f.read()
else:
    SECRET_KEY = os.urandom(24)
    with open(_secret_key_file, 'wb') as _f:
        _f.write(SECRET_KEY)
app.secret_key = SECRET_KEY
csrf.init_app(app)
    
# Set session lifetime
app.permanent_session_lifetime = timedelta(hours=24)

app.jinja_env.filters['num'] = format_num

# ── Base de datos ──────────────────────────────────────────────────────────────

app.teardown_appcontext(_cerrar_db)

from schema import init_db
# Decoradores de sesión/rol compartidos con los módulos de rutas
from auth import login_required, admin_required

# Initialize session
@app.before_request
def initialize_session():
    # Make session permanent to use the lifetime setting
    session.permanent = True
    
    if 'cart' not in session:
        session['cart'] = []
    if 'order_id' not in session:
        session['order_id'] = str(uuid.uuid4())[:8]

# Login page
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('Por favor ingresa usuario y contraseña', 'error')
            return render_template('login.html')
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash(f'¡Bienvenido {username}!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Usuario o contraseña incorrectos', 'error')
    
    return render_template('login.html')

# Logout
@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('Sesión cerrada exitosamente', 'success')
    return redirect(url_for('login'))

# Save customer name
@app.route('/save_customer_name', methods=['POST'])
@login_required
def save_customer_name():
    try:
        data = request.get_json()
        customer_name = data.get('customer_name', '').strip()
        
        if not customer_name:
            return jsonify({'success': False, 'message': 'Nombre del cliente requerido'})
        
        if len(customer_name) > 50:
            return jsonify({'success': False, 'message': 'El nombre es demasiado largo (máximo 50 caracteres)'})
        
        # Save to session
        session['customer_name'] = customer_name
        session.modified = True
        
        return jsonify({'success': True, 'message': 'Nombre guardado exitosamente'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error al guardar: {str(e)}'})

def _beverage_list():
    """Build beverage list with prices from menu_prices (for display)."""
    options = get_menu_options('beverage')
    conn = get_db_connection()
    result = []
    for o in options:
        price_row = conn.execute('SELECT price FROM menu_prices WHERE key=?', (o['name'],)).fetchone()
        price = price_row['price'] if price_row else o['price']
        result.append({'id': o['name'].lower().replace(' ', '_'), 'name': o['name'], 'icon': o['icon'], 'price': price})
    return result

@app.route('/')
@login_required
def home():
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))
    return render_template('index.html')


@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    today = datetime.now().strftime('%Y-%m-%d')
    today_total = conn.execute(
        "SELECT COALESCE(SUM(total), 0) FROM orders WHERE date LIKE ? AND status != 'voided'",
        (today + '%',)
    ).fetchone()[0]
    today_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE date LIKE ? AND status != 'voided'",
        (today + '%',)
    ).fetchone()[0]

    # Low-stock count from Java service (best-effort)
    low_stock_count = 0
    try:
        inv_resp = requests.get(f'{JAVA_INVENTORY_SERVICE}/api/inventory/low-stock', timeout=2)
        if inv_resp.status_code == 200:
            low_stock_count = len(inv_resp.json())
    except Exception:
        pass

    pending_prints = conn.execute(
        "SELECT COUNT(*) FROM print_jobs WHERE status = 'pending'"
    ).fetchone()[0]

    printer_name = conn.execute(
        "SELECT value FROM config WHERE key = 'printer_name'"
    ).fetchone()
    printer_name = printer_name['value'] if printer_name else 'Printer_POS_80'

    users_with_default = conn.execute(
        "SELECT COUNT(*) FROM users WHERE password_changed = 0"
    ).fetchone()[0]

    try:
        releases_path = os.path.join(os.path.dirname(__file__), 'releases.json')
        with open(releases_path, 'r', encoding='utf-8') as f:
            releases_data = json.load(f)
        app_version = releases_data[0]['version'] if releases_data else '—'
    except Exception:
        app_version = '—'

    return render_template('admin_dashboard.html',
                           today_total=today_total,
                           today_orders=today_orders,
                           low_stock_count=low_stock_count,
                           pending_prints=pending_prints,
                           printer_name=printer_name,
                           usd_rate=_usd_rate(),
                           users_with_default=users_with_default,
                           app_version=app_version)

@app.route('/admin/api/dashboard-summary')
@login_required
@admin_required
def dashboard_summary_api():
    conn = get_db_connection()
    today = datetime.now().strftime('%Y-%m-%d')
    today_total = conn.execute(
        "SELECT COALESCE(SUM(total), 0) FROM orders WHERE date LIKE ? AND status != 'voided'",
        (today + '%',)
    ).fetchone()[0]
    today_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE date LIKE ? AND status != 'voided'",
        (today + '%',)
    ).fetchone()[0]
    return jsonify({'today_total': float(today_total), 'today_orders': int(today_orders)})

@app.route('/admin/api/low-stock-check')
@login_required
@admin_required
def low_stock_check_api():
    try:
        resp = requests.get(f'{JAVA_INVENTORY_SERVICE}/api/inventory/low-stock', timeout=2)
        if resp.status_code == 200:
            items = resp.json()
            return jsonify({'count': len(items), 'items': [i.get('name', '') for i in items[:5]]})
    except Exception:
        pass
    return jsonify({'count': 0, 'items': []})







def _calc_rice_ball_price(ingredients):
    """Return (base, ostion, total) for a rice ball ingredient list."""
    ostion_count = sum(1 for i in ingredients if i == 'Ostión')
    base  = get_item_price('Bola de Arroz')
    extra = ostion_count * get_item_price('Ostión')
    return base, extra, base + extra


def _calc_sushi_price(ingredients, prepared):
    """Return (base, ostion, total) for a sushi order."""
    ostion_count = sum(1 for i in ingredients if i == 'Ostión')
    base  = get_item_price('Sushi', prepared)
    extra = ostion_count * get_item_price('Ostión')
    return base, extra, base + extra


# Customize Beverages - UPDATED TO REDIRECT TO HOME
@app.route('/customize/beverages', methods=['GET', 'POST'])
@login_required
def customize_beverages():
    if request.method == 'POST':
        # Get form data
        beverage_type = request.form.get('beverage_type')
        notes = request.form.get('notes', '')
        
        # Validate required fields
        if not beverage_type:
            flash('Por favor selecciona una bebida.', 'error')
            return render_template('beverages.html', item=None, beverages=_beverage_list())

        # Get price using new pricing system
        price = get_item_price(beverage_type)

        # Create item dictionary
        item = {
            'name': 'Bebida',
            'type': 'Bebida',
            'beverage_type': beverage_type,
            'price': price,
            'unit_price': price,
            'quantity': 1,
            'notes': notes
        }

        session['cart'].append(item)
        session.modified = True
        flash('¡Bebida agregada a la orden!', 'success')
        return redirect(url_for('home'))

    return render_template('beverages.html', item=None, beverages=_beverage_list())

# Customize Boneless with multiple sauces - UPDATED TO REDIRECT TO HOME
@app.route('/customize/boneless', methods=['GET', 'POST'])
@login_required
def customize_boneless():
    if request.method == 'POST':
        # Get form data - now supporting multiple sauces
        sauces = request.form.getlist('sauce')  # Changed to getlist for multiple selection
        accompaniment = request.form.get('accompaniment')
        notes = request.form.get('notes', '')
        
        # Validate required fields
        if not sauces:
            flash('Por favor selecciona al menos una salsa.', 'error')
            return render_template('boneless.html', item=None, boneless_sauces=get_menu_options('boneless_sauce'))

        base_price = get_item_price('Boneless')
        total_price = base_price

        item = {
            'name': 'Boneless',
            'type': 'Boneless',
            'price': total_price,
            'unit_price': total_price,
            'quantity': 1,
            'sauces': sauces,
            'accompaniment': accompaniment,
            'notes': notes
        }

        session['cart'].append(item)
        session.modified = True
        flash('¡Boneless agregado a la orden!', 'success')
        return redirect(url_for('home'))

    return render_template('boneless.html', item=None, boneless_sauces=get_menu_options('boneless_sauce'))

# Customize Complementos (Extra Sauces) - UPDATED TO REDIRECT TO HOME
@app.route('/customize/complementos', methods=['GET', 'POST'])
@login_required
def customize_complementos():
    if request.method == 'POST':
        # Get form data
        sauces = request.form.getlist('sauces')
        notes = request.form.get('notes', '')
        
        # Validate required fields
        if not sauces:
            flash('Por favor selecciona al menos una salsa extra.', 'error')
            return render_template('complementos.html', item=None, extra_sauces=get_menu_options('extra_sauce'),
                                   sauce_price=get_item_price('Complementos'))

        sauce_count = len(sauces)
        sauce_unit = get_item_price('Complementos')
        total_price = sauce_count * sauce_unit

        item = {
            'name': 'Complementos',
            'type': 'Complementos',
            'price': total_price,
            'unit_price': total_price,
            'quantity': 1,
            'sauces': sauces,
            'notes': notes,
            'sauce_count': sauce_count
        }

        session['cart'].append(item)
        session.modified = True
        flash('¡Complementos agregados a la orden!', 'success')
        return redirect(url_for('home'))

    return render_template('complementos.html', item=None, extra_sauces=get_menu_options('extra_sauce'),
                           sauce_price=get_item_price('Complementos'))

# Customize Rice Ball with enhanced Ostión validation - UPDATED TO REDIRECT TO HOME
@app.route('/customize/rice_ball', methods=['GET', 'POST'])
@login_required
def customize_rice_ball():
    if request.method == 'POST':
        # Get form data
        base = request.form.getlist('base')
        ingredients = request.form.getlist('ingredients')
        style = request.form.get('style')
        sauce = request.form.get('sauce')
        toppings = request.form.getlist('toppings')
        notes = request.form.get('notes', '')
        
        # Validate required fields
        if not style:
            flash('Por favor selecciona si deseas tu bola de arroz Fría o Empanizada.', 'error')
            return render_template('rice_ball.html', item=None)
            
        if not sauce:
            flash('Por favor selecciona una salsa.', 'error')
            return render_template('rice_ball.html', item=None)
        
        # Enhanced ingredient validation with Ostión exception
        regular_ingredients = [ing for ing in ingredients if ing != 'Ostión']
        ostion_ingredients = [ing for ing in ingredients if ing == 'Ostión']
        
        # Validate regular ingredients (max 6)
        if len(regular_ingredients) > 6:
            flash('Máximo 6 ingredientes regulares permitidos', 'error')
            return render_template('rice_ball.html', item=None,
                                   rice_ingredients=get_menu_options('rice_ingredient'),
                                   rice_sauces=get_menu_options('rice_sauce'),
                                   base_price=get_item_price('Bola de Arroz'),
                                   ostion_price=get_item_price('Ostión'))

        if len(regular_ingredients) < 1:
            flash('Selecciona al menos 1 ingrediente', 'error')
            return render_template('rice_ball.html', item=None,
                                   rice_ingredients=get_menu_options('rice_ingredient'),
                                   rice_sauces=get_menu_options('rice_sauce'),
                                   base_price=get_item_price('Bola de Arroz'),
                                   ostion_price=get_item_price('Ostión'))

        if len(ostion_ingredients) > 1:
            flash('Solo puedes agregar un Ostión', 'error')
            return render_template('rice_ball.html', item=None,
                                   rice_ingredients=get_menu_options('rice_ingredient'),
                                   rice_sauces=get_menu_options('rice_sauce'),
                                   base_price=get_item_price('Bola de Arroz'),
                                   ostion_price=get_item_price('Ostión'))

        base_price, ostion_price, total_price = _calc_rice_ball_price(ingredients)

        item = {
            'name': 'Bola de Arroz',
            'type': 'Bola de Arroz',
            'price': total_price,
            'unit_price': total_price,
            'quantity': 1,
            'base': base,
            'ingredients': ingredients,
            'style': style,
            'sauce': sauce,
            'toppings': toppings,
            'notes': notes,
            'ostion_cost': ostion_price
        }

        session['cart'].append(item)
        session.modified = True
        flash('¡Bola de Arroz agregada a la orden!', 'success')
        return redirect(url_for('home'))

    return render_template('rice_ball.html', item=None,
                           rice_ingredients=get_menu_options('rice_ingredient'),
                           rice_sauces=get_menu_options('rice_sauce'),
                           base_price=get_item_price('Bola de Arroz'),
                           ostion_price=get_item_price('Ostión'))

# Customize Sushi with enhanced Ostión validation - UPDATED TO REDIRECT TO HOME
@app.route('/customize/sushi', methods=['GET', 'POST'])
@login_required
def customize_sushi():
    if request.method == 'POST':
        # Get form data
        base = request.form.getlist('base')
        ingredients = request.form.getlist('ingredients')
        style = request.form.get('style')
        prepared = request.form.get('prepared')
        
        # For sushi, we want to use the prepared value as the sauce if sauce is empty
        sauce = request.form.get('sauce')
        if not sauce or sauce.strip() == '':
            sauce = prepared
        
        toppings = request.form.getlist('toppings')
        notes = request.form.get('notes', '')
        
        # Validate required fields
        if not style:
            flash('Por favor selecciona si deseas tu sushi Frío o Empanizado.', 'error')
            return render_template('sushi.html', item=None, sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_sauces=get_menu_options('sushi_sauce'), sushi_prep_prices=get_sushi_prep_prices(), ostion_price=get_item_price('Ostión'))

        if not prepared:
            flash('Por favor selecciona una opción de preparado.', 'error')
            return render_template('sushi.html', item=None, sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_sauces=get_menu_options('sushi_sauce'), sushi_prep_prices=get_sushi_prep_prices(), ostion_price=get_item_price('Ostión'))

        regular_ingredients = [ing for ing in ingredients if ing != 'Ostión']
        ostion_ingredients = [ing for ing in ingredients if ing == 'Ostión']

        if len(regular_ingredients) > 3:
            flash('Máximo 3 ingredientes regulares permitidos', 'error')
            return render_template('sushi.html', item=None, sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_sauces=get_menu_options('sushi_sauce'), sushi_prep_prices=get_sushi_prep_prices(), ostion_price=get_item_price('Ostión'))

        if len(regular_ingredients) < 1:
            flash('Selecciona al menos 1 ingrediente', 'error')
            return render_template('sushi.html', item=None, sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_sauces=get_menu_options('sushi_sauce'), sushi_prep_prices=get_sushi_prep_prices(), ostion_price=get_item_price('Ostión'))

        if len(ostion_ingredients) > 1:
            flash('Solo puedes agregar un Ostión', 'error')
            return render_template('sushi.html', item=None, sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_sauces=get_menu_options('sushi_sauce'), sushi_prep_prices=get_sushi_prep_prices(), ostion_price=get_item_price('Ostión'))

        base_price, ostion_price, total_price = _calc_sushi_price(ingredients, prepared)

        item = {
            'name': 'Sushi',
            'type': 'Sushi',
            'price': total_price,
            'unit_price': total_price,
            'quantity': 1,
            'base': base,
            'ingredients': ingredients,
            'style': style,
            'prepared': prepared,
            'sauce': sauce,
            'toppings': toppings,
            'notes': notes,
            'ostion_cost': ostion_price
        }

        session['cart'].append(item)
        session.modified = True
        flash('¡Sushi agregado a la orden!', 'success')
        return redirect(url_for('home'))

    return render_template('sushi.html', item=None, sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_sauces=get_menu_options('sushi_sauce'), sushi_prep_prices=get_sushi_prep_prices())

# View Cart - UNCHANGED (still goes to cart when explicitly requested)
@app.route('/cart')
@login_required
def view_cart():
    cart = session.get('cart', [])
    
    # Get active promotions with debugging
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
    return render_template('cart.html', cart=cart, total_price=total_price, promotions=promotions,
                           order_id=session.get('order_id', ''),
                           applied_discount=applied_discount)

# Update Item Quantity
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

        # unit_price es siempre el precio unitario BASE (sin descuento). Si falta,
        # derívalo del precio base (original_price cuando había promo).
        if 'unit_price' not in item:
            base = item['original_price'] if had_promo else item['price']
            item['unit_price'] = base / max(current_quantity, 1)

        item['quantity'] = quantity
        item['price'] = money(item['unit_price'] * quantity)
        # Limpia el descuento de ESTA línea; reapply reevalúa el carrito completo.
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

# Updated update_item function to handle all item types including Complementos
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
            
            # Update price using new pricing system
            new_price = get_item_price(item['beverage_type'])
            item['unit_price'] = new_price
            item['price'] = new_price * item.get('quantity', 1)
        
        elif item['type'] == 'Boneless':
            # Handle multiple sauces - FIXED PRICING
            sauces = request.form.getlist('sauce')
            item['sauces'] = sauces
            item['accompaniment'] = request.form.get('accompaniment')
            item['notes'] = request.form.get('notes', '')
            
            # NEW PRICING: Base price only (no extra sauce charges)
            base_price = get_item_price('Boneless')
            total_price = base_price  # No extra charges for included sauces
            item['unit_price'] = total_price
            item['price'] = total_price * item.get('quantity', 1)
        
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
            
            # Enhanced validation for Ostión
            regular_ingredients = [ing for ing in ingredients if ing != 'Ostión']
            ostion_ingredients = [ing for ing in ingredients if ing == 'Ostión']
            
            # Validate regular ingredients (max 6)
            if len(regular_ingredients) > 6:
                flash('Máximo 6 ingredientes regulares permitidos', 'error')
                return render_template('rice_ball.html', item=item, item_index=item_index,
                                       rice_ingredients=get_menu_options('rice_ingredient'),
                                       rice_sauces=get_menu_options('rice_sauce'),
                                       base_price=get_item_price('Bola de Arroz'),
                                       ostion_price=get_item_price('Ostión'))

            if len(regular_ingredients) < 1:
                flash('Selecciona al menos 1 ingrediente', 'error')
                return render_template('rice_ball.html', item=item, item_index=item_index,
                                       rice_ingredients=get_menu_options('rice_ingredient'),
                                       rice_sauces=get_menu_options('rice_sauce'),
                                       base_price=get_item_price('Bola de Arroz'),
                                       ostion_price=get_item_price('Ostión'))

            if len(ostion_ingredients) > 1:
                flash('Solo puedes agregar un Ostión', 'error')
                return render_template('rice_ball.html', item=item, item_index=item_index,
                                       rice_ingredients=get_menu_options('rice_ingredient'),
                                       rice_sauces=get_menu_options('rice_sauce'),
                                       base_price=get_item_price('Bola de Arroz'),
                                       ostion_price=get_item_price('Ostión'))
            
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
            
            # Enhanced validation for Ostión
            regular_ingredients = [ing for ing in ingredients if ing != 'Ostión']
            ostion_ingredients = [ing for ing in ingredients if ing == 'Ostión']
            
            # Validate regular ingredients (max 3)
            if len(regular_ingredients) > 3:
                flash('Máximo 3 ingredientes regulares permitidos', 'error')
                return render_template('sushi.html', item=item, item_index=item_index,
                                       sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_sauces=get_menu_options('sushi_sauce'), sushi_prep_prices=get_sushi_prep_prices(), ostion_price=get_item_price('Ostión'))

            if len(regular_ingredients) < 1:
                flash('Selecciona al menos 1 ingrediente', 'error')
                return render_template('sushi.html', item=item, item_index=item_index,
                                       sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_sauces=get_menu_options('sushi_sauce'), sushi_prep_prices=get_sushi_prep_prices(), ostion_price=get_item_price('Ostión'))

            if len(ostion_ingredients) > 1:
                flash('Solo puedes agregar un Ostión', 'error')
                return render_template('sushi.html', item=item, item_index=item_index,
                                       sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_sauces=get_menu_options('sushi_sauce'), sushi_prep_prices=get_sushi_prep_prices(), ostion_price=get_item_price('Ostión'))
            
            item['base'] = request.form.getlist('base')
            item['ingredients'] = ingredients
            item['style'] = request.form.get('style')
            item['prepared'] = prepared
            
            # Handle sauce field
            sauce = request.form.get('sauce')
            if not sauce or sauce.strip() == '':
                sauce = prepared
            item['sauce'] = sauce
            
            item['toppings'] = request.form.getlist('toppings')
            item['notes'] = request.form.get('notes', '')
            
            base_price, ostion_price, total_price = _calc_sushi_price(ingredients, prepared)
            item['unit_price'] = total_price
            item['price'] = total_price * item.get('quantity', 1)
            item['ostion_cost'] = ostion_price
        
        # El precio recalculado ES el nuevo precio base: descarta el descuento
        # viejo de esta línea para que reapply no lo revierta a un base obsoleto.
        item.pop('original_price', None)
        item.pop('discount', None)
        cart[item_index] = item
        # El precio/línea cambió: reevalúa la promo activa contra precios base.
        reapply_active_coupon(cart)
        session['cart'] = cart
        session.modified = True
        flash('Item actualizado con éxito', 'success')
        return redirect(url_for('view_cart'))  # Updates still go back to cart for review
    
    # GET request - show form to edit
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
                               sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_sauces=get_menu_options('sushi_sauce'), sushi_prep_prices=get_sushi_prep_prices(), ostion_price=get_item_price('Ostión'))

# Remove Item
@app.route('/remove_item/<int:item_index>', methods=['POST'])
@login_required
def remove_item(item_index):
    cart = session.get('cart', [])
    
    if item_index < len(cart):
        cart.pop(item_index)
        # Quitar una línea puede invalidar la promo (p.ej. la línea pagada de un
        # 2x1): reevalúa para no dejar líneas gratis huérfanas ni descuentos rotos.
        reapply_active_coupon(cart)
        session['cart'] = cart
        session.modified = True
        flash('Item eliminado de la orden', 'success')

    return redirect(url_for('view_cart'))

def _reset_cart_prices(cart):
    """Restaura cada ítem a su precio base (pre-descuento) y borra las
    insignias de descuento, dejando el carrito en estado limpio."""
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
    """Aplica `promo` al carrito partiendo SIEMPRE de precios base limpios.
    Devuelve True si se aplicó, False si la promoción ya no califica (deja el
    carrito limpio en ese caso). Centraliza la lógica de descuentos para que
    cualquier mutación del carrito la pueda reevaluar de forma consistente."""
    _reset_cart_prices(cart)

    # Asegura unit_price (base) y calcula el total base
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

    # Monto fijo: reduce la ORDEN por exactamente `value` una sola vez,
    # descontando de las líneas más caras primero (independiente del agrupamiento).
    remaining = money(promo['value'] or 0)
    applicable = [item for item in cart if not applicable_items or item['type'] in applicable_items]
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
    """Reevalúa el cupón activo tras mutar el carrito. Deja SIEMPRE el carrito
    consistente: reaplica desde precios base si la promo sigue válida, o borra
    todos los descuentos y olvida el cupón si ya no aplica (o no hay cupón)."""
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


# Apply Coupon
@app.route('/apply_coupon', methods=['POST'])
@login_required
def apply_coupon():
    coupon_code = request.form.get('coupon_code', '').strip().upper()

    if not coupon_code:
        flash('Por favor ingresa un código de promoción', 'error')
        return redirect(url_for('view_cart'))

    cart = session.get('cart', [])
    if any('discount' in item for item in cart):
        flash('Ya hay una promoción aplicada a esta orden. Para usar otro código, elimina los artículos y agrégalos de nuevo.', 'error')
        return redirect(url_for('view_cart'))

    conn = get_db_connection()
    promo = conn.execute('SELECT * FROM promotions WHERE name = ? AND active = 1', (coupon_code,)).fetchone()

    if not promo:
        flash('Código de promoción inválido o expirado', 'error')
        return redirect(url_for('view_cart'))

    total_price = 0
    for item in cart:
        quantity = item.get('quantity', 1)
        if 'unit_price' not in item:
            item['unit_price'] = item['price'] / max(quantity, 1)
        total_price += item['price']

    # Check minimum purchase requirement
    if (promo['min_purchase'] or 0) > 0 and total_price < promo['min_purchase']:
        flash(f'Se requiere una compra mínima de ${promo["min_purchase"]} para aplicar esta promoción', 'error')
        return redirect(url_for('view_cart'))

    applied = _apply_promo_to_cart(cart, promo)
    if not applied:
        if promo['type'] == 'bxgy':
            buy_qty = int(promo['value']) if promo['value'] else 2
            get_free = int(promo['get_free'] or 1)
            applicable_items = _parse_applicable_items(promo)
            items_label = ', '.join(applicable_items) if applicable_items else 'productos'
            flash(f'Necesitas al menos {buy_qty + get_free} {items_label} para aplicar esta promoción', 'error')
        else:
            flash('No se pudo aplicar la promoción a esta orden', 'error')
        return redirect(url_for('view_cart'))

    session['coupon_code'] = promo['name']
    session['cart'] = cart
    session.modified = True
    flash(f'Promoción "{promo["description"] or promo["name"]}" aplicada con éxito', 'success')
    return redirect(url_for('view_cart'))

# Remove Coupon
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

def _issue_ticket_token():
    """Emite un token de un solo uso para /ticket y lo guarda en sesión.
    Previene que un doble-submit del mismo carrito registre la venta dos veces."""
    token = str(uuid.uuid4())
    session['ticket_token'] = token
    session.modified = True
    return token

# Payment selection page
@app.route('/payment')
@login_required
def payment():
    cart = session.get('cart', [])
    if not cart:
        flash('Agrega al menos un ítem antes de proceder al pago.', 'error')
        return redirect(url_for('home'))

    total_price = 0
    for item in cart:
        total_price += item['price']
    total_price = money(total_price)

    return render_template('payment.html', total_price=total_price,
                           ticket_token=_issue_ticket_token())

# Cash payment page
@app.route('/cash_payment')
@login_required
def cash_payment():
    cart = session.get('cart', [])
    if not cart:
        flash('Agrega al menos un ítem antes de proceder al pago.', 'error')
        return redirect(url_for('home'))

    total_price = 0
    for item in cart:
        total_price += item['price']
    total_price = money(total_price)

    return render_template('cash_payment.html', total_price=total_price,
                           usd_rate=_usd_rate(),
                           ticket_token=_issue_ticket_token())

def _api_autorizada():
    """Permite acceso desde localhost (bridge de impresión) o sesión activa."""
    if request.remote_addr in ('127.0.0.1', '::1'):
        return True
    return 'user_id' in session

@app.route('/favicon.ico')
def favicon():
    base = os.path.dirname(os.path.dirname(__file__))
    for fname, mime in [('icon.png', 'image/png'), ('icon.jpeg', 'image/jpeg'), ('icon.jpg', 'image/jpeg')]:
        icon_path = os.path.join(base, 'assets', fname)
        if os.path.exists(icon_path):
            return send_file(icon_path, mimetype=mime)
    return '', 204

@app.route('/api/print_queue')
@csrf.exempt
def get_print_queue():
    """Trabajos de impresión pendientes para el bridge (solo localhost o sesión activa)."""
    if not _api_autorizada():
        return jsonify({'error': 'No autorizado'}), 401
    conn = get_db_connection()
    jobs = conn.execute(
        "SELECT id, receipt_content FROM print_jobs WHERE status = 'pending' ORDER BY created_at"
    ).fetchall()
    return jsonify({'jobs': [{'id': j['id'], 'receipt_content': j['receipt_content']} for j in jobs]})

@app.route('/api/mark_printed/<job_id>', methods=['POST'])
@csrf.exempt
def mark_printed(job_id):
    """Marcar un trabajo como impreso (solo localhost o sesión activa)."""
    if not _api_autorizada():
        return jsonify({'error': 'No autorizado'}), 401
    conn = get_db_connection()
    conn.execute("UPDATE print_jobs SET status = 'printed' WHERE id = ?", (job_id,))
    conn.commit()
    return jsonify({'success': True})


@app.route('/api/config/printer', methods=['POST'])
@csrf.exempt
def update_printer_api():
    """El bridge llama este endpoint cuando detecta una impresora automáticamente."""
    if not _api_autorizada():
        return jsonify({'error': 'No autorizado'}), 401
    data = request.get_json(silent=True) or {}
    nombre = data.get('printer_name', '').strip()
    if not nombre:
        return jsonify({'error': 'Nombre requerido'}), 400
    conn = get_db_connection()
    conn.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES ('printer_name', ?)",
        (nombre,)
    )
    conn.commit()
    return jsonify({'success': True, 'printer_name': nombre})


# Replace your existing ticket route with this complete version
@app.route('/ticket', methods=['POST'])
@login_required
def ticket():
    # POST-only: crear una orden muta estado — por GET un refresh, el botón
    # atrás o un prefetch del navegador podían duplicar ventas (y sin CSRF).
    cart = session.get('cart', [])

    # Carrito vacío: no registres una orden de $0. (Igual que /payment.)
    if not cart:
        flash('Agrega al menos un ítem antes de proceder al pago.', 'error')
        return redirect(url_for('home'))

    # Idempotencia: la página de pago sembró un token de un solo uso. Si la
    # sesión ya tiene un token y el POST no coincide (ya se consumió por un
    # doble-submit del mismo carrito), no insertes de nuevo.
    session_token = session.get('ticket_token')
    if session_token is not None:
        if request.form.get('ticket_token') != session_token:
            flash('Esta orden ya fue procesada.', 'error')
            return redirect(url_for('home'))
        session.pop('ticket_token', None)

    # Calculate total price correctly
    total_price = 0
    for item in cart:
        total_price += item['price']
    total_price = money(total_price)

    payment_method = request.form.get('payment_method', 'card')

    # Moneda del efectivo recibido. El total, el cambio y lo guardado en la
    # orden siempre quedan en MXN; si pagaron en USD se convierte con el tipo
    # de cambio configurado y se conserva el monto original para el ticket.
    paid_currency = request.form.get('currency', 'mxn').lower()
    if paid_currency not in ('mxn', 'usd'):
        paid_currency = 'mxn'
    paid_amount_usd = 0.0
    usd_rate_used = 0.0

    try:
        amount_paid = money(float(request.form.get('amount_paid', total_price)))
    except (ValueError, TypeError):
        amount_paid = total_price
        paid_currency = 'mxn'

    if payment_method == 'cash' and paid_currency == 'usd':
        usd_rate_used = _usd_rate()
        paid_amount_usd = amount_paid
        amount_paid = money(paid_amount_usd * usd_rate_used)

    change = money(amount_paid - total_price) if payment_method == 'cash' else 0
    # Efectivo: no permitas registrar la venta con un pago menor al total.
    if payment_method == 'cash' and amount_paid < total_price:
        flash(f'Pago insuficiente. Se recibió ${amount_paid:.2f} de ${total_price:.2f}.', 'error')
        return redirect(url_for('view_cart'))
    # Split payment: store cash_portion and card_portion in amount_paid as a JSON string
    if payment_method == 'split':
        try:
            cash_portion = float(request.form.get('cash_portion', 0))
            card_portion = float(request.form.get('card_portion', 0))
        except (ValueError, TypeError):
            cash_portion = 0.0
            card_portion = 0.0
        if cash_portion < 0 or card_portion < 0:
            flash('Los montos de pago no pueden ser negativos.', 'error')
            return redirect(url_for('view_cart'))
        if money(card_portion) > total_price:
            flash('El monto con tarjeta no puede exceder el total.', 'error')
            return redirect(url_for('view_cart'))
        # La porción en efectivo puede venir en USD; la tarjeta siempre es MXN.
        cash_currency = request.form.get('cash_currency', 'mxn').lower()
        if cash_currency == 'usd' and cash_portion > 0:
            usd_rate_used = _usd_rate()
            paid_amount_usd = money(cash_portion)
            paid_currency = 'usd'
            cash_portion = money(paid_amount_usd * usd_rate_used)
        else:
            paid_currency = 'mxn'
            cash_portion = money(cash_portion)
        amount_paid = money(cash_portion + card_portion)
        if amount_paid < total_price:
            flash(f'Pago insuficiente. Se recibió ${amount_paid:.2f} de ${total_price:.2f}.', 'error')
            return redirect(url_for('view_cart'))
        change = money(max(0, amount_paid - total_price))
        split_cash_mxn = cash_portion
        split_card = money(card_portion)
    else:
        split_cash_mxn = None
        split_card = None

    # Order ID for this transaction
    order_id = session.get('order_id')
    
    # Get customer name from session
    customer_name = session.get('customer_name', 'Cliente')
    
    # Save order to database with proper error handling
    conn = None
    try:
        conn = get_db_connection()
        # El id de orden son 8 caracteres de un uuid: puede chocar con una orden
        # existente. Reintentar con un id nuevo en vez de fallar la venta.
        for _intento in range(5):
            try:
                conn.execute(
                    'INSERT INTO orders (id, items, total, payment_method, amount_paid, change_amount, date, status, customer_name, paid_currency, paid_amount_usd, usd_rate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (
                        order_id,
                        json.dumps(cart),
                        total_price,
                        payment_method,
                        amount_paid,
                        change,
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'completed',
                        customer_name,
                        paid_currency,
                        paid_amount_usd,
                        usd_rate_used
                    )
                )
                break
            except sqlite3.IntegrityError:
                if _intento == 4:
                    raise
                order_id = str(uuid.uuid4())[:8]
        # La orden ya se cobró: si venía de la cola de pedidos, sácala de ahí.
        held_id = session.pop('held_id', None)
        if held_id:
            conn.execute('DELETE FROM held_orders WHERE id = ?', (held_id,))
        conn.commit()

        # Save receipt file and queue print job
        receipt_file_success = False
        try:
            receipt_path, receipt_text = print_receipt_physical(
                cart, total_price, payment_method, amount_paid, change, order_id, customer_name,
                paid_currency=paid_currency, paid_amount_usd=paid_amount_usd, usd_rate=usd_rate_used,
                split_cash_mxn=split_cash_mxn, split_card=split_card)
            receipt_file_success = True
            # Store job in DB so the bridge can pick it up (survives restarts, works remotely)
            conn.execute(
                "INSERT OR IGNORE INTO print_jobs (id, receipt_content, status, created_at) VALUES (?, ?, 'pending', ?)",
                (order_id, receipt_text, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
            conn.commit()
        except Exception as e:
            print(f"Error saving receipt: {str(e)}")
        
        log_activity('orden_completada', f'Orden #{order_id} — {customer_name} — ${total_price:.2f} ({payment_method})')
        # Clear cart, customer name, and generate new order ID for the next order
        session['cart'] = []
        session['order_id'] = str(uuid.uuid4())[:8]
        session['customer_name'] = ''  # Clear customer name for next order
        session.pop('coupon_code', None)  # el cupón no debe cruzar entre órdenes
        # Token fresco: un re-POST del mismo carrito ya no coincidirá y no duplicará.
        session['ticket_token'] = str(uuid.uuid4())
        session.modified = True
        
        # Return success page with both statuses
        # Check actual print job status so the UI reflects reality
        job_status = 'none'
        if receipt_file_success:
            job_row = conn.execute(
                "SELECT status FROM print_jobs WHERE id = ?", (order_id,)
            ).fetchone()
            job_status = job_row['status'] if job_row else 'none'

        return render_template('thank_you.html',
                             order_id=order_id,
                             print_success=receipt_file_success,
                             job_status=job_status)
        
    except sqlite3.Error as e:
        # Database error handling
        error_message = f"Error al guardar la orden: {str(e)}"
        flash(error_message, "error")
        print(error_message)
        if conn:
            conn.rollback()
        return redirect(url_for('view_cart'))

def print_receipt_physical(cart, total, payment_method, amount_paid=0, change=0, order_id=None, customer_name=None,
                           paid_currency='mxn', paid_amount_usd=0, usd_rate=0,
                           split_cash_mxn=None, split_card=None):
    """Print receipt using physical printer connected to laptop - UPDATED WITH COMPLEMENTOS"""
    
    # Generate receipt content
    receipt_content = []
    receipt_content.append(f"Orden #: {order_id or session.get('order_id')}")
    receipt_content.append(f"Cliente: {customer_name or 'Cliente'}")
    receipt_content.append("-" * 38)
    
    # Items
    receipt_content.append("ARTICULO                PRECIO")
    receipt_content.append("-" * 38)
    
    for item in cart:
        quantity = item.get('quantity', 1)
        receipt_content.append(f"{item['name']} x{quantity:<2}      ${item['price']:.2f}")
        
        # Add item details based on type
        if item['type'] == 'Bebida':
            if 'beverage_type' in item and item['beverage_type']:
                receipt_content.append(f"  {item['beverage_type']}")

        elif item['type'] == 'Boneless':
            if 'sauces' in item and item['sauces']:
                receipt_content.append(f"  {', '.join(item['sauces'])}")
            elif 'sauce' in item and item['sauce']:
                receipt_content.append(f"  {item['sauce']}")
            if 'accompaniment' in item and item['accompaniment']:
                receipt_content.append(f"  {item['accompaniment']}")

        elif item['type'] == 'Complementos':
            if 'sauces' in item and item['sauces']:
                receipt_content.append(f"  {', '.join(item['sauces'])}")
                sauce_count = len(item['sauces'])
                receipt_content.append(f"  {sauce_count} x $10 = ${sauce_count * 10:.2f}")

        elif item['type'] in ['Bola de Arroz', 'Sushi']:
            # Ingredients (abbreviated to 3 chars, Queso/Aguacate omitted)
            _skip = {'queso', 'aguacate'}
            if 'ingredients' in item:
                filtered = [i for i in item['ingredients'] if i.lower() not in _skip]
                abbr = [i[:3] for i in filtered] if filtered else []
                if abbr:
                    receipt_content.append(f"  {', '.join(abbr)}")
                if item.get('ostion_cost', 0) > 0:
                    receipt_content.append(f"  Ostión: +${item['ostion_cost']:.2f}")

            if 'style' in item and item['style']:
                receipt_content.append(f"  {item['style']}")

            if 'sauce' in item and item['sauce']:
                receipt_content.append(f"  {item['sauce']}")

            if 'prepared' in item and item['prepared']:
                receipt_content.append(f"  {item['prepared']}")

            if 'toppings' in item:
                topping_text = ', '.join(item['toppings']) if item['toppings'] else "Ninguno"
                receipt_content.append(f"  {topping_text}")
        
        # Notes for any item type
        if 'notes' in item and item['notes']:
            receipt_content.append(f"  Notas: {item['notes']}")
            
        receipt_content.append("-" * 38)
    
    # Total
    receipt_content.append(f"TOTAL: ${total:.2f}")

    # Pago y cambio (solo ventas en efectivo o mixtas; el cambio siempre en MXN)
    if payment_method == 'split' and amount_paid:
        if paid_currency == 'usd' and paid_amount_usd:
            receipt_content.append(f"EFECTIVO: US${paid_amount_usd:.2f} (TC ${usd_rate:.2f})")
            receipt_content.append(f"          = ${split_cash_mxn:.2f} MXN")
        else:
            receipt_content.append(f"EFECTIVO: ${split_cash_mxn:.2f}")
        receipt_content.append(f"TARJETA:  ${split_card:.2f}")
        if change:
            receipt_content.append(f"CAMBIO (MXN): ${change:.2f}")
    elif payment_method == 'cash' and amount_paid:
        if paid_currency == 'usd' and paid_amount_usd:
            receipt_content.append(f"PAGO: US${paid_amount_usd:.2f} (TC ${usd_rate:.2f})")
            receipt_content.append(f"      = ${amount_paid:.2f} MXN")
        else:
            receipt_content.append(f"PAGO: ${amount_paid:.2f}")
        if change:
            receipt_content.append(f"CAMBIO (MXN): ${change:.2f}")


    # Save receipt to file
    receipt_id = order_id or session.get('order_id')
    receipts_dir = os.path.join(os.getcwd(), 'receipts')
    os.makedirs(receipts_dir, exist_ok=True)
    receipt_path = os.path.join(receipts_dir, f"receipt_{receipt_id}.txt")
    
    receipt_text = "\n".join(receipt_content)

    # Write receipt to file as a local backup
    with open(receipt_path, "w", encoding="utf-8") as f:
        f.write(receipt_text)

    return receipt_path, receipt_text



    

    




# ── New Order ─────────────────────────────────────────────────────────────────
@app.route('/new_order', methods=['POST'])
@login_required
def new_order():
    session.pop('cart', None)
    session.pop('customer_name', None)
    # Si había una orden retenida cargada, se abandona la edición pero la
    # orden se queda en la cola (no se borra: la cocina ya la tiene).
    session.pop('held_id', None)
    session['order_id'] = str(uuid.uuid4())[:8]
    session['cart'] = []
    session.modified = True
    return redirect(url_for('home'))


# ── Held Orders (Cola de Pedidos) ─────────────────────────────────────────────

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
    # Si esta orden venía de la cola (resume), reemplaza la entrada anterior
    # en vez de duplicarla.
    prev_held = session.pop('held_id', None)
    if prev_held:
        conn.execute('DELETE FROM held_orders WHERE id = ?', (prev_held,))
    cursor = conn.execute(
        'INSERT INTO held_orders (order_ref, customer_name, cart_json, total, created_at) VALUES (?, ?, ?, ?, ?)',
        ('', customer_name, json.dumps(cart), total, created_at)
    )
    held_id = cursor.lastrowid
    order_ref = f'HOLD-{held_id:03d}'
    conn.execute('UPDATE held_orders SET order_ref = ? WHERE id = ?', (order_ref, held_id))
    conn.commit()

    # Print kitchen ticket so kitchen can start preparing
    try:
        _, receipt_text = print_receipt_physical(
            cart=cart,
            total=total,
            payment_method='PEDIDO EN ESPERA',
            order_id=order_ref,
            customer_name=customer_name
        )
        conn.execute(
            "INSERT OR IGNORE INTO print_jobs (id, receipt_content, status, created_at) VALUES (?, ?, 'pending', ?)",
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

    # La orden retenida NO se borra aquí: si cierran sesión o se pierde la
    # sesión antes de cobrar, debe seguir en la cola. Se borra al cobrar
    # (/ticket) o al re-retenerla (hold_order).
    session['cart'] = cart
    session['customer_name'] = order['customer_name']
    session['order_id'] = str(uuid.uuid4())[:8]
    session['held_id'] = held_id
    session.modified = True

    flash(f'Orden {order["order_ref"]} cargada. Modifica si es necesario y procede al pago.', 'success')
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
        "WHERE customer_name IS NOT NULL AND customer_name != '' AND customer_name != 'Cliente' "
        "ORDER BY date DESC LIMIT 30"
    ).fetchall()
    names = list(dict.fromkeys(r['customer_name'] for r in rows))[:20]
    return jsonify(names)


@app.route('/split_payment')
@login_required
def split_payment():
    cart = session.get('cart', [])
    total_price = money(sum(item['price'] for item in cart))
    return render_template('split_payment.html', total_price=total_price,
                           usd_rate=_usd_rate(),
                           ticket_token=_issue_ticket_token())


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


# ── Configuración general ─────────────────────────────────────────────────────

def get_config(key, default=''):
    """Lee un valor de la tabla config."""
    conn = get_db_connection()
    row = conn.execute('SELECT value FROM config WHERE key = ?', (key,)).fetchone()
    return row['value'] if row else default


DEFAULT_USD_RATE = 18.0


def _usd_rate():
    """Tipo de cambio USD → MXN configurado; cae al default si está corrupto."""
    try:
        rate = float(get_config('usd_rate', str(DEFAULT_USD_RATE)))
    except (ValueError, TypeError):
        return DEFAULT_USD_RATE
    return rate if rate > 0 else DEFAULT_USD_RATE


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
    """Endpoint para que el print bridge lea la configuración (solo localhost)."""
    if not _api_autorizada():
        return jsonify({'error': 'No autorizado'}), 401
    conn = get_db_connection()
    rows = conn.execute('SELECT key, value FROM config').fetchall()
    return jsonify({r['key']: r['value'] for r in rows})


# ── Manejo de errores ─────────────────────────────────────────────────────────

_ERROR_CSS = (
    "body{margin:0;background:#121212;color:#f5f5f5;font-family:'SF Pro Display',"
    "Helvetica,sans-serif;display:flex;flex-direction:column;align-items:center;"
    "justify-content:center;height:100vh;text-align:center;gap:16px;}"
    "h1{font-size:4rem;color:#ff9800;margin:0;}"
    "h2{font-size:1.5rem;font-weight:400;color:#aaa;margin:0;}"
    "p{color:#666;max-width:420px;line-height:1.6;}"
    "a{display:inline-block;margin-top:8px;padding:12px 28px;background:#ff9800;"
    "color:#121212;border-radius:10px;text-decoration:none;font-weight:700;}"
)

@app.errorhandler(404)
def pagina_no_encontrada(e):
    html = (
        f'<!doctype html><html lang="es"><head><meta charset="UTF-8">'
        f'<title>Página no encontrada</title>'
        f'<style>{_ERROR_CSS}</style></head><body>'
        f'<h1>404</h1><h2>Página no encontrada</h2>'
        f'<p>La dirección que buscas no existe en esta aplicación.</p>'
        f'<a href="/">← Volver al inicio</a></body></html>'
    )
    return html, 404

@app.errorhandler(500)
def error_servidor(e):
    html = (
        f'<!doctype html><html lang="es"><head><meta charset="UTF-8">'
        f'<title>Error del servidor</title>'
        f'<style>{_ERROR_CSS}</style></head><body>'
        f'<h1>500</h1><h2>Error interno del servidor</h2>'
        f'<p>Algo salió mal. Intenta recargar la página o reinicia la aplicación.</p>'
        f'<a href="/">← Volver al inicio</a></body></html>'
    )
    return html, 500


# ── Módulos de rutas (extraídos de este archivo por dominio) ─────────────────
import routes_orders_admin
import routes_users
import routes_employees
import routes_promotions
import routes_respaldo
import routes_kuike
import routes_menu_options
import routes_inventory
import routes_prices

routes_orders_admin.register(app, print_receipt_physical)
routes_users.register(app)
routes_employees.register(app)
routes_promotions.register(app)
routes_respaldo.register(app)
routes_kuike.register(app)
routes_menu_options.register(app)
routes_inventory.register(app)
routes_prices.register(app)


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001)), debug=False)