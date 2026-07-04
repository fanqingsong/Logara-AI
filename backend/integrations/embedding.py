"""
Embedding integration helpers (SiliconFlow via OpenAI-compatible API).
"""

import logging
import time
from functools import lru_cache

from openai import APIConnectionError, APITimeoutError, OpenAI

from core.settings import get_settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY_SEC = 1.0


@lru_cache
def get_embedding_client() -> OpenAI:
    settings = get_settings()
    return OpenAI(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        timeout=30.0,
        max_retries=2,
    )


def embed_texts(texts: str | list[str]) -> list[list[float]]:
    """Generate embeddings for one or more texts via SiliconFlow.

    Returns a list of vectors, one per input text.
    """
    settings = get_settings()
    client = get_embedding_client()

    if isinstance(texts, str):
        texts = [texts]

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.embeddings.create(
                model=settings.embedding_model,
                input=texts,
            )
            return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
        except (APIConnectionError, APITimeoutError) as exc:
            last_error = exc
            if attempt >= MAX_RETRIES:
                break
            delay = RETRY_BASE_DELAY_SEC * attempt
            logger.warning(
                "Embedding API unreachable (attempt %d/%d), retrying in %.1fs: %s",
                attempt,
                MAX_RETRIES,
                delay,
                exc,
            )
            time.sleep(delay)

    assert last_error is not None
    raise last_error
