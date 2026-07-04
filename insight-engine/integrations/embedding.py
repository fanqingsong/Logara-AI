"""
Embedding integration helpers for the AI Engine (SiliconFlow via OpenAI-compatible API).
"""

from functools import lru_cache

from openai import OpenAI

from core.settings import get_settings


@lru_cache
def get_embedding_client() -> OpenAI:
    settings = get_settings()
    return OpenAI(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
    )


def embed_text(text: str) -> list[float]:
    """Generate an embedding vector for a single text via SiliconFlow."""
    settings = get_settings()
    client = get_embedding_client()

    response = client.embeddings.create(
        model=settings.embedding_model,
        input=text,
    )

    return response.data[0].embedding
