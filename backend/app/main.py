from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import logging

from app.core.config import settings
from app.db.database import Base, engine
import app.db.models  # noqa: F401 – ensure models are registered with Base.metadata
from app.workflow.checkpointer import setup_checkpointer, teardown_checkpointer

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan handler.

    Startup  → create application tables (incidents, evidence_items) and
               initialise the LangGraph PostgresSaver checkpointer.
    Shutdown → close the long-lived psycopg3 connection gracefully.
    """
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Application relational tables created / verified successfully.")
    except Exception as exc:
        logger.warning("Could not auto-create tables: %s", exc)

    setup_checkpointer()
    yield
    teardown_checkpointer()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    docs_url=f"{settings.API_PREFIX}/docs",
    lifespan=lifespan,
)

# CORS middleware for frontend / local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.routes import api_router  # noqa: E402 – import after app creation

app.include_router(api_router, prefix=settings.API_PREFIX)


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "environment": settings.ENVIRONMENT,
    }


@app.get("/", tags=["Root"])
def root():
    return {
        "message": f"Welcome to {settings.PROJECT_NAME} API",
        "docs": f"{settings.API_PREFIX}/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
