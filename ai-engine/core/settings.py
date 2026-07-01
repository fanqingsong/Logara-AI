"""
Application settings for the AI Engine, loaded from environment variables.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the root .env shared across all services
ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "logs"
    incident_memory_collection: str = "incident_memory"
    incident_similarity_threshold: float = 0.95

    # LLM (GLM via OpenAI-compatible API)
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    llm_api_key: str = ""
    llm_model: str = "glm-5.1"
    llm_timeout_seconds: float = 60.0

    # Embedding (SiliconFlow via OpenAI-compatible API)
    embedding_base_url: str = "https://api.siliconflow.cn/v1/"
    embedding_api_key: str = ""
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimensions: int = 1024

    # Service defaults
    ai_engine_search_limit: int = 10
    ai_engine_context_limit: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
