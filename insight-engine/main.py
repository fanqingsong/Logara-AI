"""
AI Engine — FastAPI application entry point.

Exposes:
  GET  /search   — Semantic log search
  POST /explain  — RAG-powered error explanation
  GET  /health   — Liveness + dependency health check
"""
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from core.settings import get_settings
from routes.explain import router as explain_router
from routes.search import router as search_router
from services.incident_memory import ensure_incident_memory_collection
from services.search import get_qdrant_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] AI-Engine: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Probes Qdrant and the LLM endpoint at startup so that health is
    established early, but no model warm-up is required (remote APIs).
    """
    logger.info("AI Engine starting up...")
    try:
        ensure_incident_memory_collection()
    except Exception as e:
        logger.warning(f"Could not ensure incident_memory collection: {e}")
    yield
    logger.info("AI Engine shut down.")


settings = get_settings()

app = FastAPI(
    title="Logara AI Engine",
    description=(
        "Semantic log search and RAG-powered error explanation service "
        "for the Logara AI observability platform."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(search_router)
app.include_router(explain_router)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    """
    Liveness and dependency health check.

    Probes Qdrant (list collections) and the LLM endpoint.
    Returns overall status 'ok' only when both dependencies are reachable.
    """
    qdrant_ok = False
    llm_ok = False

    try:
        client = get_qdrant_client()
        client.get_collections()
        qdrant_ok = True
    except Exception as e:
        logger.warning(f"Qdrant health probe failed: {e}")

    try:
        async with httpx.AsyncClient(timeout=3.0) as http_client:
            resp = await http_client.get(
                settings.llm_base_url.rstrip("/")
            )
            llm_ok = resp.status_code < 500
    except Exception as e:
        logger.warning(f"LLM health probe failed: {e}")

    return {
        "status": "ok" if (qdrant_ok and llm_ok) else "degraded",
        "qdrant": qdrant_ok,
        "llm": llm_ok,
    }
