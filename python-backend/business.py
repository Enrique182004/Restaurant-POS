from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP


def money(value):
    """Redondea un precio a centavos exactos vía Decimal. Evita que errores de
    punto flotante (103.50000000000001) se guarden o rompan comparaciones."""
    return float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def format_num(value):
    """Renders whole numbers without a trailing .0 (e.g. 5.0 -> 5) for editable qty inputs."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    return int(f) if f == int(f) else f


def get_week_bounds(reference_date):
    """reference_date: 'YYYY-MM-DD'. Returns (monday, sunday) as 'YYYY-MM-DD' strings
    for the Mon-Sun week containing reference_date."""
    d = datetime.strptime(reference_date, '%Y-%m-%d')
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime('%Y-%m-%d'), sunday.strftime('%Y-%m-%d')


# Roles de empleado y sus reglas de pago.
# gerente: pago semanal fijo (default $2000) por 6 días — cada falta descuenta 1/6.
# empleado: tarifa fija por día trabajado según el día de la semana.
EMPLOYEE_ROLES = ('empleado', 'gerente')
GERENTE_BASE_DAYS = 6
GERENTE_DEFAULT_WEEKLY = 2000.0
EMPLEADO_RATE_WEEKDAY = 200.0   # lun–jue
EMPLEADO_RATE_WEEKEND = 300.0   # vie–dom


def empleado_day_rate(work_date):
    """Tarifa de un día trabajado para rol 'empleado' ('YYYY-MM-DD')."""
    weekday = datetime.strptime(work_date, '%Y-%m-%d').weekday()
    return EMPLEADO_RATE_WEEKEND if weekday >= 4 else EMPLEADO_RATE_WEEKDAY


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
    present counts toward pay, not only the employee's scheduled days.

    gerente: per_day_rate = pay_amount / 6 (semana fija de 6 días), sin
    importar cuántos días estén programados — faltar descuenta 1/6.
    empleado: $200 por día lun–jue y $300 vie–dom; per_day_rate se reporta
    como 0 porque la tarifa varía por día."""
    schedule = resolve_employee_schedule(conn, employee_id, week_start)
    if schedule is None:
        return 0.0, 0.0, 0, []

    scheduled_days = [int(x) for x in schedule['scheduled_days'].split(',') if x != '']

    emp = conn.execute('SELECT role FROM employees WHERE id = ?', (employee_id,)).fetchone()
    role = emp['role'] if emp and emp['role'] in EMPLOYEE_ROLES else 'empleado'

    worked_dates = [
        r['work_date'] for r in conn.execute(
            'SELECT work_date FROM attendance WHERE employee_id = ? AND work_date BETWEEN ? AND ?',
            (employee_id, week_start, week_end)
        ).fetchall()
    ]
    days_worked = len(worked_dates)

    if role == 'gerente':
        per_day_rate = schedule['pay_amount'] / GERENTE_BASE_DAYS
        total_pay = round(per_day_rate * days_worked, 2)
    else:
        per_day_rate = 0.0
        total_pay = round(sum(empleado_day_rate(d) for d in worked_dates), 2)
    return total_pay, per_day_rate, days_worked, scheduled_days


def parse_scheduled_days(form):
    """Reads the 'days' multi-value field from a submitted form and returns
    a sorted, deduped CSV string of valid weekday ints (0=Mon..6=Sun),
    or '' if nothing valid was selected."""
    raw = form.getlist('days')
    days = sorted({int(d) for d in raw if d.isascii() and d.isdigit() and 0 <= int(d) <= 6})
    return ','.join(str(d) for d in days)


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
        item['price'] = money(max(0, item['original_price'] - unit_price * units_to_free))
        item['discount'] = f"{buy_qty + get_free}x{buy_qty} - ¡{units_to_free} GRATIS!"
        units_remaining -= units_to_free

    return True
