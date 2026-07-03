"""
Kuike local assistant — intent detection and response formatting.

Depends on nothing from app.py. All DB access is injected via `run_tool`,
a callable with signature: run_tool(tool_name: str, inputs: dict) -> any
"""
import re

_PERIOD_LABELS = {
    'today':     'hoy',
    'yesterday': 'ayer',
    'week':      'esta semana',
    'month':     'este mes',
    'alltime':   'histórico',
}

_FALLBACK = (
    'No encontré información específica para esa consulta. Prueba preguntar sobre:\n'
    'ventas, productos más vendidos, horarios pico, métodos de pago, empleados, '
    'inventario, clientes frecuentes, promociones o precios.'
)


# ── Period detection ──────────────────────────────────────────────────────────

def detect_period(text):
    if any(w in text for w in ['ayer', 'yesterday']):
        return 'yesterday'
    if any(w in text for w in ['semana', 'week', 'semanal', 'esta semana', 'this week']):
        return 'week'
    if any(w in text for w in ['month', 'mensual', 'este mes', 'this month']) or re.search(r'\bmes\b', text):
        return 'month'
    if any(w in text for w in ['año', 'year', 'anual', 'este año', 'this year']):
        return 'alltime'
    return 'today'


# ── Intent handlers ───────────────────────────────────────────────────────────

def _handle_greeting(text, period, plabel, run_tool):
    return ('¡Hola! Soy Kuike 🦐. Puedo consultarte ventas, inventario, empleados, '
            'clientes frecuentes, promociones y más. ¿Qué quieres saber?')


def _handle_help(text, period, plabel, run_tool):
    return (
        'Puedo ayudarte con:\n'
        '• Ventas: totales y tendencias por período\n'
        '• Productos más vendidos\n'
        '• Horarios pico\n'
        '• Métodos de pago: efectivo, tarjeta, mixto\n'
        '• Empleados: asistencia y nómina\n'
        '• Inventario y alertas de bajo stock\n'
        '• Clientes frecuentes\n'
        '• Promociones activas\n'
        '• Precios del menú\n'
        '• Bitácora de actividad\n\n'
        'Puedes agregar: hoy, ayer, esta semana o este mes.'
    )


def _handle_inventory(text, period, plabel, run_tool):
    data = run_tool('get_inventory', {})
    if not isinstance(data, list):
        return 'No hay datos de inventario.'
    low = [i for i in data if i.get('low')]
    if any(w in text for w in ['bajo', 'low', 'agota', 'mínimo', 'minimo', 'alerta']):
        if not low:
            return 'Todo el inventario está por encima del mínimo. ✅'
        lines = [f'Inventario bajo ({len(low)} ítems):']
        for i in low:
            lines.append(f'⚠️ {i["name"]}: {i["qty"]} {i["unit"]} (mín. {i["min"]})')
        return '\n'.join(lines)
    lines = [f'Inventario ({len(data)} ítems):']
    for i in data:
        flag = ' ⚠️' if i.get('low') else ''
        lines.append(f'• {i["name"]}: {i["qty"]} {i["unit"]}{flag}')
    return '\n'.join(lines)


def _handle_employees(text, period, plabel, run_tool):
    data = run_tool('get_employee_data', {})
    if not isinstance(data, dict) or 'employees' not in data:
        return 'No hay datos de empleados.'
    lines = [f'Empleados — semana {data.get("week", "")}:']
    for e in data['employees']:
        lines.append(
            f'• {e["name"]}: {e["days_worked"]}/{e["scheduled_days"]} días'
            f' — ${e["pay_this_week"]:.2f}'
        )
    return '\n'.join(lines)


def _handle_top_items(text, period, plabel, run_tool):
    limit = 5
    m = re.search(r'\b(\d+)\b', text)
    if m:
        limit = min(int(m.group(1)), 20)
    data = run_tool('get_top_items', {'period': period, 'limit': limit})
    if not isinstance(data, list) or not data:
        return f'No hay datos de productos para {plabel}.'
    lines = [f'Productos más vendidos ({plabel}):']
    for idx, item in enumerate(data, 1):
        lines.append(f'{idx}. {item["item"]} — {item["qty"]} uds. (${item.get("revenue", 0):.2f})')
    return '\n'.join(lines)


def _handle_peak_hours(text, period, plabel, run_tool):
    data = run_tool('get_peak_hours', {'period': period})
    if not isinstance(data, list) or not data:
        return f'No hay datos de horarios para {plabel}.'
    lines = [f'Horas con más pedidos ({plabel}):']
    for row in data[:6]:
        lines.append(f'• {row["hour"]} — {row["orders"]} órdenes (${row["revenue"]:.2f})')
    return '\n'.join(lines)


def _handle_payment(text, period, plabel, run_tool):
    data = run_tool('get_payment_breakdown', {'period': period})
    if not isinstance(data, list) or not data:
        return f'No hay datos de pagos para {plabel}.'
    names = {'cash': 'Efectivo', 'card': 'Tarjeta', 'split': 'Mixto'}
    lines = [f'Métodos de pago ({plabel}):']
    for row in data:
        label = names.get(row['method'], row['method'])
        lines.append(f'• {label}: {row["orders"]} órdenes — ${row["revenue"]:.2f}')
    return '\n'.join(lines)


def _handle_held_orders(text, period, plabel, run_tool):
    data = run_tool('get_held_orders', {})
    if not isinstance(data, list):
        return 'Error consultando órdenes retenidas.'
    if not data:
        return 'No hay órdenes retenidas en este momento.'
    lines = [f'Órdenes retenidas ({len(data)}):']
    for o in data:
        lines.append(f'• {o["ref"]} — {o.get("customer") or "Sin nombre"} — ${o.get("total", 0):.2f}')
    return '\n'.join(lines)


def _handle_recent_orders(text, period, plabel, run_tool):
    limit = 10
    m = re.search(r'\b(\d+)\b', text)
    if m:
        limit = min(int(m.group(1)), 50)
    data = run_tool('get_recent_orders', {'limit': limit})
    if not isinstance(data, list) or not data:
        return 'No hay órdenes recientes.'
    lines = [f'Últimas {len(data)} órdenes:']
    for o in data:
        flag = '✓' if o.get('status') == 'completed' else '✗'
        lines.append(f'{flag} #{o["id"]} — {o.get("customer_name") or "Sin nombre"} — ${o.get("total", 0):.2f}')
    return '\n'.join(lines)


def _handle_sales(text, period, plabel, run_tool):
    data = run_tool('get_sales_summary', {'period': period})
    if not isinstance(data, dict) or 'orders' not in data:
        return f'No hay datos de ventas para {plabel}.'
    avg = data['revenue'] / data['orders'] if data['orders'] > 0 else 0
    return (
        f'Resumen de ventas ({plabel}):\n'
        f'• Órdenes completadas: {data["orders"]}\n'
        f'• Ingresos totales: ${data["revenue"]:.2f}\n'
        f'• Ticket promedio: ${avg:.2f}'
    )


def _handle_promotions(text, period, plabel, run_tool):
    data = run_tool('get_promotions', {})
    if not isinstance(data, list):
        return 'No hay datos de promociones.'
    active = [p for p in data if p.get('active')]
    if not active:
        return 'No hay promociones activas en este momento.'
    lines = [f'Promociones activas ({len(active)} de {len(data)}):']
    for p in active:
        desc = p.get('description') or p.get('type', '')
        lines.append(f'• {p["name"]}: {desc}')
    return '\n'.join(lines)


def _handle_prices(text, period, plabel, run_tool):
    data = run_tool('get_menu_prices', {})
    if not isinstance(data, list) or not data:
        return 'No hay precios configurados.'
    lines = ['Precios del menú:']
    for item in data:
        lines.append(f'• {item["item"]}: ${item["price"]:.2f}')
    return '\n'.join(lines)


def _handle_activity(text, period, plabel, run_tool):
    data = run_tool('get_activity_log', {'limit': 15})
    if not isinstance(data, list) or not data:
        return 'No hay actividad registrada.'
    lines = ['Actividad reciente:']
    for entry in data[:10]:
        lines.append(
            f'• {entry.get("timestamp", "")} — '
            f'{entry.get("action", "")} — '
            f'{entry.get("description", "")}'
        )
    return '\n'.join(lines)


def _handle_customers(text, period, plabel, run_tool):
    data = run_tool('get_frequent_customers', {'limit': 10})
    if not isinstance(data, list):
        return 'No hay datos de clientes.'
    if not data:
        return 'Aún no hay clientes frecuentes registrados.'
    lines = ['Clientes más frecuentes:']
    for c in data:
        lines.append(f'• {c["customer"]}: {c["visits"]} visitas — ${c["total_spent"]:.2f}')
    return '\n'.join(lines)


# ── Intent table ──────────────────────────────────────────────────────────────
# Order is load-bearing: more specific / disambiguation-prone entries come first.
# Each row: (trigger_keywords, handler_fn)
_INTENTS = [
    (
        ['hola', 'hello', 'hi', 'hey', 'buenas', 'qué tal', 'que tal'],
        _handle_greeting,
    ),
    (
        ['ayuda', 'help', 'qué puedes', 'que puedes', 'qué sabes', 'que sabes',
         'puedes hacer', 'cómo funciona', 'como funciona'],
        _handle_help,
    ),
    # inventory before sales — "inventario" contains "venta" as substring
    (
        ['inventario', 'inventory', 'stock', 'existencia', 'material',
         'ingrediente', 'agotad', 'mínimo', 'minimo', 'alerta', 'debajo'],
        _handle_inventory,
    ),
    # employees before sales — "cuantos" contains "cuanto" as substring
    (
        ['empleado', 'employee', 'trabajador', 'personal', 'staff',
         'nómina', 'nomina', 'salario', 'sueldo'],
        _handle_employees,
    ),
    (
        ['producto', 'item', 'artículo', 'articulo', 'más vendido', 'mas vendido',
         'popular', 'top ', 'best', 'mayor venta'],
        _handle_top_items,
    ),
    # peak hours before recent orders — "pedidos" appears in peak-hour queries;
    # also before top_items — "más pedido" is a substring of "más pedidos"
    (
        ['hora', 'pico', 'peak', 'concurrido', 'ocupado', 'busy', 'rush',
         'cuándo más', 'cuando más', 'cuándo hay', 'cuando hay',
         'gente', 'movimiento', 'momento'],
        _handle_peak_hours,
    ),
    # payment before recent orders
    (
        ['pago', 'pagaron', 'pagar', 'pagó', 'payment',
         'efectivo', 'tarjeta', 'cash', 'card', 'mixto', 'split',
         'método de pago'],
        _handle_payment,
    ),
    # held orders before recent orders — "ordenes" matches both
    (
        ['retenid', 'en espera', 'hold', 'guardad', 'retenidas'],
        _handle_held_orders,
    ),
    # activity log before recent orders — "actividad reciente" contains "reciente"
    (
        ['actividad', 'bitácora', 'bitacora', 'log', 'activity',
         'registro', 'acción', 'accion', 'audit'],
        _handle_activity,
    ),
    (
        ['orden', 'ordenes', 'órdenes', 'pedido', 'pedidos',
         'reciente', 'últim', 'order', 'recent'],
        _handle_recent_orders,
    ),
    (
        ['vend', 'venta', 'ventas', 'ingreso', 'ganancia', 'ganancias',
         'recaud', 'factur', 'revenue', 'sales', 'sold'],
        _handle_sales,
    ),
    (
        ['promoci', 'descuento', 'cupón', 'cupon', 'promo',
         'oferta', 'discount', 'promotion'],
        _handle_promotions,
    ),
    (
        ['precio', 'menú', 'menu', 'price', 'costo',
         'cuánto cuesta', 'cuanto cuesta'],
        _handle_prices,
    ),
    (
        ['cliente', 'customer', 'frecuente', 'frequent',
         'fiel', 'loyal', 'visita', 'regular'],
        _handle_customers,
    ),
]


# ── Public entry point ────────────────────────────────────────────────────────

def local_response(text, run_tool):
    """
    Return a response string for `text` (must be lowercased by caller).
    `run_tool(name, inputs)` is the DB query callback provided by app.py.
    """
    period = detect_period(text)
    plabel = _PERIOD_LABELS.get(period, 'hoy')
    for keywords, handler in _INTENTS:
        if any(w in text for w in keywords):
            return handler(text, period, plabel, run_tool)
    return _FALLBACK
