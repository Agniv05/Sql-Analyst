"""
tools/executor.py — Safe, read-only SQL query executor.

Enforces SELECT-only access via two layers:
  1. Keyword check — reject anything that isn't a SELECT statement
  2. SQLite connection opened in read-only URI mode — the DB file itself
     cannot be modified even if a clever prompt bypasses layer 1

Returns results as a list of row dicts (column_name → value), capped at
MAX_ROWS to keep the context window payload reasonable.
"""

import re
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent.parent / "db" / "sales.db"

MAX_ROWS = 500          # cap result set sent back to Claude
TIMEOUT_SECONDS = 10    # abort long-running queries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DISALLOWED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|PRAGMA)\b",
    re.IGNORECASE,
)


def _is_safe(query: str) -> tuple[bool, str]:
    """Return (True, '') if query looks safe, else (False, reason)."""
    stripped = query.strip()
    if not stripped.upper().startswith("SELECT"):
        return False, "Only SELECT statements are allowed."
    if _DISALLOWED.search(stripped):
        match = _DISALLOWED.search(stripped)
        return False, f"Disallowed keyword detected: {match.group()}"
    return True, ""


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run_sql(query: str) -> dict[str, Any]:
    """
    Execute a SELECT query and return structured results.

    Returns on success:
        {
          "rows":    [{"col": val, ...}, ...],
          "columns": ["col1", "col2", ...],
          "row_count": N,
          "truncated": bool,   # True if results were capped at MAX_ROWS
        }

    Returns on error:
        {
          "error": "human-readable message"
        }
    """
    # --- safety gate ---
    safe, reason = _is_safe(query)
    if not safe:
        return {"error": f"Query rejected: {reason}"}

    # --- execute in read-only mode ---
    # The ?mode=ro URI prevents any writes at the SQLite driver level
    uri = f"file:{DB_PATH}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=TIMEOUT_SECONDS)
        conn.row_factory = sqlite3.Row          # enables column-name access
        try:
            cursor = conn.cursor()
            cursor.execute(query)
            raw_rows = cursor.fetchmany(MAX_ROWS + 1)   # fetch one extra to detect truncation

            truncated = len(raw_rows) > MAX_ROWS
            rows = raw_rows[:MAX_ROWS]

            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            row_dicts = [dict(row) for row in rows]

            return {
                "rows": row_dicts,
                "columns": columns,
                "row_count": len(row_dicts),
                "truncated": truncated,
            }

        finally:
            conn.close()

    except sqlite3.OperationalError as exc:
        return {"error": f"SQL error: {exc}"}
    except sqlite3.DatabaseError as exc:
        return {"error": f"Database error: {exc}"}
    except Exception as exc:
        return {"error": f"Unexpected error: {exc}"}
