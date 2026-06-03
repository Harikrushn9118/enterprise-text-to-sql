from fastapi import APIRouter, HTTPException
import structlog

from app.services.sql_generator import SQLGeneratorService
from app.services.retrieval import RetrievalService
from app.services.benchmark import BenchmarkService
from app.models.schemas import (
    RetrieveRequest, GenerateSQLRequest,
)

logger = structlog.get_logger()
router = APIRouter()


@router.post("/retrieve")
async def retrieve_tables(request: RetrieveRequest):
    logger.info("api_request_retrieve", question=request.question)
    try:
        service = RetrievalService()
        result = await service.retrieve(request.question)
        details = {}
        scores = []
        retrieved_tables = []
        for t in result.tables:
            retrieved_tables.append(t.table_name)
            scores.append(round(t.relevance_score, 2))
            details[t.table_name] = {
                "relevance_score": round(t.relevance_score, 2),
                "reason": t.reasoning,
            }
        confidence = round(sum(scores) / len(scores), 2) if scores else 0.0
        return {
            "retrieved_tables": retrieved_tables,
            "scores": scores,
            "confidence": confidence,
            "details": details,
        }
    except Exception as e:
        logger.error("api_retrieve_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-sql")
async def generate_sql(request: GenerateSQLRequest):
    logger.info("api_request_generate", question=request.question)
    try:
        service = SQLGeneratorService()
        result = await service.generate(request.question)
        return {
            "sql": result.sql_query,
            "retrieved_tables": result.retrieved_tables,
            "is_valid_syntax": result.is_valid,
            "parsing_errors": None if result.is_valid else result.validation_message,
            "confidence": 0.85 if result.is_valid else 0.3,
            "prompt_used": result.prompt_used,
        }
    except Exception as e:
        logger.error("api_generate_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/benchmark")
async def run_benchmark(limit: int = 5):
    logger.info("api_request_benchmark", limit=limit)
    try:
        service = BenchmarkService()
        result = await service.run_benchmark(limit=limit)
        return result
    except Exception as e:
        logger.error("api_benchmark_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
