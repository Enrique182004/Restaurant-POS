# Split Admin Dashboard Sections Into Their Own Pages — Design Spec

Date: 2026-06-27
Status: Approved, ready for implementation plan

## Problem

`admin_dashboard.html` is 1218 lines. Three large, self-contained sections —
Gestión de Precios, Opciones del Menú, and Promociones — are rendered inline
on the main admin dashboard alongside the summary cards, the nav-card grid,
and printer config. Every other admin feature (Reportes, Historial,
Inventario, Usuarios, Empleados) is its own page reached via a nav-card;
these three are not, making the dashboard long and crowded.

## Decision

Extract each of the three sections into its own page, following the exact
pattern already used for Reportes/Historial/Inventario/Usuarios/Empleados:
a dedicated `GET` route, a self-contained template (own `<style>` block,
same dark/orange theme as the rest of the app), and a nav-card on the
dashboard linking to it.

This is a pure relocation — no behavior changes, no new functionality.
Each existing POST handler (add/delete/toggle/update) keeps its current
logic; only its redirect target changes from `admin_dashboard` to the new
page that now owns that section.

**Rejected alternative:** combining Opciones del Menú and Gestión de
Precios into one "Catálogo" page (since beverage prices are displayed
inline in the menu-options list). Rejected because the request was for
three distinct pages matching the three distinct sections, consistent
with how every other admin feature here is one page per concern.

## New routes

| Method | Route                 | View function         | Renders             |
| ------ | --------------------- | --------------------- | ------------------- |
| GET    | `/admin/prices`       | `manage_prices`       | `prices.html`       |
| GET    | `/admin/menu-options` | `manage_menu_options` | `menu_options.html` |
| GET    | `/admin/promotions`   | `manage_promotions`   | `promotions.html`   |

All three use `@login_required @admin_required`, matching every other admin
route.

### `manage_prices`

Moves this exact block out of `admin_dashboard()`:

```python
prices = conn.execute('SELECT * FROM menu_prices ORDER BY label').fetchall()
```

Renders `prices.html` with `prices=prices`.

### `manage_menu_options`

Moves this exact block out of `admin_dashboard()`:

```python
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
```

Renders `menu_options.html` with `menu_opts=menu_opts`.

### `manage_promotions`

Moves this exact block out of `admin_dashboard()`:

```python
promotions = [dict(p) for p in conn.execute('SELECT * FROM promotions ORDER BY name').fetchall()]
```

Renders `promotions.html` with `promotions=promotions`.

## `admin_dashboard()` after extraction

Keeps only what the summary cards, nav-grid badges, and printer config
need: `today_total`, `today_orders`, `low_stock_count`, `pending_prints`,
`printer_name`, `users_with_default`. Drops `prices`, `menu_opts`,
`promotions` entirely — `admin_dashboard.html` no longer needs those
sections' markup at all.

## Existing POST handlers — redirect target changes only

These handlers keep their exact current logic; only the redirect target
changes:

- `add_menu_option`, `delete_menu_option`, `toggle_menu_option` →
  redirect to `url_for('manage_menu_options')` instead of
  `url_for('admin_dashboard')`.
- `update_prices` (route `/admin/prices/update`) → redirect to
  `url_for('manage_prices')` instead of `url_for('admin_dashboard')`.
- `add_promotion`, `delete_promotion`, `toggle_promotion` → redirect to
  `url_for('manage_promotions')` instead of `url_for('admin_dashboard')`.

There are 17 total `redirect(url_for('admin_dashboard'))` call sites in
`app.py`; only those belonging to the above six handlers change. The
`home()` route's redirect to `admin_dashboard` (for admin users hitting
`/`) is unrelated and stays as-is.

## Templates

Three new templates, each extending `base.html` with its own `<style>`
block (no shared CSS file — matches the existing one-style-block-per-page
convention used by every other admin template):

- **`prices.html`** — page header, back-to-panel link, flash messages,
  the existing price-editing form and "Guardar Precios" button, moved
  verbatim from `admin_dashboard.html`.
- **`menu_options.html`** — page header, flash messages, the existing
  per-category `<details>` list (Bebidas, Salsas Boneless, Salsas Extra,
  Ingredientes Bola de Arroz, Salsas Bola de Arroz, Ingredientes Sushi)
  with add/delete/toggle controls, moved verbatim.
- **`promotions.html`** — page header, flash messages, the existing
  active-promotions list (with Desactivar/✕ controls) and the "Nueva
  Promoción" creation form, moved verbatim.

`admin_dashboard.html` loses these three sections' markup and the CSS
rules that exist solely to style them (anything not also used by the
summary cards, nav-grid, or printer config sections that remain).

## Dashboard nav-grid after

Three new `.nav-card` entries added alongside the existing five
(Reportes, Historial, Inventario, Usuarios, Empleados), styled
identically (icon, name, description divs), no badges (matching
Usuarios/Empleados/Reportes/Historial — only Inventario has a badge, for
pre-existing low-stock logic, which is untouched):

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
<a href="{{ url_for('manage_promotions') }}" class="nav-card">
  <div class="nav-card-icon">🏷️</div>
  <div class="nav-card-name">Promociones</div>
  <div class="nav-card-desc">Cupones y descuentos</div>
</a>
```

## Testing

This codebase's test suite (`python-backend/tests/`) currently only
covers the employee attendance/payroll feature added in the prior branch.
Following that same precedent, add route-level tests for the three new
`GET` routes (page loads for admin, blocked for non-admin) using the
existing `admin_client`/`client` pytest fixtures — matching the test
depth already established for `manage_users`-style pages. Full
regression coverage of the pre-existing add/delete/toggle POST handlers
is out of scope (they had no tests before this change either; only their
redirect target is touched).

## Out of scope

- No new functionality on any of the three pages — exact current
  behavior, just relocated.
- No changes to the printer config section, summary cards, or any other
  part of `admin_dashboard.html` not listed above.
- No shared/extracted CSS file — each new template gets its own
  self-contained `<style>` block, matching existing convention.
