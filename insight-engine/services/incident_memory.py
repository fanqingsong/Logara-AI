import logging
import uuid

try:
    from qdrant_client.models import PointStruct, VectorParams, Distance
except ImportError:
    from qdrant_client.http.models import PointStruct, VectorParams, Distance  # type: ignore

from core.settings import get_settings
from integrations.embedding import embed_text
from schemas.incident_memory import IncidentMemoryResult
from services.search import get_qdrant_client

logger = logging.getLogger(__name__)


def ensure_incident_memory_collection() -> None:
    """Create the incident_memory collection if it does not yet exist."""
    settings = get_settings()
    client = get_qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if settings.incident_memory_collection in existing:
        return
    client.create_collection(
        collection_name=settings.incident_memory_collection,
        vectors_config=VectorParams(
            size=settings.embedding_dimensions,
            distance=Distance.COSINE,
        ),
    )
    logger.info(
        "Created Qdrant collection '%s' (dim=%d)",
        settings.incident_memory_collection,
        settings.embedding_dimensions,
    )


class IncidentMemoryService:

    def search_similar_incident(
        self,
        query: str,
    ):

        settings = get_settings()

        vector = embed_text(query)

        client = get_qdrant_client()

        hits = client.query_points(
            collection_name=settings.incident_memory_collection,
            query=vector,
            limit=1,
            with_payload=True,
        ).points

        if not hits:
            return None

        hit = hits[0]

        payload = hit.payload or {}

        return IncidentMemoryResult(
            id=str(hit.id),
            score=float(hit.score),
            error_message=payload.get("error_message", ""),
            explanation=payload.get("explanation", ""),
            service_id=payload.get("service_id"),
        )

    def store_incident(
        self,
        error_message: str,
        explanation: str,
        service_id: str | None = None,
    ):
        settings = get_settings()
        vector = embed_text(error_message)

        client = get_qdrant_client()

        client.upsert(
            collection_name=settings.incident_memory_collection,
            points=[
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={
                        "error_message": error_message,
                        "explanation": explanation,
                        "service_id": service_id,
                    },
                )
            ],
        )
