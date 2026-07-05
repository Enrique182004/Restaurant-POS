import os
import sqlite3
from flask import g, session


def _get_db_path():
    return os.environ.get('RESTAURANT_DB_PATH') or 'restaurant.db'


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
    db_path = _get_db_path()
    try:
        if 'db' not in g:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            g.db = _GConnection(conn)
            g._raw_db = conn
        return g.db
    except RuntimeError:
        # Fuera de contexto de aplicación (inicio de servidor, tests sin contexto)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _cerrar_db(error):
    """Cierra la conexión real al final de cada request, sin importar si hubo error."""
    raw = g.pop('_raw_db', None)
    g.pop('db', None)
    if raw is not None:
        try:
            raw.close()
        except Exception:
            pass


def get_item_price(item_type, style=None):
    """Get item price from the database (editable by admin)."""
    if item_type == 'Sushi' and style:
        if 'Seco' in style or 'Salsas Aparte' in style:
            key = 'Sushi Seco'
        elif 'Flamin' in style:
            key = 'Sushi Flamin'
        else:
            key = 'Sushi Preparado'
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
        'Sushi Preparado':      p('Sushi Preparado'),
        'Seco':                 p('Sushi Seco'),
        'Sushi Flamin':         p('Sushi Flamin'),
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


def log_activity(action, description):
    """Append a row to activity_log. actor comes from Flask session if available."""
    try:
        actor = 'sistema'
        try:
            from flask import session as _s
            actor = _s.get('username', 'sistema')
        except Exception:
            pass
        conn = get_db_connection()
        from datetime import datetime
        conn.execute(
            'INSERT INTO activity_log (action, description, actor, timestamp) VALUES (?, ?, ?, ?)',
            (action, description, actor, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
    except Exception:
        pass
