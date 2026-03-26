"""
tools/schema.py — Database schema inspector.

Returns all table names with their column names and types.
Claude calls this first when it doesn't yet know the structure of the DB.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "sales.db"


def get_schema() -> dict:
    """
    Introspect the SQLite database and return its schema.

    Returns:
        {
          "table_name": [
            {"name": "col_name", "type": "TEXT", "pk": 0, "notnull": 0},
            ...
          ],
          ...
        }
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()

        # Get all user-defined tables (exclude SQLite internals)
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        tables = [row[0] for row in cursor.fetchall()]

        schema: dict = {}
        for table in tables:
            cursor.execute(f"PRAGMA table_info({table});")
            columns = [
                {
                    "name": row[1],
                    "type": row[2],
                    "notnull": bool(row[3]),
                    "pk": bool(row[5]),
                }
                for row in cursor.fetchall()
            ]

            # Also attach row count — useful context for Claude
            cursor.execute(f"SELECT COUNT(*) FROM {table};")
            row_count = cursor.fetchone()[0]

            schema[table] = {
                "columns": columns,
                "row_count": row_count,
            }

        return schema

    finally:
        conn.close()
