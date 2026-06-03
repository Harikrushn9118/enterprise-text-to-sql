import sqlite3
import json
import os

def create_mock_db():
    db_path = "mock_db.db"
    
    if os.path.exists(db_path):
        os.remove(db_path)
        
    print(f"Creating new SQLite database at {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    with open("app/table_schemas.json", "r") as f:
        schemas = json.load(f)
        
    for schema in schemas:
        table_name = schema["table_name"]
        columns = schema["columns"]
        
        if not columns:
            print(f"Skipping {table_name}: No columns found.")
            continue
        col_defs = ", ".join([f'"{col}" TEXT' for col in columns])
        
        create_stmt = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({col_defs});'
        
        try:
            cursor.execute(create_stmt)
        except Exception as e:
            print(f"Failed to create table {table_name}: {e}")
            
    conn.commit()
    conn.close()

    print(f"Successfully created {len(schemas)} tables in {db_path}!")

if __name__ == "__main__":
    create_mock_db()
