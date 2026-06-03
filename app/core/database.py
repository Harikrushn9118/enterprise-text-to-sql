import sqlite3
import os
import structlog

logger = structlog.get_logger()
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "mock_db.db")

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def execute_query(sql: str) -> dict:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
        return {
            "success": True,
            "columns": columns,
            "rows": rows[:50],
            "row_count": len(rows),
            "error": None,
        }
    except Exception as e:
        logger.error("sql_execution_error", error=str(e), sql=sql[:200])
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": str(e),
        }

def get_all_table_names() -> list[str]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    return tables