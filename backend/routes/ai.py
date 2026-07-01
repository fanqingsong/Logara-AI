"""
AI service routes including LLM status.
"""

import logging

from fastapi import APIRouter

from core.settings import get_settings
from integrations.llm import llm_health_check

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status")
async def get_ai_status():
    """
    Get the status of the LLM service.

    Returns the configured LLM model name and endpoint reachability.
    """
    settings = get_settings()
    try:
        result = llm_health_check()
        healthy = result.get("status_code", 503) < 500
        return {
            "status": "ready" if healthy else "unhealthy",
            "model": settings.llm_model,
            "endpoint": settings.llm_base_url,
            "error": result.get("error") if not healthy else None,
        }
    except Exception as e:
        logger.error(f"Error getting AI status: {e}", exc_info=True)
        return {
            "status": "failed",
            "model": settings.llm_model,
            "endpoint": settings.llm_base_url,
            "error": str(e),
        }
