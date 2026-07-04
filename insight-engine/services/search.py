"""
SearchService — Embeds a natural language query and searches Qdrant for
semantically similar log vectors, with optional service_id partitioning.
"""
import logging
from typing import Optional

from qdrant_client import QdrantClient

try:
    from qdrant_client.models import Filter, FieldCondition, MatchValue
except ImportError:
    from qdrant_client.http.models import Filter, FieldCondition, MatchValue  # type: ignore

from core.settings import get_settings
from integrations.embedding import embed_text
from schemas.search import SearchResult

logger = logging.getLogger(__name__)

# Lazy-loaded module globals — avoids loading the client at import time so
# unit tests remain fast and offline.
_qdrant_client: Optional[QdrantClient] = None


def get_qdrant_client() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        settings = get_settings()
        _qdrant_client = QdrantClient(url=settings.qdrant_url, timeout=5)
    return _qdrant_client


def get_query_embedding(query: str) -> list[float]:
    """Generate an embedding vector for a query via SiliconFlow."""
    return embed_text(query)


class SearchService:
    """
    Encapsulates semantic similarity search over the Qdrant log collection.

    Converts a raw query string into a vector embedding and retrieves the
    top-K most similar log records, optionally filtered to a single service
    partition using the 'service_id' keyword payload index.
    """

    def search(
        self,
        query: str,
        service_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """
        Perform semantic search and return ranked log results.

        Args:
            query:      Natural language search query.
            service_id: When provided, restricts results to this service
                        partition via the Qdrant keyword payload index.
            limit:      Maximum number of results to return (1-50).

        Returns:
            List of SearchResult objects ordered by descending similarity score.

        Raises:
            Exception: Propagates Qdrant connectivity or query errors to the
                       caller (route layer) for consistent HTTP error mapping.
        """
        settings = get_settings()

        # 1. Embed the query
        vector = get_query_embedding(query)

        # 2. Build optional service_id filter — reuses the keyword index
        #    created by the backend worker for O(1) partition lookup.
        query_filter: Optional[Filter] = None
        if service_id and service_id.strip():
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="service_id",
                        match=MatchValue(value=service_id.strip()),
                    )
                ]
            )

        # 3. Query Qdrant
        try:
            client = get_qdrant_client()
            response = client.query_points(
                collection_name=settings.qdrant_collection,
                query=vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            hits = response.points
        except Exception as e:
            logger.error(f"Qdrant search failed: {e}")
            raise

        # 4. Map to schema
        results: list[SearchResult] = []
        for hit in hits:
            payload = hit.payload or {}
            results.append(
                SearchResult(
                    id=str(hit.id),
                    score=float(hit.score),
                    message=payload.get("message", ""),
                    level=payload.get("level", "UNKNOWN"),
                    timestamp=payload.get("timestamp"),
                    service_id=payload.get("service_id", "unknown_service"),
                    metadata=payload.get("metadata", {}),
                )
            )

        return results
