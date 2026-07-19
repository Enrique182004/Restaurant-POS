"""Kuike — asistente local del admin: rutas y capa de consultas a la BD."""
import csv
import io
import json
import os
import tempfile
from datetime import datetime, timedelta

from flask import (render_template, request, redirect, url_for, session,
                   flash, jsonify, Response, send_file)

from auth import login_required, admin_required
from db import (get_db_connection, log_activity, _get_db_path,
                backup_db_to_file, get_item_price, get_menu_options)
from business import (money, format_num, get_week_bounds, parse_scheduled_days,
                      resolve_employee_schedule, compute_employee_pay)


def register(app):
    # ── Kuike — AI Admin Assistant ────────────────────────────────────────────────
    # Intent detection and response logic lives in kuike.py.
    # This file owns only the DB query layer (_run_kuike_tool) and the Flask routes.

    from kuike import local_response as _kuike_respond


    def _kuike_local_response(text):
        return _kuike_respond(text, _run_kuike_tool)


    def _period_range(period):
        # audit v2.1.1: cada período ahora tiene límite superior explícito.
        # Antes solo había cota inferior (date >= start), así 'ayer' incluía hoy
        # y 'semana'/'mes' incluían el futuro del período. Devuelve (start, end)
        # inclusivos; el SQL filtra con date >= start AND date <= end.
        now = datetime.now()
        end = now  # por defecto la cota superior es "ahora"
        if period == 'yesterday':
            y = now - timedelta(days=1)
            start = y.replace(hour=0, minute=0, second=0, microsecond=0)
            end = y.replace(hour=23, minute=59, second=59, microsecond=0)
        elif period == 'week':
            start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'month':
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif period == 'year':
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        elif period == 'alltime':
            start = datetime(2000, 1, 1)
        else:  # today
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        fmt = '%Y-%m-%d %H:%M:%S'
        return start.strftime(fmt), end.strftime(fmt)


    def _run_kuike_tool(name, inputs):
        conn = get_db_connection()
        if name == 'get_sales_summary':
            start, end = _period_range(inputs.get('period', 'today'))
            row = conn.execute(
                "SELECT COUNT(*) as cnt, COALESCE(SUM(total),0) as rev FROM orders "
                "WHERE date >= ? AND date <= ? AND status != 'voided'", (start, end)
            ).fetchone()
            voided = conn.execute(
                "SELECT COUNT(*) FROM orders WHERE date >= ? AND date <= ? AND status = 'voided'",
                (start, end)
            ).fetchone()[0]
            avg = (row['rev'] / row['cnt']) if row['cnt'] else 0
            return {"period": inputs.get('period'), "orders": row['cnt'],
                    "revenue": round(row['rev'], 2), "avg_ticket": round(avg, 2), "voided": voided}

        elif name == 'get_top_items':
            start, end = _period_range(inputs.get('period', 'today'))
            limit = inputs.get('limit', 10)
            rows = conn.execute(
                "SELECT items, total FROM orders WHERE date >= ? AND date <= ? AND status != 'voided'",
                (start, end)
            ).fetchall()
            counts, revenues = {}, {}
            for r in rows:
                try:
                    items = json.loads(r['items']) if r['items'] else []
                except Exception:
                    items = []
                n = len(items) or 1
                for it in items:
                    nm = it.get('name') or it.get('type', '?')
                    counts[nm] = counts.get(nm, 0) + it.get('quantity', 1)
                    revenues[nm] = revenues.get(nm, 0.0) + it.get('price', r['total'] / n)
            top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
            return [{"item": nm, "qty": qty, "revenue": round(revenues.get(nm, 0), 2)} for nm, qty in top]

        elif name == 'get_recent_orders':
            limit = inputs.get('limit', 20)
            customer = inputs.get('customer_name', '')
            status = inputs.get('status', 'all')
            conds, params = [], []
            if customer:
                conds.append("customer_name LIKE ?"); params.append(f'%{customer}%')
            if status != 'all':
                conds.append("status = ?"); params.append(status)
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            rows = conn.execute(
                f"SELECT id, customer_name, total, payment_method, date, status "
                f"FROM orders {where} ORDER BY date DESC LIMIT ?",
                params + [limit]
            ).fetchall()
            return [dict(r) for r in rows]

        elif name == 'get_payment_breakdown':
            start, end = _period_range(inputs.get('period', 'today'))
            rows = conn.execute(
                "SELECT payment_method, COUNT(*) as cnt, COALESCE(SUM(total),0) as rev "
                "FROM orders WHERE date >= ? AND date <= ? AND status != 'voided' "
                "GROUP BY payment_method", (start, end)
            ).fetchall()
            return [{"method": r['payment_method'], "orders": r['cnt'], "revenue": round(r['rev'], 2)} for r in rows]

        elif name == 'get_peak_hours':
            start, end = _period_range(inputs.get('period', 'today'))
            rows = conn.execute(
                "SELECT CAST(substr(date,12,2) AS INTEGER) as hr, COUNT(*) as cnt, "
                "COALESCE(SUM(total),0) as rev FROM orders "
                "WHERE date >= ? AND date <= ? AND status != 'voided' "
                "GROUP BY hr ORDER BY cnt DESC", (start, end)
            ).fetchall()
            return [{"hour": f"{r['hr']:02d}:00", "orders": r['cnt'], "revenue": round(r['rev'], 2)} for r in rows]

        elif name == 'get_employee_data':
            week_date = inputs.get('week', datetime.now().strftime('%Y-%m-%d'))
            monday, sunday = get_week_bounds(week_date)
            employees = conn.execute("SELECT * FROM employees WHERE active = 1").fetchall()
            result = []
            for emp in employees:
                total_pay, rate, days_worked, sched = compute_employee_pay(conn, emp['id'], monday, sunday)
                result.append({
                    "name": emp['name'], "days_worked": days_worked,
                    "daily_rate": round(rate, 2), "pay_this_week": round(total_pay, 2),
                    "scheduled_days": len(sched)
                })
            return {"week": f"{monday} to {sunday}", "employees": result}

        elif name == 'get_inventory':
            rows = conn.execute("SELECT name, quantity, min_threshold, unit FROM inventory ORDER BY name").fetchall()
            return [{"name": r['name'], "qty": r['quantity'], "min": r['min_threshold'],
                     "unit": r['unit'], "low": r['quantity'] <= r['min_threshold']} for r in rows]

        elif name == 'get_held_orders':
            rows = conn.execute("SELECT * FROM held_orders ORDER BY created_at DESC").fetchall()
            return [{"ref": r['order_ref'], "customer": r['customer_name'],
                     "total": r['total'], "since": r['created_at']} for r in rows]

        elif name == 'get_promotions':
            rows = conn.execute("SELECT name, type, value, min_purchase, active, description FROM promotions").fetchall()
            return [dict(r) for r in rows]

        elif name == 'get_menu_prices':
            rows = conn.execute("SELECT label, price FROM menu_prices ORDER BY label").fetchall()
            return [{"item": r['label'], "price": r['price']} for r in rows]

        elif name == 'get_activity_log':
            limit = inputs.get('limit', 20)
            rows = conn.execute(
                "SELECT action, description, actor, timestamp FROM activity_log ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

        elif name == 'get_frequent_customers':
            limit = inputs.get('limit', 15)
            rows = conn.execute(
                "SELECT customer_name, COUNT(*) as visits, COALESCE(SUM(total),0) as spent "
                "FROM orders WHERE status != 'voided' AND customer_name IS NOT NULL "
                "AND customer_name != '' AND customer_name != 'Cliente' "
                "GROUP BY customer_name HAVING visits > 1 ORDER BY visits DESC LIMIT ?", (limit,)
            ).fetchall()
            return [{"customer": r['customer_name'], "visits": r['visits'], "total_spent": round(r['spent'], 2)} for r in rows]

        return {"error": f"Tool '{name}' not found"}


    @app.route('/admin/kuike')
    @login_required
    @admin_required
    def kuike_chat():
        return render_template('kuike.html')


    @app.route('/admin/kuike/chat', methods=['POST'])
    @login_required
    @admin_required
    def kuike_chat_api():
        data = request.get_json(silent=True) or {}
        messages = data.get('messages', [])
        if not messages:
            return jsonify({'error': 'Sin mensajes.'}), 400

        user_msg = ''
        for m in reversed(messages):
            if m.get('role') == 'user':
                user_msg = m.get('content', '')
                break

        if not user_msg:
            return jsonify({'reply': '¿En qué te puedo ayudar?'})

        try:
            reply = _kuike_local_response(user_msg.lower())
        except Exception as e:
            reply = f'Error consultando datos: {e}'

        return jsonify({'reply': reply})
