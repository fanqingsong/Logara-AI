"""
Qdrant client integration helpers.
"""

import threading

from qdrant_client import QdrantClient

from core.settings import get_settings


class ThreadSafeQdrantClient:
    """
    Thread-safe, lazy-initialized, and mock-friendly Qdrant client wrapper.
    """

    def __init__(self):
        self._client = None
        self._last_class = None
        self._lock = threading.Lock()

    @property
    def client(self) -> QdrantClient:
        settings = get_settings()
        if self._client is None or self._last_class is not QdrantClient:
            with self._lock:
                if self._client is None or self._last_class is not QdrantClient:
                    self._client = QdrantClient(
                        url=settings.qdrant_url,
                        timeout=settings.qdrant_timeout_seconds,
                    )
                    self._last_class = QdrantClient
        return self._client

    def close(self):
        if self._client is not None:
            try:
                self._client.close()
            except AttributeError:
                pass

    def __getattr__(self, name):
        return getattr(self.client, name)


qdrant_client = ThreadSafeQdrantClient()


def vector_search(
    client,
    *,
    collection_name: str,
    query_vector: list[float],
    limit: int = 10,
    with_payload: bool = True,
    query_filter=None,
    score_threshold: float | None = None,
):
    """Search vectors using legacy ``search`` or modern ``query_points`` API."""
    search = getattr(client, "search", None)
    if callable(search):
        kwargs = {
            "collection_name": collection_name,
            "query_vector": query_vector,
            "limit": limit,
            "with_payload": with_payload,
        }
        if query_filter is not None:
            kwargs["query_filter"] = query_filter
        if score_threshold is not None:
            kwargs["score_threshold"] = score_threshold
        return search(**kwargs)

    kwargs = {
        "collection_name": collection_name,
        "query": query_vector,
        "limit": limit,
        "with_payload": with_payload,
    }
    if query_filter is not None:
        kwargs["query_filter"] = query_filter
    if score_threshold is not None:
        kwargs["score_threshold"] = score_threshold

    response = client.query_points(**kwargs)
    return response.points
