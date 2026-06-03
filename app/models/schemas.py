from pydantic import BaseModel, Field
from typing import Optional

class RetrieveRequest(BaseModel):
    question: str = Field(
        ...,
        description="Natural language question about the data",
        min_length=3,
        json_schema_extra={"example": "What are the total sales by region?"},
    )


class TableMatch(BaseModel):
    table_name: str
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    columns: list[str] = []
    db: str = ""


class RetrieveResponse(BaseModel):
    question: str
    tables: list[TableMatch]
    total_tables_searched: int

class GenerateSQLRequest(BaseModel):
    question: str = Field(
        ...,
        description="Natural language question to convert to SQL",
        min_length=3,
        json_schema_extra={"example": "Find the top 5 customers by order value"},
    )

class GenerateSQLResponse(BaseModel):
    question: str
    sql_query: str
    is_valid: bool
    validation_message: str
    prompt_used: str
    execution_result: Optional[dict] = None
    retrieved_tables: list[str] = []

class BenchmarkResult(BaseModel):
    question: str
    expected_tables: list[str]
    retrieved_tables: list[str]
    retrieval_correct: bool
    generated_sql: str
    sql_executed: bool
    latency_ms: float
    error_message: Optional[str] = None

class BenchmarkResponse(BaseModel):
    total_questions: int
    retrieval_accuracy: float
    sql_execution_accuracy: float
    average_latency_ms: float
    results: list[BenchmarkResult]
    error_breakdown: dict
