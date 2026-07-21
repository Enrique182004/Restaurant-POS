"""Inventario — proxy al microservicio Java de inventario (admin)."""
import os

import requests
from flask import render_template, request, jsonify

from auth import login_required, admin_required

JAVA_INVENTORY_SERVICE = os.environ.get('JAVA_SERVICE_URL', 'http://localhost:8081')


def register(app):
    @app.route('/inventory')
    @login_required
    @admin_required
    def inventory_page():
        try:
            # Call Java inventory service
            response = requests.get(f'{JAVA_INVENTORY_SERVICE}/api/inventory', timeout=5)
            items = response.json() if response.status_code == 200 else []
        except requests.exceptions.RequestException as e:
            print(f"Error connecting to inventory service: {e}")
            items = []
    
        return render_template('inventory.html', items=items)


    @app.route('/inventory/low-stock')
    @login_required
    @admin_required
    def low_stock():
        try:
            response = requests.get(f'{JAVA_INVENTORY_SERVICE}/api/inventory/low-stock', timeout=5)
            items = response.json() if response.status_code == 200 else []
        except requests.exceptions.RequestException as e:
            print(f"Error connecting to inventory service: {e}")
            items = []
    
        return render_template('inventory.html', items=items, low_stock_only=True)


    @app.route('/inventory/update/<int:item_id>', methods=['POST'])
    @login_required
    @admin_required
    def update_inventory_item(item_id):
        try:
            data = request.get_json()
        
            # Get current item first
            current_response = requests.get(
                f'{JAVA_INVENTORY_SERVICE}/api/inventory/{item_id}',
                timeout=5
            )
        
            if current_response.status_code != 200:
                return jsonify({'success': False, 'error': f'Producto no encontrado (código {current_response.status_code})'})

            current_item = current_response.json()
            current_item['quantity'] = data.get('quantity', current_item['quantity'])
            current_item['minThreshold'] = data.get('minThreshold', current_item['minThreshold'])

            response = requests.put(
                f'{JAVA_INVENTORY_SERVICE}/api/inventory/{item_id}',
                json=current_item,
                timeout=5
            )
            if response.status_code == 200:
                updated = response.json()
                return jsonify({
                    'success': True,
                    'quantity': updated.get('quantity'),
                    'minThreshold': updated.get('minThreshold'),
                })
            return jsonify({'success': False, 'error': f'Error al guardar en Java (código {response.status_code})'})
        except requests.exceptions.RequestException as e:
            return jsonify({'success': False, 'error': f'Sin conexión al servicio de inventario: {e}'})


    @app.route('/inventory/add', methods=['POST'])
    @login_required
    @admin_required
    def add_inventory_item():
        """
        Inserta directamente en SQLite. El servicio Java usa getGeneratedKeys()
        después del INSERT, lo cual no está implementado en el driver SQLite JDBC,
        causando un 500. Flask + sqlite3 no tiene ese problema.
        """
        try:
            data = request.get_json() or {}
            name = (data.get('name') or '').strip()
            quantity = int(data.get('quantity', 0))
            min_threshold = int(data.get('minThreshold', 0))
            unit = (data.get('unit') or 'piezas').strip()

            if not name:
                return jsonify({'success': False, 'error': 'El nombre es requerido'})

            conn = get_db_connection()
            conn.execute(
                'INSERT INTO inventory (name, quantity, min_threshold, unit) VALUES (?, ?, ?, ?)',
                (name, quantity, min_threshold, unit)
            )
            conn.commit()
            return jsonify({'success': True})
        except Exception as e:
            err = str(e)
            if 'UNIQUE' in err or 'unique' in err:
                return jsonify({'success': False, 'error': f'Ya existe un ingrediente con ese nombre'})
            return jsonify({'success': False, 'error': err})


    @app.route('/inventory/delete/<int:item_id>', methods=['DELETE'])
    @login_required
    @admin_required
    def delete_inventory_item(item_id):
        try:
            response = requests.delete(
                f'{JAVA_INVENTORY_SERVICE}/api/inventory/{item_id}',
                timeout=5
            )
            return jsonify({'success': response.status_code == 200})
        except requests.exceptions.RequestException as e:
            return jsonify({'success': False, 'error': str(e)})
