"""Esquema e inicialización de la base de datos.
Crea tablas si faltan, aplica migraciones idempotentes y siembra datos por
defecto (precios, opciones de menú, usuarios admin/user). Se llama al arrancar
(app.py __main__) y desde las pruebas."""
import sqlite3

from werkzeug.security import generate_password_hash

from db import get_db_connection


def init_db():
    conn = get_db_connection()

    # WAL mode: uncommitted writes are rolled back on crash instead of
    # leaving the DB in a half-written state.
    conn.execute('PRAGMA journal_mode=WAL')

    # Detect corruption early; log a warning but don't crash so the owner
    # can still open the app and restore from a backup manually.
    integrity = conn.execute('PRAGMA quick_check').fetchone()[0]
    if integrity != 'ok':
        import logging
        logging.getLogger(__name__).error(
            '[DB] Integrity check failed: %s — restore from a backup in userData/backups/', integrity
        )

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

    # Historial y reportes filtran por rango de fecha en cada carga
    conn.execute('CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(date)')

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
        ('Sushi Flamin',    'Sushi (Flamin)',       125.0),
        ('Complementos',    'Complementos (x salsa)',10.0),
        ('Ostión',          'Ostión (extra)',        10.0),
    ]
    for key, label, price in default_prices:
        conn.execute(
            'INSERT OR IGNORE INTO menu_prices (key, label, price) VALUES (?, ?, ?)',
            (key, label, price)
        )

    # Held orders queue (phone orders waiting for client to arrive)
    conn.execute('''
    CREATE TABLE IF NOT EXISTS held_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_ref TEXT NOT NULL,
        customer_name TEXT DEFAULT 'Cliente',
        cart_json TEXT NOT NULL,
        total REAL NOT NULL,
        created_at TEXT NOT NULL
    )
    ''')

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
    # Tipo de cambio USD → MXN, editable por el admin en el panel.
    conn.execute(
        "INSERT OR IGNORE INTO config (key, value) VALUES ('usd_rate', '18.00')"
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
            # Sushi sauces
            ('sushi_sauce', 'Tradicional', '🔴', 0, 1),
            ('sushi_sauce', 'Flamin Hot',  '🔥', 0, 2),
            ('sushi_sauce', 'Puff',        '💨', 0, 3),
            ('sushi_sauce', 'Nacha',       '🌮', 0, 4),
            ('sushi_sauce', 'Búfalo',      '🦬', 0, 5),
            ('sushi_sauce', 'Barbecue',    '🍖', 0, 6),
            ('sushi_sauce', 'Agridulce',   '🍯', 0, 7),
            ('sushi_sauce', 'Frutal',      '🍎', 0, 8),
            ('sushi_sauce', 'Seca',        '🌾', 0, 9),
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

    # Pagos en dólares: moneda usada, monto original en USD y tipo de cambio
    # aplicado (el total y el cambio siempre quedan en MXN).
    for _col in ("paid_currency TEXT DEFAULT 'mxn'",
                 'paid_amount_usd REAL DEFAULT 0',
                 'usd_rate REAL DEFAULT 0'):
        try:
            conn.execute(f'ALTER TABLE orders ADD COLUMN {_col}')
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

    # Migrate: seed sushi_sauce category for existing installations
    if conn.execute("SELECT COUNT(*) FROM menu_options WHERE category='sushi_sauce'").fetchone()[0] == 0:
        for name, icon, sort in [
            ('Tradicional', '🔴', 1), ('Flamin Hot', '🔥', 2), ('Puff', '💨', 3),
            ('Nacha', '🌮', 4), ('Búfalo', '🦬', 5), ('Barbecue', '🍖', 6),
            ('Agridulce', '🍯', 7), ('Frutal', '🍎', 8), ('Seca', '🌾', 9),
        ]:
            conn.execute(
                'INSERT INTO menu_options (category, name, icon, price, sort_order) VALUES (?, ?, ?, 0, ?)',
                ('sushi_sauce', name, icon, sort)
            )
        conn.commit()

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
        role TEXT DEFAULT 'empleado',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Rol del empleado: 'gerente' (semanal fijo ÷ 6 días) o 'empleado'
    # (tarifa por día: $200 lun–jue, $300 vie–dom).
    try:
        conn.execute("ALTER TABLE employees ADD COLUMN role TEXT DEFAULT 'empleado'")
    except sqlite3.OperationalError:
        pass  # Column already exists

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

    # Activity log for audit trail
    conn.execute('''
    CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        description TEXT NOT NULL,
        actor TEXT DEFAULT 'sistema',
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.commit()
    conn.close()
