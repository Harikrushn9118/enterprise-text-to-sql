import re
import structlog
from difflib import SequenceMatcher

logger = structlog.get_logger()
class SchemaLinker:
    def detect_join_keys(self, schemas: list[dict]) -> list[dict]:
        joins = []
        seen = set()
        for schema in schemas:
            table = schema["table_name"]
            for jk in schema.get("join_keys", []):
                if "→" in jk:
                    parts = jk.split("→")
                    if len(parts) == 2:
                        left_col = parts[0].strip()
                        right_ref = parts[1].strip()
                        right_table = right_ref.split(".")[0] if "." in right_ref else ""
                        right_col = right_ref.split(".")[1] if "." in right_ref else right_ref

                        retrieved_tables = {s["table_name"].lower() for s in schemas}
                        if right_table.lower() in retrieved_tables:
                            key = tuple(sorted([f"{table}.{left_col}", right_ref]))
                            if key not in seen:
                                seen.add(key)
                                joins.append({
                                    "left": f"{table}.{left_col}",
                                    "right": right_ref,
                                    "confidence": "high",
                                    "method": "explicit_schema_hint",
                                })
        table_names = [s["table_name"] for s in schemas]
        for i in range(len(schemas)):
            for j in range(i + 1, len(schemas)):
                t1_name = schemas[i]["table_name"]
                t2_name = schemas[j]["table_name"]
                t1_cols = set(schemas[i].get("columns", []))
                t2_cols = set(schemas[j].get("columns", []))

                shared_cols = t1_cols & t2_cols
                for col in shared_cols:
                    if col.lower() in {"status", "name", "description", "type", "date", "created_date"}:
                        continue

                    key = tuple(sorted([f"{t1_name}.{col}", f"{t2_name}.{col}"]))
                    if key not in seen:
                        seen.add(key)
                        joins.append({
                            "left": f"{t1_name}.{col}",
                            "right": f"{t2_name}.{col}",
                            "confidence": "high",
                            "method": "exact_column_match",
                        })
        for i in range(len(schemas)):
            for j in range(i + 1, len(schemas)):
                t1_name = schemas[i]["table_name"]
                t2_name = schemas[j]["table_name"]
                t1_cols = schemas[i].get("columns", [])
                t2_cols = schemas[j].get("columns", [])

                for c1 in t1_cols:
                    if c1.endswith("_id"):
                        base = c1.replace("_id", "")
                        if base == t2_name.rstrip("s") or base + "s" == t2_name:
                            for c2 in t2_cols:
                                if c2 == c1:
                                    key = tuple(sorted([f"{t1_name}.{c1}", f"{t2_name}.{c2}"]))
                                    if key not in seen:
                                        seen.add(key)
                                        joins.append({
                                            "left": f"{t1_name}.{c1}",
                                            "right": f"{t2_name}.{c2}",
                                            "confidence": "medium",
                                            "method": "id_suffix_match",
                                        })
        logger.info("join_keys_detected", count=len(joins))
        return joins

    def map_columns(self, question: str, schemas: list[dict]) -> list[dict]:
        mappings = []
        question_lower = question.lower()
        question_words = set(re.findall(r'\b\w+\b', question_lower))

        SEMANTIC_MAP = {
            "revenue": {"expression": "SUM({t}.quantity * {t}.unit_price)", "columns": ["quantity", "unit_price"]},
            "sales": {"expression": "SUM({t}.total_amount)", "columns": ["total_amount"]},
            "total sales": {"expression": "SUM({t}.total_amount)", "columns": ["total_amount"]},
            "spending": {"expression": "SUM({t}.total_amount)", "columns": ["total_amount"]},
            "average order": {"expression": "AVG({t}.total_amount)", "columns": ["total_amount"]},
            "order value": {"expression": "SUM({t}.total_amount)", "columns": ["total_amount"]},
            "return rate": {"expression": "COUNT(DISTINCT {t}.return_id) * 100.0 / COUNT(DISTINCT {t2}.item_id)", "columns": ["return_id", "item_id"]},
            "delivery time": {"expression": "julianday({t}.delivery_date) - julianday({t}.ship_date)", "columns": ["delivery_date", "ship_date"]},
            "roi": {"expression": "(SUM({t}.revenue) - SUM({t2}.budget)) / NULLIF(SUM({t2}.budget), 0)", "columns": ["revenue", "budget"]},
            "headcount": {"expression": "COUNT({t}.employee_id)", "columns": ["employee_id"]},
            "rating": {"expression": "AVG({t}.rating)", "columns": ["rating"]},
        }

        for term, info in SEMANTIC_MAP.items():
            if term in question_lower:
                for schema in schemas:
                    table_cols = set(schema.get("columns", []))
                    matching_cols = [c for c in info["columns"] if c in table_cols]
                    if matching_cols:
                        mappings.append({
                            "phrase": term,
                            "table": schema["table_name"],
                            "columns": matching_cols,
                            "expression": info["expression"],
                            "confidence": 0.9,
                            "method": "semantic_map",
                        })
                        break

        for schema in schemas:
            table_name = schema["table_name"]
            for col in schema.get("columns", []):
                col_words = set(col.lower().replace("_", " ").split())
                overlap = question_words & col_words
                if overlap and len(overlap) >= 1:
                    score = len(overlap) / max(len(col_words), 1)

                    if len(overlap) == 1 and list(overlap)[0] in {"id", "name", "date", "type", "status", "key"}:
                        score *= 0.3
                    if score >= 0.3:
                        mappings.append({
                            "phrase": " ".join(overlap),
                            "table": table_name,
                            "columns": [col],
                            "expression": f"{table_name}.{col}",
                            "confidence": round(score, 2),
                            "method": "word_overlap",
                        })
        mappings.sort(key=lambda x: x["confidence"], reverse=True)

        seen_cols = set()
        unique_mappings = []
        for m in mappings:
            col_key = (m["table"], tuple(m["columns"]))
            if col_key not in seen_cols:
                seen_cols.add(col_key)
                unique_mappings.append(m)
        logger.info("columns_mapped", count=len(unique_mappings))
        return unique_mappings
