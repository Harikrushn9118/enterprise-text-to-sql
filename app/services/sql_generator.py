import structlog
from app.models.schemas import GenerateSQLResponse
from app.services.retrieval import RetrievalService
from app.services.schema_linker import SchemaLinker
from app.services.domain_resolver import DomainResolver
from app.services.query_planner import QueryPlanner
from app.services.llm_client import LLMClient
from app.services.validator import SQLValidator
from app.core.database import execute_query
from app.utils.prompts import SYSTEM_PROMPT, build_oracle_prompt

logger = structlog.get_logger()
MAX_RETRIES = 6
RETRY_DELAY = 5  

class SQLGeneratorService:
    def __init__(self):
        self.retrieval = RetrievalService()
        self.schema_linker = SchemaLinker()
        self.domain_resolver = DomainResolver()
        self.query_planner = QueryPlanner()
        self.llm = LLMClient()
        self.validator = SQLValidator()

    async def generate(self, question: str) -> GenerateSQLResponse:
        logger.info("pipeline_start", question=question[:100])
        retrieval_result = await self.retrieval.retrieve(question)
        schemas = []
        for t in retrieval_result.tables:
            full = self.retrieval.get_schemas_for_tables([t.table_name])
            if full:
                schemas.append(full[0])
            else:
                schemas.append({
                    "table_name": t.table_name,
                    "columns": t.columns,
                    "join_keys": [],
                })
        logger.info("subtask1_retrieval_done",
                     tables=[s["table_name"] for s in schemas])
        join_keys = self.schema_linker.detect_join_keys(schemas)

        logger.info("subtask2_joins_detected",
                     count=len(join_keys),
                     joins=[f"{j['left']} = {j['right']}" for j in join_keys])
        column_mappings = self.schema_linker.map_columns(question, schemas)
        logger.info("subtask3_columns_mapped",
                     count=len(column_mappings),
                     mappings=[f"{m['phrase']}→{m['table']}.{m['columns']}"
                               for m in column_mappings[:5]])
        domain_facts = self.domain_resolver.resolve(question, schemas)
        logger.info("subtask4_domain_resolved",
                     count=len(domain_facts),
                     facts=[f['predicate'] for f in domain_facts])
        query_plan = self.query_planner.plan(
            question=question,
            num_tables=len(schemas),
            join_count=len(join_keys),
        )
        logger.info("subtask5_query_planned",
                     complexity=query_plan["complexity"],
                     strategy=query_plan["strategy"])
        oracle_hints = {
            "schemas": schemas,
            "join_keys": join_keys,
            "column_mappings": column_mappings,
            "domain_facts": domain_facts,
            "query_plan": query_plan,
        }
        prompt = build_oracle_prompt(question, oracle_hints)
        logger.info("oracle_prompt_built", prompt_length=len(prompt))
        sql_query = ""
        is_valid = False
        validation_msg = ""
        execution_result = None

        for attempt in range(1, MAX_RETRIES + 2):
            if attempt == 1:
                sql_query = await self.llm.generate(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=prompt,
                )
            else:
                import asyncio
                await asyncio.sleep(RETRY_DELAY)
                correction_prompt = self._build_correction_prompt(
                    question, schemas, sql_query, validation_msg,
                    execution_error=execution_result.get("error") if execution_result else None
                )
                sql_query = await self.llm.generate(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=correction_prompt,
                )
            logger.info("sql_generated", attempt=attempt,
                         sql_preview=sql_query[:100])
            is_valid, validation_msg = self.validator.validate(sql_query)

            if not is_valid:
                logger.warning("sql_invalid_retrying",
                               attempt=attempt, reason=validation_msg)
                continue

            execution_result = execute_query(sql_query)

            if execution_result.get("success"):
                logger.info("pipeline_success", attempt=attempt)
                break
            else:
                logger.warning("sql_execution_failed_retrying",
                               attempt=attempt,
                               error=execution_result.get("error", "")[:200])
                validation_msg = f"Execution error: {execution_result.get('error', 'unknown')}"

        return GenerateSQLResponse(
            question=question,
            sql_query=sql_query,
            is_valid=is_valid,
            validation_message=validation_msg,
            prompt_used=prompt,
            execution_result=execution_result,
            retrieved_tables=[t.table_name for t in retrieval_result.tables],
        )

    def _build_correction_prompt(
        self, question: str, schemas: list[dict],
        failed_sql: str, error_msg: str,
        execution_error: str = None,
    ) -> str:
        schema_lines = []
        for s in schemas:
            cols = s.get("columns", [])
            ddl = f"CREATE TABLE {s['table_name']} (\n"
            for i, col in enumerate(cols):
                comma = "," if i < len(cols) - 1 else ""
                ddl += f"  {col}{comma}\n"
            ddl += ");"
            schema_lines.append(ddl)

        schemas_text = "\n\n".join(schema_lines)
        error_detail = execution_error if execution_error else error_msg

        return f"""Your previous SQL query had an error. Please fix it.
Original Question: {question}
Available Tables (ONLY use columns listed here):
{schemas_text}
Your Previous SQL (FAILED):
{failed_sql}
Error Message:
{error_detail}
INSTRUCTIONS:
1. Analyze the error message carefully
2. Cross-check EVERY column name against the CREATE TABLE definitions above
3. If a column does not appear in the CREATE TABLE, do NOT use it
4. Fix the SQL and return ONLY the corrected query — no explanations
5. Do NOT add a trailing semicolon
Corrected SQL:"""
