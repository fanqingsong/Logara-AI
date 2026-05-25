"""
Log Processor Worker

Consumes log payloads from the Redis queue and processes them for
future vectorization and LLM analysis workflows.
"""
from anomaly.detector import analyze_log
import json
import logging
import os
import time
import uuid
from typing import Dict, Any, Optional

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
try:
    from qdrant_client.models import PointStruct, VectorParams, Distance
except ImportError:
    from qdrant_client.http.models import PointStruct, VectorParams, Distance

from utils.queue import redis_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] Worker: %(message)s"
)

logger = logging.getLogger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "logs")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")

# Lazy-loaded globals to keep unit tests fast/offline
_embedding_model = None
_qdrant_client = None

# Guards against repeated collection-init RPCs on every log in the hot path
_collection_initialized: bool = False


def get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def get_qdrant_client() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(url=QDRANT_URL, timeout=3)
    return _qdrant_client


def _create_service_id_index(client: QdrantClient, collection_name: str) -> None:
    """
    Idempotently create a keyword payload index on 'service_id'.
    Qdrant treats duplicate index creation as a no-op, so this is safe
    to call on both new and pre-existing collections.
    """
    try:
        client.create_payload_index(
            collection_name=collection_name,
            field_name="service_id",
            field_schema="keyword"
        )
        logger.info(
            f"Payload index on 'service_id' ensured for collection '{collection_name}'"
        )
    except Exception as index_err:
        logger.error(
            f"Failed to create payload index on 'service_id' "
            f"for collection '{collection_name}': {index_err}"
        )


def init_qdrant_collection(client: QdrantClient, collection_name: str) -> None:
    """
    Ensure the target Qdrant collection exists, is configured for
    384-dimensional cosine-similarity vectors, and has a keyword payload
    index on 'service_id' for O(1) partition-based filtering.

    Safe to call on pre-existing collections — both collection creation
    and index creation are idempotent operations in Qdrant.
    """
    try:
        collection_exists = client.collection_exists(collection_name)
    except Exception:
        # Older qdrant-client versions may not expose collection_exists;
        # fall back to get_collection to determine existence.
        try:
            client.get_collection(collection_name)
            collection_exists = True
        except Exception:
            collection_exists = False

    if not collection_exists:
        try:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE)
            )
            logger.info(f"Created Qdrant collection '{collection_name}'")
        except Exception as create_err:
            logger.error(
                f"Failed to create Qdrant collection '{collection_name}': {create_err}"
            )
            return

    # Always ensure the index exists — new or pre-existing collection.
    _create_service_id_index(client, collection_name)


# Lightweight in-memory worker metrics
WORKER_METRICS: Dict[str, int] = {
    "processed_logs": 0,
    "failed_logs": 0,
    "malformed_payloads": 0
}


# Ordered list of metadata keys that may carry the originating service name.
# Checked in priority order: internal canonical key first, then OTel variants.
_SERVICE_ID_KEYS = ("service", "service.name", "service_id")


def _extract_service_id(metadata: Dict[str, Any]) -> str:
    """
    Derive a non-empty service identifier from a log's metadata dict.

    Resolution order:
      1. ``service``       — canonical key written by the ingestion service
      2. ``service.name``  — standard OpenTelemetry resource attribute
      3. ``service_id``    — explicit override (e.g. from raw structured logs)
      4. ``"unknown_service"`` sentinel when none of the above are present
                             or when the resolved value is empty / whitespace.
    """
    if not isinstance(metadata, dict):
        return "unknown_service"

    for key in _SERVICE_ID_KEYS:
        value = metadata.get(key)
        if value and isinstance(value, str) and value.strip():
            return value.strip()

    return "unknown_service"


def _ensure_collection_initialized(client: QdrantClient) -> None:
    """
    Call ``init_qdrant_collection`` exactly once per worker process.

    Caches the result in the module-level ``_collection_initialized`` flag
    so that the collection-existence check and index-creation RPC are not
    repeated on every log in the hot path.
    """
    global _collection_initialized
    if not _collection_initialized:
        init_qdrant_collection(client, QDRANT_COLLECTION)
        _collection_initialized = True


def increment_metric(metric_name: str):
    """
    Safely increment worker metrics.
    """
    if metric_name in WORKER_METRICS:
        WORKER_METRICS[metric_name] += 1


def process_log(payload_str: str) -> bool:
    """
    Deserialize, process, vectorize, and store a log payload in Qdrant.
    """
    if not payload_str or not payload_str.strip():
        logger.warning("Received empty payload from queue.")
        increment_metric("malformed_payloads")
        return False

    try:
        data = json.loads(payload_str)

        if not isinstance(data, dict):
            logger.warning("Received non-dictionary JSON payload.")
            increment_metric("malformed_payloads")
            return False

        parsed = data.get("parsed")

        if not isinstance(parsed, dict):
            logger.warning("Payload missing valid 'parsed' structure.")
            increment_metric("malformed_payloads")
            return False

        level = parsed.get("level", "UNKNOWN")
        message = parsed.get("message", "No message")
        parser_type = parsed.get("parser_type", "unknown")
        timestamp = parsed.get("timestamp")

        metadata = data.get("metadata", {})

        logger.info(
            f"Processing log | level={level} | "
            f"parser={parser_type} | "
            f"message={message[:100]}"
        )

        # 1. Generate Embeddings
        try:
            model = get_embedding_model()
            vector = model.encode(message).tolist()
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            increment_metric("failed_logs")
            return False

        # 2. Store in Qdrant
        try:
            q_client = get_qdrant_client()
            _ensure_collection_initialized(q_client)

            point_id = str(uuid.uuid4())

            # Extract service_id for partitioning.
            # Priority: 'service' (canonical internal key set by ingestion)
            # → 'service.name' (OTel resource attribute)
            # → 'service_id' (explicit override)
            # → 'unknown_service' sentinel when no service is identified.
            service_id = _extract_service_id(metadata)

            payload = {
                "timestamp": timestamp,
                "level": level,
                "message": message,
                "parser_type": parser_type,
                "metadata": metadata,
                "service_id": service_id
            }

            q_client.upsert(
                collection_name=QDRANT_COLLECTION,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload
                    )
                ]
            )
            logger.info(
                f"Successfully vectorized and indexed log to Qdrant | "
                f"id={point_id} | service_id={service_id}"
            )
        except Exception as e:
            logger.error(f"Failed to store log in Qdrant: {e}")
            increment_metric("failed_logs")
            return False

        increment_metric("processed_logs")
        return True

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse payload as JSON: {e}")
        increment_metric("failed_logs")
        return False

    except Exception as e:
        logger.error(f"Unexpected error processing payload: {e}")
        increment_metric("failed_logs")
        return False


def run_worker():
    """
    Continuously consume payloads from the Redis queue.
    """
    logger.info("Starting Log Processor worker. Waiting for logs...")

    while True:
        try:
            result = redis_client.brpop("log_queue", timeout=1)

            if result:
                queue_name, payload = result

                logger.info(
                    f"Dequeued payload from queue='{queue_name}'"
                )

                process_log(payload)

        except KeyboardInterrupt:
            logger.info("Worker shutting down gracefully.")
            break

        except Exception as e:
            logger.error(f"Queue connection error: {e}")

            time.sleep(5)


if __name__ == "__main__":
    run_worker()