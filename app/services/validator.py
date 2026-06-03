import sqlparse
import structlog

logger = structlog.get_logger()
class SQLValidator:
    BLOCKED_KEYWORDS = {"DROP", "DELETE", "TRUNCATE", "ALTER", "INSERT", "UPDATE", "CREATE"}
    def validate(self, sql: str) -> tuple[bool, str]:
        if not sql or not sql.strip():
            return False, "Empty SQL query"

        sql = sql.strip()
        upper_sql = sql.upper()
        for keyword in self.BLOCKED_KEYWORDS:
            if f" {keyword} " in f" {upper_sql} ":
                return False, f"Blocked SQL operation: {keyword}"

        parsed = sqlparse.parse(sql)
        if not parsed:
            return False, "Could not parse SQL"

        first_statement = parsed[0]
        stmt_type = first_statement.get_type()

        if stmt_type and stmt_type.upper() not in ("SELECT", "UNKNOWN"):
            if not upper_sql.strip().startswith("WITH") and not upper_sql.strip().startswith("SELECT"):
                return False, f"Only SELECT queries are allowed, got: {stmt_type}"
        try:
            formatted = sqlparse.format(sql, reindent=True, keyword_case="upper")
            if not formatted.strip():
                return False, "SQL formatting produced empty result"
        except Exception as e:
            return False, f"SQL parsing error: {str(e)}"
        if "SELECT" not in upper_sql:
            return False, "Query must contain SELECT"

        if "FROM" not in upper_sql:
            if "SELECT" in upper_sql and ("(" in upper_sql or upper_sql.strip().startswith("SELECT 1")):
                pass
            else:
                return False, "Query must contain FROM clause"
        logger.info("sql_validated", sql_preview=sql[:100])
        return True, "SQL is valid"
