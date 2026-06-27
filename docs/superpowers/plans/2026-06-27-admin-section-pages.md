# Split Admin Dashboard Sections Into Their Own Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Gestión de Precios, Opciones del Menú, and Promociones off the main admin dashboard into their own pages, each reached via a nav-card, matching the existing Reportes/Historial/Inventario/Usuarios/Empleados pattern.

**Architecture:** Three new `GET` routes in `app.py`, each rendering a new self-contained template (own `<style>` block, same dark/orange theme). The existing POST handlers (add/delete/toggle/update) keep their exact logic — only their redirect target changes from `admin_dashboard` to the new page that now owns that section. `admin_dashboard()` and `admin_dashboard.html` lose the three sections' data-fetching, markup, and section-specific CSS once the new pages are confirmed working.

**Tech Stack:** Flask, raw `sqlite3`, Jinja2 templates — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-27-admin-section-pages-design.md`

---

## Task 1: Gestión de Precios page

**Files:**

- Modify: `python-backend/app.py`
- Create: `python-backend/templates/prices.html`
- Modify: `python-backend/templates/admin_dashboard.html` (add nav-card only — old section stays for now, removed in Task 4)
- Create: `python-backend/tests/test_route_manage_prices.py`

- [ ] **Step 1: Write the failing tests**

Create `python-backend/tests/test_route_manage_prices.py`:

```python
def test_manage_prices_page_loads_for_admin(admin_client):
    resp = admin_client.get("/admin/prices")
    assert resp.status_code == 200
    assert "Gestión de Precios".encode("utf-8") in resp.data


def test_manage_prices_blocks_non_admin(client):
    client.post("/login", data={"username": "user", "password": "user123"})
    resp = client.get("/admin/prices")
    assert resp.status_code == 302


def test_update_prices_redirects_to_manage_prices(admin_client, app_module):
    conn = app_module.get_db_connection()
    a_key = conn.execute("SELECT key FROM menu_prices LIMIT 1").fetchone()["key"]
    resp = admin_client.post("/admin/prices/update", data={a_key: "99.50"})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/prices"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && ./venv/bin/python -m pytest tests/test_route_manage_prices.py -v`
Expected: FAIL — `test_manage_prices_page_loads_for_admin` and `test_manage_prices_blocks_non_admin` fail with 404 (route doesn't exist yet); `test_update_prices_redirects_to_manage_prices` fails because `resp.headers["Location"]` is `/admin` not `/admin/prices`.

- [ ] **Step 3: Add the route and fix `update_prices`'s redirect**

In `python-backend/app.py`, find this exact block:

```python
@app.route('/admin/prices/update', methods=['POST'])
@login_required
@admin_required
def update_prices():
    conn = get_db_connection()
    for key, value in request.form.items():
        try:
            conn.execute('UPDATE menu_prices SET price = ? WHERE key = ?', (float(value), key))
        except (ValueError, sqlite3.Error):
            pass
    conn.commit()
    flash('Precios actualizados correctamente.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/reports')
```

Replace it with:

```python
@app.route('/admin/prices/update', methods=['POST'])
@login_required
@admin_required
def update_prices():
    conn = get_db_connection()
    for key, value in request.form.items():
        try:
            conn.execute('UPDATE menu_prices SET price = ? WHERE key = ?', (float(value), key))
        except (ValueError, sqlite3.Error):
            pass
    conn.commit()
    flash('Precios actualizados correctamente.', 'success')
    return redirect(url_for('manage_prices'))


@app.route('/admin/prices')
@login_required
@admin_required
def manage_prices():
    conn = get_db_connection()
    prices = conn.execute('SELECT * FROM menu_prices ORDER BY label').fetchall()
    return render_template('prices.html', prices=prices)


@app.route('/admin/reports')
```

- [ ] **Step 4: Create the template**

Create `python-backend/templates/prices.html`:

```html
{% extends 'base.html' %} {% block title %}Gestión de Precios{% endblock %} {%
block styles %}
<style>
  .page-wrap {
    max-width: 700px;
    margin: 0 auto;
    padding: 24px 20px 60px;
  }
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 28px;
  }
  .page-title-txt {
    font-size: 1.8rem;
    font-weight: 800;
    color: #ff9800;
    margin: 0;
  }
  .back-btn {
    color: #aaa;
    text-decoration: none;
    font-size: 0.9rem;
    border: 1px solid #333;
    padding: 8px 16px;
    border-radius: 10px;
    background: #1e1e1e;
  }
  .back-btn:hover {
    border-color: #ff9800;
    color: #ff9800;
  }
  .alert {
    padding: 12px 18px;
    border-radius: 10px;
    margin-bottom: 16px;
    font-weight: 600;
    font-size: 0.95rem;
  }
  .alert-success {
    background: rgba(43, 138, 62, 0.2);
    color: #81c784;
    border: 1px solid rgba(43, 138, 62, 0.35);
  }
  .alert-error {
    background: rgba(231, 76, 60, 0.2);
    color: #ff8a80;
    border: 1px solid rgba(231, 76, 60, 0.35);
  }
  .prices-card {
    background: #1e1e1e;
    border-radius: 16px;
    padding: 6px 0;
    border: 2px solid #2a2a2a;
    overflow: hidden;
  }
  .price-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 20px;
    border-bottom: 1px solid #2a2a2a;
    gap: 12px;
  }
  .price-row:last-of-type {
    border-bottom: none;
  }
  .price-label {
    font-size: 0.95rem;
    color: #e0e0e0;
    font-weight: 500;
    flex: 1;
  }
  .price-input-wrap {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .price-prefix {
    color: #ff9800;
    font-size: 1rem;
    font-weight: 700;
  }
  .price-input {
    width: 90px;
    padding: 8px 10px;
    border: 1px solid #3d3d3d;
    border-radius: 10px;
    font-size: 1rem;
    text-align: right;
    background: #2d2d2d;
    color: #f5f5f5;
    font-weight: 600;
    transition: border-color 0.2s;
  }
  .price-input:focus {
    outline: none;
    border-color: #ff9800;
  }
  .save-prices-btn {
    display: block;
    margin: 16px 20px 20px;
    width: calc(100% - 40px);
    padding: 13px;
    background: #ff9800;
    color: #121212;
    border: none;
    border-radius: 12px;
    font-size: 1rem;
    font-weight: 800;
    cursor: pointer;
    transition: background 0.2s;
    letter-spacing: 0.02em;
  }
  .save-prices-btn:hover {
    background: #e68900;
  }
</style>
{% endblock %} {% block body %}
<div class="page-wrap">
  <div class="page-header">
    <h1 class="page-title-txt">💲 Gestión de Precios</h1>
    <a href="{{ url_for('admin_dashboard') }}" class="back-btn">← Panel</a>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %} {% if
  messages %}{% for cat, msg in messages %}
  <div class="alert alert-{{ cat }}">{{ msg }}</div>
  {% endfor %}{% endif %} {% endwith %}

  <div class="prices-card">
    <form method="POST" action="{{ url_for('update_prices') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />
      {% for p in prices %}
      <div class="price-row">
        <span class="price-label">{{ p.label }}</span>
        <div class="price-input-wrap">
          <span class="price-prefix">$</span>
          <input
            type="number"
            class="price-input"
            name="{{ p.key }}"
            value="{{ p.price }}"
            min="0"
            step="0.50"
            required
          />
        </div>
      </div>
      {% endfor %}
      <button type="submit" class="save-prices-btn">Guardar Precios</button>
    </form>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Add the nav-card**

In `python-backend/templates/admin_dashboard.html`, find:

```html
    <a href="{{ url_for('employees_attendance') }}" class="nav-card">
      <div class="nav-card-icon">💰</div>
      <div class="nav-card-name">Empleados</div>
      <div class="nav-card-desc">Asistencia y pagos</div>
    </a>
  </div>
```

Replace it with:

```html
    <a href="{{ url_for('employees_attendance') }}" class="nav-card">
      <div class="nav-card-icon">💰</div>
      <div class="nav-card-name">Empleados</div>
      <div class="nav-card-desc">Asistencia y pagos</div>
    </a>
    <a href="{{ url_for('manage_prices') }}" class="nav-card">
      <div class="nav-card-icon">💲</div>
      <div class="nav-card-name">Precios</div>
      <div class="nav-card-desc">Gestión de precios</div>
    </a>
  </div>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd python-backend && ./venv/bin/python -m pytest tests/test_route_manage_prices.py -v`
Expected: 3 passed

- [ ] **Step 7: Run the full suite**

Run: `cd python-backend && ./venv/bin/python -m pytest tests/ -v`
Expected: all previously-passing tests still pass, plus the 3 new ones.

- [ ] **Step 8: Commit**

```bash
git add python-backend/app.py python-backend/templates/prices.html python-backend/templates/admin_dashboard.html python-backend/tests/test_route_manage_prices.py
git commit -m "feat: add standalone Gestión de Precios page"
```

---

## Task 2: Opciones del Menú page

**Files:**

- Modify: `python-backend/app.py`
- Create: `python-backend/templates/menu_options.html`
- Modify: `python-backend/templates/admin_dashboard.html` (add nav-card only)
- Create: `python-backend/tests/test_route_manage_menu_options.py`

- [ ] **Step 1: Write the failing tests**

Create `python-backend/tests/test_route_manage_menu_options.py`:

```python
def test_manage_menu_options_page_loads_for_admin(admin_client):
    resp = admin_client.get("/admin/menu-options")
    assert resp.status_code == 200
    assert "Opciones del Menú".encode("utf-8") in resp.data


def test_manage_menu_options_blocks_non_admin(client):
    client.post("/login", data={"username": "user", "password": "user123"})
    resp = client.get("/admin/menu-options")
    assert resp.status_code == 302


def test_add_menu_option_redirects_to_manage_menu_options(admin_client):
    resp = admin_client.post(
        "/admin/menu-options/add",
        data={"category": "beverage", "name": "Limonada", "icon": "🍋", "price": "20"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/menu-options"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && ./venv/bin/python -m pytest tests/test_route_manage_menu_options.py -v`
Expected: FAIL — page-load and non-admin tests fail with 404; redirect test fails because Location is `/admin` not `/admin/menu-options`.

- [ ] **Step 3: Add the route and fix the three redirect targets**

In `python-backend/app.py`, find this exact block:

```python
@app.route('/admin/menu-options/add', methods=['POST'])
@login_required
@admin_required
def add_menu_option():
    category = request.form.get('category', '').strip()
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', '🍽️').strip() or '🍽️'
    try:
        price = float(request.form.get('price', 0) or 0)
    except ValueError:
        price = 0.0

    if not name or not category:
        flash('Nombre y categoría son requeridos', 'error')
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    existing = conn.execute(
        'SELECT id FROM menu_options WHERE category=? AND name=?', (category, name)
    ).fetchone()
    if existing:
        conn.execute('UPDATE menu_options SET active=1 WHERE id=?', (existing['id'],))
    else:
        max_sort = conn.execute(
            'SELECT COALESCE(MAX(sort_order),0) FROM menu_options WHERE category=?', (category,)
        ).fetchone()[0]
        conn.execute(
            'INSERT INTO menu_options (category, name, icon, price, sort_order) VALUES (?, ?, ?, ?, ?)',
            (category, name, icon, price, max_sort + 1)
        )
        # Sync new beverages to menu_prices so get_item_price works immediately
        if category == 'beverage':
            conn.execute(
                'INSERT OR IGNORE INTO menu_prices (key, label, price) VALUES (?, ?, ?)',
                (name, name, price)
            )
    conn.commit()
    flash(f'"{name}" agregado al menú', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/menu-options/delete/<int:option_id>', methods=['POST'])
@login_required
@admin_required
def delete_menu_option(option_id):
    conn = get_db_connection()
    option = conn.execute('SELECT * FROM menu_options WHERE id=?', (option_id,)).fetchone()
    if option:
        conn.execute('DELETE FROM menu_options WHERE id=?', (option_id,))
        conn.commit()
        flash(f'"{option["name"]}" eliminado del menú', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/menu-options/toggle/<int:option_id>', methods=['POST'])
@login_required
@admin_required
def toggle_menu_option(option_id):
    conn = get_db_connection()
    option = conn.execute('SELECT * FROM menu_options WHERE id=?', (option_id,)).fetchone()
    if option:
        new_active = 0 if option['active'] else 1
        conn.execute('UPDATE menu_options SET active=? WHERE id=?', (new_active, option_id))
        conn.commit()
        status = 'activado' if new_active else 'desactivado'
        flash(f'"{option["name"]}" {status}', 'success')
    return redirect(url_for('admin_dashboard'))
```

Replace it with (note: ONLY the three `return redirect(url_for('admin_dashboard'))` calls inside `add_menu_option`, `delete_menu_option`, and `toggle_menu_option` change to `url_for('manage_menu_options')`; everything else is byte-for-byte identical, plus the new route is appended at the end):

```python
@app.route('/admin/menu-options/add', methods=['POST'])
@login_required
@admin_required
def add_menu_option():
    category = request.form.get('category', '').strip()
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', '🍽️').strip() or '🍽️'
    try:
        price = float(request.form.get('price', 0) or 0)
    except ValueError:
        price = 0.0

    if not name or not category:
        flash('Nombre y categoría son requeridos', 'error')
        return redirect(url_for('manage_menu_options'))

    conn = get_db_connection()
    existing = conn.execute(
        'SELECT id FROM menu_options WHERE category=? AND name=?', (category, name)
    ).fetchone()
    if existing:
        conn.execute('UPDATE menu_options SET active=1 WHERE id=?', (existing['id'],))
    else:
        max_sort = conn.execute(
            'SELECT COALESCE(MAX(sort_order),0) FROM menu_options WHERE category=?', (category,)
        ).fetchone()[0]
        conn.execute(
            'INSERT INTO menu_options (category, name, icon, price, sort_order) VALUES (?, ?, ?, ?, ?)',
            (category, name, icon, price, max_sort + 1)
        )
        # Sync new beverages to menu_prices so get_item_price works immediately
        if category == 'beverage':
            conn.execute(
                'INSERT OR IGNORE INTO menu_prices (key, label, price) VALUES (?, ?, ?)',
                (name, name, price)
            )
    conn.commit()
    flash(f'"{name}" agregado al menú', 'success')
    return redirect(url_for('manage_menu_options'))

@app.route('/admin/menu-options/delete/<int:option_id>', methods=['POST'])
@login_required
@admin_required
def delete_menu_option(option_id):
    conn = get_db_connection()
    option = conn.execute('SELECT * FROM menu_options WHERE id=?', (option_id,)).fetchone()
    if option:
        conn.execute('DELETE FROM menu_options WHERE id=?', (option_id,))
        conn.commit()
        flash(f'"{option["name"]}" eliminado del menú', 'success')
    return redirect(url_for('manage_menu_options'))

@app.route('/admin/menu-options/toggle/<int:option_id>', methods=['POST'])
@login_required
@admin_required
def toggle_menu_option(option_id):
    conn = get_db_connection()
    option = conn.execute('SELECT * FROM menu_options WHERE id=?', (option_id,)).fetchone()
    if option:
        new_active = 0 if option['active'] else 1
        conn.execute('UPDATE menu_options SET active=? WHERE id=?', (new_active, option_id))
        conn.commit()
        status = 'activado' if new_active else 'desactivado'
        flash(f'"{option["name"]}" {status}', 'success')
    return redirect(url_for('manage_menu_options'))

@app.route('/admin/menu-options')
@login_required
@admin_required
def manage_menu_options():
    conn = get_db_connection()
    categories = ['beverage', 'boneless_sauce', 'extra_sauce', 'rice_ingredient', 'rice_sauce', 'sushi_ingredient']
    menu_opts = {}
    for cat in categories:
        rows = conn.execute(
            'SELECT * FROM menu_options WHERE category=? ORDER BY active DESC, sort_order, name',
            (cat,)
        ).fetchall()
        opts = [dict(r) for r in rows]
        if cat == 'beverage':
            for opt in opts:
                mp = conn.execute('SELECT price FROM menu_prices WHERE key=?', (opt['name'],)).fetchone()
                if mp:
                    opt['price'] = mp['price']
        menu_opts[cat] = opts
    return render_template('menu_options.html', menu_opts=menu_opts)
```

- [ ] **Step 4: Create the template**

Create `python-backend/templates/menu_options.html`:

```html
{% extends 'base.html' %} {% block title %}Opciones del Menú{% endblock %} {%
block styles %}
<style>
  .page-wrap {
    max-width: 800px;
    margin: 0 auto;
    padding: 24px 20px 60px;
  }
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 28px;
  }
  .page-title-txt {
    font-size: 1.8rem;
    font-weight: 800;
    color: #ff9800;
    margin: 0;
  }
  .back-btn {
    color: #aaa;
    text-decoration: none;
    font-size: 0.9rem;
    border: 1px solid #333;
    padding: 8px 16px;
    border-radius: 10px;
    background: #1e1e1e;
  }
  .back-btn:hover {
    border-color: #ff9800;
    color: #ff9800;
  }
  .alert {
    padding: 12px 18px;
    border-radius: 10px;
    margin-bottom: 16px;
    font-weight: 600;
    font-size: 0.95rem;
  }
  .alert-success {
    background: rgba(43, 138, 62, 0.2);
    color: #81c784;
    border: 1px solid rgba(43, 138, 62, 0.35);
  }
  .alert-error {
    background: rgba(231, 76, 60, 0.2);
    color: #ff8a80;
    border: 1px solid rgba(231, 76, 60, 0.35);
  }
  .menu-section {
    background: #1e1e1e;
    border-radius: 14px;
    border: 2px solid #2a2a2a;
    margin-bottom: 10px;
    overflow: hidden;
  }
  .menu-section-title {
    padding: 14px 18px;
    font-size: 0.95rem;
    font-weight: 700;
    color: #f5f5f5;
    cursor: pointer;
    user-select: none;
    list-style: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    transition: background 0.15s;
  }
  .menu-section-title:hover {
    background: #252525;
  }
  .menu-section-title::-webkit-details-marker {
    display: none;
  }
  .menu-section-title::after {
    content: "›";
    font-size: 1.3rem;
    color: #555;
    transition: transform 0.2s;
    line-height: 1;
  }
  details[open] > .menu-section-title::after {
    transform: rotate(90deg);
    color: #ff9800;
  }
  details[open] > .menu-section-title {
    color: #ff9800;
  }
  .opt-count {
    color: #555;
    font-weight: 500;
    font-size: 0.82rem;
    margin-left: 8px;
  }
  .menu-section-body {
    padding: 4px 18px 16px;
    border-top: 1px solid #2a2a2a;
  }
  .opt-list {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding: 12px 0 10px;
    min-height: 20px;
  }
  .opt-item {
    display: flex;
    align-items: center;
    gap: 6px;
    background: #2a2a2a;
    border: 1px solid #3d3d3d;
    border-radius: 20px;
    padding: 5px 10px 5px 8px;
    font-size: 0.88rem;
  }
  .opt-icon {
    font-size: 1rem;
    line-height: 1;
  }
  .opt-name {
    color: #e0e0e0;
    font-weight: 500;
  }
  .opt-price {
    color: #ff9800;
    font-size: 0.8rem;
    font-weight: 600;
  }
  .opt-del-btn {
    background: none;
    border: none;
    color: #555;
    cursor: pointer;
    font-size: 0.75rem;
    padding: 0 0 0 4px;
    line-height: 1;
    transition: color 0.15s;
  }
  .opt-del-btn:hover {
    color: #ff6b6b;
  }
  .opt-toggle-btn {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.9rem;
    padding: 0 0 0 4px;
    line-height: 1;
    transition: color 0.15s;
  }
  .opt-toggle-active {
    color: #4caf50;
  }
  .opt-toggle-active:hover {
    color: #888;
  }
  .opt-toggle-inactive {
    color: #555;
  }
  .opt-toggle-inactive:hover {
    color: #4caf50;
  }
  .opt-item-inactive {
    opacity: 0.45;
  }
  .opt-sold-out {
    font-size: 0.68rem;
    font-weight: 700;
    color: #ff6b6b;
    background: rgba(255, 107, 107, 0.15);
    border-radius: 8px;
    padding: 2px 6px;
    letter-spacing: 0.03em;
  }
  .add-opt-form {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
    padding-top: 4px;
  }
  .opt-input {
    padding: 8px 12px;
    border: 1px solid #3d3d3d;
    border-radius: 10px;
    font-size: 0.9rem;
    background: #2d2d2d;
    color: #f5f5f5;
    transition: border-color 0.2s;
  }
  .opt-input:focus {
    outline: none;
    border-color: #ff9800;
  }
  .opt-input::placeholder {
    color: #555;
  }
  .opt-icon-input {
    width: 62px;
    text-align: center;
  }
  .opt-name-input {
    flex: 1;
    min-width: 130px;
  }
  .opt-price-input {
    width: 84px;
    text-align: right;
  }
  .opt-add-btn {
    padding: 8px 18px;
    background: #ff9800;
    color: #121212;
    border: none;
    border-radius: 10px;
    font-size: 0.9rem;
    font-weight: 700;
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.2s;
  }
  .opt-add-btn:hover {
    background: #e68900;
  }
  @media (max-width: 520px) {
    .add-opt-form {
      flex-direction: column;
      align-items: stretch;
    }
    .opt-icon-input,
    .opt-price-input {
      width: 100%;
    }
    .opt-add-btn {
      width: 100%;
      text-align: center;
    }
  }
</style>
{% endblock %} {% block body %}
<div class="page-wrap">
  <div class="page-header">
    <h1 class="page-title-txt">🍽️ Opciones del Menú</h1>
    <a href="{{ url_for('admin_dashboard') }}" class="back-btn">← Panel</a>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %} {% if
  messages %}{% for cat, msg in messages %}
  <div class="alert alert-{{ cat }}">{{ msg }}</div>
  {% endfor %}{% endif %} {% endwith %} {% set cat_labels = { 'beverage':
  'Bebidas', 'boneless_sauce': 'Salsas Boneless', 'extra_sauce': 'Salsas Extra
  (Complementos)', 'rice_ingredient': 'Ingredientes Bola de Arroz',
  'rice_sauce': 'Salsas Bola de Arroz', 'sushi_ingredient': 'Ingredientes Sushi'
  } %} {% set cat_icons = { 'beverage': '🥤', 'boneless_sauce': '🍗',
  'extra_sauce': '🌶️', 'rice_ingredient': '🍙', 'rice_sauce': '🔴',
  'sushi_ingredient': '🍣' } %} {% for cat, opts in menu_opts.items() %}
  <details class="menu-section">
    <summary class="menu-section-title">
      <span
        >{{ cat_icons[cat] }} &nbsp;{{ cat_labels[cat] }}
        <span class="opt-count">{{ opts|length }} opciones</span></span
      >
    </summary>
    <div class="menu-section-body">
      <div class="opt-list">
        {% for opt in opts %}
        <div
          class="opt-item {% if not opt.active %}opt-item-inactive{% endif %}"
        >
          <span class="opt-icon">{{ opt.icon }}</span>
          <span class="opt-name">{{ opt.name }}</span>
          {% if cat == 'beverage' %}<span class="opt-price"
            >${{ "%.0f"|format(opt.price) }}</span
          >{% endif %} {% if not opt.active %}<span class="opt-sold-out"
            >Agotado</span
          >{% endif %}
          <form
            method="POST"
            action="{{ url_for('toggle_menu_option', option_id=opt.id) }}"
            style="display: inline; margin: 0"
          >
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />
            <button
              type="submit"
              class="opt-toggle-btn {% if opt.active %}opt-toggle-active{% else %}opt-toggle-inactive{% endif %}"
              title="{{ 'Desactivar' if opt.active else 'Activar' }}"
            >
              {{ '●' if opt.active else '○' }}
            </button>
          </form>
          {% if opt.active %}
          <form
            method="POST"
            action="{{ url_for('delete_menu_option', option_id=opt.id) }}"
            style="display: inline; margin: 0"
          >
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />
            <button
              type="submit"
              class="opt-del-btn"
              title="Eliminar permanentemente"
              onclick="event.preventDefault(); showConfirm('¿Eliminar {{ opt.name }}?', () => this.closest('form').submit())"
            >
              ✕
            </button>
          </form>
          {% endif %}
        </div>
        {% endfor %} {% if not opts %}
        <span style="color: #555; font-size: 0.85rem; padding: 4px 0"
          >Sin opciones — agrega una abajo</span
        >
        {% endif %}
      </div>
      <form
        method="POST"
        action="{{ url_for('add_menu_option') }}"
        class="add-opt-form"
      >
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />
        <input type="hidden" name="category" value="{{ cat }}" />
        <input
          type="text"
          name="icon"
          placeholder="🍽️"
          class="opt-input opt-icon-input"
          maxlength="4"
        />
        <input
          type="text"
          name="name"
          placeholder="Nombre del item"
          class="opt-input opt-name-input"
          required
        />
        {% if cat == 'beverage' %}
        <input
          type="number"
          name="price"
          placeholder="Precio $"
          class="opt-input opt-price-input"
          min="0"
          step="0.5"
          value=""
        />
        {% else %}
        <input type="hidden" name="price" value="0" />
        {% endif %}
        <button type="submit" class="opt-add-btn">+ Agregar</button>
      </form>
    </div>
  </details>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 5: Add the nav-card**

In `python-backend/templates/admin_dashboard.html`, find:

```html
    <a href="{{ url_for('manage_prices') }}" class="nav-card">
      <div class="nav-card-icon">💲</div>
      <div class="nav-card-name">Precios</div>
      <div class="nav-card-desc">Gestión de precios</div>
    </a>
  </div>
```

Replace it with:

```html
    <a href="{{ url_for('manage_prices') }}" class="nav-card">
      <div class="nav-card-icon">💲</div>
      <div class="nav-card-name">Precios</div>
      <div class="nav-card-desc">Gestión de precios</div>
    </a>
    <a href="{{ url_for('manage_menu_options') }}" class="nav-card">
      <div class="nav-card-icon">🍽️</div>
      <div class="nav-card-name">Opciones del Menú</div>
      <div class="nav-card-desc">Ingredientes y salsas</div>
    </a>
  </div>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd python-backend && ./venv/bin/python -m pytest tests/test_route_manage_menu_options.py -v`
Expected: 3 passed

- [ ] **Step 7: Run the full suite**

Run: `cd python-backend && ./venv/bin/python -m pytest tests/ -v`
Expected: all previously-passing tests still pass, plus the 3 new ones.

- [ ] **Step 8: Commit**

```bash
git add python-backend/app.py python-backend/templates/menu_options.html python-backend/templates/admin_dashboard.html python-backend/tests/test_route_manage_menu_options.py
git commit -m "feat: add standalone Opciones del Menú page"
```

---

## Task 3: Promociones page

**Files:**

- Modify: `python-backend/app.py`
- Create: `python-backend/templates/promotions.html`
- Modify: `python-backend/templates/admin_dashboard.html` (add nav-card only)
- Create: `python-backend/tests/test_route_manage_promotions.py`

- [ ] **Step 1: Write the failing tests**

Create `python-backend/tests/test_route_manage_promotions.py`:

```python
def test_manage_promotions_page_loads_for_admin(admin_client):
    resp = admin_client.get("/admin/promotions")
    assert resp.status_code == 200
    assert "Promociones".encode("utf-8") in resp.data


def test_manage_promotions_blocks_non_admin(client):
    client.post("/login", data={"username": "user", "password": "user123"})
    resp = client.get("/admin/promotions")
    assert resp.status_code == 302


def test_add_promotion_redirects_to_manage_promotions(admin_client):
    resp = admin_client.post(
        "/admin/promotions/add",
        data={"name": "VERANO20", "type": "percentage", "value": "20"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/promotions"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && ./venv/bin/python -m pytest tests/test_route_manage_promotions.py -v`
Expected: FAIL — page-load and non-admin tests fail with 404; redirect test fails because Location is `/admin` not `/admin/promotions`.

- [ ] **Step 3: Add the route and fix the redirect targets**

In `python-backend/app.py`, find this exact block:

```python
@app.route('/admin/promotions/add', methods=['POST'])
@login_required
@admin_required
def add_promotion():
    name = request.form.get('name', '').strip().upper().replace(' ', '')
    description = request.form.get('description', '').strip()
    promo_type = request.form.get('type', 'percentage')
    value = request.form.get('value', '0')
    min_purchase = request.form.get('min_purchase', '0') or '0'
    applicable_items = request.form.getlist('applicable_items')

    if not name:
        flash('El código de promoción no puede estar vacío.', 'error')
        return redirect(url_for('admin_dashboard'))
    if promo_type not in ('percentage', 'fixed', 'bxgy'):
        flash('Tipo de promoción inválido.', 'error')
        return redirect(url_for('admin_dashboard'))

    get_free = 1
    try:
        min_purchase = float(min_purchase or '0')
        if promo_type == 'bxgy':
            buy_qty_str = request.form.get('buy_qty', '').strip()
            get_free_str = request.form.get('get_free', '1').strip() or '1'
            value = int(float(buy_qty_str)) if buy_qty_str else 0
            get_free = int(float(get_free_str))
            if value < 1 or get_free < 1:
                raise ValueError('buy/free must be >= 1')
        else:
            value = float(value) if value.strip() else 0.0
    except (ValueError, AttributeError):
        flash('Valor inválido.', 'error')
        return redirect(url_for('admin_dashboard'))

    if promo_type == 'percentage' and not (0 < value <= 100):
        flash('El porcentaje debe estar entre 1 y 100.', 'error')
        return redirect(url_for('admin_dashboard'))
    if promo_type != 'bxgy' and value <= 0:
        flash('El valor debe ser mayor a 0.', 'error')
        return redirect(url_for('admin_dashboard'))

    applicable_json = json.dumps(applicable_items) if applicable_items else '[]'

    conn = get_db_connection()
    existing = conn.execute('SELECT id FROM promotions WHERE name = ?', (name,)).fetchone()
    if existing:
        flash(f'Ya existe una promoción con el código "{name}".', 'error')
        return redirect(url_for('admin_dashboard'))
    conn.execute(
        'INSERT INTO promotions (name, description, type, value, get_free, min_purchase, applicable_items, active) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, 1)',
        (name, description, promo_type, value, get_free, min_purchase, applicable_json)
    )
    conn.commit()
    flash(f'Promoción "{name}" creada.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/promotions/delete/<int:promo_id>', methods=['POST'])
@login_required
@admin_required
def delete_promotion(promo_id):
    conn = get_db_connection()
    promo = conn.execute('SELECT name FROM promotions WHERE id = ?', (promo_id,)).fetchone()
    if promo:
        conn.execute('DELETE FROM promotions WHERE id = ?', (promo_id,))
        conn.commit()
        flash(f'Promoción "{promo["name"]}" eliminada.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/promotions/toggle/<int:promo_id>', methods=['POST'])
@login_required
@admin_required
def toggle_promotion(promo_id):
    conn = get_db_connection()
    promo = conn.execute('SELECT active, name FROM promotions WHERE id = ?', (promo_id,)).fetchone()
    if promo:
        new_state = 0 if promo['active'] else 1
        conn.execute('UPDATE promotions SET active = ? WHERE id = ?', (new_state, promo_id))
        conn.commit()
        state_label = 'activada' if new_state else 'desactivada'
        flash(f'Promoción "{promo["name"]}" {state_label}.', 'success')
    return redirect(url_for('admin_dashboard'))
```

Replace it with (every `url_for('admin_dashboard')` in these three functions becomes `url_for('manage_promotions')`; logic is otherwise byte-for-byte identical, plus the new route is appended at the end):

```python
@app.route('/admin/promotions/add', methods=['POST'])
@login_required
@admin_required
def add_promotion():
    name = request.form.get('name', '').strip().upper().replace(' ', '')
    description = request.form.get('description', '').strip()
    promo_type = request.form.get('type', 'percentage')
    value = request.form.get('value', '0')
    min_purchase = request.form.get('min_purchase', '0') or '0'
    applicable_items = request.form.getlist('applicable_items')

    if not name:
        flash('El código de promoción no puede estar vacío.', 'error')
        return redirect(url_for('manage_promotions'))
    if promo_type not in ('percentage', 'fixed', 'bxgy'):
        flash('Tipo de promoción inválido.', 'error')
        return redirect(url_for('manage_promotions'))

    get_free = 1
    try:
        min_purchase = float(min_purchase or '0')
        if promo_type == 'bxgy':
            buy_qty_str = request.form.get('buy_qty', '').strip()
            get_free_str = request.form.get('get_free', '1').strip() or '1'
            value = int(float(buy_qty_str)) if buy_qty_str else 0
            get_free = int(float(get_free_str))
            if value < 1 or get_free < 1:
                raise ValueError('buy/free must be >= 1')
        else:
            value = float(value) if value.strip() else 0.0
    except (ValueError, AttributeError):
        flash('Valor inválido.', 'error')
        return redirect(url_for('manage_promotions'))

    if promo_type == 'percentage' and not (0 < value <= 100):
        flash('El porcentaje debe estar entre 1 y 100.', 'error')
        return redirect(url_for('manage_promotions'))
    if promo_type != 'bxgy' and value <= 0:
        flash('El valor debe ser mayor a 0.', 'error')
        return redirect(url_for('manage_promotions'))

    applicable_json = json.dumps(applicable_items) if applicable_items else '[]'

    conn = get_db_connection()
    existing = conn.execute('SELECT id FROM promotions WHERE name = ?', (name,)).fetchone()
    if existing:
        flash(f'Ya existe una promoción con el código "{name}".', 'error')
        return redirect(url_for('manage_promotions'))
    conn.execute(
        'INSERT INTO promotions (name, description, type, value, get_free, min_purchase, applicable_items, active) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, 1)',
        (name, description, promo_type, value, get_free, min_purchase, applicable_json)
    )
    conn.commit()
    flash(f'Promoción "{name}" creada.', 'success')
    return redirect(url_for('manage_promotions'))


@app.route('/admin/promotions/delete/<int:promo_id>', methods=['POST'])
@login_required
@admin_required
def delete_promotion(promo_id):
    conn = get_db_connection()
    promo = conn.execute('SELECT name FROM promotions WHERE id = ?', (promo_id,)).fetchone()
    if promo:
        conn.execute('DELETE FROM promotions WHERE id = ?', (promo_id,))
        conn.commit()
        flash(f'Promoción "{promo["name"]}" eliminada.', 'success')
    return redirect(url_for('manage_promotions'))


@app.route('/admin/promotions/toggle/<int:promo_id>', methods=['POST'])
@login_required
@admin_required
def toggle_promotion(promo_id):
    conn = get_db_connection()
    promo = conn.execute('SELECT active, name FROM promotions WHERE id = ?', (promo_id,)).fetchone()
    if promo:
        new_state = 0 if promo['active'] else 1
        conn.execute('UPDATE promotions SET active = ? WHERE id = ?', (new_state, promo_id))
        conn.commit()
        state_label = 'activada' if new_state else 'desactivada'
        flash(f'Promoción "{promo["name"]}" {state_label}.', 'success')
    return redirect(url_for('manage_promotions'))


@app.route('/admin/promotions')
@login_required
@admin_required
def manage_promotions():
    conn = get_db_connection()
    promotions = [dict(p) for p in conn.execute('SELECT * FROM promotions ORDER BY name').fetchall()]
    return render_template('promotions.html', promotions=promotions)
```

- [ ] **Step 4: Create the template**

Create `python-backend/templates/promotions.html`:

```html
{% extends 'base.html' %} {% block title %}Promociones{% endblock %} {% block
styles %}
<style>
  .page-wrap {
    max-width: 700px;
    margin: 0 auto;
    padding: 24px 20px 60px;
  }
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 28px;
  }
  .page-title-txt {
    font-size: 1.8rem;
    font-weight: 800;
    color: #ff9800;
    margin: 0;
  }
  .back-btn {
    color: #aaa;
    text-decoration: none;
    font-size: 0.9rem;
    border: 1px solid #333;
    padding: 8px 16px;
    border-radius: 10px;
    background: #1e1e1e;
  }
  .back-btn:hover {
    border-color: #ff9800;
    color: #ff9800;
  }
  .alert {
    padding: 12px 18px;
    border-radius: 10px;
    margin-bottom: 16px;
    font-weight: 600;
    font-size: 0.95rem;
  }
  .alert-success {
    background: rgba(43, 138, 62, 0.2);
    color: #81c784;
    border: 1px solid rgba(43, 138, 62, 0.35);
  }
  .alert-error {
    background: rgba(231, 76, 60, 0.2);
    color: #ff8a80;
    border: 1px solid rgba(231, 76, 60, 0.35);
  }
  .prices-card {
    background: #1e1e1e;
    border-radius: 16px;
    padding: 6px 0;
    border: 2px solid #2a2a2a;
    overflow: hidden;
  }
  .price-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 20px;
    border-bottom: 1px solid #2a2a2a;
    gap: 12px;
  }
  .price-row:last-of-type {
    border-bottom: none;
  }
  .add-card {
    background: #1e1e1e;
    border-radius: 16px;
    padding: 20px 20px 22px;
    border: 2px solid #2a2a2a;
  }
  .add-grid {
    display: grid;
    gap: 14px;
  }
  .section-heading {
    font-size: 0.78rem;
    font-weight: 700;
    color: #ff9800;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin: 0 0 14px;
    padding-left: 4px;
  }
  .field-label {
    display: block;
    font-size: 0.78rem;
    font-weight: 700;
    color: #888;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 6px;
  }
  .field-input {
    width: 100%;
    box-sizing: border-box;
    padding: 9px 12px;
    border: 1px solid #3d3d3d;
    border-radius: 10px;
    font-size: 0.92rem;
    background: #2d2d2d;
    color: #f5f5f5;
    transition: border-color 0.2s;
  }
  .field-input:focus {
    outline: none;
    border-color: #ff9800;
  }
  .field-input::placeholder {
    color: #555;
  }
  .field-select {
    width: 100%;
    box-sizing: border-box;
    padding: 9px 12px;
    border: 1px solid #3d3d3d;
    border-radius: 10px;
    font-size: 0.92rem;
    background: #2d2d2d;
    color: #f5f5f5;
    appearance: none;
    cursor: pointer;
    transition: border-color 0.2s;
  }
  .field-select:focus {
    outline: none;
    border-color: #ff9800;
  }
  .add-btn {
    margin-top: 6px;
    padding: 11px 24px;
    background: #ff9800;
    color: #121212;
    border: none;
    border-radius: 11px;
    font-size: 0.95rem;
    font-weight: 800;
    cursor: pointer;
    transition: background 0.2s;
  }
  .add-btn:hover {
    background: #e68900;
  }
</style>
{% endblock %} {% block body %}
<div class="page-wrap">
  <div class="page-header">
    <h1 class="page-title-txt">🏷️ Promociones</h1>
    <a href="{{ url_for('admin_dashboard') }}" class="back-btn">← Panel</a>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %} {% if
  messages %}{% for cat, msg in messages %}
  <div class="alert alert-{{ cat }}">{{ msg }}</div>
  {% endfor %}{% endif %} {% endwith %}

  <div class="section-heading">Promociones activas</div>
  <div class="prices-card" style="margin-bottom: 28px">
    {% if promotions %} {% for promo in promotions %}
    <div class="price-row" style="flex-wrap: wrap; gap: 10px">
      <div style="flex: 1; min-width: 160px">
        <div style="font-weight: 700; color: #f5f5f5; font-size: 0.95rem">
          {{ promo.name }}
        </div>
        <div style="font-size: 0.8rem; color: #888; margin-top: 2px">
          {{ promo.description or '' }}
          <span style="color: #555; margin-left: 6px">
            {% if promo.type == 'percentage' %}· {{ promo.value|int }}%
            descuento {% elif promo.type == 'fixed' %}· ${{
            "%.2f"|format(promo.value) }} descuento {% elif promo.type in
            ('bxgy', 'special') %} {% set gf = (promo.get_free or 1)|int %} · {{
            promo.value|int + gf }}x{{ promo.value|int }} — compra {{
            promo.value|int }}, {{ gf }} gratis {% else %}· Especial{% endif %}
            {% if promo.min_purchase and promo.min_purchase > 0 %}· mín ${{
            promo.min_purchase|int }}{% endif %}
          </span>
        </div>
      </div>
      <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0">
        <span
          style="font-size:0.8rem;color:{% if promo.active %}#81C784{% else %}#888{% endif %};"
        >
          {% if promo.active %}● Activa{% else %}○ Inactiva{% endif %}
        </span>
        <form
          method="POST"
          action="{{ url_for('toggle_promotion', promo_id=promo.id) }}"
          style="margin: 0"
        >
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />
          <button
            type="submit"
            style="padding:5px 12px;border-radius:8px;border:none;cursor:pointer;font-size:0.82rem;font-weight:600;
                        background:{% if promo.active %}#4A1F1F{% else %}#1B5E20{% endif %};
                        color:{% if promo.active %}#FF6B6B{% else %}#81C784{% endif %};"
          >
            {% if promo.active %}Desactivar{% else %}Activar{% endif %}
          </button>
        </form>
        <form
          method="POST"
          action="{{ url_for('delete_promotion', promo_id=promo.id) }}"
          style="margin: 0"
          data-confirm="¿Eliminar la promoción {{ promo.name }}?"
        >
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />
          <button
            type="submit"
            style="
              padding: 5px 10px;
              border-radius: 8px;
              border: none;
              cursor: pointer;
              font-size: 0.82rem;
              font-weight: 600;
              background: #2a2a2a;
              color: #ff6b6b;
            "
          >
            ✕
          </button>
        </form>
      </div>
    </div>
    {% endfor %} {% else %}
    <div
      style="padding: 20px; color: #555; text-align: center; font-size: 0.9rem"
    >
      Sin promociones configuradas
    </div>
    {% endif %}
  </div>

  <div class="add-card">
    <div class="section-heading" style="margin-bottom: 16px">
      Nueva Promoción
    </div>
    <form method="POST" action="{{ url_for('add_promotion') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />
      <div
        class="add-grid"
        style="grid-template-columns: 1fr 1fr; margin-bottom: 14px"
      >
        <div>
          <label class="field-label">Código (cupón)</label>
          <input
            type="text"
            name="name"
            class="field-input"
            placeholder="Ej: VERANO20"
            required
            maxlength="20"
            style="text-transform: uppercase"
          />
        </div>
        <div>
          <label class="field-label">Descripción</label>
          <input
            type="text"
            name="description"
            class="field-input"
            placeholder="Ej: 20% en toda la orden"
            maxlength="60"
          />
        </div>
      </div>
      <div
        class="add-grid"
        style="grid-template-columns: 1fr 1fr 1fr; margin-bottom: 14px"
      >
        <div>
          <label class="field-label">Tipo</label>
          <select
            name="type"
            class="field-select"
            id="promo-type-select"
            onchange="updatePromoLabel()"
          >
            <option value="percentage">Porcentaje (%)</option>
            <option value="fixed">Monto fijo ($)</option>
            <option value="bxgy">NxM — lleva N, paga M</option>
          </select>
        </div>
        <div id="promo-discount-field" style="transition: opacity 0.25s ease">
          <label class="field-label" id="promo-value-label">Valor (%)</label>
          <div
            id="promo-value-wrapper"
            style="position: relative; display: flex; align-items: center"
          >
            <input
              type="number"
              name="value"
              id="promo-value-input"
              class="field-input"
              placeholder="Ej: 20"
              min="0.01"
              step="0.5"
              style="padding-right: 2.4rem"
              oninput="syncPromoSlider(); updatePromoPreview();"
            />
            <span
              id="promo-value-suffix"
              style="position: absolute; right: 10px; font-size: 0.9rem; color: #aaa; pointer-events: none; font-weight: 600"
              >%</span
            >
          </div>
          <div id="promo-slider-wrap" style="margin-top: 8px">
            <input
              type="range"
              id="promo-pct-slider"
              min="0"
              max="100"
              step="1"
              value="0"
              oninput="syncPromoInput(); updatePromoPreview();"
              style="width: 100%; accent-color: #ff9800; cursor: pointer; height: 4px"
            />
          </div>
          <div
            id="promo-preview"
            style="margin-top: 6px; font-size: 0.82rem; color: #ff9800; font-weight: 600; min-height: 1.1em; transition: opacity 0.2s ease"
          ></div>
        </div>
        <div id="promo-bxgy-fields" style="display: none; grid-column: span 2">
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px">
            <div>
              <label class="field-label">Lleva (N)</label>
              <input
                type="number"
                name="buy_qty"
                id="promo-buy-input"
                class="field-input"
                placeholder="Ej: 4"
                min="1"
                step="1"
              />
            </div>
            <div>
              <label class="field-label">Gratis (M)</label>
              <input
                type="number"
                name="get_free"
                id="promo-free-input"
                class="field-input"
                placeholder="Ej: 1"
                min="1"
                step="1"
                value="1"
              />
            </div>
          </div>
        </div>
        <div>
          <label class="field-label"
            >Mínimo de compra
            <span style="color: #555; font-weight: 400; text-transform: none"
              >opcional</span
            ></label
          >
          <input
            type="number"
            name="min_purchase"
            class="field-input"
            placeholder="$0"
            min="0"
            step="1"
            value="0"
          />
        </div>
      </div>
      <div style="margin-bottom: 18px">
        <label class="field-label"
          >Aplica a
          <span style="color: #555; font-weight: 400; text-transform: none"
            >dejar vacío = toda la orden</span
          ></label
        >
        <div style="display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px">
          {% for item_type in ['Boneless','Bola de
          Arroz','Sushi','Bebida','Complementos'] %}
          <label
            style="display: flex; align-items: center; gap: 6px; font-size: 0.88rem; color: #ccc; cursor: pointer; background: #2a2a2a; border: 1px solid #3d3d3d; border-radius: 20px; padding: 5px 12px"
          >
            <input
              type="checkbox"
              name="applicable_items"
              value="{{ item_type }}"
              style="accent-color: #ff9800; width: 14px; height: 14px"
            />
            {{ item_type }}
          </label>
          {% endfor %}
        </div>
      </div>
      <button type="submit" class="add-btn">+ Crear Promoción</button>
    </form>
  </div>
</div>

<script>
  function updatePromoLabel() {
    const type = document.getElementById("promo-type-select").value;
    const discountField = document.getElementById("promo-discount-field");
    const bxgyFields = document.getElementById("promo-bxgy-fields");
    const valueInput = document.getElementById("promo-value-input");
    const buyInput = document.getElementById("promo-buy-input");
    const sliderWrap = document.getElementById("promo-slider-wrap");
    const suffix = document.getElementById("promo-value-suffix");
    const preview = document.getElementById("promo-preview");

    if (type === "bxgy") {
      discountField.style.opacity = "0";
      discountField.style.pointerEvents = "none";
      setTimeout(() => {
        discountField.style.display = "none";
        discountField.style.opacity = "";
        discountField.style.pointerEvents = "";
      }, 220);

      bxgyFields.style.display = "block";
      bxgyFields.style.opacity = "0";
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          bxgyFields.style.transition = "opacity 0.25s ease";
          bxgyFields.style.opacity = "1";
        });
      });

      valueInput.removeAttribute("required");
      buyInput.setAttribute("required", "");
      preview.textContent = "";
    } else {
      bxgyFields.style.transition = "opacity 0.25s ease";
      bxgyFields.style.opacity = "0";
      setTimeout(() => {
        bxgyFields.style.display = "none";
        bxgyFields.style.opacity = "";
      }, 220);

      discountField.style.display = "";
      discountField.style.opacity = "0";
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          discountField.style.opacity = "1";
        });
      });

      valueInput.setAttribute("required", "");
      buyInput.removeAttribute("required");

      if (type === "percentage") {
        document.getElementById("promo-value-label").textContent = "Valor (%)";
        valueInput.max = "100";
        suffix.textContent = "%";
        suffix.style.display = "";
        sliderWrap.style.display = "";
      } else {
        document.getElementById("promo-value-label").textContent = "Valor ($)";
        valueInput.removeAttribute("max");
        suffix.textContent = "$";
        suffix.style.display = "";
        sliderWrap.style.display = "none";
      }

      updatePromoPreview();
    }
  }

  function syncPromoSlider() {
    const val =
      parseFloat(document.getElementById("promo-value-input").value) || 0;
    const slider = document.getElementById("promo-pct-slider");
    slider.value = Math.min(100, Math.max(0, val));
  }

  function syncPromoInput() {
    const slider = document.getElementById("promo-pct-slider");
    document.getElementById("promo-value-input").value = slider.value;
  }

  function updatePromoPreview() {
    const type = document.getElementById("promo-type-select").value;
    const raw = document.getElementById("promo-value-input").value;
    const preview = document.getElementById("promo-preview");
    const val = parseFloat(raw);

    if (!raw || isNaN(val) || val <= 0) {
      preview.textContent = "";
      return;
    }

    if (type === "percentage") {
      preview.textContent = val + "% off";
    } else if (type === "fixed") {
      preview.textContent = "$" + val.toFixed(2) + " off";
    } else {
      preview.textContent = "";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    updatePromoLabel();
  });
</script>
{% endblock %}
```

- [ ] **Step 5: Add the nav-card**

In `python-backend/templates/admin_dashboard.html`, find:

```html
    <a href="{{ url_for('manage_menu_options') }}" class="nav-card">
      <div class="nav-card-icon">🍽️</div>
      <div class="nav-card-name">Opciones del Menú</div>
      <div class="nav-card-desc">Ingredientes y salsas</div>
    </a>
  </div>
```

Replace it with:

```html
    <a href="{{ url_for('manage_menu_options') }}" class="nav-card">
      <div class="nav-card-icon">🍽️</div>
      <div class="nav-card-name">Opciones del Menú</div>
      <div class="nav-card-desc">Ingredientes y salsas</div>
    </a>
    <a href="{{ url_for('manage_promotions') }}" class="nav-card">
      <div class="nav-card-icon">🏷️</div>
      <div class="nav-card-name">Promociones</div>
      <div class="nav-card-desc">Cupones y descuentos</div>
    </a>
  </div>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd python-backend && ./venv/bin/python -m pytest tests/test_route_manage_promotions.py -v`
Expected: 3 passed

- [ ] **Step 7: Run the full suite**

Run: `cd python-backend && ./venv/bin/python -m pytest tests/ -v`
Expected: all previously-passing tests still pass, plus the 3 new ones.

- [ ] **Step 8: Commit**

```bash
git add python-backend/app.py python-backend/templates/promotions.html python-backend/templates/admin_dashboard.html python-backend/tests/test_route_manage_promotions.py
git commit -m "feat: add standalone Promociones page"
```

---

## Task 4: Remove the old inline sections from the dashboard

Now that all three pages work independently (confirmed by Tasks 1–3's tests and the nav-cards), remove the now-redundant inline copies from `admin_dashboard()` and `admin_dashboard.html`.

**Files:**

- Modify: `python-backend/app.py`
- Modify: `python-backend/templates/admin_dashboard.html`

- [ ] **Step 1: Remove `prices`/`menu_opts`/`promotions` from `admin_dashboard()`**

In `python-backend/app.py`, find this exact block:

```python
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    prices = conn.execute('SELECT * FROM menu_prices ORDER BY label').fetchall()
    today = datetime.now().strftime('%Y-%m-%d')
    today_total = conn.execute(
        "SELECT COALESCE(SUM(total), 0) FROM orders WHERE date LIKE ? AND status != 'voided'",
        (today + '%',)
    ).fetchone()[0]
    today_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE date LIKE ? AND status != 'voided'",
        (today + '%',)
    ).fetchone()[0]
    # Promotions
    promotions = [dict(p) for p in conn.execute('SELECT * FROM promotions ORDER BY name').fetchall()]

    # Low-stock count from Java service (best-effort)
    low_stock_count = 0
    try:
        inv_resp = requests.get(f'{JAVA_INVENTORY_SERVICE}/api/inventory/low-stock', timeout=2)
        if inv_resp.status_code == 200:
            low_stock_count = len(inv_resp.json())
    except Exception:
        pass

    # Menu options grouped by category — include inactive so admin can re-enable them
    categories = ['beverage', 'boneless_sauce', 'extra_sauce', 'rice_ingredient', 'rice_sauce', 'sushi_ingredient']
    menu_opts = {}
    for cat in categories:
        rows = conn.execute(
            'SELECT * FROM menu_options WHERE category=? ORDER BY active DESC, sort_order, name',
            (cat,)
        ).fetchall()
        opts = [dict(r) for r in rows]
        if cat == 'beverage':
            for opt in opts:
                mp = conn.execute('SELECT price FROM menu_prices WHERE key=?', (opt['name'],)).fetchone()
                if mp:
                    opt['price'] = mp['price']
        menu_opts[cat] = opts

    pending_prints = conn.execute(
        "SELECT COUNT(*) FROM print_jobs WHERE status = 'pending'"
    ).fetchone()[0]

    printer_name = conn.execute(
        "SELECT value FROM config WHERE key = 'printer_name'"
    ).fetchone()
    printer_name = printer_name['value'] if printer_name else 'Printer_POS_80'

    users_with_default = conn.execute(
        "SELECT COUNT(*) FROM users WHERE password_changed = 0"
    ).fetchone()[0]

    return render_template('admin_dashboard.html',
                           prices=prices,
                           today_total=today_total,
                           today_orders=today_orders,
                           menu_opts=menu_opts,
                           promotions=promotions,
                           low_stock_count=low_stock_count,
                           pending_prints=pending_prints,
                           printer_name=printer_name,
                           users_with_default=users_with_default)
```

Replace it with:

```python
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    today = datetime.now().strftime('%Y-%m-%d')
    today_total = conn.execute(
        "SELECT COALESCE(SUM(total), 0) FROM orders WHERE date LIKE ? AND status != 'voided'",
        (today + '%',)
    ).fetchone()[0]
    today_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE date LIKE ? AND status != 'voided'",
        (today + '%',)
    ).fetchone()[0]

    # Low-stock count from Java service (best-effort)
    low_stock_count = 0
    try:
        inv_resp = requests.get(f'{JAVA_INVENTORY_SERVICE}/api/inventory/low-stock', timeout=2)
        if inv_resp.status_code == 200:
            low_stock_count = len(inv_resp.json())
    except Exception:
        pass

    pending_prints = conn.execute(
        "SELECT COUNT(*) FROM print_jobs WHERE status = 'pending'"
    ).fetchone()[0]

    printer_name = conn.execute(
        "SELECT value FROM config WHERE key = 'printer_name'"
    ).fetchone()
    printer_name = printer_name['value'] if printer_name else 'Printer_POS_80'

    users_with_default = conn.execute(
        "SELECT COUNT(*) FROM users WHERE password_changed = 0"
    ).fetchone()[0]

    return render_template('admin_dashboard.html',
                           today_total=today_total,
                           today_orders=today_orders,
                           low_stock_count=low_stock_count,
                           pending_prints=pending_prints,
                           printer_name=printer_name,
                           users_with_default=users_with_default)
```

- [ ] **Step 2: Run the full test suite to confirm nothing depends on the removed template variables**

Run: `cd python-backend && ./venv/bin/python -m pytest tests/ -v`
Expected: all tests still pass (no test currently checks `admin_dashboard` for `prices`/`menu_opts`/`promotions` content).

- [ ] **Step 3: Remove the three sections' markup from `admin_dashboard.html`**

In `python-backend/templates/admin_dashboard.html`, find this exact block (the `<style>` block opening through `.opt-add-btn:hover`, i.e. the CSS used only by Promociones/Opciones del Menú/Precios — but NOT `.add-card`/`.add-grid`/`.field-label`/`.field-input`/`.field-select`/`.add-btn`, which are still needed if any other part of the dashboard uses them; verify with `grep -n "add-card\|add-grid\|field-label\|field-input\|field-select\|class=\"add-btn\"" python-backend/templates/admin_dashboard.html` after this edit — if zero matches remain outside the `<style>` block, the CSS removal in this step is safe):

```css
  /* ── Menu options (collapsible) ──────────────────────────────── */
  .menu-section {
```

through

```css
.add-btn:hover {
  background: #e68900;
}
```

and replace that entire span (everything from `/* ── Menu options (collapsible) ──────────────────────────────── */` through the closing `}` of `.add-btn:hover`) with nothing (delete it).

Then find this exact block (the responsive media query, which currently has rules only relevant to the removed sections):

```css
/* ── Responsive ──────────────────────────────────────────────── */
@media (max-width: 520px) {
  .summary-row {
    grid-template-columns: 1fr;
  }
  .nav-grid {
    grid-template-columns: 1fr 1fr;
  }
  .add-opt-form {
    flex-direction: column;
    align-items: stretch;
  }
  .opt-icon-input,
  .opt-price-input {
    width: 100%;
  }
  .opt-add-btn {
    width: 100%;
    text-align: center;
  }
}
```

Replace it with:

```css
/* ── Responsive ──────────────────────────────────────────────── */
@media (max-width: 520px) {
  .summary-row {
    grid-template-columns: 1fr;
  }
  .nav-grid {
    grid-template-columns: 1fr 1fr;
  }
}
```

Then find this exact block (everything from the `<style>` low-stock-badge block through the end of the Prices section, i.e. the three sections' HTML plus the trailing `<script>` block):

```html
<style>
  .low-stock-badge {
    position: absolute;
    bottom: 10px;
    left: 50%;
    transform: translateX(-50%);
    background: #ff9800;
    color: #121212;
    font-size: 0.72rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 20px;
    white-space: nowrap;
  }
</style>

<!-- Promotions -->
```

Replace it with:

```html
  <style>
    .low-stock-badge {
      position: absolute;
      bottom: 10px;
      left: 50%;
      transform: translateX(-50%);
      background: #ff9800;
      color: #121212;
      font-size: 0.72rem;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 20px;
      white-space: nowrap;
    }
  </style>
</div>
{% endblock %}
```

(this closes `.admin-wrap` and the `body` block right after the printer config form — everything from `<!-- Promotions -->` through the end of the file, including the closing `</div>` that used to wrap all three sections and the trailing `<script>` block, is deleted because it's all being replaced by the single line `</div>\n{% endblock %}` above).

- [ ] **Step 4: Confirm the shared form-field CSS classes are still needed elsewhere or were only used by the removed sections**

Run: `grep -n 'class="add-card\|class="add-grid\|class="field-label\|class="field-input\|class="field-select\|class="add-btn"' python-backend/templates/admin_dashboard.html`

If this returns zero matches, those CSS rules (`.add-card`, `.add-grid`, `.field-label`, `.field-input`, `.field-select`, `.add-btn`) were already deleted as part of Step 3's first replacement (they live in the same CSS span that was removed) — confirm by checking `grep -n "\.add-card {" python-backend/templates/admin_dashboard.html` returns zero matches too. If anything unexpectedly still references them, stop and report rather than guessing.

- [ ] **Step 5: Manually verify the dashboard still renders**

Run: `cd python-backend && ./venv/bin/python -m pytest tests/ -v`
Expected: all tests pass (no existing test asserts on the removed sections' presence on `/admin` — if one does, that test needs updating to match the new reality that those sections live on their own pages now).

- [ ] **Step 6: Commit**

```bash
git add python-backend/app.py python-backend/templates/admin_dashboard.html
git commit -m "refactor: remove Precios/Opciones del Menú/Promociones from the dashboard now that they have their own pages"
```

---

## Task 5: Manual verification in the running app

- [ ] **Step 1: Start the app against an isolated copy of the database** (never the real `restaurant.db` directly — copy it to a temp path first, same approach used for the employee feature's manual verification)

```bash
cp python-backend/restaurant.db /tmp/verify_admin_pages.db
cd python-backend
./venv/bin/python -c "
import sqlite3
from werkzeug.security import generate_password_hash
conn = sqlite3.connect('/tmp/verify_admin_pages.db')
conn.execute(\"UPDATE users SET password=? WHERE username='admin'\", (generate_password_hash('verify123'),))
conn.commit()
"
RESTAURANT_DB_PATH=/tmp/verify_admin_pages.db SECRET_KEY=verify-key PORT=5096 ./venv/bin/python app.py
```

- [ ] **Step 2: Log in and visit the dashboard**

Open `http://localhost:5096/login`, log in with `admin` / `verify123`. Confirm the dashboard shows 8 nav-cards (Reportes, Historial, Inventario, Usuarios, Empleados, Precios, Opciones del Menú, Promociones) and no longer shows the old inline Promociones/Opciones del Menú/Gestión de Precios sections below the nav grid.

- [ ] **Step 3: Walk through each new page**

- Click "Precios" → confirm the price list loads, change one price, save, confirm the success flash and that you land back on `/admin/prices` (not `/admin`).
- Click "Opciones del Menú" → confirm the category lists load, add a test option, confirm it appears and you land back on `/admin/menu-options`.
- Click "Promociones" → confirm the promotions list loads, create a test promotion, confirm it appears and you land back on `/admin/promotions`. Toggle and delete it to clean up.

- [ ] **Step 4: Stop the server and remove the temp database**

`Ctrl+C`, then `rm /tmp/verify_admin_pages.db`.

---

## Self-review notes

- **Spec coverage:** three new routes/templates/nav-cards (Tasks 1–3) → matches the spec's "New routes," "Templates," and "Dashboard nav-grid after" sections. Redirect-target changes for all 6 existing POST handlers → matches "Existing POST handlers" section. `admin_dashboard()` slimming and dashboard markup removal → matches "`admin_dashboard()` after extraction" section. Manual verification → matches the project's established pattern of never testing against the real `restaurant.db` directly.
- **Placeholder scan:** none — every step has complete, runnable code or exact commands.
- **Type/name consistency:** route endpoint names (`manage_prices`, `manage_menu_options`, `manage_promotions`) and template filenames (`prices.html`, `menu_options.html`, `promotions.html`) are identical everywhere they're referenced, including every `url_for()` call across all three new templates and the dashboard's nav-cards.
