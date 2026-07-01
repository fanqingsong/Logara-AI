"""
Embedding integration helpers (SiliconFlow via OpenAI-compatible API).
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


def embed_texts(texts: str | list[str]) -> list[list[float]]:
    """Generate embeddings for one or more texts via SiliconFlow.

    Returns a list of vectors, one per input text.
    """
    settings = get_settings()
    client = get_embedding_client()

    if isinstance(texts, str):
        texts = [texts]

    response = client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )

    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
