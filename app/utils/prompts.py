import json
import os
import numpy as np

SYSTEM_PROMPT = """You are an expert SQL writer. Your ONLY job is to write the final SQL query.

IMPORTANT: All analysis (tables, joins, mappings, domain knowledge, query plan) is PRE-COMPUTED and provided below. 
Do NOT ignore the hints. Do NOT add tables, joins, or columns that are not explicitly provided.

CRITICAL SYNTAX & COMPATIBILITY RULES:
1. NO SEMICOLONS: NEVER EVER add a semicolon (;) anywhere in your response. The system will crash if you output a semicolon.
2. TABLE ALIASES & AMBIGUOUS COLUMNS: 
   - ALWAYS fully qualify EVERY column name with its table name or alias (e.g., `table_name.column_name`).
   - NEVER use bare columns. If two tables have the same column name (e.g. `id`), you MUST prefix it (e.g. `t1.id`) to avoid ambiguous column errors.
   - Ensure you are pulling columns from the correct table alias.
3. EXACT COLUMNS: ONLY select columns that explicitly exist in the provided CREATE TABLE schemas. NEVER guess, hallucinate, or truncate names. If a column is not in the schema, do NOT use it.
4. STRICT SQLITE COMPLIANCE:
   - You MUST write 100% compliant, explicit SQLite 3 syntax. Never use shorthand syntax, and never use functions/features from other dialects (e.g. SQL Server, PostgreSQL).
   - Use COALESCE, never ISNULL. Use LOG(), never LN(). Use LIKE/GLOB, never REGEXP.
   - For variance, use: AVG(x*x) - AVG(x)*AVG(x)
   - For stddev, use: SQRT(AVG(x*x) - AVG(x)*AVG(x))
   - For geometric mean, use: EXP(AVG(LOG(x)))
   - FULLY SPECIFY SYNTAX: If SQLite requires full bounds or explicit formatting (e.g. for window frames), you MUST spell out the complete specification (e.g. `ROWS BETWEEN CURRENT ROW AND n FOLLOWING`, never shorthand).
5. GROUP BY RULES: When using aggregations, you MUST include a GROUP BY clause that contains ALL non-aggregated columns from your SELECT statement.
6. NULL HANDLING: Handle NULLs properly with COALESCE or IS NOT NULL.
7. CTE RULES: If using WITH clauses, you MUST have a final main SELECT at the end. Do NOT nest WITH clauses.
8. OUTPUT FORMAT: Return ONLY the raw SQL string. Do NOT wrap it in ```sql ... ``` markdown blocks. No explanations.
"""


FEW_SHOT_POOL = [
    {
        "question": "Among the top 10 instance display names in availability zone 'flare3' with the highest number of network info cache records, return only those display names that also have a non-deleted system metadata entry with KEY = 'image_image_type' and whose average instance MEMORY_MB is greater than 75% of the maximum MEMORY_MB for that same display name...",
        "schemas": "Table: instances (uuid, display_name, availability_zone, memory_mb, vcpus)\nTable: instance_system_metadata (id, instance_uuid, key, value, deleted)\nTable: instance_info_caches (id, instance_uuid, network_info)",
        "reasoning": "Tables: instances, instance_system_metadata, instance_info_caches | Join: instance.uuid = ism.instance_uuid | Plan: Complex CTEs required for filtering by top 10 records, then joining back.",
        "sql": "WITH MemoryStatsByDisplayName AS ( WITH inner_cte AS ( SELECT i.DISPLAY_NAME, AVG(i.MEMORY_MB*i.MEMORY_MB) - AVG(i.MEMORY_MB)*AVG(i.MEMORY_MB) AS memory_mb_variance, SQRT(AVG(i.MEMORY_MB*i.MEMORY_MB) - AVG(i.MEMORY_MB)*AVG(i.MEMORY_MB)) AS memory_mb_stddev FROM INSTANCES AS i JOIN INSTANCE_SYSTEM_METADATA AS ism ON ism.INSTANCE_UUID = i.UUID JOIN INSTANCE_INFO_CACHES AS iic ON i.UUID = iic.INSTANCE_UUID WHERE ism.KEY = 'image_image_type' AND ism.DELETED = 0 GROUP BY i.DISPLAY_NAME ORDER BY memory_mb_variance DESC ) SELECT inner_cte.DISPLAY_NAME, inner_cte.memory_mb_variance, inner_cte.memory_mb_stddev, AVG(i.MEMORY_MB) AS avg_memory_mb, MAX(i.MEMORY_MB) AS max_memory_mb FROM inner_cte JOIN INSTANCES AS i ON i.DISPLAY_NAME = inner_cte.DISPLAY_NAME JOIN INSTANCE_SYSTEM_METADATA AS ism ON ism.INSTANCE_UUID = i.UUID JOIN INSTANCE_INFO_CACHES AS iic ON iic.INSTANCE_UUID = i.UUID WHERE ism.KEY = 'image_image_type' AND ism.DELETED = 0 GROUP BY inner_cte.DISPLAY_NAME, inner_cte.memory_mb_variance, inner_cte.memory_mb_stddev HAVING (AVG(i.MEMORY_MB) * 1.0 / MAX(i.MEMORY_MB)) > 0.75 ORDER BY avg_memory_mb DESC ), Top10CacheRecordsFlare3 AS ( WITH inner_cte AS ( SELECT i.display_name, COUNT(iic.id) AS cache_records FROM INSTANCES AS i JOIN INSTANCE_INFO_CACHES AS iic ON i.uuid = iic.instance_uuid WHERE i.availability_zone = 'flare3' GROUP BY i.display_name ORDER BY cache_records DESC LIMIT 10 ) SELECT inner_cte.display_name, inner_cte.cache_records, SUM(i.vcpus) AS total_vcpus, SUM(i.memory_mb) AS total_memory_mb FROM inner_cte JOIN INSTANCES AS i ON i.display_name = inner_cte.display_name AND i.availability_zone = 'flare3' GROUP BY inner_cte.display_name, inner_cte.cache_records ORDER BY inner_cte.cache_records DESC ) SELECT t.display_name, t.cache_records, t.total_vcpus, t.total_memory_mb, m.memory_mb_variance, m.memory_mb_stddev, m.avg_memory_mb, m.max_memory_mb FROM Top10CacheRecordsFlare3 AS t JOIN MemoryStatsByDisplayName AS m ON m.DISPLAY_NAME = t.display_name ORDER BY t.cache_records DESC, m.avg_memory_mb DESC"
    },
    {
        "question": "For each department that grants degrees (excluding Political Science), provide the department name, the average and variance of the total number of enrolled students in subjects offered by that department...",
        "schemas": "Table: SIS_COURSE_DESCRIPTION (COURSE, DEPARTMENT_NAME, IS_DEGREE_GRANTING)\nTable: SUBJECT_OFFERED_SUMMARY (COURSE_NUMBER, NUM_ENROLLED_STUDENTS)\nTable: TIP_DETAIL (TIP_SUBJECT_OFFERED_KEY, TIP_MATERIAL_STATUS_KEY)",
        "reasoning": "Tables: SIS_COURSE_DESCRIPTION, SUBJECT_OFFERED_SUMMARY, TIP_DETAIL | Domain: IS_DEGREE_GRANTING = 'Y' | Plan: Two CTEs required. One for DeptEnrollmentStats, another for DeptMaterialVariance. Then LEFT JOIN them.",
        "sql": "WITH DeptEnrollmentStats AS ( SELECT scd.DEPARTMENT_NAME, AVG(sos.NUM_ENROLLED_STUDENTS) AS avg_enrollment, AVG(sos.NUM_ENROLLED_STUDENTS*sos.NUM_ENROLLED_STUDENTS) - AVG(sos.NUM_ENROLLED_STUDENTS)*AVG(sos.NUM_ENROLLED_STUDENTS) AS enrollment_variance FROM SIS_COURSE_DESCRIPTION scd JOIN SUBJECT_OFFERED_SUMMARY sos ON scd.COURSE = sos.COURSE_NUMBER WHERE sos.NUM_ENROLLED_STUDENTS > 0 AND scd.IS_DEGREE_GRANTING = 'Y' AND scd.DEPARTMENT_NAME != 'Political Science' GROUP BY scd.DEPARTMENT_NAME ORDER BY enrollment_variance DESC ), DeptMaterialVariance AS ( SELECT tso.OFFER_DEPT_NAME, AVG(tso.NUM_ENROLLED_STUDENTS*tso.NUM_ENROLLED_STUDENTS) - AVG(tso.NUM_ENROLLED_STUDENTS)*AVG(tso.NUM_ENROLLED_STUDENTS) AS enrolled_variance FROM TIP_DETAIL td JOIN TIP_SUBJECT_OFFERED tso ON td.TIP_SUBJECT_OFFERED_KEY = tso.TIP_SUBJECT_OFFERED_KEY WHERE tso.NUM_ENROLLED_STUDENTS > 0 AND td.TIP_MATERIAL_STATUS_KEY = 'RQ' AND tso.OFFER_DEPT_NAME IN ('Chemistry', 'Biology') GROUP BY tso.OFFER_DEPT_NAME ORDER BY enrolled_variance DESC ) SELECT des.DEPARTMENT_NAME, des.avg_enrollment, des.enrollment_variance, dmv.enrolled_variance FROM DeptEnrollmentStats des LEFT JOIN DeptMaterialVariance dmv ON des.DEPARTMENT_NAME = dmv.OFFER_DEPT_NAME ORDER BY des.enrollment_variance DESC, dmv.enrolled_variance DESC"
    }
]

_pool_embeddings = None
_pool_model = None


def _get_pool_embeddings():
    global _pool_embeddings, _pool_model
    if _pool_embeddings is None:
        from sentence_transformers import SentenceTransformer
        from app.core.config import settings
        _pool_model = SentenceTransformer(settings.EMBEDDING_MODEL)
        questions = [ex["question"] for ex in FEW_SHOT_POOL]
        _pool_embeddings = _pool_model.encode(
            questions, show_progress_bar=False, normalize_embeddings=True
        )
    return _pool_model, _pool_embeddings


def select_dynamic_examples(question: str, top_k: int = 5) -> list[dict]:
    model, pool_embs = _get_pool_embeddings()
    q_emb = model.encode([question], show_progress_bar=False, normalize_embeddings=True)[0]
    similarities = np.dot(pool_embs, q_emb)
    top_indices = np.argsort(similarities)[::-1][:top_k]
    return [FEW_SHOT_POOL[i] for i in top_indices]


def build_few_shot_section(question: str = None) -> str:
    if question:
        examples = select_dynamic_examples(question, top_k=5)
    else:
        examples = FEW_SHOT_POOL[:1]

    lines = ["--- FEW-SHOT EXAMPLES (follow this reasoning pattern) ---\n"]
    for i, ex in enumerate(examples, 1):
        lines.append(f"Example {i}:")
        lines.append(f"Question: {ex['question']}")
        lines.append(f"Schemas: {ex['schemas']}")
        lines.append(f"Reasoning: {ex['reasoning']}")
        lines.append(f"SQL: {ex['sql']}\n")
    return "\n".join(lines)


def build_join_hints(schemas: list[dict]) -> str:
    hints = []
    table_cols = {}
    for s in schemas:
        table_cols[s["table_name"]] = set(s.get("columns", []))
    table_names = list(table_cols.keys())
    for i in range(len(table_names)):
        for j in range(i + 1, len(table_names)):
            t1, t2 = table_names[i], table_names[j]
            shared = table_cols[t1] & table_cols[t2]
            for col in shared:
                hints.append(f"  {t1}.{col} = {t2}.{col}")
    for s in schemas:
        for jk in s.get("join_keys", []):
            if "→" in jk:
                hints.append(f"  {s['table_name']}.{jk}")
    if hints:
        return "Join Relationships:\n" + "\n".join(hints)
    return ""


def build_domain_knowledge(schemas: list[dict]) -> str:
    knowledge_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "domain_knowledge.json"
    )
    if not os.path.exists(knowledge_path):
        return ""
    with open(knowledge_path, "r") as f:
        knowledge = json.load(f)
    if not knowledge:
        return ""
    table_names = {s["table_name"].lower() for s in schemas}
    relevant = [
        k for k in knowledge
        if k.get("table", "").lower() in table_names
    ]
    if not relevant:
        return ""
    lines = ["Domain Knowledge (use these mappings in your query):"]
    for k in relevant:
        lines.append(f"  \"{k['term']}\" → {k['table']}.{k['column']} = '{k['value']}'")
    return "\n".join(lines)


SQL_GENERATION_PROMPT = """Given the following question and relevant table schemas, generate a valid SQL query.
Follow the Chain-of-Thought reasoning pattern shown in the examples.
{few_shot_section}
--- CURRENT TASK ---

Question: {question}

Relevant Table Schemas:
{schemas}

{join_hints}

{domain_knowledge}

Think step by step, then generate the SQL query:"""


def build_sql_prompt(question: str, schemas: list[dict]) -> str:
    """
    Build the full SQL generation prompt with:
    - Dynamic few-shot examples (selected by similarity)
    - Chain-of-Thought reasoning pattern
    - Explicit join key hints
    - Domain knowledge mappings
    """
    schema_lines = []
    for s in schemas:
        cols = ", ".join(s.get("columns", []))
        jk = s.get("join_keys", [])
        line = f"Table: {s['table_name']} ({cols})"
        if jk:
            line += f" [Join keys: {', '.join(jk)}]"
        schema_lines.append(line)

    schemas_text = "\n".join(schema_lines)
    few_shot = build_few_shot_section(question=question)
    join_hints = build_join_hints(schemas)
    domain_knowledge = build_domain_knowledge(schemas)

    return SQL_GENERATION_PROMPT.format(
        question=question,
        schemas=schemas_text,
        few_shot_section=few_shot,
        join_hints=join_hints,
        domain_knowledge=domain_knowledge,
    )


def build_oracle_prompt(question: str, hints: dict) -> str:
    schemas = hints["schemas"]
    join_keys = hints["join_keys"]
    column_mappings = hints["column_mappings"]
    domain_facts = hints["domain_facts"]
    query_plan = hints["query_plan"]
    schema_section = "TABLES TO USE (ONLY use columns listed here, do NOT invent columns):\n\n"
    for s in schemas:
        cols = s.get("columns", [])
        schema_section += f"CREATE TABLE {s['table_name']} (\n"
        for i, col in enumerate(cols):
            comma = "," if i < len(cols) - 1 else ""
            schema_section += f"  {col}{comma}\n"
        schema_section += ");\n\n"
    join_section = ""
    if join_keys:
        join_section = "JOIN CONDITIONS (use these EXACTLY):\n"
        for j in join_keys:
            join_section += f"  {j['left']} = {j['right']} [{j['confidence']} confidence]\n"
    else:
        join_section = "JOIN CONDITIONS: No joins needed (single table query).\n"
    mapping_section = ""
    if column_mappings:
        mapping_section = "COLUMN MAPPINGS (which columns match which concepts):\n"
        for m in column_mappings[:10]:  # Limit to top 10
            if m.get("method") == "semantic_map":
                mapping_section += f"  \"{m['phrase']}\" → {m['expression']}\n"
            else:
                mapping_section += f"  \"{m['phrase']}\" → {m['table']}.{', '.join(m['columns'])}\n"
    domain_section = ""
    if domain_facts:
        domain_section = "DOMAIN KNOWLEDGE (apply these predicates):\n"
        for f in domain_facts:
            if f["type"] == "exact_match":
                domain_section += f"  \"{f['term']}\" means: WHERE {f['predicate']}\n"
            elif f["type"] == "formula":
                domain_section += f"  \"{f['term']}\" means: {f['value']}\n"
            else:
                domain_section += f"  \"{f['term']}\" requires lookup: {f['predicate']}\n"
    plan_section = f"""QUERY STRUCTURE PLAN:
  Complexity: {query_plan['complexity']}
  Strategy: {query_plan['strategy'].upper()}
  Reason: {query_plan['reason']}
"""
    if query_plan["needs_aggregation"]:
        plan_section += "  → Use aggregation functions (SUM, AVG, COUNT, etc.)\n"
    if query_plan["needs_group_by"]:
        plan_section += "  → Include GROUP BY clause\n"
    if query_plan["needs_order"]:
        plan_section += "  → Include ORDER BY clause\n"
    if query_plan["needs_limit"]:
        plan_section += "  → Include LIMIT clause\n"
    if query_plan["suggested_cte_count"] > 0:
        plan_section += f"  → Use {query_plan['suggested_cte_count']} CTE(s) with WITH clause\n"
    for hint in query_plan.get("decomposition_hints", []):
        plan_section += f"  → {hint}\n"

    few_shot = build_few_shot_section(question=question)
    return f"""{SYSTEM_PROMPT}

{few_shot}

═══════════════════════════════════════════
 CURRENT TASK — All analysis is pre-computed
═══════════════════════════════════════════

Question: {question}

{schema_section}
{join_section}
{mapping_section}
{domain_section}
{plan_section}
Using ALL the hints above, write the SQL query.
Return ONLY the SQL — no explanations:"""
