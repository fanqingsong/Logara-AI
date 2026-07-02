import uuid
import logging
from typing import List, Dict, Any, Optional, Tuple

from integrations.qdrant import vector_search
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.models import PointStruct

from core.settings import get_settings
from integrations.embedding import embed_texts
from integrations.llm import llm_chat
from utils.constants import (
    SCHEMA_TIMESTAMP,
    SCHEMA_LEVEL,
    SCHEMA_MESSAGE,
    SCHEMA_METADATA,
    SCHEMA_PARSER_TYPE,
    SCHEMA_RAW,
)

logger = logging.getLogger(__name__)

QDRANT_COLLECTION = "logs"


class LogService:
    def __init__(self, qclient: QdrantClient):
        self.qclient = qclient
        self._collection_verified = False

    def _ensure_collection(self):
        """
        Create the Qdrant collection if it does not already exist.
        """
        if self._collection_verified:
            return
        settings = get_settings()
        try:
            collections = self.qclient.get_collections().collections
            collection_names = [c.name for c in collections]
            if QDRANT_COLLECTION not in collection_names:
                self.qclient.create_collection(
                    collection_name=QDRANT_COLLECTION,
                    vectors_config=qmodels.VectorParams(
                        size=settings.embedding_dimensions,
                        distance=qmodels.Distance.COSINE
                    ),
                )
                logger.info(f"Created Qdrant collection '{QDRANT_COLLECTION}'.")
            self._collection_verified = True
        except Exception as e:
            logger.debug(f"Failed to verify/create Qdrant collection: {e}")


    def get_embedding(self, text: str) -> List[float]:
        """Generate vector embedding using the SiliconFlow embedding service."""
        vectors = embed_texts([text])
        if vectors and isinstance(vectors[0], list) and len(vectors[0]) > 0:
            return vectors[0]
        return []

    def store_log(self, parsed_log: Dict[str, Any], raw_log: str) -> str:
        """
        Vectorize and store a parsed log payload directly into Qdrant.
        """
        log_id = str(uuid.uuid4())
        message = parsed_log.get(SCHEMA_MESSAGE, "")
        vector = self.get_embedding(message)

        metadata = parsed_log.get(SCHEMA_METADATA, {}) or {}
        service_id = metadata.get("service") or metadata.get("service.name") or "unknown_service"

        payload = {
            "id": log_id,
            SCHEMA_TIMESTAMP: parsed_log.get(SCHEMA_TIMESTAMP),
            SCHEMA_LEVEL: parsed_log.get(SCHEMA_LEVEL, "INFO").upper(),
            SCHEMA_MESSAGE: message,
            SCHEMA_PARSER_TYPE: parsed_log.get(SCHEMA_PARSER_TYPE),
            SCHEMA_RAW: raw_log,
            SCHEMA_METADATA: metadata,
            "service_id": service_id
        }

        point = PointStruct(
            id=log_id,
            vector=vector,
            payload=payload
        )

        self._ensure_collection()
        self.qclient.upsert(
            collection_name=QDRANT_COLLECTION,
            points=[point]
        )
        return log_id

    def get_logs(
        self,
        page: int = 1,
        limit: int = 10,
        level: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Retrieve, filter, and paginate logs with timestamp-based sorting.
        """
        filter_conditions = []

        if level:
            filter_conditions.append(
                qmodels.FieldCondition(
                    key=SCHEMA_LEVEL,
                    match=qmodels.MatchValue(value=level.upper())
                )
            )

        if start_time or end_time:
            range_cond = qmodels.Range()
            if start_time:
                range_cond.gte = start_time
            if end_time:
                range_cond.lte = end_time
            filter_conditions.append(
                qmodels.FieldCondition(
                    key=SCHEMA_TIMESTAMP,
                    range=range_cond
                )
            )

        scroll_filter = qmodels.Filter(must=filter_conditions) if filter_conditions else None

        # Fetch up to a large threshold for sorting in memory to guarantee chronologically accurate pages
        # scroll returns Tuple[List[Record], Optional[PointId]]
        self._ensure_collection()
        records, _ = self.qclient.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=scroll_filter,
            limit=5000,
            with_payload=True,
            with_vectors=False
        )

        logs = []
        for record in records:
            if not record.payload:
                continue
            log = dict(record.payload)
            log.setdefault("id", str(record.id))
            log.setdefault("level", "INFO")
            log.setdefault("message", "")
            logs.append(log)

        # Sort descending by timestamp
        def get_ts(log):
            return log.get(SCHEMA_TIMESTAMP) or ""

        sorted_logs = sorted(logs, key=get_ts, reverse=True)

        total = len(sorted_logs)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_logs = sorted_logs[start_idx:end_idx]

        return paginated_logs, total

    def semantic_search(self, query: str, limit: int = 5) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Perform vector similarity search on logs and use GLM to synthesize an answer.
        """
        if limit < 1 or limit > 50:
            raise ValueError("Result limit must be between 1 and 50")

        self._ensure_collection()
        query_vector = self.get_embedding(query)

        results = vector_search(
            self.qclient,
            collection_name=QDRANT_COLLECTION,
            query_vector=query_vector,
            limit=limit,
            with_payload=True,
        )

        logs = [r.payload for r in results if r.payload]

        # If we have no logs, we return empty list and message
        if not logs:
            return [], "No matching logs found."

        # Attempt to synthesize natural language query response using GLM
        answer = None
        try:
            log_context = "\n".join(
                f"- [{log.get(SCHEMA_TIMESTAMP)}] {log.get(SCHEMA_LEVEL)}: {log.get(SCHEMA_MESSAGE)} (Raw: {log.get(SCHEMA_RAW)})"
                for log in logs
            )

            prompt = (
                f"You are an expert system reliability assistant for Logara AI.\n"
                f"Based on the following relevant system logs, answer the user's natural language query.\n"
                f"Be concise, helpful, and technically accurate.\n\n"
                f"Query: \"{query}\"\n\n"
                f"Logs:\n{log_context}\n\n"
                f"Answer:"
            )

            answer = llm_chat(prompt)
        except Exception as e:
            logger.debug(f"GLM natural language synthesis failed: {e}")
            answer = "Unable to contact LLM for natural language summary. Please check your connection."

        return logs, answer
