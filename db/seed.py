"""
db/seed.py — Create and populate the sales database.

Tables:
  regions    — geographic sales regions
  customers  — individual customers linked to a region
  products   — product catalogue with category and unit price
  orders     — order header (customer, date, status)
  order_items — order lines (order, product, qty, unit_price at time of sale)

Run directly to (re)create the database:
  python db/seed.py

Called automatically by main.py lifespan on startup — skips seeding if the
database already contains data.
"""

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "sales.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS regions (
    region_id   INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    country     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    email       TEXT    NOT NULL UNIQUE,
    region_id   INTEGER NOT NULL REFERENCES regions(region_id),
    joined_date TEXT    NOT NULL       -- ISO-8601 date
);

CREATE TABLE IF NOT EXISTS products (
    product_id  INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    category    TEXT    NOT NULL,
    unit_price  REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id    INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date  TEXT    NOT NULL,      -- ISO-8601 date
    status      TEXT    NOT NULL       -- 'completed' | 'pending' | 'cancelled'
);

CREATE TABLE IF NOT EXISTS order_items (
    item_id     INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(order_id),
    product_id  INTEGER NOT NULL REFERENCES products(product_id),
    quantity    INTEGER NOT NULL,
    unit_price  REAL    NOT NULL       -- price at time of sale (may differ from catalogue)
);
"""

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

REGIONS = [
    (1, "North America", "USA"),
    (2, "Europe",        "Germany"),
    (3, "Asia Pacific",  "Singapore"),
    (4, "Latin America", "Brazil"),
    (5, "Middle East",   "UAE"),
]

PRODUCTS = [
    # (id, name, category, unit_price)
    (1,  "Laptop Pro 15",       "Electronics",   1_299.99),
    (2,  "Wireless Mouse",      "Electronics",      29.99),
    (3,  "Mechanical Keyboard", "Electronics",     119.99),
    (4,  "4K Monitor",          "Electronics",     499.99),
    (5,  "USB-C Hub",           "Electronics",      49.99),
    (6,  "Office Chair",        "Furniture",       349.99),
    (7,  "Standing Desk",       "Furniture",       599.99),
    (8,  "Desk Lamp",           "Furniture",        39.99),
    (9,  "Notebook (A5)",       "Stationery",        8.99),
    (10, "Ballpoint Pens 10pk", "Stationery",        5.99),
    (11, "Whiteboard 90×60",    "Stationery",       59.99),
    (12, "Python Bootcamp",     "Training",        199.99),
    (13, "SQL Masterclass",     "Training",        149.99),
    (14, "Cloud Foundations",   "Training",        179.99),
    (15, "Noise-Cancel Headset","Electronics",     249.99),
]

FIRST_NAMES = [
    "Lena","Marcus","Sofia","James","Yuki","Carlos","Amara","Noah",
    "Priya","Ethan","Chloe","Ravi","Isabella","Omar","Zoe","Felix",
    "Anika","Lucas","Maya","Soren","Nia","Hugo","Elena","Kenji",
]
LAST_NAMES = [
    "Schmidt","Okafor","Tanaka","Reyes","Müller","Chen","Patel","Kowalski",
    "Diallo","Johansson","Kim","Santos","Andersen","Nguyen","Hoffmann","Al-Rashid",
]

STATUSES = ["completed", "completed", "completed", "pending", "cancelled"]   # weighted


def _random_date(start: date, end: date) -> str:
    delta = (end - start).days
    return (start + timedelta(days=random.randint(0, delta))).isoformat()


def _generate_customers(n: int = 200) -> list[tuple]:
    random.seed(42)
    seen_emails: set[str] = set()
    customers = []
    for i in range(1, n + 1):
        first = random.choice(FIRST_NAMES)
        last  = random.choice(LAST_NAMES)
        base_email = f"{first.lower()}.{last.lower()}{i}@example.com"
        while base_email in seen_emails:
            base_email = f"{first.lower()}.{last.lower()}{i}_{random.randint(10,99)}@example.com"
        seen_emails.add(base_email)
        region_id   = random.randint(1, len(REGIONS))
        joined_date = _random_date(date(2020, 1, 1), date(2023, 6, 30))
        customers.append((i, f"{first} {last}", base_email, region_id, joined_date))
    return customers


def _generate_orders_and_items(
    customers: list[tuple],
    n_orders: int = 1_200,
) -> tuple[list[tuple], list[tuple]]:
    random.seed(7)
    orders: list[tuple]      = []
    order_items: list[tuple] = []
    item_id = 1

    for order_id in range(1, n_orders + 1):
        customer = random.choice(customers)
        customer_id  = customer[0]
        joined_date  = date.fromisoformat(customer[4])
        order_date   = _random_date(joined_date, date(2024, 12, 31))
        status       = random.choice(STATUSES)
        orders.append((order_id, customer_id, order_date, status))

        # 1–5 line items per order
        n_items  = random.randint(1, 5)
        products = random.sample(PRODUCTS, n_items)
        for prod in products:
            product_id = prod[0]
            catalogue_price = prod[3]
            # Simulate occasional discounts (±10 %)
            sale_price = round(catalogue_price * random.uniform(0.90, 1.05), 2)
            quantity   = random.randint(1, 10)
            order_items.append((item_id, order_id, product_id, quantity, sale_price))
            item_id += 1

    return orders, order_items


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def seed_database(force: bool = False) -> None:
    """
    Create and populate the database.

    Args:
        force: If True, drop and recreate all tables even if data exists.
               Useful for a fresh reset during development.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    try:
        cursor = conn.cursor()

        # Check if already seeded
        if not force:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='orders';"
            )
            if cursor.fetchone():
                cursor.execute("SELECT COUNT(*) FROM orders;")
                if cursor.fetchone()[0] > 0:
                    print("[seed] Database already populated — skipping.")
                    return

        if force:
            for tbl in ["order_items", "orders", "products", "customers", "regions"]:
                cursor.execute(f"DROP TABLE IF EXISTS {tbl};")

        # Create schema
        conn.executescript(DDL)

        # Insert reference data
        cursor.executemany(
            "INSERT OR IGNORE INTO regions VALUES (?,?,?);", REGIONS
        )
        cursor.executemany(
            "INSERT OR IGNORE INTO products VALUES (?,?,?,?);", PRODUCTS
        )

        # Generate and insert transactional data
        customers   = _generate_customers(200)
        orders, items = _generate_orders_and_items(customers, 1_200)

        cursor.executemany(
            "INSERT OR IGNORE INTO customers VALUES (?,?,?,?,?);", customers
        )
        cursor.executemany(
            "INSERT OR IGNORE INTO orders VALUES (?,?,?,?);", orders
        )
        cursor.executemany(
            "INSERT OR IGNORE INTO order_items VALUES (?,?,?,?,?);", items
        )

        conn.commit()
        print(
            f"[seed] Database created at {DB_PATH}\n"
            f"       {len(REGIONS)} regions, {len(customers)} customers, "
            f"{len(PRODUCTS)} products, {len(orders)} orders, {len(items)} line items."
        )

    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    seed_database(force=force)
