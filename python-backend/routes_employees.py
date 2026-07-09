"""Empleados: altas, horarios, asistencia y nómina (admin)."""
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
