"""Customize routes — order-building for each item type."""
from flask import render_template, request, redirect, url_for, session, flash

from auth import login_required
from db import get_db_connection, get_item_price, get_menu_options, get_sushi_prep_prices


def _beverage_list():
    options = get_menu_options('beverage')
    conn = get_db_connection()
    result = []
    for o in options:
        price_row = conn.execute('SELECT price FROM menu_prices WHERE key=?', (o['name'],)).fetchone()
        price = price_row['price'] if price_row else o['price']
        result.append({'id': o['name'].lower().replace(' ', '_'), 'name': o['name'],
                       'icon': o['icon'], 'price': price})
    return result


def _calc_rice_ball_price(ingredients):
    ostion_count = sum(1 for i in ingredients if i == 'Ostión')
    base  = get_item_price('Bola de Arroz')
    extra = ostion_count * get_item_price('Ostión')
    return base, extra, base + extra


def _calc_sushi_price(ingredients, prepared):
    ostion_count = sum(1 for i in ingredients if i == 'Ostión')
    base  = get_item_price('Sushi', prepared)
    extra = ostion_count * get_item_price('Ostión')
    return base, extra, base + extra


def _rice_template_ctx(item=None, item_index=None):
    return dict(item=item, item_index=item_index,
                rice_ingredients=get_menu_options('rice_ingredient'),
                rice_sauces=get_menu_options('rice_sauce'),
                base_price=get_item_price('Bola de Arroz'),
                ostion_price=get_item_price('Ostión'))


def _sushi_template_ctx(item=None, item_index=None):
    return dict(item=item, item_index=item_index,
                sushi_ingredients=get_menu_options('sushi_ingredient'),
                sushi_sauces=get_menu_options('sushi_sauce'),
                sushi_prep_prices=get_sushi_prep_prices(),
                ostion_price=get_item_price('Ostión'))


def register(app):
    @app.route('/customize/beverages', methods=['GET', 'POST'])
    @login_required
    def customize_beverages():
        if request.method == 'POST':
            beverage_type = request.form.get('beverage_type')
            notes = request.form.get('notes', '')
            if not beverage_type:
                flash('Por favor selecciona una bebida.', 'error')
                return render_template('beverages.html', item=None, beverages=_beverage_list())
            price = get_item_price(beverage_type)
            item = {
                'name': 'Bebida', 'type': 'Bebida',
                'beverage_type': beverage_type, 'price': price,
                'unit_price': price, 'quantity': 1, 'notes': notes,
            }
            session['cart'].append(item)
            session.modified = True
            flash('¡Bebida agregada a la orden!', 'success')
            return redirect(url_for('home'))
        return render_template('beverages.html', item=None, beverages=_beverage_list())

    @app.route('/customize/boneless', methods=['GET', 'POST'])
    @login_required
    def customize_boneless():
        if request.method == 'POST':
            sauces = request.form.getlist('sauce')
            accompaniment = request.form.get('accompaniment')
            notes = request.form.get('notes', '')
            if not sauces:
                flash('Por favor selecciona al menos una salsa.', 'error')
                return render_template('boneless.html', item=None,
                                       boneless_sauces=get_menu_options('boneless_sauce'))
            base_price = get_item_price('Boneless')
            item = {
                'name': 'Boneless', 'type': 'Boneless',
                'price': base_price, 'unit_price': base_price, 'quantity': 1,
                'sauces': sauces, 'accompaniment': accompaniment, 'notes': notes,
            }
            session['cart'].append(item)
            session.modified = True
            flash('¡Boneless agregado a la orden!', 'success')
            return redirect(url_for('home'))
        return render_template('boneless.html', item=None,
                               boneless_sauces=get_menu_options('boneless_sauce'))

    @app.route('/customize/complementos', methods=['GET', 'POST'])
    @login_required
    def customize_complementos():
        if request.method == 'POST':
            sauces = request.form.getlist('sauces')
            notes = request.form.get('notes', '')
            if not sauces:
                flash('Por favor selecciona al menos una salsa extra.', 'error')
                return render_template('complementos.html', item=None,
                                       extra_sauces=get_menu_options('extra_sauce'),
                                       sauce_price=get_item_price('Complementos'))
            sauce_count = len(sauces)
            sauce_unit = get_item_price('Complementos')
            total_price = sauce_count * sauce_unit
            item = {
                'name': 'Complementos', 'type': 'Complementos',
                'price': total_price, 'unit_price': total_price, 'quantity': 1,
                'sauces': sauces, 'notes': notes, 'sauce_count': sauce_count,
            }
            session['cart'].append(item)
            session.modified = True
            flash('¡Complementos agregados a la orden!', 'success')
            return redirect(url_for('home'))
        return render_template('complementos.html', item=None,
                               extra_sauces=get_menu_options('extra_sauce'),
                               sauce_price=get_item_price('Complementos'))

    @app.route('/customize/rice_ball', methods=['GET', 'POST'])
    @login_required
    def customize_rice_ball():
        if request.method == 'POST':
            base       = request.form.getlist('base')
            ingredients = request.form.getlist('ingredients')
            style      = request.form.get('style')
            sauce      = request.form.get('sauce')
            toppings   = request.form.getlist('toppings')
            notes      = request.form.get('notes', '')

            if not style:
                flash('Por favor selecciona si deseas tu bola de arroz Fría o Empanizada.', 'error')
                return render_template('rice_ball.html', item=None)
            if not sauce:
                flash('Por favor selecciona una salsa.', 'error')
                return render_template('rice_ball.html', item=None)

            regular_ingredients = [i for i in ingredients if i != 'Ostión']
            ostion_ingredients  = [i for i in ingredients if i == 'Ostión']

            if len(regular_ingredients) > 6:
                flash('Máximo 6 ingredientes regulares permitidos', 'error')
                return render_template('rice_ball.html', **_rice_template_ctx())
            if len(regular_ingredients) < 1:
                flash('Selecciona al menos 1 ingrediente', 'error')
                return render_template('rice_ball.html', **_rice_template_ctx())
            if len(ostion_ingredients) > 1:
                flash('Solo puedes agregar un Ostión', 'error')
                return render_template('rice_ball.html', **_rice_template_ctx())

            base_price, ostion_price, total_price = _calc_rice_ball_price(ingredients)
            item = {
                'name': 'Bola de Arroz', 'type': 'Bola de Arroz',
                'price': total_price, 'unit_price': total_price, 'quantity': 1,
                'base': base, 'ingredients': ingredients, 'style': style,
                'sauce': sauce, 'toppings': toppings, 'notes': notes,
                'ostion_cost': ostion_price,
            }
            session['cart'].append(item)
            session.modified = True
            flash('¡Bola de Arroz agregada a la orden!', 'success')
            return redirect(url_for('home'))

        return render_template('rice_ball.html', item=None,
                               rice_ingredients=get_menu_options('rice_ingredient'),
                               rice_sauces=get_menu_options('rice_sauce'),
                               base_price=get_item_price('Bola de Arroz'),
                               ostion_price=get_item_price('Ostión'))

    @app.route('/customize/sushi', methods=['GET', 'POST'])
    @login_required
    def customize_sushi():
        if request.method == 'POST':
            base       = request.form.getlist('base')
            ingredients = request.form.getlist('ingredients')
            style      = request.form.get('style')
            prepared   = request.form.get('prepared')
            sauce      = request.form.get('sauce') or prepared
            toppings   = request.form.getlist('toppings')
            notes      = request.form.get('notes', '')

            if not style:
                flash('Por favor selecciona si deseas tu sushi Frío o Empanizado.', 'error')
                return render_template('sushi.html', **_sushi_template_ctx())
            if not prepared:
                flash('Por favor selecciona una opción de preparado.', 'error')
                return render_template('sushi.html', **_sushi_template_ctx())

            regular_ingredients = [i for i in ingredients if i != 'Ostión']
            ostion_ingredients  = [i for i in ingredients if i == 'Ostión']

            if len(regular_ingredients) > 3:
                flash('Máximo 3 ingredientes regulares permitidos', 'error')
                return render_template('sushi.html', **_sushi_template_ctx())
            if len(regular_ingredients) < 1:
                flash('Selecciona al menos 1 ingrediente', 'error')
                return render_template('sushi.html', **_sushi_template_ctx())
            if len(ostion_ingredients) > 1:
                flash('Solo puedes agregar un Ostión', 'error')
                return render_template('sushi.html', **_sushi_template_ctx())

            base_price, ostion_price, total_price = _calc_sushi_price(ingredients, prepared)
            item = {
                'name': 'Sushi', 'type': 'Sushi',
                'price': total_price, 'unit_price': total_price, 'quantity': 1,
                'base': base, 'ingredients': ingredients, 'style': style,
                'prepared': prepared, 'sauce': sauce, 'toppings': toppings,
                'notes': notes, 'ostion_cost': ostion_price,
            }
            session['cart'].append(item)
            session.modified = True
            flash('¡Sushi agregado a la orden!', 'success')
            return redirect(url_for('home'))

        return render_template('sushi.html', **_sushi_template_ctx())
