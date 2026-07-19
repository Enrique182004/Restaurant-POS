"""
Tests for Kuike intent detection and response formatting.
Run from python-backend/: pytest tests/test_kuike.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from kuike import local_response, detect_period

# ── Mock DB layer ─────────────────────────────────────────────────────────────

def mock_run_tool(name, inputs):
    if name == 'get_sales_summary':
        return {'orders': 47, 'revenue': 2430.0, 'avg_ticket': 51.70, 'voided': 0}
    if name == 'get_top_items':
        return [{'item': 'Boneless', 'qty': 120, 'revenue': 1800.0}]
    if name == 'get_inventory':
        return [
            {'name': 'Camarones', 'qty': 85, 'unit': 'kg', 'min': 10, 'low': False},
            {'name': 'Aguacate',  'qty': 2,  'unit': 'kg', 'min': 5,  'low': True},
        ]
    if name == 'get_employee_data':
        return {
            'week': '2026-06-30 to 2026-07-06',
            'employees': [
                {'name': 'Ana', 'days_worked': 5, 'scheduled_days': 5, 'pay_this_week': 1200.0}
            ],
        }
    if name == 'get_peak_hours':
        return [{'hour': '13:00', 'orders': 15, 'revenue': 750.0}]
    if name == 'get_payment_breakdown':
        return [
            {'method': 'cash', 'orders': 30, 'revenue': 1500.0},
            {'method': 'card', 'orders': 17, 'revenue': 930.0},
        ]
    if name == 'get_held_orders':
        return [{'ref': 'H-001', 'customer': 'Juan', 'total': 45.0}]
    if name == 'get_recent_orders':
        return [{'id': 1, 'customer_name': 'Ana', 'total': 45.0, 'status': 'completed'}]
    if name == 'get_promotions':
        return [{'name': '10% off', 'type': 'percentage', 'active': True, 'description': '10% descuento'}]
    if name == 'get_menu_prices':
        return [{'item': 'Boneless 1/2 lb', 'price': 85.0}]
    if name == 'get_activity_log':
        return [{'timestamp': '2026-07-02 10:00', 'action': 'login', 'description': 'Admin login'}]
    if name == 'get_frequent_customers':
        return [{'customer': 'Ana García', 'visits': 12, 'total_spent': 540.0}]
    return []


def r(text):
    return local_response(text, mock_run_tool)


# ── Period detection ──────────────────────────────────────────────────────────

def test_period_defaults_to_today():
    assert detect_period('ventas') == 'today'

def test_period_yesterday():
    assert detect_period('ventas de ayer') == 'yesterday'

def test_period_week():
    assert detect_period('esta semana') == 'week'

def test_period_month():
    assert detect_period('este mes') == 'month'

def test_period_year():
    # audit v2.1.1: 'año' ahora es el año en curso, no el histórico completo.
    assert detect_period('ventas del año') == 'year'


# ── Intent: greeting ──────────────────────────────────────────────────────────

def test_greeting_hola():
    assert '🦐' in r('hola')

def test_greeting_hello():
    assert '🦐' in r('hello')

def test_greeting_hey():
    assert '🦐' in r('hey kuike')


# ── Intent: help ─────────────────────────────────────────────────────────────

def test_help_que_puedes():
    resp = r('qué puedes hacer')
    assert 'Ventas' in resp and 'Inventario' in resp

def test_help_ayuda():
    assert 'Ventas' in r('necesito ayuda')


# ── Intent: sales ────────────────────────────────────────────────────────────

def test_sales_today():
    resp = r('cuánto vendimos hoy')
    assert '47' in resp and '2430' in resp

def test_sales_ventas():
    resp = r('ventas de esta semana')
    assert 'ventas' in resp.lower()


# ── Intent: top items ────────────────────────────────────────────────────────

def test_top_items():
    resp = r('cuál es el producto más vendido')
    assert 'Boneless' in resp

def test_top_items_popular():
    assert 'Boneless' in r('qué es lo más popular')


# ── Intent: inventory ────────────────────────────────────────────────────────

def test_inventory_all():
    resp = r('qué hay en inventario')
    assert 'Camarones' in resp

def test_inventory_low_stock():
    resp = r('qué hay en inventario bajo')
    assert 'Aguacate' in resp
    assert 'Camarones' not in resp

def test_inventory_minimo():
    resp = r('qué está debajo del mínimo')
    assert 'Aguacate' in resp


# ── Intent: employees ────────────────────────────────────────────────────────

def test_employees():
    resp = r('cuántos empleados tengo')
    assert 'Ana' in resp

def test_employees_nomina():
    assert 'Ana' in r('muéstrame la nómina')


# ── Intent: peak hours ───────────────────────────────────────────────────────

def test_peak_hours():
    resp = r('a qué hora tenemos más pedidos')
    assert '13:00' in resp

def test_peak_hours_concurrido():
    assert '13:00' in r('cuándo es más concurrido')


# ── Intent: payment ──────────────────────────────────────────────────────────

def test_payment_breakdown():
    resp = r('como pagaron hoy')
    assert 'Efectivo' in resp

def test_payment_efectivo():
    assert 'Efectivo' in r('cuánto pagaron en efectivo')

def test_payment_metodo():
    assert 'Efectivo' in r('métodos de pago de hoy')


# ── Intent: held orders ──────────────────────────────────────────────────────

def test_held_orders():
    resp = r('hay ordenes retenidas')
    assert 'H-001' in resp

def test_held_orders_en_espera():
    assert 'H-001' in r('órdenes en espera')


# ── Intent: recent orders ────────────────────────────────────────────────────

def test_recent_orders():
    resp = r('muéstrame las últimas órdenes')
    assert 'Ana' in resp

def test_recent_orders_pedidos():
    assert 'Ana' in r('últimos pedidos')


# ── Intent: promotions ───────────────────────────────────────────────────────

def test_promotions():
    resp = r('qué promociones hay')
    assert '10%' in resp

def test_promotions_descuento():
    assert '10%' in r('hay algún descuento activo')


# ── Intent: menu prices ──────────────────────────────────────────────────────

def test_prices():
    resp = r('cuánto cuesta el menú')
    assert 'Boneless' in resp

def test_prices_precio():
    assert 'Boneless' in r('cuál es el precio del boneless')


# ── Intent: activity log ─────────────────────────────────────────────────────

def test_activity_log():
    resp = r('muéstrame la bitácora')
    assert 'login' in resp.lower()

def test_activity_log_actividad():
    assert 'login' in r('actividad reciente').lower()


# ── Intent: frequent customers ───────────────────────────────────────────────

def test_frequent_customers():
    resp = r('clientes frecuentes')
    assert 'Ana García' in resp

def test_frequent_customers_visitas():
    assert 'Ana García' in r('quién visita más')


# ── Disambiguation (substring false-positive prevention) ─────────────────────

def test_inventory_not_sales():
    # "inventario" contains "venta" — must not match sales
    resp = r('qué hay en inventario')
    assert 'Órdenes completadas' not in resp

def test_employees_not_sales():
    # "cuantos" contains "cuanto" — must not match sales
    resp = r('cuantos empleados')
    assert 'Ana' in resp
    assert 'Órdenes completadas' not in resp

def test_peak_hours_not_recent_orders():
    # "pedidos" in phrase must route to peak hours, not recent orders
    resp = r('a qué hora hay más pedidos')
    assert '13:00' in resp

def test_held_not_recent_orders():
    # "ordenes" must be caught by held-orders check first
    resp = r('ordenes retenidas')
    assert 'H-001' in resp

def test_payment_not_recent_orders():
    # "pagaron" must route to payment, not fallback
    resp = r('cómo pagaron')
    assert 'Efectivo' in resp


# ── Fallback ─────────────────────────────────────────────────────────────────

def test_fallback_weather():
    resp = r('cómo está el clima hoy')
    assert 'No encontré' in resp

def test_fallback_geography():
    resp = r('cuál es la capital de francia')
    assert 'No encontré' in resp
