import sqlite3

conn = sqlite3.connect('restaurant.db')
cursor = conn.cursor()

# Create table
cursor.execute('''
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    quantity INTEGER NOT NULL,
    min_threshold INTEGER NOT NULL,
    unit TEXT
)
''')

# Insert initial data
ingredients = [
    ('Camarón', 50, 10, 'pieces'),
    ('Surimi', 30, 8, 'pieces'),
    ('Arrachera', 25, 5, 'pieces'),
    ('Pollo', 40, 10, 'pieces'),
    ('Tocino', 35, 8, 'pieces'),
    ('Queso Crema', 20, 5, 'containers'),
    ('Aguacate', 15, 3, 'pieces')
]

cursor.executemany(
    'INSERT OR IGNORE INTO inventory (name, quantity, min_threshold, unit) VALUES (?, ?, ?, ?)',
    ingredients
)

conn.commit()
conn.close()
print("Inventory table created and initialized successfully!")
