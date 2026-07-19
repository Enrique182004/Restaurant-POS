"""Admin: reportes, historial de órdenes, anulación, reimpresión y export CSV."""
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


def register(app, print_receipt_physical):
    @app.route('/admin/reports')
    @login_required
    @admin_required
    def reports():
        period = request.args.get('period', 'today')
        selected_date = request.args.get('date', '')
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
        elif period == 'custom' and selected_date:
            try:
                start = datetime.strptime(selected_date, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
            except ValueError:
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                selected_date = ''
            label = selected_date
        else:  # today (and custom with no date)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            label = 'Hoy'

        start_str = start.strftime('%Y-%m-%d %H:%M:%S')

        # For a specific custom day, cap at midnight of the next day so only that
        # day's orders are counted (without an upper bound, selecting July 3rd
        # would return July 3rd + 4th + 5th ... and inflate every total).
        if period == 'custom' and selected_date:
            end_str = (start + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
            date_clause = "date >= ? AND date < ?"
            date_args = (start_str, end_str)
        else:
            date_clause = "date >= ?"
            date_args = (start_str,)

        conn = get_db_connection()

        # Core summary
        row = conn.execute(
            f"SELECT COUNT(*) as cnt, COALESCE(SUM(total),0) as rev FROM orders "
            f"WHERE {date_clause} AND status != 'voided'", date_args
        ).fetchone()
        total_orders = row['cnt']
        total_revenue = row['rev']
        avg_ticket = (total_revenue / total_orders) if total_orders else 0

        # Payment method split
        pay_rows = conn.execute(
            f"SELECT payment_method, COUNT(*) as cnt, COALESCE(SUM(total),0) as rev "
            f"FROM orders WHERE {date_clause} AND status != 'voided' "
            f"GROUP BY payment_method", date_args
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

        # Hourly distribution within selected period — orders + revenue
        hour_rows = conn.execute(
            f"SELECT CAST(substr(date,12,2) AS INTEGER) as hr, COUNT(*) as cnt, COALESCE(SUM(total),0) as rev "
            f"FROM orders WHERE {date_clause} AND status != 'voided' "
            f"GROUP BY hr ORDER BY hr", date_args
        ).fetchall()
        hourly = {h: {'cnt': 0, 'rev': 0.0} for h in range(8, 23)}
        for r in hour_rows:
            if 0 <= r['hr'] <= 23:
                hourly[r['hr']] = {'cnt': r['cnt'], 'rev': r['rev']}
        # Re-emit keys in chronological order so late-night / early hours (23, 0–7)
        # that landed after the pre-seeded 8–22 range don't render out of order.
        hourly = {h: hourly[h] for h in sorted(hourly)}

        # Item popularity — parse JSON items, track qty + revenue
        all_orders = conn.execute(
            f"SELECT items, total FROM orders WHERE {date_clause} AND status != 'voided'", date_args
        ).fetchall()
        item_counts = {}
        item_revenue = {}
        for o in all_orders:
            try:
                items = json.loads(o['items']) if o['items'] else []
            except (json.JSONDecodeError, TypeError):
                items = []
            n_items = len(items) or 1
            per_item_rev = (o['total'] or 0) / n_items
            for it in items:
                name = it.get('name') or it.get('type', 'Desconocido')
                qty = it.get('quantity', 1)
                item_counts[name] = item_counts.get(name, 0) + qty
                item_revenue[name] = item_revenue.get(name, 0.0) + it.get('price', per_item_rev)
        top_items = sorted(item_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        # Build enriched top_items list: (name, qty, revenue)
        top_items_data = [(name, qty, item_revenue.get(name, 0.0)) for name, qty in top_items]

        # Voided orders count
        voided = conn.execute(
            f"SELECT COUNT(*) FROM orders WHERE {date_clause} AND status = 'voided'", date_args
        ).fetchone()[0]

        return render_template('reports.html',
            period=period, label=label,
            total_orders=total_orders, total_revenue=total_revenue, avg_ticket=avg_ticket,
            payment_split=payment_split,
            daily_trend=daily_trend,
            hourly=hourly,
            top_items=top_items,
            top_items_data=top_items_data,
            voided=voided,
            today_str=now.strftime('%Y-%m-%d'),
            selected_date=selected_date,
        )


    def _order_date_range(period, selected_date, now):
        """Return (start_str, end_str, label) for order history queries.

        Day-specific periods (today / custom) span the FULL calendar day
        (00:00:00–23:59:59) so Historial, reports() and the dashboard all agree
        and no order is ever hidden/unreachable.  Week starts Monday 00:00 and
        alltime both use an open upper bound (end_str = None).
        """
        if period == 'week':
            monday = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0)
            return monday.strftime('%Y-%m-%d %H:%M:%S'), None, 'Esta semana'

        if period == 'alltime':
            return '2000-01-01 00:00:00', None, 'Todo el tiempo'

        if period == 'custom' and selected_date:
            try:
                day = datetime.strptime(selected_date, '%Y-%m-%d')
            except ValueError:
                day = now
                selected_date = ''
            start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            end   = day.replace(hour=23, minute=59, second=59, microsecond=0)
            return start.strftime('%Y-%m-%d %H:%M:%S'), end.strftime('%Y-%m-%d %H:%M:%S'), selected_date or 'Hoy'

        # today (default)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end   = now.replace(hour=23, minute=59, second=59, microsecond=0)
        return start.strftime('%Y-%m-%d %H:%M:%S'), end.strftime('%Y-%m-%d %H:%M:%S'), 'Hoy'


    @app.route('/admin/orders')
    @login_required
    @admin_required
    def order_history():
        q             = request.args.get('q', '').strip()
        period        = request.args.get('period', 'today')
        selected_date = request.args.get('date', '')
        estado        = request.args.get('estado', '').strip()

        now = datetime.now()
        start_str, end_str, label = _order_date_range(period, selected_date, now)
        if period == 'custom' and not selected_date:
            period = 'today'

        conn = get_db_connection()

        conditions = ['date >= ?']
        params     = [start_str]
        if end_str:
            conditions.append('date <= ?')
            params.append(end_str)
        if q:
            conditions.append('(id LIKE ? OR customer_name LIKE ?)')
            params += [f'%{q}%', f'%{q}%']
        if estado == 'anuladas':
            conditions.append("status = 'voided'")
        elif estado == 'activas':
            conditions.append("status != 'voided'")

        where  = 'WHERE ' + ' AND '.join(conditions)

        # Period-wide aggregates over the FULL filtered range (independent of the
        # 500-row display cap) so summary + per-day totals reflect reality even
        # when more than 500 orders match.  Voided orders are excluded from the
        # money totals; the same param bindings are reused (no extra placeholder).
        totals_where = 'WHERE ' + ' AND '.join(conditions + ["status != 'voided'"])
        summary = conn.execute(
            f'SELECT COUNT(*) AS cnt, COALESCE(SUM(total),0) AS rev FROM orders {totals_where}',
            params
        ).fetchone()
        total_orders  = summary['cnt']
        total_revenue = summary['rev']
        daily_totals  = {
            r['day']: r['rev'] for r in conn.execute(
                f'SELECT substr(date,1,10) AS day, COALESCE(SUM(total),0) AS rev '
                f'FROM orders {totals_where} GROUP BY day', params
            ).fetchall()
        }

        # Rendered list is capped at 500 most-recent rows for performance.
        orders = conn.execute(
            f'SELECT * FROM orders {where} ORDER BY date DESC LIMIT 500', params
        ).fetchall()

        parsed = []
        for o in orders:
            items = []
            try:
                items = json.loads(o['items']) if o['items'] else []
            except json.JSONDecodeError:
                pass
            day = o['date'][:10] if o['date'] else ''
            parsed.append({'order': dict(o), 'items': items, 'day': day})

        return render_template('orders.html',
            orders=parsed, daily_totals=daily_totals,
            total_orders=total_orders, total_revenue=total_revenue,
            q=q, period=period, selected_date=selected_date, estado=estado,
            label=label, today_str=now.strftime('%Y-%m-%d'),
            estado_activas=(estado == 'activas'),
            estado_anuladas=(estado == 'anuladas'),
        )


    @app.route('/admin/void_order/<order_id>', methods=['POST'])
    @login_required
    @admin_required
    def void_order(order_id):
        conn = get_db_connection()
        cursor = conn.execute("UPDATE orders SET status = 'voided' WHERE id = ?", (order_id,))
        conn.commit()
        if cursor.rowcount == 0:
            flash('Orden no encontrada.', 'error')
            return redirect(url_for('order_history'))
        log_activity('orden_anulada', f'Orden #{order_id} anulada')
        flash(f'Orden {order_id} anulada.', 'success')
        return redirect(url_for('order_history'))


    @app.route('/admin/orders/delete/<order_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_order(order_id):
        conn = get_db_connection()
        conn.execute('DELETE FROM orders WHERE id = ?', (order_id,))
        conn.commit()
        flash(f'Orden {order_id} eliminada.', 'success')
        return redirect(url_for('order_history'))


    @app.route('/admin/orders/delete_selected', methods=['POST'])
    @login_required
    @admin_required
    def delete_orders_selected():
        order_ids = request.form.getlist('order_ids')
        if order_ids:
            conn = get_db_connection()
            conn.executemany('DELETE FROM orders WHERE id = ?', [(oid,) for oid in order_ids])
            conn.commit()
            flash(f'{len(order_ids)} orden(es) eliminada(s).', 'success')
        return redirect(url_for('order_history'))


    @app.route('/admin/orders/delete_all', methods=['POST'])
    @login_required
    @admin_required
    def delete_orders_all():
        q             = request.form.get('q', '').strip()
        period        = request.form.get('period', 'today')
        selected_date = request.form.get('date', '')
        estado        = request.form.get('estado', '').strip()

        now = datetime.now()
        start_str, end_str, _ = _order_date_range(period, selected_date, now)

        conditions = ['date >= ?']
        params     = [start_str]
        if end_str:
            conditions.append('date <= ?')
            params.append(end_str)
        if q:
            conditions.append('(id LIKE ? OR customer_name LIKE ?)')
            params += [f'%{q}%', f'%{q}%']
        if estado == 'anuladas':
            conditions.append("status = 'voided'")
        elif estado == 'activas':
            conditions.append("status != 'voided'")

        where  = 'WHERE ' + ' AND '.join(conditions)
        conn   = get_db_connection()
        cursor = conn.execute(f'DELETE FROM orders {where}', params)
        conn.commit()
        flash(f'{cursor.rowcount} orden(es) eliminada(s).', 'success')
        return redirect(url_for('order_history', q=q, period=period, date=selected_date, estado=estado))


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
        q             = request.args.get('q', '').strip()
        period        = request.args.get('period', 'today')
        selected_date = request.args.get('date', '')
        estado        = request.args.get('estado', '').strip()

        now = datetime.now()
        start_str, end_str, _ = _order_date_range(period, selected_date, now)

        conditions = ['date >= ?']
        params     = [start_str]
        if end_str:
            conditions.append('date <= ?')
            params.append(end_str)
        if q:
            conditions.append('(id LIKE ? OR customer_name LIKE ?)')
            params += [f'%{q}%', f'%{q}%']
        if estado == 'anuladas':
            conditions.append("status = 'voided'")
        elif estado == 'activas':
            conditions.append("status != 'voided'")

        where = 'WHERE ' + ' AND '.join(conditions)

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
