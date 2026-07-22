"""Payment, ticket processing, receipt printing, and print queue."""
import json
import os
import sqlite3
import uuid
from datetime import datetime

from flask import render_template, request, redirect, url_for, session, flash, jsonify

from auth import login_required
from db import get_db_connection, log_activity, get_config, get_item_price
from business import money


DEFAULT_USD_RATE = 18.0


def _api_autorizada():
    """Allow access from localhost (print bridge) or active session."""
    if request.remote_addr in ('127.0.0.1', '::1'):
        return True
    return 'user_id' in session


def _usd_rate():
    try:
        rate = float(get_config('usd_rate', str(DEFAULT_USD_RATE)))
    except (ValueError, TypeError):
        return DEFAULT_USD_RATE
    return rate if rate > 0 else DEFAULT_USD_RATE


def _issue_ticket_token():
    """Mint a one-use token for /ticket to prevent double-submit duplicates."""
    token = str(uuid.uuid4())
    session['ticket_token'] = token
    session.modified = True
    return token


def print_receipt_physical(cart, total, payment_method, amount_paid=0, change=0,
                           order_id=None, customer_name=None,
                           paid_currency='mxn', paid_amount_usd=0, usd_rate=0,
                           split_cash_mxn=None, split_card=None):
    receipt_content = []
    receipt_content.append(f"Orden #: {order_id or session.get('order_id')}")
    receipt_content.append(f"Cliente: {customer_name or 'Cliente'}")
    receipt_content.append("-" * 38)
    receipt_content.append("ARTICULO                PRECIO")
    receipt_content.append("-" * 38)

    for item in cart:
        quantity = item.get('quantity', 1)
        receipt_content.append(f"{item['name']} x{quantity:<2}      ${item['price']:.2f}")

        if item['type'] == 'Bebida':
            if item.get('beverage_type'):
                receipt_content.append(f"  {item['beverage_type']}")

        elif item['type'] == 'Boneless':
            if item.get('sauces'):
                receipt_content.append(f"  {', '.join(item['sauces'])}")
            elif item.get('sauce'):
                receipt_content.append(f"  {item['sauce']}")
            if item.get('accompaniment'):
                receipt_content.append(f"  {item['accompaniment']}")

        elif item['type'] == 'Complementos':
            if item.get('sauces'):
                receipt_content.append(f"  {', '.join(item['sauces'])}")
                sauce_count = len(item['sauces'])
                sauce_price = get_item_price('Complementos')
                receipt_content.append(f"  {sauce_count} x ${sauce_price:.0f} = ${sauce_count * sauce_price:.2f}")

        elif item['type'] in ('Bola de Arroz', 'Sushi'):
            _skip = {'queso', 'aguacate'}
            if 'ingredients' in item:
                filtered = [i for i in item['ingredients'] if i.lower() not in _skip]
                abbr = [i[:3] for i in filtered] if filtered else []
                if abbr:
                    receipt_content.append(f"  {', '.join(abbr)}")
                if item.get('ostion_cost', 0) > 0:
                    receipt_content.append(f"  Ostión: +${item['ostion_cost']:.2f}")
            if item.get('style'):
                receipt_content.append(f"  {item['style']}")
            if item.get('sauce'):
                receipt_content.append(f"  {item['sauce']}")
            if item.get('prepared'):
                receipt_content.append(f"  {item['prepared']}")
            if 'toppings' in item:
                topping_text = ', '.join(item['toppings']) if item['toppings'] else "Ninguno"
                receipt_content.append(f"  {topping_text}")

        if item.get('notes'):
            receipt_content.append(f"  Notas: {item['notes']}")
        receipt_content.append("-" * 38)

    receipt_content.append(f"TOTAL: ${total:.2f}")

    if payment_method == 'split' and amount_paid:
        if paid_currency == 'usd' and paid_amount_usd:
            receipt_content.append(f"EFECTIVO: US${paid_amount_usd:.2f} (TC ${usd_rate:.2f})")
            receipt_content.append(f"          = ${split_cash_mxn:.2f} MXN")
        else:
            receipt_content.append(f"EFECTIVO: ${split_cash_mxn:.2f}")
        receipt_content.append(f"TARJETA:  ${split_card:.2f}")
        if change:
            receipt_content.append(f"CAMBIO (MXN): ${change:.2f}")
    elif payment_method == 'cash' and amount_paid:
        if paid_currency == 'usd' and paid_amount_usd:
            receipt_content.append(f"PAGO: US${paid_amount_usd:.2f} (TC ${usd_rate:.2f})")
            receipt_content.append(f"      = ${amount_paid:.2f} MXN")
        else:
            receipt_content.append(f"PAGO: ${amount_paid:.2f}")
        if change:
            receipt_content.append(f"CAMBIO (MXN): ${change:.2f}")

    receipt_id = order_id or session.get('order_id')
    receipts_dir = os.path.join(os.getcwd(), 'receipts')
    os.makedirs(receipts_dir, exist_ok=True)
    receipt_path = os.path.join(receipts_dir, f"receipt_{receipt_id}.txt")
    receipt_text = "\n".join(receipt_content)
    with open(receipt_path, "w", encoding="utf-8") as f:
        f.write(receipt_text)
    return receipt_path, receipt_text


def register(app, csrf):
    @app.route('/payment')
    @login_required
    def payment():
        cart = session.get('cart', [])
        if not cart:
            flash('Agrega al menos un ítem antes de proceder al pago.', 'error')
            return redirect(url_for('home'))
        total_price = money(sum(item['price'] for item in cart))
        return render_template('payment.html', total_price=total_price,
                               ticket_token=_issue_ticket_token())

    @app.route('/cash_payment')
    @login_required
    def cash_payment():
        cart = session.get('cart', [])
        if not cart:
            flash('Agrega al menos un ítem antes de proceder al pago.', 'error')
            return redirect(url_for('home'))
        total_price = money(sum(item['price'] for item in cart))
        return render_template('cash_payment.html', total_price=total_price,
                               usd_rate=_usd_rate(),
                               ticket_token=_issue_ticket_token())

    @app.route('/split_payment')
    @login_required
    def split_payment():
        cart = session.get('cart', [])
        total_price = money(sum(item['price'] for item in cart))
        return render_template('split_payment.html', total_price=total_price,
                               usd_rate=_usd_rate(),
                               ticket_token=_issue_ticket_token())

    @app.route('/ticket', methods=['POST'])
    @login_required
    def ticket():
        cart = session.get('cart', [])
        if not cart:
            flash('Agrega al menos un ítem antes de proceder al pago.', 'error')
            return redirect(url_for('home'))

        session_token = session.get('ticket_token')
        if session_token is not None:
            if request.form.get('ticket_token') != session_token:
                flash('Esta orden ya fue procesada.', 'error')
                return redirect(url_for('home'))
            session.pop('ticket_token', None)

        total_price = money(sum(item['price'] for item in cart))
        payment_method = request.form.get('payment_method', 'card')

        paid_currency = request.form.get('currency', 'mxn').lower()
        if paid_currency not in ('mxn', 'usd'):
            paid_currency = 'mxn'
        paid_amount_usd = 0.0
        usd_rate_used = 0.0

        try:
            amount_paid = money(float(request.form.get('amount_paid', total_price)))
        except (ValueError, TypeError):
            amount_paid = total_price
            paid_currency = 'mxn'

        if payment_method == 'cash' and paid_currency == 'usd':
            usd_rate_used = _usd_rate()
            paid_amount_usd = amount_paid
            amount_paid = money(paid_amount_usd * usd_rate_used)

        change = money(amount_paid - total_price) if payment_method == 'cash' else 0

        if payment_method == 'cash' and amount_paid < total_price:
            flash(f'Pago insuficiente. Se recibió ${amount_paid:.2f} de ${total_price:.2f}.', 'error')
            return redirect(url_for('view_cart'))

        split_cash_mxn = None
        split_card = None
        if payment_method == 'split':
            try:
                cash_portion = float(request.form.get('cash_portion', 0))
                card_portion = float(request.form.get('card_portion', 0))
            except (ValueError, TypeError):
                cash_portion = 0.0
                card_portion = 0.0
            if cash_portion < 0 or card_portion < 0:
                flash('Los montos de pago no pueden ser negativos.', 'error')
                return redirect(url_for('view_cart'))
            if money(card_portion) > total_price:
                flash('El monto con tarjeta no puede exceder el total.', 'error')
                return redirect(url_for('view_cart'))
            cash_currency = request.form.get('cash_currency', 'mxn').lower()
            if cash_currency == 'usd' and cash_portion > 0:
                usd_rate_used = _usd_rate()
                paid_amount_usd = money(cash_portion)
                paid_currency = 'usd'
                cash_portion = money(paid_amount_usd * usd_rate_used)
            else:
                paid_currency = 'mxn'
                cash_portion = money(cash_portion)
            amount_paid = money(cash_portion + card_portion)
            if amount_paid < total_price:
                flash(f'Pago insuficiente. Se recibió ${amount_paid:.2f} de ${total_price:.2f}.', 'error')
                return redirect(url_for('view_cart'))
            change = money(max(0, amount_paid - total_price))
            split_cash_mxn = cash_portion
            split_card = money(card_portion)

        order_id = session.get('order_id')
        customer_name = session.get('customer_name', 'Cliente')

        conn = None
        try:
            conn = get_db_connection()
            for _intento in range(5):
                try:
                    conn.execute(
                        'INSERT INTO orders (id, items, total, payment_method, amount_paid, '
                        'change_amount, date, status, customer_name, paid_currency, '
                        'paid_amount_usd, usd_rate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (order_id, json.dumps(cart), total_price, payment_method,
                         amount_paid, change,
                         datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                         'completed', customer_name, paid_currency, paid_amount_usd, usd_rate_used)
                    )
                    break
                except sqlite3.IntegrityError:
                    if _intento == 4:
                        raise
                    order_id = str(uuid.uuid4())[:8]

            held_id = session.pop('held_id', None)
            if held_id:
                conn.execute('DELETE FROM held_orders WHERE id = ?', (held_id,))
            conn.commit()

            receipt_file_success = False
            try:
                receipt_path, receipt_text = print_receipt_physical(
                    cart, total_price, payment_method, amount_paid, change,
                    order_id, customer_name,
                    paid_currency=paid_currency, paid_amount_usd=paid_amount_usd,
                    usd_rate=usd_rate_used, split_cash_mxn=split_cash_mxn,
                    split_card=split_card)
                receipt_file_success = True
                conn.execute(
                    "INSERT OR IGNORE INTO print_jobs (id, receipt_content, status, created_at) "
                    "VALUES (?, ?, 'pending', ?)",
                    (order_id, receipt_text, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                )
                conn.commit()
            except Exception as e:
                print(f"Error saving receipt: {e}")

            log_activity('orden_completada',
                         f'Orden #{order_id} — {customer_name} — ${total_price:.2f} ({payment_method})')
            session['cart'] = []
            session['order_id'] = str(uuid.uuid4())[:8]
            session['customer_name'] = ''
            session.pop('coupon_code', None)
            session['ticket_token'] = str(uuid.uuid4())
            session.modified = True

            job_status = 'none'
            if receipt_file_success:
                job_row = conn.execute(
                    "SELECT status FROM print_jobs WHERE id = ?", (order_id,)
                ).fetchone()
                job_status = job_row['status'] if job_row else 'none'

            return render_template('thank_you.html', order_id=order_id,
                                   print_success=receipt_file_success,
                                   job_status=job_status)

        except Exception as e:
            flash(f"Error al guardar la orden: {e}", "error")
            print(f"Error al guardar la orden: {e}")
            if conn:
                conn.rollback()
            return redirect(url_for('view_cart'))

    @app.route('/api/print_queue')
    @csrf.exempt
    def get_print_queue():
        if not _api_autorizada():
            return jsonify({'error': 'No autorizado'}), 401
        conn = get_db_connection()
        jobs = conn.execute(
            "SELECT id, receipt_content, status, created_at FROM print_jobs "
            "WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
        return jsonify({'jobs': [dict(j) for j in jobs]})

    @app.route('/api/mark_printed/<job_id>', methods=['POST'])
    @csrf.exempt
    def mark_printed(job_id):
        if not _api_autorizada():
            return jsonify({'error': 'No autorizado'}), 401
        conn = get_db_connection()
        conn.execute("UPDATE print_jobs SET status = 'printed' WHERE id = ?", (job_id,))
        conn.commit()
        return jsonify({'ok': True})

    @app.route('/api/config/printer', methods=['POST'])
    @csrf.exempt
    def update_printer_api():
        if not _api_autorizada():
            return jsonify({'error': 'No autorizado'}), 401
        data = request.get_json(silent=True) or {}
        printer_name = data.get('printer_name', '').strip()
        if not printer_name:
            return jsonify({'error': 'printer_name required'}), 400
        conn = get_db_connection()
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES ('printer_name', ?)",
            (printer_name,)
        )
        conn.commit()
        return jsonify({'ok': True, 'printer_name': printer_name})
