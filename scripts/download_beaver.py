import os
import json
import random
from dotenv import load_dotenv
from datasets import load_dataset

load_dotenv()

DB_SPLITS = ["dw", "nova", "neutron"]

def main():
    token = os.getenv("HF_TOKEN")
    if not token:
        print("Error: HF_TOKEN not found in .env")
        return

    print("Downloading beaver-table (schemas) for all databases...")
    schemas = []
    for db_name in DB_SPLITS:
        print(f"  Loading {db_name}...")
        tables_data = load_dataset("beaverbench/beaver-table", split=db_name, token=token)
        
        for row in tables_data:
            table_name = row.get("table_name", "")
            cols = row.get("column_names", [])
            
            if isinstance(cols, str):
                try:
                    cols = json.loads(cols)
                except:
                    cols = []
                    
            column_names = []
            for col in cols:
                if isinstance(col, dict) and "name" in col:
                    column_names.append(col["name"])
                elif isinstance(col, str):
                    column_names.append(col)
                    
            readable_name = table_name.replace("_", " ").lower()
            col_text = ", ".join(column_names[:15])
            desc = f"Table {readable_name} in {db_name} database with columns: {col_text}"
            
            schemas.append({
                "table_name": table_name,
                "columns": column_names,
                "join_keys": [],
                "description": desc,
                "db": db_name
            })
        
    with open("app/table_schemas.json", "w") as f:
        json.dump(schemas, f, indent=2)
    print(f"Saved {len(schemas)} total schemas to app/table_schemas.json")

    print("Downloading beaver-query (questions) for all databases...")
    all_queries = []
    for db_name in DB_SPLITS:
        print(f"  Loading {db_name} queries...")
        queries_data = load_dataset("beaverbench/beaver-query", split=db_name, token=token)
        for q in queries_data:
            q["_db"] = db_name
            all_queries.append(q)
    
    benchmark_questions = []
    domain_knowledge_list = []
    
    complex_queries = [q for q in all_queries if "complex" in str(q.get("category", "")).lower() or "nested" in str(q.get("detailed_category", "")).lower()]
    
    random.seed(42)
    sampled = random.sample(complex_queries, min(20, len(complex_queries)))
    
    for row in sampled:
        benchmark_questions.append({
            "question": row.get("question", ""),
            "query": row.get("sql", ""),
            "db": row.get("_db", "dw"),
            "complexity": row.get("category", "complex")
        })
        
    with open("app/benchmark_questions.json", "w") as f:
        json.dump(benchmark_questions, f, indent=2)
    print(f"Saved {len(benchmark_questions)} questions to app/benchmark_questions.json")

    for row in all_queries:
        dk_raw = row.get("domain_knowledge", "[]")
        if dk_raw and dk_raw != "[]":
            try:
                dk_items = json.loads(dk_raw)
                for item in dk_items:
                    if " predicated by " in item:
                        parts = item.split(" predicated by ")
                        term = parts[0].replace('"', '').strip()
                        predicate = parts[1].replace('"', '').strip()
                        domain_knowledge_list.append({
                            "term": term,
                            "predicate": predicate
                        })
            except:
                pass
            
    unique_dk = {d["predicate"]: d for d in domain_knowledge_list}.values()
    final_dk = list(unique_dk)[:100]
    
    with open("app/domain_knowledge.json", "w") as f:
        json.dump(final_dk, f, indent=2)
    print(f"Saved {len(final_dk)} domain knowledge facts to app/domain_knowledge.json")
    print("Done!")

if __name__ == "__main__":
    main()
