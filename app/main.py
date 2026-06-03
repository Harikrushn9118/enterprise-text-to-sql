import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.api.routes import router
from app.core.config import settings
from app.core.logging import setup_logging

# Initialize structured logging
setup_logging()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup/shutdown lifecycle.
    Pre-loads the embedding model and schema index on startup.
    """
    logger.info("server_starting", app_name=settings.APP_NAME)

    # Check if database exists
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mock_db.db")
    schema_path = os.path.join(os.path.dirname(__file__), "table_schemas.json")

    if not os.path.exists(db_path) or not os.path.exists(schema_path):
        logger.warning(
            "database_not_found",
            message="Run 'python setup_db.py' first to create the database and schema index."
        )

    # Pre-load the retrieval service (loads embedding model + schema embeddings)
    try:
        from app.services.retrieval import RetrievalService
        RetrievalService()
        logger.info("retrieval_service_loaded")
    except Exception as e:
        logger.error("retrieval_service_failed", error=str(e))

    logger.info("server_ready", host=settings.HOST, port=settings.PORT)
    yield
    logger.info("server_shutdown")


from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI(
    title="Enterprise Text-to-SQL API",
    description=(
        "Convert natural language questions into optimized SQL queries "
        "using semantic retrieval + LLM generation. "
        "Built with the Beaver enterprise benchmark dataset."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    )

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(router)


@app.get("/", tags=["Health"])
async def root():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": "1.0.0",
        "docs": "/docs",
    }
