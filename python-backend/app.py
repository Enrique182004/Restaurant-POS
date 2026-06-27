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
from functools import wraps

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

# ── Base de datos ──────────────────────────────────────────────────────────────

class _GConnection:
    """
    Envuelve una conexión SQLite almacenada en Flask g.
    conn.close() es no-op: teardown_appcontext cierra la conexión real al
    final de cada request, garantizando que nunca quede abierta aunque
    una ruta lance una excepción.
    """
    def __init__(self, conn):
        self.__dict__['_conn'] = conn

    def __getattr__(self, name):
        return getattr(self.__dict__['_conn'], name)

    def close(self):
        pass  # teardown_appcontext maneja el cierre


def get_db_connection():
    """
    Dentro de un request: devuelve la conexión cacheada en g (o la crea).
    Fuera de request (ej: init_db al arrancar): devuelve una conexión directa.
    """
    try:
        if 'db' not in g:
            conn = sqlite3.connect(_DB_PATH)
            conn.row_factory = sqlite3.Row
            g.db = _GConnection(conn)
            g._raw_db = conn
        return g.db
    except RuntimeError:
        # Fuera de contexto de aplicación (inicio de servidor, tests sin contexto)
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn


@app.teardown_appcontext
def _cerrar_db(error):
    """Cierra la conexión real al final de cada request, sin importar si hubo error."""
    raw = g.pop('_raw_db', None)
    g.pop('db', None)
    if raw is not None:
        try:
            raw.close()
        except Exception:
            pass

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
    
    # Menu prices — editable by admin
    conn.execute('''
    CREATE TABLE IF NOT EXISTS menu_prices (
        key TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        price REAL NOT NULL
    )
    ''')

    default_prices = [
        ('Agua',            'Agua',                  10.0),
        ('Coca Cola',       'Coca Cola',             25.0),
        ('Sprite',          'Sprite',                25.0),
        ('Pepsi',           'Pepsi',                 25.0),
        ('Fanta',           'Fanta',                 25.0),
        ('Boneless',        'Boneless',             105.0),
        ('Bola de Arroz',   'Bola de Arroz',        115.0),
        ('Sushi Preparado', 'Sushi (Preparado)',    115.0),
        ('Sushi Seco',      'Sushi (Seco / Aparte)',110.0),
        ('Complementos',    'Complementos (x salsa)',10.0),
        ('Ostión',          'Ostión (extra)',        10.0),
    ]
    for key, label, price in default_prices:
        conn.execute(
            'INSERT OR IGNORE INTO menu_prices (key, label, price) VALUES (?, ?, ?)',
            (key, label, price)
        )

    # Persistent print job queue (survives server restarts)
    conn.execute('''
    CREATE TABLE IF NOT EXISTS print_jobs (
        id TEXT PRIMARY KEY,
        receipt_content TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Tabla de inventario compartida con el servicio Java
    # (Java usa Hibernate que falla en INSERT con getGeneratedKeys en SQLite;
    #  Flask inserta directamente, Java solo lee y actualiza)
    conn.execute('''
    CREATE TABLE IF NOT EXISTS inventory (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL UNIQUE,
        quantity   INTEGER NOT NULL DEFAULT 0,
        min_threshold INTEGER NOT NULL DEFAULT 0,
        unit       TEXT DEFAULT 'piezas'
    )
    ''')

    # Configuración general de la app (clave → valor)
    conn.execute('''
    CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    ''')
    conn.execute(
        "INSERT OR IGNORE INTO config (key, value) VALUES ('printer_name', 'Printer_POS_80')"
    )

    # Menu options — admin-manageable lists per category
    conn.execute('''
    CREATE TABLE IF NOT EXISTS menu_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        name TEXT NOT NULL,
        icon TEXT DEFAULT '🍽️',
        price REAL DEFAULT 0,
        sort_order INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1
    )
    ''')

    # Migration: add description column to promotions if missing
    try:
        conn.execute('ALTER TABLE promotions ADD COLUMN description TEXT DEFAULT ""')
        conn.commit()
    except Exception:
        pass  # Column already exists

    # Migration: add get_free column for NxM promotions
    try:
        conn.execute('ALTER TABLE promotions ADD COLUMN get_free INTEGER DEFAULT 1')
        conn.commit()
    except Exception:
        pass  # Column already exists

    existing_options = conn.execute('SELECT COUNT(*) FROM menu_options').fetchone()[0]
    if existing_options == 0:
        options_seed = [
            # Beverages (category, name, icon, price, sort)
            ('beverage', 'Agua',               '💧', 10, 1),
            ('beverage', 'Coca Cola',           '🥤', 25, 2),
            ('beverage', 'Sprite',              '🍋', 25, 3),
            ('beverage', 'Pepsi',               '🥤', 25, 4),
            ('beverage', 'Fanta',               '🍊', 25, 5),
            # Boneless sauces
            ('boneless_sauce', 'Naturales',              '🍗', 0, 1),
            ('boneless_sauce', 'Salsa Mango Habanero',   '🥭', 0, 2),
            ('boneless_sauce', 'Salsa Búfalo',           '🦬', 0, 3),
            ('boneless_sauce', 'Salsa BBQ',              '🍖', 0, 4),
            ('boneless_sauce', 'Salsa Agridulce',        '🍯', 0, 5),
            # Extra sauces (Complementos)
            ('extra_sauce', 'Anguila',        '🐍', 10, 1),
            ('extra_sauce', 'Soya',           '🟤', 10, 2),
            ('extra_sauce', 'Sriracha',       '🌶️', 10, 3),
            ('extra_sauce', 'Mango Habanero', '🥭', 10, 4),
            ('extra_sauce', 'Búfalo',         '🦬', 10, 5),
            ('extra_sauce', 'BBQ',            '🍖', 10, 6),
            ('extra_sauce', 'Agridulce',      '🍯', 10, 7),
            # Rice ball ingredients
            ('rice_ingredient', 'Camarón',   '🦐', 0, 1),
            ('rice_ingredient', 'Arrachera', '🥩', 0, 2),
            ('rice_ingredient', 'Surimi',    '🦀', 0, 3),
            ('rice_ingredient', 'Pastor',    '🌮', 0, 4),
            ('rice_ingredient', 'Pollo',     '🍗', 0, 5),
            ('rice_ingredient', 'Tocino',    '🥓', 0, 6),
            ('rice_ingredient', 'Jalapeño',  '🌶️', 0, 7),
            ('rice_ingredient', 'Pepino',    '🥒', 0, 8),
            # Rice ball sauces
            ('rice_sauce', 'Tradicional', '🔴', 0, 1),
            ('rice_sauce', 'Flamin Hot',  '🔥', 0, 2),
            ('rice_sauce', 'Puff',        '💨', 0, 3),
            ('rice_sauce', 'Nacha',       '🌮', 0, 4),
            ('rice_sauce', 'Búfalo',      '🦬', 0, 5),
            ('rice_sauce', 'Barbecue',    '🍖', 0, 6),
            ('rice_sauce', 'Agridulce',   '🍯', 0, 7),
            ('rice_sauce', 'Frutal',      '🍎', 0, 8),
            ('rice_sauce', 'Seca',        '🌾', 0, 9),
            # Sushi ingredients
            ('sushi_ingredient', 'Camarón',  '🦐', 0, 1),
            ('sushi_ingredient', 'Sirloin',  '🥩', 0, 2),
            ('sushi_ingredient', 'Surimi',   '🦀', 0, 3),
            ('sushi_ingredient', 'Pastor',   '🌮', 0, 4),
            ('sushi_ingredient', 'Pollo',    '🍗', 0, 5),
            ('sushi_ingredient', 'Tocino',   '🥓', 0, 6),
            ('sushi_ingredient', 'Jalapeño', '🌶️', 0, 7),
            ('sushi_ingredient', 'Pepino',   '🥒', 0, 8),
        ]
        for cat, name, icon, price, sort in options_seed:
            conn.execute(
                'INSERT INTO menu_options (category, name, icon, price, sort_order) VALUES (?, ?, ?, ?, ?)',
                (cat, name, icon, price, sort)
            )

    # Add new columns if they don't exist        
    try:
        conn.execute('ALTER TABLE orders ADD COLUMN customer_name TEXT')
    except sqlite3.OperationalError:
        pass  # Column already exists

    try:
        conn.execute('ALTER TABLE users ADD COLUMN password_changed INTEGER DEFAULT 0')
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Migrar tipo legacy 'buy_x_get_y' a 'bxgy' (unificar con el tipo que crea el admin)
    try:
        conn.execute("UPDATE promotions SET type = 'bxgy' WHERE type = 'buy_x_get_y'")
        conn.commit()
    except Exception:
        pass

    # Add demo promotions if they don't exist
    existing_promos = conn.execute('SELECT COUNT(*) FROM promotions').fetchone()[0]
    if existing_promos == 0:
        conn.execute(
            'INSERT INTO promotions (name, type, value, min_purchase, applicable_items, active, description) VALUES (?, ?, ?, ?, ?, ?, ?)',
            ('SUSHI4X3', 'bxgy', 3, 0, '["Sushi"]', 1, 'Compra 4 Sushi y paga solo 3')
        )
        conn.execute(
            'INSERT INTO promotions (name, type, value, min_purchase, applicable_items, active, description) VALUES (?, ?, ?, ?, ?, ?, ?)',
            ('RICEBALL2X1', 'bxgy', 1, 0, '["Bola de Arroz"]', 1, 'Compra 2 Bolas de Arroz y paga solo 1')
        )
    
    # Add default admin user if no users exist
    existing_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    if existing_users == 0:
        conn.execute(
            'INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
            ('admin', generate_password_hash('admin123'), 'admin')
        )
        conn.execute(
            'INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
            ('user', generate_password_hash('user123'), 'user')
        )

    # Migrate any existing plain-text passwords to hashed
    all_users = conn.execute('SELECT id, password FROM users').fetchall()
    for u in all_users:
        if not u['password'].startswith('pbkdf2:') and not u['password'].startswith('scrypt:'):
            conn.execute(
                'UPDATE users SET password = ? WHERE id = ?',
                (generate_password_hash(u['password']), u['id'])
            )

    # Empleados — roster, versioned pay schedules, and attendance
    conn.execute('''
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS employee_schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL REFERENCES employees(id),
        effective_from TEXT NOT NULL,
        scheduled_days TEXT NOT NULL,
        pay_amount REAL NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL REFERENCES employees(id),
        work_date TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(employee_id, work_date)
    )
    ''')

    conn.commit()
    conn.close()


# ── Empleados y asistencia: helpers ───────────────────────────────────────────

def get_week_bounds(reference_date):
    """reference_date: 'YYYY-MM-DD'. Returns (monday, sunday) as 'YYYY-MM-DD' strings
    for the Mon-Sun week containing reference_date."""
    d = datetime.strptime(reference_date, '%Y-%m-%d')
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime('%Y-%m-%d'), sunday.strftime('%Y-%m-%d')


def resolve_employee_schedule(conn, employee_id, week_start):
    """Returns the employee_schedules row in effect for the week starting on
    week_start ('YYYY-MM-DD', a Monday), or None if no version applies yet."""
    return conn.execute(
        '''SELECT * FROM employee_schedules
           WHERE employee_id = ? AND effective_from <= ?
           ORDER BY effective_from DESC, id DESC LIMIT 1''',
        (employee_id, week_start)
    ).fetchone()


def compute_employee_pay(conn, employee_id, week_start, week_end):
    """Returns (total_pay, per_day_rate, days_worked, scheduled_days) for one
    employee for the Mon-Sun week [week_start, week_end]. Any day marked
    present counts toward pay, not only the employee's scheduled days."""
    schedule = resolve_employee_schedule(conn, employee_id, week_start)
    if schedule is None:
        return 0.0, 0.0, 0, []

    scheduled_days = [int(x) for x in schedule['scheduled_days'].split(',') if x != '']
    per_day_rate = (schedule['pay_amount'] / len(scheduled_days)) if scheduled_days else 0.0

    days_worked = conn.execute(
        'SELECT COUNT(*) FROM attendance WHERE employee_id = ? AND work_date BETWEEN ? AND ?',
        (employee_id, week_start, week_end)
    ).fetchone()[0]

    total_pay = round(per_day_rate * days_worked, 2)
    return total_pay, per_day_rate, days_worked, scheduled_days


def parse_scheduled_days(form):
    """Reads the 'days' multi-value field from a submitted form and returns
    a sorted, deduped CSV string of valid weekday ints (0=Mon..6=Sun),
    or '' if nothing valid was selected."""
    raw = form.getlist('days')
    days = sorted({int(d) for d in raw if d.isascii() and d.isdigit() and 0 <= int(d) <= 6})
    return ','.join(str(d) for d in days)


# Login decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Then define admin_required (which uses login_required)
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session['role'] != 'admin':
            flash('Acceso denegado. Solo administradores.', 'error')
            return redirect(url_for('home'))
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
    prices = conn.execute('SELECT * FROM menu_prices ORDER BY label').fetchall()
    today = datetime.now().strftime('%Y-%m-%d')
    today_total = conn.execute(
        "SELECT COALESCE(SUM(total), 0) FROM orders WHERE date LIKE ? AND status != 'voided'",
        (today + '%',)
    ).fetchone()[0]
    today_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE date LIKE ? AND status != 'voided'",
        (today + '%',)
    ).fetchone()[0]
    # Promotions
    promotions = [dict(p) for p in conn.execute('SELECT * FROM promotions ORDER BY name').fetchall()]

    # Low-stock count from Java service (best-effort)
    low_stock_count = 0
    try:
        inv_resp = requests.get(f'{JAVA_INVENTORY_SERVICE}/api/inventory/low-stock', timeout=2)
        if inv_resp.status_code == 200:
            low_stock_count = len(inv_resp.json())
    except Exception:
        pass

    # Menu options grouped by category — include inactive so admin can re-enable them
    categories = ['beverage', 'boneless_sauce', 'extra_sauce', 'rice_ingredient', 'rice_sauce', 'sushi_ingredient']
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

    return render_template('admin_dashboard.html',
                           prices=prices,
                           today_total=today_total,
                           today_orders=today_orders,
                           menu_opts=menu_opts,
                           promotions=promotions,
                           low_stock_count=low_stock_count,
                           pending_prints=pending_prints,
                           printer_name=printer_name,
                           users_with_default=users_with_default)

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
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    existing = conn.execute(
        'SELECT id FROM menu_options WHERE category=? AND name=?', (category, name)
    ).fetchone()
    if existing:
        conn.execute('UPDATE menu_options SET active=1 WHERE id=?', (existing['id'],))
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
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/menu-options/delete/<int:option_id>', methods=['POST'])
@login_required
@admin_required
def delete_menu_option(option_id):
    conn = get_db_connection()
    option = conn.execute('SELECT * FROM menu_options WHERE id=?', (option_id,)).fetchone()
    if option:
        conn.execute('DELETE FROM menu_options WHERE id=?', (option_id,))
        conn.commit()
        flash(f'"{option["name"]}" eliminado del menú', 'success')
    return redirect(url_for('admin_dashboard'))

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
    return redirect(url_for('admin_dashboard'))

def get_item_price(item_type, style=None):
    """Get item price from the database (editable by admin)."""
    if item_type == 'Sushi' and style:
        key = 'Sushi Seco' if ('Seco' in style or 'Salsas Aparte' in style) else 'Sushi Preparado'
    else:
        key = item_type

    conn = get_db_connection()
    row = conn.execute('SELECT price FROM menu_prices WHERE key = ?', (key,)).fetchone()
    if row:
        return row['price']
    # Fallback: check menu_options (for newly-added beverages)
    row = conn.execute(
        "SELECT price FROM menu_options WHERE category='beverage' AND name=? AND active=1",
        (key,)
    ).fetchone()
    return row['price'] if row else 0.0

def get_sushi_prep_prices():
    """Return live prices for the three sushi preparation options."""
    conn = get_db_connection()
    def p(key):
        row = conn.execute('SELECT price FROM menu_prices WHERE key=?', (key,)).fetchone()
        return int(row['price']) if row else 0
    prices = {
        'Sushi Preparado':     p('Sushi Preparado'),
        'Sushi Seco':          p('Sushi Seco'),
        'Sushi Salsas Aparte': p('Sushi Seco'),   # same tier as Seco
    }
    return prices

def get_menu_options(category):
    """Return active menu options for a given category as a list of dicts."""
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT * FROM menu_options WHERE category=? AND active=1 ORDER BY sort_order, name',
        (category,)
    ).fetchall()
    return [dict(r) for r in rows]

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
                                   rice_sauces=get_menu_options('rice_sauce'))

        if len(regular_ingredients) < 1:
            flash('Selecciona al menos 1 ingrediente', 'error')
            return render_template('rice_ball.html', item=None,
                                   rice_ingredients=get_menu_options('rice_ingredient'),
                                   rice_sauces=get_menu_options('rice_sauce'))

        if len(ostion_ingredients) > 0 and len(regular_ingredients) < 6:
            flash('Ostión solo puede agregarse cuando tienes 6 ingredientes regulares', 'error')
            return render_template('rice_ball.html', item=None,
                                   rice_ingredients=get_menu_options('rice_ingredient'),
                                   rice_sauces=get_menu_options('rice_sauce'))

        if len(ostion_ingredients) > 1:
            flash('Solo puedes agregar un Ostión', 'error')
            return render_template('rice_ball.html', item=None,
                                   rice_ingredients=get_menu_options('rice_ingredient'),
                                   rice_sauces=get_menu_options('rice_sauce'))

        base_price = get_item_price('Bola de Arroz')
        ostion_count = len(ostion_ingredients)
        ostion_price = ostion_count * 10.0
        total_price = base_price + ostion_price

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
                           rice_sauces=get_menu_options('rice_sauce'))

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
            return render_template('sushi.html', item=None, sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_prep_prices=get_sushi_prep_prices())

        if not prepared:
            flash('Por favor selecciona una opción de preparado.', 'error')
            return render_template('sushi.html', item=None, sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_prep_prices=get_sushi_prep_prices())

        regular_ingredients = [ing for ing in ingredients if ing != 'Ostión']
        ostion_ingredients = [ing for ing in ingredients if ing == 'Ostión']

        if len(regular_ingredients) > 3:
            flash('Máximo 3 ingredientes regulares permitidos', 'error')
            return render_template('sushi.html', item=None, sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_prep_prices=get_sushi_prep_prices())

        if len(regular_ingredients) < 1:
            flash('Selecciona al menos 1 ingrediente', 'error')
            return render_template('sushi.html', item=None, sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_prep_prices=get_sushi_prep_prices())

        if len(ostion_ingredients) > 0 and len(regular_ingredients) < 3:
            flash('Ostión solo puede agregarse cuando tienes 3 ingredientes regulares', 'error')
            return render_template('sushi.html', item=None, sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_prep_prices=get_sushi_prep_prices())

        if len(ostion_ingredients) > 1:
            flash('Solo puedes agregar un Ostión', 'error')
            return render_template('sushi.html', item=None, sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_prep_prices=get_sushi_prep_prices())

        base_price = get_item_price('Sushi', prepared)
        ostion_count = len(ostion_ingredients)
        ostion_price = ostion_count * 10.0
        total_price = base_price + ostion_price

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

    return render_template('sushi.html', item=None, sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_prep_prices=get_sushi_prep_prices())

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
    return render_template('cart.html', cart=cart, total_price=total_price, promotions=promotions,
                           order_id=session.get('order_id', ''))

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
        
        cart[item_index]['quantity'] = quantity
        cart[item_index]['price'] = unit_price * quantity
        # Clear stale promotion data so the displayed price stays accurate
        cart[item_index].pop('original_price', None)
        cart[item_index].pop('discount', None)

        session['cart'] = cart
        session.modified = True

        new_total = sum(item['price'] for item in cart)
        return jsonify({
            'success': True,
            'new_item_price': cart[item_index]['price'],
            'new_total': new_total,
        })

    return jsonify({'success': True, 'new_item_price': 0, 'new_total': 0})

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
                                       rice_sauces=get_menu_options('rice_sauce'))

            if len(regular_ingredients) < 1:
                flash('Selecciona al menos 1 ingrediente', 'error')
                return render_template('rice_ball.html', item=item, item_index=item_index,
                                       rice_ingredients=get_menu_options('rice_ingredient'),
                                       rice_sauces=get_menu_options('rice_sauce'))

            if len(ostion_ingredients) > 0 and len(regular_ingredients) < 6:
                flash('Ostión solo puede agregarse cuando tienes 6 ingredientes regulares', 'error')
                return render_template('rice_ball.html', item=item, item_index=item_index,
                                       rice_ingredients=get_menu_options('rice_ingredient'),
                                       rice_sauces=get_menu_options('rice_sauce'))

            if len(ostion_ingredients) > 1:
                flash('Solo puedes agregar un Ostión', 'error')
                return render_template('rice_ball.html', item=item, item_index=item_index,
                                       rice_ingredients=get_menu_options('rice_ingredient'),
                                       rice_sauces=get_menu_options('rice_sauce'))
            
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
                return render_template('sushi.html', item=item, item_index=item_index,
                                       sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_prep_prices=get_sushi_prep_prices())

            if len(regular_ingredients) < 1:
                flash('Selecciona al menos 1 ingrediente', 'error')
                return render_template('sushi.html', item=item, item_index=item_index,
                                       sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_prep_prices=get_sushi_prep_prices())

            if len(ostion_ingredients) > 0 and len(regular_ingredients) < 3:
                flash('Ostión solo puede agregarse cuando tienes 3 ingredientes regulares', 'error')
                return render_template('sushi.html', item=item, item_index=item_index,
                                       sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_prep_prices=get_sushi_prep_prices())

            if len(ostion_ingredients) > 1:
                flash('Solo puedes agregar un Ostión', 'error')
                return render_template('sushi.html', item=item, item_index=item_index,
                                       sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_prep_prices=get_sushi_prep_prices())
            
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
                               rice_sauces=get_menu_options('rice_sauce'))
    elif item['type'] == 'Sushi':
        return render_template('sushi.html', item=item, item_index=item_index,
                               sushi_ingredients=get_menu_options('sushi_ingredient'), sushi_prep_prices=get_sushi_prep_prices())

# Remove Item
@app.route('/remove_item/<int:item_index>', methods=['POST'])
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
    
    if not coupon_code:
        flash('Por favor ingresa un código de promoción', 'error')
        return redirect(url_for('view_cart'))
    
    # Connect to database
    conn = get_db_connection()
    promo = conn.execute('SELECT * FROM promotions WHERE name = ? AND active = 1', (coupon_code,)).fetchone()
    
    if not promo:
        flash('Código de promoción inválido o expirado', 'error')
        return redirect(url_for('view_cart'))
    
    # Apply promotion
    cart = session.get('cart', [])

    total_price = 0
    for item in cart:
        quantity = item.get('quantity', 1)
        if 'unit_price' not in item:
            item['unit_price'] = item['price'] / quantity
        total_price += item['price']
    
    # Check minimum purchase requirement
    if promo['min_purchase'] > 0 and total_price < promo['min_purchase']:
        flash(f'Se requiere una compra mínima de ${promo["min_purchase"]} para aplicar esta promoción', 'error')
        return redirect(url_for('view_cart'))
    
    # Apply discount based on promotion type
    if promo['type'] == 'bxgy':
        # NxM promotion: buy `value` units, get `get_free` units free
        buy_qty = int(promo['value']) if promo['value'] else 2
        get_free = int(promo['get_free'] or 1)
        try:
            applicable_items = json.loads(promo['applicable_items']) if promo['applicable_items'] else []
        except (json.JSONDecodeError, TypeError):
            applicable_items = []

        success = apply_bxgy_promotion(cart, applicable_items, buy_qty, get_free)
        if not success:
            items_label = ', '.join(applicable_items) if applicable_items else 'productos'
            flash(f'Necesitas al menos {buy_qty + get_free} {items_label} para aplicar esta promoción', 'error')
            return redirect(url_for('view_cart'))
    else:
        # Handle regular percentage/fixed discounts
        try:
            applicable_items = json.loads(promo['applicable_items']) if promo['applicable_items'] else []
        except json.JSONDecodeError:
            applicable_items = []
        
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
    
    session['cart'] = cart
    session.modified = True
    flash(f'Promoción "{promo["description"]}" aplicada con éxito', 'success')
    return redirect(url_for('view_cart'))

def apply_bxgy_promotion(cart, applicable_items, buy_qty, get_free):
    """Generic NxM promotion: buy buy_qty, get get_free free (cheapest units discounted)."""
    # Count total matching units
    total_quantity = 0
    for item in cart:
        if not applicable_items or item['type'] in applicable_items:
            total_quantity += item.get('quantity', 1)

    required = buy_qty + get_free
    if total_quantity < required:
        return False

    # How many free units are earned across the full cart
    free_units = (total_quantity // required) * get_free

    # Sort matching cart entries by unit price ascending so cheapest are made free first
    matching = [i for i in cart if not applicable_items or i['type'] in applicable_items]
    matching.sort(key=lambda i: i.get('unit_price', i['price'] / max(i.get('quantity', 1), 1)))

    units_remaining = free_units
    for item in matching:
        if units_remaining <= 0:
            break
        unit_price = item.get('unit_price', item['price'] / max(item.get('quantity', 1), 1))
        qty = item.get('quantity', 1)
        units_to_free = min(units_remaining, qty)
        if 'original_price' not in item:
            item['original_price'] = item['price']
        item['price'] = max(0, item['price'] - unit_price * units_to_free)
        item['discount'] = f"{buy_qty + get_free}x{buy_qty} - ¡{units_to_free} GRATIS!"
        units_remaining -= units_to_free

    return True

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

    return render_template('payment.html', total_price=total_price)

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

    return render_template('cash_payment.html', total_price=total_price)

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
        
        # Save receipt file and queue print job
        receipt_file_success = False
        try:
            receipt_path, receipt_text = print_receipt_physical(cart, total_price, payment_method, amount_paid, change, order_id, customer_name)
            receipt_file_success = True
            # Store job in DB so the bridge can pick it up (survives restarts, works remotely)
            conn.execute(
                "INSERT OR IGNORE INTO print_jobs (id, receipt_content, status, created_at) VALUES (?, ?, 'pending', ?)",
                (order_id, receipt_text, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
            conn.commit()
        except Exception as e:
            print(f"Error saving receipt: {str(e)}")
        
        # Clear cart, customer name, and generate new order ID for the next order
        session['cart'] = []
        session['order_id'] = str(uuid.uuid4())[:8]
        session['customer_name'] = ''  # Clear customer name for next order
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

def print_receipt_physical(cart, total, payment_method, amount_paid=0, change=0, order_id=None, customer_name=None):
    """Print receipt using physical printer connected to laptop - UPDATED WITH COMPLEMENTOS"""
    
    # Generate receipt content
    receipt_content = []
    receipt_content.append("=" * 38)
    receipt_content.append(f"  {RESTAURANT_NAME.center(34)}")
    receipt_content.append("=" * 38)
    receipt_content.append(f"Orden #: {order_id or session.get('order_id')}")
    receipt_content.append(f"Cliente: {customer_name or 'Cliente'}")
    receipt_content.append(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
            
        receipt_content.append("-" * 38)
    
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
    
    receipt_text = "\n".join(receipt_content)

    # Write receipt to file as a local backup
    with open(receipt_path, "w", encoding="utf-8") as f:
        f.write(receipt_text)

    return receipt_path, receipt_text

@app.route('/inventory')
@login_required
@admin_required
def inventory_page():
    try:
        # Call Java inventory service
        response = requests.get(f'{JAVA_INVENTORY_SERVICE}/api/inventory', timeout=5)
        items = response.json() if response.status_code == 200 else []
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to inventory service: {e}")
        items = []
    
    return render_template('inventory.html', items=items)

@app.route('/inventory/low-stock')
@login_required
@admin_required
def low_stock():
    try:
        response = requests.get(f'{JAVA_INVENTORY_SERVICE}/api/inventory/low-stock', timeout=5)
        items = response.json() if response.status_code == 200 else []
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to inventory service: {e}")
        items = []
    
    return render_template('inventory.html', items=items, low_stock_only=True)

@app.route('/inventory/update/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def update_inventory_item(item_id):
    try:
        data = request.get_json()
        
        # Get current item first
        current_response = requests.get(
            f'{JAVA_INVENTORY_SERVICE}/api/inventory/{item_id}',
            timeout=5
        )
        
        if current_response.status_code != 200:
            return jsonify({'success': False, 'error': f'Producto no encontrado (código {current_response.status_code})'})

        current_item = current_response.json()
        current_item['quantity'] = data.get('quantity', current_item['quantity'])

        response = requests.put(
            f'{JAVA_INVENTORY_SERVICE}/api/inventory/{item_id}',
            json=current_item,
            timeout=5
        )
        if response.status_code == 200:
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': f'Error al guardar en Java (código {response.status_code})'})
    except requests.exceptions.RequestException as e:
        return jsonify({'success': False, 'error': f'Sin conexión al servicio de inventario: {e}'})
    
@app.route('/inventory/add', methods=['POST'])
@login_required
@admin_required
def add_inventory_item():
    """
    Inserta directamente en SQLite. El servicio Java usa getGeneratedKeys()
    después del INSERT, lo cual no está implementado en el driver SQLite JDBC,
    causando un 500. Flask + sqlite3 no tiene ese problema.
    """
    try:
        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        quantity = int(data.get('quantity', 0))
        min_threshold = int(data.get('minThreshold', 0))
        unit = (data.get('unit') or 'piezas').strip()

        if not name:
            return jsonify({'success': False, 'error': 'El nombre es requerido'})

        conn = get_db_connection()
        conn.execute(
            'INSERT INTO inventory (name, quantity, min_threshold, unit) VALUES (?, ?, ?, ?)',
            (name, quantity, min_threshold, unit)
        )
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        err = str(e)
        if 'UNIQUE' in err or 'unique' in err:
            return jsonify({'success': False, 'error': f'Ya existe un ingrediente con ese nombre'})
        return jsonify({'success': False, 'error': err})

@app.route('/inventory/delete/<int:item_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_inventory_item(item_id):
    try:
        response = requests.delete(
            f'{JAVA_INVENTORY_SERVICE}/api/inventory/{item_id}',
            timeout=5
        )
        return jsonify({'success': response.status_code == 200})
    except requests.exceptions.RequestException as e:
        return jsonify({'success': False, 'error': str(e)})
    
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
    flash('Precios actualizados correctamente.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/reports')
@login_required
@admin_required
def reports():
    period = request.args.get('period', 'today')
    now = datetime.now()

    if period == 'week':
        # Start of current week (Monday)
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        label = 'Esta semana'
    elif period == 'month':
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        label = 'Este mes'
    elif period == 'alltime':
        start = datetime(2000, 1, 1)
        label = 'Todo el tiempo'
    else:  # today
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = 'Hoy'

    start_str = start.strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db_connection()

    # Core summary
    row = conn.execute(
        "SELECT COUNT(*) as cnt, COALESCE(SUM(total),0) as rev FROM orders "
        "WHERE date >= ? AND status != 'voided'", (start_str,)
    ).fetchone()
    total_orders = row['cnt']
    total_revenue = row['rev']
    avg_ticket = (total_revenue / total_orders) if total_orders else 0

    # Payment method split
    pay_rows = conn.execute(
        "SELECT payment_method, COUNT(*) as cnt, COALESCE(SUM(total),0) as rev "
        "FROM orders WHERE date >= ? AND status != 'voided' "
        "GROUP BY payment_method", (start_str,)
    ).fetchall()
    payment_split = {r['payment_method']: {'count': r['cnt'], 'revenue': r['rev']} for r in pay_rows}

    # Daily revenue for trend (last 14 days always shown for context)
    trend_start = (now - timedelta(days=13)).replace(hour=0, minute=0, second=0, microsecond=0)
    trend_rows = conn.execute(
        "SELECT substr(date,1,10) as day, COALESCE(SUM(total),0) as rev, COUNT(*) as cnt "
        "FROM orders WHERE date >= ? AND status != 'voided' "
        "GROUP BY day ORDER BY day", (trend_start.strftime('%Y-%m-%d %H:%M:%S'),)
    ).fetchall()
    # Fill all 14 days so gaps show as zero
    daily_trend = {}
    for i in range(14):
        d = (trend_start + timedelta(days=i)).strftime('%Y-%m-%d')
        daily_trend[d] = {'rev': 0, 'cnt': 0}
    for r in trend_rows:
        daily_trend[r['day']] = {'rev': r['rev'], 'cnt': r['cnt']}

    # Hourly distribution within selected period
    hour_rows = conn.execute(
        "SELECT CAST(substr(date,12,2) AS INTEGER) as hr, COUNT(*) as cnt "
        "FROM orders WHERE date >= ? AND status != 'voided' "
        "GROUP BY hr ORDER BY hr", (start_str,)
    ).fetchall()
    hourly = {h: 0 for h in range(8, 23)}
    for r in hour_rows:
        if 0 <= r['hr'] <= 23:
            hourly[r['hr']] = r['cnt']

    # Item popularity — parse JSON items
    all_orders = conn.execute(
        "SELECT items FROM orders WHERE date >= ? AND status != 'voided'", (start_str,)
    ).fetchall()
    item_counts = {}
    for o in all_orders:
        try:
            items = json.loads(o['items']) if o['items'] else []
        except (json.JSONDecodeError, TypeError):
            items = []
        for it in items:
            name = it.get('name') or it.get('type', 'Desconocido')
            qty = it.get('quantity', 1)
            item_counts[name] = item_counts.get(name, 0) + qty
    top_items = sorted(item_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Voided orders count
    voided = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE date >= ? AND status = 'voided'", (start_str,)
    ).fetchone()[0]


    return render_template('reports.html',
        period=period, label=label,
        total_orders=total_orders, total_revenue=total_revenue, avg_ticket=avg_ticket,
        payment_split=payment_split,
        daily_trend=daily_trend,
        hourly=hourly,
        top_items=top_items,
        voided=voided,
        today_str=now.strftime('%Y-%m-%d'),
    )


@app.route('/admin/orders')
@login_required
@admin_required
def order_history():
    q         = request.args.get('q', '').strip()
    fecha     = request.args.get('fecha', '').strip()
    estado    = request.args.get('estado', '').strip()

    conn = get_db_connection()

    conditions = []
    params = []

    if q:
        conditions.append("(id LIKE ? OR customer_name LIKE ?)")
        params += [f'%{q}%', f'%{q}%']
    if fecha:
        conditions.append("date LIKE ?")
        params.append(f'{fecha}%')
    if estado == 'anuladas':
        conditions.append("status = 'voided'")
    elif estado == 'activas':
        conditions.append("status != 'voided'")

    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    orders = conn.execute(
        f'SELECT * FROM orders {where} ORDER BY date DESC LIMIT 200',
        params
    ).fetchall()

    parsed = []
    daily_totals = {}
    for o in orders:
        items = []
        try:
            items = json.loads(o['items']) if o['items'] else []
        except json.JSONDecodeError:
            pass
        day = o['date'][:10] if o['date'] else ''
        daily_totals[day] = daily_totals.get(day, 0) + (o['total'] or 0)
        parsed.append({'order': dict(o), 'items': items, 'day': day})

    return render_template('orders.html', orders=parsed, daily_totals=daily_totals,
                           q=q, fecha=fecha, estado=estado)


@app.route('/admin/void_order/<order_id>', methods=['POST'])
@login_required
@admin_required
def void_order(order_id):
    conn = get_db_connection()
    conn.execute("UPDATE orders SET status = 'voided' WHERE id = ?", (order_id,))
    conn.commit()
    flash(f'Orden {order_id} anulada.', 'success')
    return redirect(url_for('order_history'))


@app.route('/admin/reprint/<order_id>', methods=['POST'])
@login_required
@admin_required
def reprint_ticket(order_id):
    """Re-encola el ticket de una orden para que el bridge lo reimprimia."""
    conn = get_db_connection()
    try:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            flash('Orden no encontrada.', 'error')
            return redirect(url_for('order_history'))

        cart = json.loads(order['items']) if order['items'] else []
        _, receipt_text = print_receipt_physical(
            cart,
            order['total'] or 0,
            order['payment_method'] or 'card',
            order['amount_paid'] or 0,
            order['change_amount'] or 0,
            order_id,
            order['customer_name'] or 'Cliente',
        )

        # Usar un ID único para que no choque con el job original
        reprint_id = f"re_{order_id}_{datetime.now().strftime('%H%M%S')}"
        conn.execute(
            "INSERT INTO print_jobs (id, receipt_content, status, created_at) VALUES (?, ?, 'pending', ?)",
            (reprint_id, receipt_text, datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        )
        conn.commit()
        flash(f'Ticket #{order_id} enviado a reimprimir.', 'success')
    except Exception as e:
        flash(f'Error al reimprimir: {str(e)}', 'error')

    return redirect(url_for('order_history'))


@app.route('/admin/orders/export')
@login_required
@admin_required
def export_orders_csv():
    """Descarga las órdenes filtradas como archivo CSV."""
    q      = request.args.get('q', '').strip()
    fecha  = request.args.get('fecha', '').strip()
    estado = request.args.get('estado', '').strip()

    conditions, params = [], []
    if q:
        conditions.append('(id LIKE ? OR customer_name LIKE ?)')
        params += [f'%{q}%', f'%{q}%']
    if fecha:
        conditions.append('date LIKE ?')
        params.append(f'{fecha}%')
    if estado == 'anuladas':
        conditions.append("status = 'voided'")
    elif estado == 'activas':
        conditions.append("status != 'voided'")

    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''

    conn = get_db_connection()
    orders = conn.execute(
        f'SELECT * FROM orders {where} ORDER BY date DESC', params
    ).fetchall()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['ID', 'Fecha', 'Cliente', 'Total', 'Método de pago',
                'Monto pagado', 'Cambio', 'Estado', 'Artículos'])
    for o in orders:
        try:
            items = json.loads(o['items']) if o['items'] else []
            items_str = ' | '.join(
                f"{it.get('name','?')} x{it.get('quantity',1)}" for it in items
            )
        except Exception:
            items_str = ''
        w.writerow([
            o['id'],
            o['date'],
            o['customer_name'] or 'Cliente',
            f"{o['total']:.2f}" if o['total'] else '0.00',
            o['payment_method'] or '',
            f"{o['amount_paid']:.2f}" if o['amount_paid'] else '0.00',
            f"{o['change_amount']:.2f}" if o['change_amount'] else '0.00',
            'Anulada' if o['status'] == 'voided' else 'Completada',
            items_str,
        ])

    fecha_str = datetime.now().strftime('%Y-%m-%d')
    return Response(
        '﻿' + buf.getvalue(),   # UTF-8 BOM so Excel opens it correctly
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename=ordenes_{fecha_str}.csv'},
    )


# ── New Order ─────────────────────────────────────────────────────────────────
@app.route('/new_order', methods=['POST'])
@login_required
def new_order():
    session.pop('cart', None)
    session.pop('customer_name', None)
    session['order_id'] = str(uuid.uuid4())[:8]
    session['cart'] = []
    session.modified = True
    return redirect(url_for('home'))


# ── Forgot Password ───────────────────────────────────────────────────────────
# Sin verificación por correo: la app corre localmente y solo es accesible
# desde la computadora donde está instalada, así que el acceso físico al
# equipo es la autorización (ver subtítulo en forgot_password.html).
@app.route('/forgot_password', methods=['GET', 'POST'])
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
        flash(f'Usuario "{user["username"]}" eliminado.', 'success')
    return redirect(url_for('manage_users'))


# ── Empleados y asistencia ─────────────────────────────────────────────────────
@app.route('/admin/employees/add', methods=['POST'])
@login_required
@admin_required
def add_employee():
    name = request.form.get('name', '').strip()
    pay_amount_raw = request.form.get('pay_amount', '').strip()
    days_csv = parse_scheduled_days(request.form)

    if not name:
        flash('El nombre es requerido.', 'error')
        return redirect(url_for('employees_manage'))
    if not days_csv:
        flash('Selecciona al menos un día de la semana.', 'error')
        return redirect(url_for('employees_manage'))
    try:
        pay_amount = float(pay_amount_raw)
    except ValueError:
        pay_amount = 0
    if pay_amount <= 0:
        flash('El pago semanal debe ser mayor a 0.', 'error')
        return redirect(url_for('employees_manage'))

    conn = get_db_connection()
    cur = conn.execute('INSERT INTO employees (name) VALUES (?)', (name,))
    employee_id = cur.lastrowid
    week_start, _ = get_week_bounds(datetime.now().strftime('%Y-%m-%d'))
    conn.execute(
        'INSERT INTO employee_schedules (employee_id, effective_from, scheduled_days, pay_amount) '
        'VALUES (?, ?, ?, ?)',
        (employee_id, week_start, days_csv, pay_amount)
    )
    conn.commit()
    flash(f'Empleado "{name}" agregado.', 'success')
    return redirect(url_for('employees_manage'))


@app.route('/admin/employees/update/<int:employee_id>', methods=['POST'])
@login_required
@admin_required
def update_employee(employee_id):
    conn = get_db_connection()
    employee = conn.execute('SELECT * FROM employees WHERE id = ?', (employee_id,)).fetchone()
    if not employee:
        flash('Empleado no encontrado.', 'error')
        return redirect(url_for('employees_manage'))

    name = request.form.get('name', '').strip()
    pay_amount_raw = request.form.get('pay_amount', '').strip()
    days_csv = parse_scheduled_days(request.form)

    if not name:
        flash('El nombre es requerido.', 'error')
        return redirect(url_for('employees_manage'))
    if not days_csv:
        flash('Selecciona al menos un día de la semana.', 'error')
        return redirect(url_for('employees_manage'))
    try:
        pay_amount = float(pay_amount_raw)
    except ValueError:
        pay_amount = 0
    if pay_amount <= 0:
        flash('El pago semanal debe ser mayor a 0.', 'error')
        return redirect(url_for('employees_manage'))

    conn.execute('UPDATE employees SET name = ? WHERE id = ?', (name, employee_id))

    today_week_start, _ = get_week_bounds(datetime.now().strftime('%Y-%m-%d'))
    next_week_start = (
        datetime.strptime(today_week_start, '%Y-%m-%d') + timedelta(days=7)
    ).strftime('%Y-%m-%d')
    conn.execute(
        'INSERT INTO employee_schedules (employee_id, effective_from, scheduled_days, pay_amount) '
        'VALUES (?, ?, ?, ?)',
        (employee_id, next_week_start, days_csv, pay_amount)
    )
    conn.commit()
    flash(f'Empleado "{name}" actualizado. Los cambios de horario/pago aplican a partir de la próxima semana.', 'success')
    return redirect(url_for('employees_manage'))


@app.route('/admin/employees/remove/<int:employee_id>', methods=['POST'])
@login_required
@admin_required
def remove_employee(employee_id):
    conn = get_db_connection()
    employee = conn.execute('SELECT * FROM employees WHERE id = ?', (employee_id,)).fetchone()
    if not employee:
        flash('Empleado no encontrado.', 'error')
        return redirect(url_for('employees_manage'))

    has_attendance = conn.execute(
        'SELECT COUNT(*) FROM attendance WHERE employee_id = ?', (employee_id,)
    ).fetchone()[0] > 0

    if has_attendance:
        conn.execute('UPDATE employees SET active = 0 WHERE id = ?', (employee_id,))
        conn.commit()
        flash(f'Empleado "{employee["name"]}" desactivado.', 'success')
    else:
        conn.execute('DELETE FROM employee_schedules WHERE employee_id = ?', (employee_id,))
        conn.execute('DELETE FROM employees WHERE id = ?', (employee_id,))
        conn.commit()
        flash(f'Empleado "{employee["name"]}" eliminado.', 'success')
    return redirect(url_for('employees_manage'))


@app.route('/admin/employees/attendance/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_attendance():
    employee_id = request.form.get('employee_id', '')
    work_date = request.form.get('work_date', '')
    week_param = request.form.get('week', '')

    if not employee_id.isdigit() or not work_date:
        flash('Solicitud inválida.', 'error')
        return redirect(url_for('employees_attendance'))

    conn = get_db_connection()
    existing = conn.execute(
        'SELECT id FROM attendance WHERE employee_id = ? AND work_date = ?',
        (employee_id, work_date)
    ).fetchone()
    if existing:
        conn.execute('DELETE FROM attendance WHERE id = ?', (existing['id'],))
    else:
        conn.execute(
            'INSERT OR IGNORE INTO attendance (employee_id, work_date) VALUES (?, ?)',
            (employee_id, work_date)
        )
    conn.commit()
    return redirect(url_for('employees_attendance', week=week_param or work_date))


@app.route('/admin/employees')
@login_required
@admin_required
def employees_attendance():
    week_param = request.args.get('week', '').strip()
    reference_date = week_param or datetime.now().strftime('%Y-%m-%d')
    try:
        week_start, week_end = get_week_bounds(reference_date)
    except ValueError:
        week_start, week_end = get_week_bounds(datetime.now().strftime('%Y-%m-%d'))

    conn = get_db_connection()
    employees = conn.execute('SELECT * FROM employees WHERE active = 1 ORDER BY name').fetchall()

    week_dates = [
        (datetime.strptime(week_start, '%Y-%m-%d') + timedelta(days=i)).strftime('%Y-%m-%d')
        for i in range(7)
    ]
    day_labels = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']

    rows = []
    week_total = 0.0
    for emp in employees:
        schedule = resolve_employee_schedule(conn, emp['id'], week_start)
        scheduled_days = [int(x) for x in schedule['scheduled_days'].split(',')] if schedule else []
        total_pay, per_day_rate, days_worked, _ = compute_employee_pay(conn, emp['id'], week_start, week_end)
        present_dates = {
            r['work_date'] for r in conn.execute(
                'SELECT work_date FROM attendance WHERE employee_id = ? AND work_date BETWEEN ? AND ?',
                (emp['id'], week_start, week_end)
            ).fetchall()
        }
        days = [
            {
                'date': d,
                'label': day_labels[i],
                'scheduled': i in scheduled_days,
                'present': d in present_dates,
            }
            for i, d in enumerate(week_dates)
        ]
        rows.append({
            'id': emp['id'],
            'name': emp['name'],
            'days': days,
            'per_day_rate': per_day_rate,
            'days_worked': days_worked,
            'total_pay': total_pay,
        })
        week_total += total_pay

    prev_week = (datetime.strptime(week_start, '%Y-%m-%d') - timedelta(days=7)).strftime('%Y-%m-%d')
    next_week = (datetime.strptime(week_start, '%Y-%m-%d') + timedelta(days=7)).strftime('%Y-%m-%d')

    return render_template(
        'employees.html',
        rows=rows,
        week_start=week_start,
        week_end=week_end,
        prev_week=prev_week,
        next_week=next_week,
        week_total=round(week_total, 2),
    )


@app.route('/admin/employees/manage')
@login_required
@admin_required
def employees_manage():
    conn = get_db_connection()
    today_week_start, _ = get_week_bounds(datetime.now().strftime('%Y-%m-%d'))
    employees = conn.execute('SELECT * FROM employees ORDER BY active DESC, name').fetchall()

    day_labels = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
    rows = []
    for emp in employees:
        schedule = resolve_employee_schedule(conn, emp['id'], today_week_start)
        scheduled_days = [int(x) for x in schedule['scheduled_days'].split(',')] if schedule else []
        pay_amount = schedule['pay_amount'] if schedule else 0
        per_day_rate = (pay_amount / len(scheduled_days)) if scheduled_days else 0
        has_attendance = conn.execute(
            'SELECT COUNT(*) FROM attendance WHERE employee_id = ?', (emp['id'],)
        ).fetchone()[0] > 0
        rows.append({
            'id': emp['id'],
            'name': emp['name'],
            'active': emp['active'],
            'scheduled_days': scheduled_days,
            'pay_amount': pay_amount,
            'per_day_rate': per_day_rate,
            'has_attendance': has_attendance,
        })

    return render_template('employees_manage.html', rows=rows, day_labels=day_labels)


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
        return redirect(url_for('admin_dashboard'))
    if promo_type not in ('percentage', 'fixed', 'bxgy'):
        flash('Tipo de promoción inválido.', 'error')
        return redirect(url_for('admin_dashboard'))

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
        return redirect(url_for('admin_dashboard'))

    if promo_type == 'percentage' and not (0 < value <= 100):
        flash('El porcentaje debe estar entre 1 y 100.', 'error')
        return redirect(url_for('admin_dashboard'))
    if promo_type != 'bxgy' and value <= 0:
        flash('El valor debe ser mayor a 0.', 'error')
        return redirect(url_for('admin_dashboard'))

    applicable_json = json.dumps(applicable_items) if applicable_items else '[]'

    conn = get_db_connection()
    existing = conn.execute('SELECT id FROM promotions WHERE name = ?', (name,)).fetchone()
    if existing:
        flash(f'Ya existe una promoción con el código "{name}".', 'error')
        return redirect(url_for('admin_dashboard'))
    conn.execute(
        'INSERT INTO promotions (name, description, type, value, get_free, min_purchase, applicable_items, active) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, 1)',
        (name, description, promo_type, value, get_free, min_purchase, applicable_json)
    )
    conn.commit()
    flash(f'Promoción "{name}" creada.', 'success')
    return redirect(url_for('admin_dashboard'))


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
    return redirect(url_for('admin_dashboard'))


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
    return redirect(url_for('admin_dashboard'))


# ── Configuración general ─────────────────────────────────────────────────────

def get_config(key, default=''):
    """Lee un valor de la tabla config."""
    conn = get_db_connection()
    row = conn.execute('SELECT value FROM config WHERE key = ?', (key,)).fetchone()
    return row['value'] if row else default


@app.route('/admin/config/update', methods=['POST'])
@login_required
@admin_required
def update_config():
    printer_name = request.form.get('printer_name', '').strip()
    if not printer_name:
        flash('El nombre de la impresora no puede estar vacío.', 'error')
        return redirect(url_for('admin_dashboard'))
    conn = get_db_connection()
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


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001)), debug=False)