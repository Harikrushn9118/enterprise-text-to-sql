import json
import os
import re
import structlog

logger = structlog.get_logger()
KNOWLEDGE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "domain_knowledge.json"
)

class DomainResolver:
    def __init__(self):
        self.knowledge_base = self._load_knowledge()

    def _load_knowledge(self) -> list[dict]:
        if not os.path.exists(KNOWLEDGE_PATH):
            logger.warning("domain_knowledge_not_found", path=KNOWLEDGE_PATH)
            return []

        with open(KNOWLEDGE_PATH, "r") as f:
            data = json.load(f)

        logger.info("domain_knowledge_loaded", count=len(data))
        return data

    def resolve(self, question: str, schemas: list[dict]) -> list[dict]:
        if not self.knowledge_base:
            return []
        question_lower = question.lower()
        retrieved_tables = {s["table_name"].lower() for s in schemas}
        resolved = []
        for entry in self.knowledge_base:
            term = entry.get("term", "").lower()
            table = entry.get("table", "")
            column = entry.get("column", "")
            value = entry.get("value", "")
            if term not in question_lower:
                continue
            if str(value).startswith("FORMULA:"):
                resolved.append({
                    "term": entry["term"],
                    "predicate": f"/* {value} */",
                    "table": table,
                    "column": column,
                    "value": value,
                    "type": "formula",
                })
                continue

            if table.lower() in retrieved_tables:
                predicate = f"{table}.{column} = '{value}'"
                resolved.append({
                    "term": entry["term"],
                    "predicate": predicate,
                    "table": table,
                    "column": column,
                    "value": value,
                    "type": "exact_match",
                })
            else:
                resolved.append({
                    "term": entry["term"],
                    "predicate": f"{table}.{column} = '{value}'",
                    "table": table,
                    "column": column,
                    "value": value,
                    "type": "external_lookup",
                })
        logger.info("domain_resolved", count=len(resolved),
                     terms=[r["term"] for r in resolved])
        return resolved
