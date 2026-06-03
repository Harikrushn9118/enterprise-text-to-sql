import json
import os
import numpy as np
import structlog
from sentence_transformers import SentenceTransformer
from app.core.config import settings
from app.models.schemas import RetrieveResponse, TableMatch

logger = structlog.get_logger()
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "app", "table_schemas.json")

class RetrievalService:
    _instance = None
    _model = None
    _schemas = None
    _schema_embeddings = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if RetrievalService._model is None:
            self._load_resources()

    def _load_resources(self):
        logger.info("loading_retrieval_resources", model=settings.EMBEDDING_MODEL)
        RetrievalService._model = SentenceTransformer(settings.EMBEDDING_MODEL)
        logger.info("embedding_model_loaded")

        schema_path = SCHEMA_PATH
        if not os.path.exists(schema_path):
            alt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "table_schemas.json")
            if os.path.exists(alt_path):
                schema_path = alt_path
            else:
                logger.error("schema_file_not_found", path=schema_path)
                RetrievalService._schemas = []
                RetrievalService._schema_embeddings = np.array([])
                return

        with open(schema_path, "r") as f:
            RetrievalService._schemas = json.load(f)
        logger.info("schemas_loaded", count=len(RetrievalService._schemas))
        descriptions = [s["description"] for s in RetrievalService._schemas]
        if descriptions:
            RetrievalService._schema_embeddings = RetrievalService._model.encode(
                descriptions, show_progress_bar=False, normalize_embeddings=True
            )
        else:
            RetrievalService._schema_embeddings = np.array([])

        logger.info("schema_embeddings_computed", shape=str(RetrievalService._schema_embeddings.shape))

    async def retrieve(self, question: str, top_k: int = None) -> RetrieveResponse:
        if top_k is None:
            top_k = settings.TOP_K_TABLES
        if not self._schemas or len(self._schema_embeddings) == 0:
            return RetrieveResponse(
                question=question,
                tables=[],
                total_tables_searched=0,
            )
        logger.info("retrieving_tables", question=question[:100], top_k=top_k)
        question_embedding = self._model.encode(
            [question], show_progress_bar=False, normalize_embeddings=True
        )[0]
        similarities = np.dot(self._schema_embeddings, question_embedding)
        tables = []
        for idx in np.argsort(similarities)[::-1][:top_k]:
            schema = self._schemas[idx]
            score = float(similarities[idx])
            reasoning = self._generate_reasoning(question, schema, score)
            tables.append(TableMatch(
                table_name=schema["table_name"],
                relevance_score=round(min(max(score, 0.0), 1.0), 4),
                reasoning=reasoning,
                columns=schema.get("columns", []),
                db=schema.get("db", ""),
            ))
        logger.info("retrieval_complete", tables_found=len(tables))
        return RetrieveResponse(
            question=question,
            tables=tables,
            total_tables_searched=len(self._schemas),
        )
    def get_schemas_for_tables(self, table_names: list[str]) -> list[dict]:
        result = []
        for name in table_names:
            for schema in self._schemas:
                if schema["table_name"].lower() == name.lower():
                    result.append(schema)
                    break
        return result

    def _generate_reasoning(self, question: str, schema: dict, score: float) -> str:
        table_name = schema["table_name"]
        columns = schema.get("columns", [])

        if score > 0.6:
            confidence = "high"
        elif score > 0.4:
            confidence = "moderate"
        else:
            confidence = "low"

        question_lower = question.lower()
        relevant_cols = [c for c in columns if any(
            word in question_lower for word in c.lower().replace("_", " ").split()
        )]

        reasoning = f"{confidence.capitalize()} relevance ({score:.2f}). "
        reasoning += f"Table '{table_name}' "

        if relevant_cols:
            reasoning += f"has columns [{', '.join(relevant_cols[:5])}] "
            reasoning += f"which may relate to the question."
        else:
            reasoning += f"with columns [{', '.join(columns[:5])}] "
            reasoning += f"may contain relevant data."

        return reasoning
