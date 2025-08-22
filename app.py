from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import os
import uuid
from datetime import datetime, timedelta
import sqlite3
import json
import subprocess
import platform
from functools import wraps

app = Flask(__name__)

# Store secret key in environment variable or generate a persistent one
SECRET_KEY = os.environ.get('SECRET_KEY') or os.urandom(24)
app.secret_key = SECRET_KEY

# Set session lifetime
app.permanent_session_lifetime = timedelta(hours=24)

# Database setup
def get_db_connection():
    conn = sqlite3.connect('restaurant.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        id TEXT PRIMARY KEY,
        items TEXT,
        total REAL,
        payment_method TEXT,
        amount_paid REAL,
        change_amount REAL,
        date TEXT,
        status TEXT,
        customer_name TEXT
    )
    ''')
    
    # Create promotions table with new columns
    conn.execute('''
    CREATE TABLE IF NOT EXISTS promotions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        value REAL NOT NULL,
        min_purchase REAL,
        applicable_items TEXT,
        active INTEGER DEFAULT 1
    )
    ''')
    
    # Create users table for login
    conn.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Add new columns if they don't exist
    try:
        conn.execute('ALTER TABLE promotions ADD COLUMN description TEXT')
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    try:
        conn.execute('ALTER TABLE promotions ADD COLUMN promo_type TEXT DEFAULT "discount"')
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    try:
        conn.execute('ALTER TABLE orders ADD COLUMN customer_name TEXT')
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Add demo promotions if they don't exist
    existing_promos = conn.execute('SELECT COUNT(*) FROM promotions').fetchone()[0]
    if existing_promos == 0:
        # 4x3 Sushi promotion
        conn.execute('''
        INSERT INTO promotions (name, type, value, min_purchase, applicable_items, active, description, promo_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', ('SUSHI4X3', 'buy_x_get_y', 3, 0, '["Sushi"]', 1, 'Compra 4 Sushi y paga solo 3', 'special'))
        
        # 2x1 Rice Ball promotion
        conn.execute('''
        INSERT INTO promotions (name, type, value, min_purchase, applicable_items, active, description, promo_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', ('RICEBALL2X1', 'buy_x_get_y', 1, 0, '["Bola de Arroz"]', 1, 'Compra 2 Bolas de Arroz y paga solo 1', 'special'))
    
    # Add default admin user if no users exist
    existing_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    if existing_users == 0:
        conn.execute('''
        INSERT INTO users (username, password, role)
        VALUES (?, ?, ?)
        ''', ('admin', 'admin123', 'admin'))
        
        conn.execute('''
        INSERT INTO users (username, password, role)
        VALUES (?, ?, ?)
        ''', ('user', 'user123', 'user'))
    
    conn.commit()
    conn.close()

# Login decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

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
        user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?', 
                          (username, password)).fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash(f'¡Bienvenido {username}!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Usuario o contraseña incorrectos', 'error')
    
    return render_template('login.html')

# Logout
@app.route('/logout')
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

# Home page
@app.route('/')
@login_required
def home():
    return render_template('index.html')

# Updated pricing structure
def get_item_price(item_type, style=None):
    """Get item price based on type and style"""
    base_prices = {
        'Agua': 10.0,
        'Coca Cola': 25.0,
        'Sprite': 25.0,
        'Pepsi': 25.0,
        'Fanta': 25.0,
        'Boneless': 105.0,
        'Bola de Arroz': 115.0,
        'Sushi': 115.0,  # Will be adjusted based on preparation
        'Complementos': 10.0  # Base price per sauce
    }
    
    price = base_prices.get(item_type, 0.0)
    
    # Adjust sushi price based on preparation
    if item_type == 'Sushi' and style:
        if 'Seco' in style or 'Salsas Aparte' in style:
            price = 110.0
        else:  # Preparado
            price = 115.0
    
    return price

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
            return render_template('beverages.html', item=None)
        
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
        return redirect(url_for('home'))  # CHANGED: Now redirects to home instead of cart
    
    return render_template('beverages.html', item=None)

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
            return render_template('boneless.html', item=None)
        
        # NEW PRICING: Base price includes up to 2 sauces (no extra charges)
        base_price = get_item_price('Boneless')
        total_price = base_price  # No extra sauce charges for included sauces
        
        # Create item dictionary
        item = {
            'name': 'Boneless',
            'type': 'Boneless',
            'price': total_price,
            'unit_price': total_price,
            'quantity': 1,
            'sauces': sauces,  # Changed to plural to store list
            'accompaniment': accompaniment,
            'notes': notes
            # REMOVED: 'extra_sauce_cost': extra_sauce_price
        }
        
        session['cart'].append(item)
        session.modified = True
        flash('¡Boneless agregado a la orden!', 'success')
        return redirect(url_for('home'))  # CHANGED: Now redirects to home instead of cart
    
    return render_template('boneless.html', item=None)

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
            return render_template('complementos.html', item=None)
        
        # Calculate price - $10 per sauce
        sauce_count = len(sauces)
        total_price = sauce_count * 10.0
        
        # Create item dictionary
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
        return redirect(url_for('home'))  # CHANGED: Now redirects to home instead of cart
    
    return render_template('complementos.html', item=None)

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
            return render_template('rice_ball.html', item=None)
            
        # Validate minimum ingredients (at least 1)
        if len(regular_ingredients) < 1:
            flash('Selecciona al menos 1 ingrediente', 'error')
            return render_template('rice_ball.html', item=None)
            
        # Validate Ostión can only be added as 7th ingredient when you have 6 regular ingredients
        if len(ostion_ingredients) > 0 and len(regular_ingredients) < 6:
            flash('Ostión solo puede agregarse cuando tienes 6 ingredientes regulares', 'error')
            return render_template('rice_ball.html', item=None)
            
        # Only allow one Ostión
        if len(ostion_ingredients) > 1:
            flash('Solo puedes agregar un Ostión', 'error')
            return render_template('rice_ball.html', item=None)
        
        # Calculate price - base price + ostión charges
        base_price = get_item_price('Bola de Arroz')
        ostion_count = len(ostion_ingredients)
        ostion_price = ostion_count * 10.0  # $10 per ostión
        total_price = base_price + ostion_price
        
        # Create item dictionary
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
        return redirect(url_for('home'))  # CHANGED: Now redirects to home instead of cart
    
    return render_template('rice_ball.html', item=None)

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
            return render_template('sushi.html', item=None)
            
        if not prepared:
            flash('Por favor selecciona una opción de preparado.', 'error')
            return render_template('sushi.html', item=None)
        
        # Enhanced ingredient validation with Ostión exception
        regular_ingredients = [ing for ing in ingredients if ing != 'Ostión']
        ostion_ingredients = [ing for ing in ingredients if ing == 'Ostión']
        
        # Validate regular ingredients (max 3)
        if len(regular_ingredients) > 3:
            flash('Máximo 3 ingredientes regulares permitidos', 'error')
            return render_template('sushi.html', item=None)
            
        # Validate minimum ingredients (at least 1)
        if len(regular_ingredients) < 1:
            flash('Selecciona al menos 1 ingrediente', 'error')
            return render_template('sushi.html', item=None)
            
        # Validate Ostión can only be added as 4th ingredient when you have 3 regular ingredients
        if len(ostion_ingredients) > 0 and len(regular_ingredients) < 3:
            flash('Ostión solo puede agregarse cuando tienes 3 ingredientes regulares', 'error')
            return render_template('sushi.html', item=None)
            
        # Only allow one Ostión
        if len(ostion_ingredients) > 1:
            flash('Solo puedes agregar un Ostión', 'error')
            return render_template('sushi.html', item=None)
        
        # Calculate price - base price based on preparation + ostión charges
        base_price = get_item_price('Sushi', prepared)
        ostion_count = len(ostion_ingredients)
        ostion_price = ostion_count * 10.0  # $10 per ostión
        total_price = base_price + ostion_price
        
        # Create item dictionary
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
        return redirect(url_for('home'))  # CHANGED: Now redirects to home instead of cart
    
    return render_template('sushi.html', item=None)

# View Cart - UNCHANGED (still goes to cart when explicitly requested)
@app.route('/cart')
@login_required
def view_cart():
    cart = session.get('cart', [])
    
    # Get active promotions with debugging
    conn = get_db_connection()
    try:
        promotions = conn.execute('SELECT * FROM promotions WHERE active = 1').fetchall()
        print(f"DEBUG: Found {len(promotions)} promotions in database")
        for promo in promotions:
            print(f"DEBUG: Promotion - {promo['name']}: {promo['description'] if 'description' in promo.keys() else 'No description'}")
    except Exception as e:
        print(f"DEBUG: Error fetching promotions: {e}")
        promotions = []
    finally:
        conn.close()
    
    # Calculate total price correctly
    total_price = 0
    for item in cart:
        # Ensure quantity is available
        quantity = item.get('quantity', 1)
        # Calculate unit price if not already stored
        if 'unit_price' not in item:
            item['unit_price'] = item['price'] / quantity
        
        # Add this item's total price to the sum
        total_price += item['price']
    
    print(f"DEBUG: Passing {len(promotions)} promotions to template")
    return render_template('cart.html', cart=cart, total_price=total_price, promotions=promotions)

# Update Item Quantity
@app.route('/update_quantity/<int:item_index>/<int:quantity>', methods=['POST'])
@login_required
def update_quantity(item_index, quantity):
    if quantity < 1:
        quantity = 1
    
    cart = session.get('cart', [])
    if item_index < len(cart):
        # Get current quantity and price
        current_quantity = cart[item_index].get('quantity', 1)
        current_price = cart[item_index]['price']
        
        # Calculate unit price if not already present
        if 'unit_price' not in cart[item_index]:
            cart[item_index]['unit_price'] = current_price / current_quantity
        
        # Get unit price
        unit_price = cart[item_index]['unit_price']
        
        # Update quantity
        cart[item_index]['quantity'] = quantity
        
        # Update item price based on quantity and unit price
        cart[item_index]['price'] = unit_price * quantity
        
        # Store updated cart back to session
        session['cart'] = cart
        session.modified = True
    
    return jsonify({'success': True})

# Updated update_item function to handle all item types including Complementos
@app.route('/update_item/<int:item_index>', methods=['GET', 'POST'])
@login_required
def update_item(item_index):
    cart = session.get('cart', [])
    
    if item_index >= len(cart):
        flash('Item not found', 'error')
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
            
            # Recalculate price - $10 per sauce
            sauce_count = len(sauces)
            total_price = sauce_count * 10.0
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
                return render_template('rice_ball.html', item=item, item_index=item_index)
                
            # Validate minimum ingredients (at least 1)
            if len(regular_ingredients) < 1:
                flash('Selecciona al menos 1 ingrediente', 'error')
                return render_template('rice_ball.html', item=item, item_index=item_index)
                
            # Validate Ostión rules
            if len(ostion_ingredients) > 0 and len(regular_ingredients) < 6:
                flash('Ostión solo puede agregarse cuando tienes 6 ingredientes regulares', 'error')
                return render_template('rice_ball.html', item=item, item_index=item_index)
                
            if len(ostion_ingredients) > 1:
                flash('Solo puedes agregar un Ostión', 'error')
                return render_template('rice_ball.html', item=item, item_index=item_index)
            
            item['base'] = request.form.getlist('base')
            item['ingredients'] = ingredients
            item['style'] = request.form.get('style')
            item['sauce'] = request.form.get('sauce')
            item['toppings'] = request.form.getlist('toppings')
            item['notes'] = request.form.get('notes', '')
            
            # Recalculate price with ostión charges
            base_price = get_item_price('Bola de Arroz')
            ostion_count = len(ostion_ingredients)
            ostion_price = ostion_count * 10.0
            total_price = base_price + ostion_price
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
                return render_template('sushi.html', item=item, item_index=item_index)
                
            # Validate minimum ingredients (at least 1)
            if len(regular_ingredients) < 1:
                flash('Selecciona al menos 1 ingrediente', 'error')
                return render_template('sushi.html', item=item, item_index=item_index)
                
            # Validate Ostión rules
            if len(ostion_ingredients) > 0 and len(regular_ingredients) < 3:
                flash('Ostión solo puede agregarse cuando tienes 3 ingredientes regulares', 'error')
                return render_template('sushi.html', item=item, item_index=item_index)
                
            if len(ostion_ingredients) > 1:
                flash('Solo puedes agregar un Ostión', 'error')
                return render_template('sushi.html', item=item, item_index=item_index)
            
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
            
            # Recalculate price with dynamic pricing and ostión charges
            base_price = get_item_price('Sushi', prepared)
            ostion_count = len(ostion_ingredients)
            ostion_price = ostion_count * 10.0
            total_price = base_price + ostion_price
            item['unit_price'] = total_price
            item['price'] = total_price * item.get('quantity', 1)
            item['ostion_cost'] = ostion_price
        
        cart[item_index] = item
        session['cart'] = cart
        session.modified = True
        flash('Item actualizado con éxito', 'success')
        return redirect(url_for('view_cart'))  # Updates still go back to cart for review
    
    # GET request - show form to edit
    if item['type'] == 'Bebida':
        return render_template('beverages.html', item=item, item_index=item_index)
    elif item['type'] == 'Boneless':
        return render_template('boneless.html', item=item, item_index=item_index)
    elif item['type'] == 'Complementos':
        return render_template('complementos.html', item=item, item_index=item_index)
    elif item['type'] == 'Bola de Arroz':
        return render_template('rice_ball.html', item=item, item_index=item_index)
    elif item['type'] == 'Sushi':
        return render_template('sushi.html', item=item, item_index=item_index)

# Remove Item
@app.route('/remove_item/<int:item_index>')
@login_required
def remove_item(item_index):
    cart = session.get('cart', [])
    
    if item_index < len(cart):
        cart.pop(item_index)
        session['cart'] = cart
        session.modified = True
        flash('Item eliminado de la orden', 'success')
    
    return redirect(url_for('view_cart'))

# Apply Coupon
@app.route('/apply_coupon', methods=['POST'])
@login_required
def apply_coupon():
    coupon_code = request.form.get('coupon_code', '').strip().upper()
    
    print(f"DEBUG: Received coupon code: '{coupon_code}'")
    
    if not coupon_code:
        flash('Por favor ingresa un código de promoción', 'error')
        return redirect(url_for('view_cart'))
    
    # Connect to database
    conn = get_db_connection()
    promo = conn.execute('SELECT * FROM promotions WHERE name = ? AND active = 1', (coupon_code,)).fetchone()
    conn.close()
    
    if not promo:
        print(f"DEBUG: Promotion '{coupon_code}' not found in database")
        flash('Código de promoción inválido o expirado', 'error')
        return redirect(url_for('view_cart'))
    
    print(f"DEBUG: Found promotion: {promo['name']} - {promo['description']}")
    
    # Apply promotion
    cart = session.get('cart', [])
    
    print(f"DEBUG: Current cart has {len(cart)} items")
    for i, item in enumerate(cart):
        print(f"DEBUG: Item {i}: {item['name']} ({item['type']}) - Qty: {item.get('quantity', 1)} - Price: ${item['price']}")
    
    # Calculate total price before discount
    total_price = 0
    for item in cart:
        quantity = item.get('quantity', 1)
        if 'unit_price' not in item:
            item['unit_price'] = item['price'] / quantity
        total_price += item['price']
    
    print(f"DEBUG: Total price before promotion: ${total_price}")
    
    # Check minimum purchase requirement
    if promo['min_purchase'] > 0 and total_price < promo['min_purchase']:
        flash(f'Se requiere una compra mínima de ${promo["min_purchase"]} para aplicar esta promoción', 'error')
        return redirect(url_for('view_cart'))
    
    # Apply discount based on promotion type
    if promo['promo_type'] == 'special':
        print(f"DEBUG: Applying special promotion: {promo['name']}")
        
        # Handle special promotions (4x3, 2x1, etc.)
        success = False
        if promo['name'] == 'SUSHI4X3':
            success = apply_4x3_promotion(cart, 'Sushi')
        elif promo['name'] == 'RICEBALL2X1':
            success = apply_2x1_promotion(cart, 'Bola de Arroz')
        
        if not success:
            if promo['name'] == 'SUSHI4X3':
                flash('Necesitas al menos 4 Sushi para aplicar esta promoción', 'error')
            elif promo['name'] == 'RICEBALL2X1':
                flash('Necesitas al menos 2 Bolas de Arroz para aplicar esta promoción', 'error')
            return redirect(url_for('view_cart'))
    else:
        print(f"DEBUG: Applying regular promotion")
        # Handle regular percentage/fixed discounts
        applicable_items = json.loads(promo['applicable_items']) if promo['applicable_items'] else []
        
        for item in cart:
            if not applicable_items or item['type'] in applicable_items:
                # Store original price before discount
                if 'original_price' not in item:
                    item['original_price'] = item['price']
                
                # Apply discount
                if promo['type'] == 'percentage':
                    item['price'] = item['original_price'] * (1 - promo['value'] / 100)
                    item['discount'] = f"{promo['value']}% off"
                else:  # fixed amount
                    item['price'] = max(0, item['original_price'] - promo['value'])
                    item['discount'] = f"${promo['value']} off"
    
    # Calculate total price after discount
    total_price_after = sum(item['price'] for item in cart)
    print(f"DEBUG: Total price after promotion: ${total_price_after}")
    
    # Save updated cart
    session['cart'] = cart
    session.modified = True
    
    print(f"DEBUG: Cart after promotion:")
    for i, item in enumerate(cart):
        discount_text = f" (Discount: {item.get('discount', 'None')})" if 'discount' in item else ""
        print(f"DEBUG: Item {i}: {item['name']} - Price: ${item['price']}{discount_text}")
    
    flash(f'Promoción "{promo["description"]}" aplicada con éxito', 'success')
    return redirect(url_for('view_cart'))

def apply_4x3_promotion(cart, item_type):
    """Apply 4x3 promotion: Buy 4, pay for 3"""
    matching_items = []
    
    # Count total quantity of matching items across all cart entries
    total_quantity = 0
    for item in cart:
        if item['type'] == item_type:
            quantity = item.get('quantity', 1)
            total_quantity += quantity
            for _ in range(quantity):
                matching_items.append(item)
    
    print(f"DEBUG: Found {total_quantity} {item_type} items (need 4 for promotion)")
    
    if total_quantity >= 4:
        # Find the cheapest item to make free
        cheapest_item = None
        cheapest_price = float('inf')
        
        for item in cart:
            if item['type'] == item_type:
                unit_price = item.get('unit_price', item['price'] / item.get('quantity', 1))
                if unit_price < cheapest_price:
                    cheapest_price = unit_price
                    cheapest_item = item
        
        if cheapest_item:
            # Store original price if not already stored
            if 'original_price' not in cheapest_item:
                cheapest_item['original_price'] = cheapest_item['price']
            
            # Make one unit free
            unit_price = cheapest_item.get('unit_price', cheapest_item['price'] / cheapest_item.get('quantity', 1))
            cheapest_item['price'] = max(0, cheapest_item['price'] - unit_price)
            cheapest_item['discount'] = "4x3 - ¡1 GRATIS!"
            
            print(f"DEBUG: Applied 4x3 discount to {cheapest_item['name']}, reduced price by ${unit_price}")
            return True
    
    return False

def apply_2x1_promotion(cart, item_type):
    """Apply 2x1 promotion: Buy 2, pay for 1"""
    matching_items = []
    
    # Count total quantity of matching items across all cart entries
    total_quantity = 0
    for item in cart:
        if item['type'] == item_type:
            quantity = item.get('quantity', 1)
            total_quantity += quantity
            for _ in range(quantity):
                matching_items.append(item)
    
    print(f"DEBUG: Found {total_quantity} {item_type} items (need 2 for promotion)")
    
    if total_quantity >= 2:
        # Find the cheapest item to make free
        cheapest_item = None
        cheapest_price = float('inf')
        
        for item in cart:
            if item['type'] == item_type:
                unit_price = item.get('unit_price', item['price'] / item.get('quantity', 1))
                if unit_price < cheapest_price:
                    cheapest_price = unit_price
                    cheapest_item = item
        
        if cheapest_item:
            # Store original price if not already stored
            if 'original_price' not in cheapest_item:
                cheapest_item['original_price'] = cheapest_item['price']
            
            # Make one unit free
            unit_price = cheapest_item.get('unit_price', cheapest_item['price'] / cheapest_item.get('quantity', 1))
            cheapest_item['price'] = max(0, cheapest_item['price'] - unit_price)
            cheapest_item['discount'] = "2x1 - ¡1 GRATIS!"
            
            print(f"DEBUG: Applied 2x1 discount to {cheapest_item['name']}, reduced price by ${unit_price}")
            return True
    
    return False

# Payment selection page
@app.route('/payment')
@login_required
def payment():
    cart = session.get('cart', [])
    
    # Calculate total price correctly
    total_price = 0
    for item in cart:
        total_price += item['price']
    
    return render_template('payment.html', total_price=total_price)

# Cash payment page
@app.route('/cash_payment')
@login_required
def cash_payment():
    cart = session.get('cart', [])
    
    # Calculate total price correctly
    total_price = 0
    for item in cart:
        total_price += item['price']
    
    return render_template('cash_payment.html', total_price=total_price)

@app.route('/ticket', methods=['GET', 'POST'])
@login_required
def ticket():
    cart = session.get('cart', [])
    
    # Calculate total price correctly
    total_price = 0
    for item in cart:
        total_price += item['price']
    
    # Get payment details from form or query parameters
    payment_method = request.form.get('payment_method', request.args.get('payment_method', 'card'))
    amount_paid = float(request.form.get('amount_paid', request.args.get('amount_paid', total_price)))
    change = amount_paid - total_price if payment_method == 'cash' else 0
    
    # Order ID for this transaction
    order_id = session.get('order_id')
    
    # Get customer name from session
    customer_name = session.get('customer_name', 'Cliente')
    
    # Save order to database with proper error handling
    conn = None
    try:
        conn = get_db_connection()
        conn.execute(
            'INSERT INTO orders (id, items, total, payment_method, amount_paid, change_amount, date, status, customer_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                order_id,
                json.dumps(cart),
                total_price,
                payment_method,
                amount_paid,
                change,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'completed',
                customer_name
            )
        )
        conn.commit()
        
        # Print receipt using physical printer
        print_success = False
        try:
            # Create receipt and try to print
            receipt_path = print_receipt_physical(cart, total_price, payment_method, amount_paid, change, order_id, customer_name)
            print_success = True
            print(f"Receipt created and printed: {receipt_path}")
            
        except Exception as e:
            error_message = f"Error al imprimir ticket: {str(e)}"
            flash(error_message, "warning")
            print(error_message)
        
        # Clear cart, customer name, and generate new order ID for the next order
        session['cart'] = []
        session['order_id'] = str(uuid.uuid4())[:8]
        session['customer_name'] = ''  # Clear customer name for next order
        session.modified = True
        
        return render_template('thank_you.html', order_id=order_id, print_success=print_success)
        
    except sqlite3.Error as e:
        # Database error handling
        error_message = f"Error al guardar la orden: {str(e)}"
        flash(error_message, "error")
        print(error_message)
        if conn:
            conn.rollback()
        return redirect(url_for('view_cart'))
    finally:
        if conn:
            conn.close()

def print_receipt_physical(cart, total, payment_method, amount_paid=0, change=0, order_id=None, customer_name=None):
    """Print receipt using physical printer connected to laptop - UPDATED WITH COMPLEMENTOS"""
    
    # Generate receipt content
    receipt_content = []
    receipt_content.append("=" * 40)
    receipt_content.append("       RESTAURANTE NOMBRE       ")
    receipt_content.append("=" * 40)
    receipt_content.append(f"Orden #: {order_id or session.get('order_id')}")
    receipt_content.append(f"Cliente: {customer_name or 'Cliente'}")
    receipt_content.append(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    receipt_content.append("-" * 40)
    
    # Items
    receipt_content.append("ARTICULO                PRECIO")
    receipt_content.append("-" * 40)
    
    for item in cart:
        quantity = item.get('quantity', 1)
        receipt_content.append(f"{item['name']} x{quantity:<2}      ${item['price']:.2f}")
        
        # Add item details based on type
        if item['type'] == 'Bebida':
            if 'beverage_type' in item and item['beverage_type']:
                receipt_content.append(f"  Bebida: {item['beverage_type']}")
        
        elif item['type'] == 'Boneless':
            if 'sauces' in item and item['sauces']:
                sauces_text = ', '.join(item['sauces'])
                receipt_content.append(f"  Salsas: {sauces_text}")
                # REMOVED: Extra sauce cost display
            elif 'sauce' in item and item['sauce']:
                receipt_content.append(f"  Salsa: {item['sauce']}")
            if 'accompaniment' in item and item['accompaniment']:
                receipt_content.append(f"  Acompañante: {item['accompaniment']}")
        
        elif item['type'] == 'Complementos':
            if 'sauces' in item and item['sauces']:
                sauces_text = ', '.join(item['sauces'])
                receipt_content.append(f"  Salsas: {sauces_text}")
                sauce_count = len(item['sauces'])
                receipt_content.append(f"  Cantidad: {sauce_count} x $10 = ${sauce_count * 10:.2f}")
        
        elif item['type'] in ['Bola de Arroz', 'Sushi']:
            # Base
            if 'base' in item:
                base_text = ', '.join(item['base']) if item['base'] else "Ninguna"
                receipt_content.append(f"  Base: {base_text}")
            
            # Ingredients
            if 'ingredients' in item:
                ing_text = ', '.join(item['ingredients']) if item['ingredients'] else "Ninguno" 
                receipt_content.append(f"  Ing: {ing_text}")
                if item.get('ostion_cost', 0) > 0:
                    receipt_content.append(f"  Ostión: +${item['ostion_cost']:.2f}")
            
            # Style
            if 'style' in item and item['style']:
                receipt_content.append(f"  Estilo: {item['style']}")
            
            # Sauce
            if 'sauce' in item and item['sauce']:
                receipt_content.append(f"  Salsa: {item['sauce']}")
            
            # Prepared (sushi only)
            if 'prepared' in item and item['prepared']:
                receipt_content.append(f"  Prep: {item['prepared']}")
            
            # Toppings
            if 'toppings' in item:
                topping_text = ', '.join(item['toppings']) if item['toppings'] else "Ninguno"
                receipt_content.append(f"  Toppings: {topping_text}")
        
        # Notes for any item type
        if 'notes' in item and item['notes']:
            receipt_content.append(f"  Notas: {item['notes']}")
            
        receipt_content.append("-" * 40)
    
    # Total
    receipt_content.append(f"TOTAL: ${total:.2f}")
    receipt_content.append("")
    
    # Payment details
    receipt_content.append(f"Método de pago: {payment_method.upper()}")
    
    if payment_method == 'cash':
        receipt_content.append(f"Monto recibido: ${amount_paid:.2f}")
        receipt_content.append(f"Cambio: ${change:.2f}")
    
    # Footer
    receipt_content.append("")
    receipt_content.append("¡Gracias por su compra!")
    receipt_content.append("Vuelva pronto")
    
    # Save receipt to file
    receipt_id = order_id or session.get('order_id')
    receipts_dir = os.path.join(os.getcwd(), 'receipts')
    os.makedirs(receipts_dir, exist_ok=True)
    receipt_path = os.path.join(receipts_dir, f"receipt_{receipt_id}.txt")
    
    # Write receipt to file
    with open(receipt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(receipt_content))
    
    # Try to print using system's default printer
    try:
        if platform.system() == "Windows":
            # Windows printing
            subprocess.run(["notepad", "/p", receipt_path], check=True)
        elif platform.system() == "Darwin":  # macOS
            # macOS printing
            subprocess.run(["lpr", receipt_path], check=True)
        elif platform.system() == "Linux":
            # Linux printing
            subprocess.run(["lpr", receipt_path], check=True)
        else:
            print(f"Unsupported operating system for automatic printing: {platform.system()}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to print receipt: {e}")
        # Continue execution even if printing fails
    except FileNotFoundError:
        print("Print command not found. Receipt saved but not printed.")
    
    return receipt_path

if __name__ == '__main__':
    init_db()
    # GoDaddy compatible configuration
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001)), debug=False)