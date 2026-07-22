from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash
import requests
import os
import uuid
from datetime import datetime, timedelta
import json
from db import (get_db_connection, _cerrar_db, log_activity,
                _get_db_path, backup_db_to_file, get_menu_options)
from business import (format_num, money, get_week_bounds,
                      resolve_employee_schedule, compute_employee_pay,
                      parse_scheduled_days)

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



@app.route('/favicon.ico')
def favicon():
    base = os.path.dirname(os.path.dirname(__file__))
    for fname, mime in [('icon.png', 'image/png'), ('icon.jpeg', 'image/jpeg'), ('icon.jpg', 'image/jpeg')]:
        icon_path = os.path.join(base, 'assets', fname)
        if os.path.exists(icon_path):
            return send_file(icon_path, mimetype=mime)
    return '', 204


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
import routes_customize
import routes_payment
import routes_cart
import routes_admin_misc
import routes_orders_admin
import routes_users
import routes_employees
import routes_promotions
import routes_respaldo
import routes_kuike
import routes_menu_options
import routes_inventory
import routes_prices

from routes_payment import _usd_rate, _api_autorizada, print_receipt_physical

routes_customize.register(app)
routes_payment.register(app, csrf)
routes_cart.register(app)
routes_admin_misc.register(app, csrf)
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