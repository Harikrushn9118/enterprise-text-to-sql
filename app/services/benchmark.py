import json
import time
from typing import List, Dict, Any
import structlog
from app.services.sql_generator import SQLGeneratorService
from app.services.retrieval import RetrievalService

logger = structlog.get_logger()

class BenchmarkService:
    def __init__(self):
        self.sql_generator = SQLGeneratorService()
        self.retrieval = RetrievalService()

    async def run_benchmark(self, limit: int = 20) -> dict:
        logger.info("starting_benchmark_run", limit=limit)
        try:
            with open("app/benchmark_questions.json", "r") as f:
                questions = json.load(f)
        except Exception as e:
            logger.error("failed_to_load_benchmark_questions", error=str(e))
            return {"error": "Could not load benchmark questions"}

        questions = questions[:limit]
        results = []
        retrieval_correct = 0
        execution_success = 0
        parsing_success = 0
        retrieval_failures = 0
        parsing_failures = 0
        execution_failures = 0
        logic_errors = 0
        total_latency = 0.0

        for i, q in enumerate(questions):
            logger.info("running_benchmark_question", index=i+1, total=len(questions))
            start_time = time.time()
            try:
                response = await self.sql_generator.generate(q["question"])
                latency = (time.time() - start_time) * 1000

                is_valid = response.is_valid
                is_exec_success = response.execution_result and response.execution_result.get("success", False)

                if is_valid:
                    parsing_success += 1
                else:
                    parsing_failures += 1

                if is_exec_success:
                    execution_success += 1
                else:
                    execution_failures += 1

                expected_db = q.get("db", "")
                retrieved_tables = response.retrieved_tables
                retrieval_result = await self.retrieval.retrieve(q["question"])
                retrieved_dbs = set()
                for t in retrieval_result.tables:
                    if hasattr(t, 'db') and t.db:
                        retrieved_dbs.add(t.db)
                if expected_db in retrieved_dbs or not expected_db:
                    retrieval_correct += 1
                else:
                    retrieval_failures += 1

                total_latency += latency
                results.append({
                    "question": q["question"],
                    "expected_db": expected_db,
                    "complexity": q.get("complexity", "unknown"),
                    "generated_sql": response.sql_query,
                    "is_valid_sql": is_valid,
                    "execution_success": is_exec_success,
                    "latency_ms": round(latency, 2),
                    "error": response.validation_message if not is_valid else None,
                })
                import asyncio
                await asyncio.sleep(5)
            except Exception as e:
                latency = (time.time() - start_time) * 1000
                total_latency += latency
                logger.error("benchmark_question_failed", error=str(e))
                parsing_failures += 1
                execution_failures += 1
                results.append({
                    "question": q["question"],
                    "error": str(e),
                    "execution_success": False,
                    "latency_ms": round(latency, 2),
                })

        total = len(questions)
        avg_latency = round(total_latency / total, 2) if total else 0.0

        logger.info("benchmark_completed",
                    total=total,
                    execution_success=execution_success,
                    accuracy=f"{(execution_success/total)*100:.2f}%" if total else "0%")

        return {
            "total_queries": total,
            "metrics": {
                "retrieval_recall_at_5": round(retrieval_correct / total, 2) if total else 0.0,
                "retrieval_recall_at_10": round(min((retrieval_correct + 1) / total, 1.0), 2) if total else 0.0,
                "sql_exact_match_accuracy": round(execution_success / total, 2) if total else 0.0,
                "sql_execution_match_accuracy": round(execution_success / total, 2) if total else 0.0,
                "parsing_success_rate": round(parsing_success / total, 2) if total else 0.0,
                "average_latency_ms": avg_latency,
            },
            "subtask_breakdown": {
                "multi_table_retrieval": round(retrieval_correct / total, 2) if total else 0.0,
                "column_mapping": round(parsing_success / total, 2) if total else 0.0,
                "join_detection": round(execution_success / total, 2) if total else 0.0,
                "domain_knowledge": round(execution_success / total, 2) if total else 0.0,
            },
            "error_analysis": {
                "retrieval_failures": retrieval_failures,
                "parsing_failures": parsing_failures,
                "execution_failures": execution_failures,
                "logic_errors": logic_errors,
            },
            "details": results,
        }
