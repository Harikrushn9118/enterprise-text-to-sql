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
        "question": "Compare each region's sales to the overall average sales",
        "schemas": "Table: customers (customer_id, name, region) [Joins: customer_id → orders.customer_id]\nTable: orders (order_id, customer_id, total_amount)",
        "reasoning": "Tables: customers, orders | Join: customers.customer_id = orders.customer_id | Mapping: sales → SUM(total_amount) | Plan: CTE for region sales, then compare to overall avg",
        "sql": "WITH region_sales AS (SELECT c.region, SUM(o.total_amount) AS total_sales FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.region), overall AS (SELECT AVG(total_sales) AS avg_sales FROM region_sales) SELECT rs.region, rs.total_sales, ov.avg_sales, rs.total_sales - ov.avg_sales AS diff_from_avg FROM region_sales rs CROSS JOIN overall ov ORDER BY rs.total_sales DESC"
    },
    {
        "question": "Show monthly revenue trend with running total",
        "schemas": "Table: orders (order_id, customer_id, order_date, total_amount)",
        "reasoning": "Tables: orders | Mapping: monthly → strftime('%Y-%m', order_date), running total → cumulative SUM | Plan: CTE for monthly aggregation then running sum",
        "sql": "WITH monthly AS (SELECT strftime('%Y-%m', order_date) AS month, SUM(total_amount) AS monthly_revenue FROM orders GROUP BY strftime('%Y-%m', order_date)) SELECT month, monthly_revenue, SUM(monthly_revenue) OVER (ORDER BY month) AS running_total FROM monthly ORDER BY month"
    },
    {
        "question": "What is the campaign ROI for each marketing channel?",
        "schemas": "Table: campaigns (campaign_id, campaign_name, start_date, end_date, budget, channel) [Joins: campaign_id → campaign_results.campaign_id]\nTable: campaign_results (result_id, campaign_id, impressions, clicks, conversions, revenue)",
        "reasoning": "Tables: campaigns, campaign_results | Join: campaigns.campaign_id = campaign_results.campaign_id | Domain: ROI = (revenue - budget) / budget | Plan: simple query",
        "sql": "SELECT c.channel, SUM(cr.revenue) AS total_revenue, SUM(c.budget) AS total_budget, (SUM(cr.revenue) - SUM(c.budget)) AS net_roi, SUM(cr.revenue) * 1.0 / NULLIF(SUM(c.budget), 0) AS roi_ratio FROM campaigns c JOIN campaign_results cr ON c.campaign_id = cr.campaign_id GROUP BY c.channel ORDER BY roi_ratio DESC"
    },
    {
        "question": "Rank customers by total spending and show their percentile",
        "schemas": "Table: customers (customer_id, name, region, segment) [Joins: customer_id → orders.customer_id]\nTable: orders (order_id, customer_id, total_amount)",
        "reasoning": "Tables: customers, orders | Join: customers.customer_id = orders.customer_id | Mapping: spending → SUM(total_amount), percentile → NTILE or PERCENT_RANK | Plan: CTE for spending then rank",
        "sql": "WITH customer_spending AS (SELECT c.customer_id, c.name, c.segment, SUM(o.total_amount) AS total_spent, COUNT(o.order_id) AS order_count FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id, c.name, c.segment) SELECT name, segment, total_spent, order_count, RANK() OVER (ORDER BY total_spent DESC) AS spending_rank, ROUND(PERCENT_RANK() OVER (ORDER BY total_spent) * 100, 1) AS percentile FROM customer_spending ORDER BY total_spent DESC"
    },
    {
        "question": "Which departments are over budget based on employee salaries?",
        "schemas": "Table: employees (employee_id, first_name, last_name, department, salary) [Joins: department → departments.department_name]\nTable: departments (department_id, department_name, location, budget)",
        "reasoning": "Tables: employees, departments | Join: employees.department = departments.department_name | Mapping: over budget → SUM(salary) > budget | Plan: CTE for salary totals, then compare",
        "sql": "WITH dept_costs AS (SELECT e.department, SUM(e.salary) AS total_salary, COUNT(e.employee_id) AS headcount FROM employees e GROUP BY e.department) SELECT d.department_name, d.budget, dc.total_salary, dc.headcount, dc.total_salary - d.budget AS over_budget_amount FROM departments d JOIN dept_costs dc ON d.department_name = dc.department WHERE dc.total_salary > d.budget ORDER BY over_budget_amount DESC"
    },
    {
        "question": "Find the average delivery time by carrier and compare to overall average",
        "schemas": "Table: shipments (shipment_id, order_id, warehouse_id, ship_date, delivery_date, carrier)",
        "reasoning": "Tables: shipments | Mapping: delivery time → julianday(delivery_date) - julianday(ship_date) | Plan: CTE for carrier avg, then compare to overall",
        "sql": "WITH carrier_stats AS (SELECT carrier, AVG(julianday(delivery_date) - julianday(ship_date)) AS avg_days, COUNT(*) AS shipment_count FROM shipments WHERE delivery_date IS NOT NULL GROUP BY carrier), overall AS (SELECT AVG(avg_days) AS overall_avg FROM carrier_stats) SELECT cs.carrier, ROUND(cs.avg_days, 1) AS avg_delivery_days, cs.shipment_count, ROUND(ov.overall_avg, 1) AS overall_avg_days, ROUND(cs.avg_days - ov.overall_avg, 1) AS diff_from_avg FROM carrier_stats cs CROSS JOIN overall ov ORDER BY cs.avg_days"
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
