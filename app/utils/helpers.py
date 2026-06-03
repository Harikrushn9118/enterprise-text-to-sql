import re
def clean_sql(sql: str) -> str:
    if not sql:
        return ""
    sql = re.sub(r'```sql\s*\n?', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'```\s*\n?', '', sql)
    lines = sql.split('\n')
    sql_lines = []
    found_sql = False
    for line in lines:
        stripped = line.strip()
        if not found_sql and stripped.startswith('--'):
            continue
        if not found_sql and re.match(r'^(SELECT|WITH|INSERT|UPDATE|DELETE)\s', stripped, re.IGNORECASE):
            found_sql = True
        if found_sql:
            sql_lines.append(line)

    if sql_lines:
        sql = '\n'.join(sql_lines)
    else:
        match = re.search(r'(SELECT|WITH)\s', sql, re.IGNORECASE)
        if match:
            sql = sql[match.start():]

    if ';' in sql:
        sql = sql[:sql.index(';')]

    sql = sql.strip()
    return sql

def truncate_text(text: str, max_length: int = 500) -> str:
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def format_schema_for_display(schema: dict) -> str:
    cols = ", ".join(schema.get("columns", []))
    return f"{schema['table_name']} ({cols})"


def normalize_table_name(name: str) -> str:
    return name.strip().lower().replace('"', '').replace("'", "").replace('`', '')
