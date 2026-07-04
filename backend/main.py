import os
import json
import httpx
from app_factory import create_app
from fastapi import Body, Response, HTTPException
from integrations.llm import llm_health_check
from integrations.qdrant import qdrant_client
from integrations.redis import redis_client
from qdrant_client import QdrantClient
from utils.parser import PARSER_METRICS, LogParser

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
log_store: list[dict] = []
total_logs_ingested: int = 0

app = create_app()

@app.post("/ingest")
async def ingest_logs(log_data: str = Body(..., embed=True)):
    """
    Accepts raw log strings, parses them into structured data,
    and pushes the payload to the Redis queue for asynchronous processing.
    """
    if not log_data or not log_data.strip():
        raise HTTPException(status_code=400, detail="Log message cannot be empty")

    parsed = LogParser.parse_line(log_data)
    if not parsed:
        return {"status": "accepted_raw", "message": log_data}

    metadata = parsed.get("metadata", {})

    payload = {
        "parsed": parsed,
        "metadata": metadata
    }

    try:
        redis_client.lpush("log_queue", json.dumps(payload))
    except Exception:
        pass  # Redis unavailable — continue without queuing

    global total_logs_ingested
    total_logs_ingested += 1
    log_store.append({
        "timestamp": parsed.get("timestamp", ""),
        "level": parsed.get("level", "INFO"),
        "message": parsed.get("message", ""),
        "service": parsed.get("metadata", {}).get("service", "unknown")
    })
    if len(log_store) > 500:
        log_store.pop(0)

    return {
        "status": "success_queued",
        "parsed": parsed,
        "metadata": metadata
    }

@app.get("/metrics/parser")
async def parser_metrics():
    return {
        "parser_metrics": PARSER_METRICS
    }

@app.get("/dashboard")
@app.get("/api/dashboard")
async def dashboard():
    log_service = app.state.log_service
    logs, total = log_service.get_logs(page=1, limit=500)

    def _service_name(log: dict) -> str:
        metadata = log.get("metadata") or {}
        return (
            log.get("service_id")
            or metadata.get("service")
            or metadata.get("service_id")
            or "unknown"
        )

    recent_logs = [
        {
            "timestamp": log.get("timestamp", ""),
            "level": log.get("level", "INFO"),
            "message": log.get("message", ""),
            "service": _service_name(log),
        }
        for log in logs[:10]
    ]
    anomalies = sum(1 for log in logs if log.get("level") == "ERROR")
    active_services = len({_service_name(log) for log in logs})

    return {
        "logs_processed": total,
        "anomalies": anomalies,
        "active_services": active_services,
        "ai_insights": anomalies,
        "recent_logs": recent_logs,
        "ai_summary": (
            "No anomalies detected."
            if anomalies == 0
            else f"{anomalies} ERROR-level events detected across {active_services} service(s). Review recent logs for details."
        ),
    }

@app.get("/logs")
async def get_logs():
    return {
        "logs": list(reversed(log_store)),
        "count": len(log_store)
    }

@app.get("/health", status_code=200)
async def health_check(response: Response):
    services = {}

    try:
        redis_client.ping()
        services["redis"] = {"status": "healthy"}
    except Exception as e:
        services["redis"] = {"status": "unhealthy", "error": str(e)}

    try:
        qclient = QdrantClient(url=QDRANT_URL, timeout=3)
        qclient.get_collections()
        services["qdrant"] = {"status": "healthy"}
    except Exception as e:
        services["qdrant"] = {"status": "unhealthy", "error": str(e)}

    try:
        result = llm_health_check()
        if result.get("status_code", 503) < 500:
            services["llm"] = {"status": "healthy"}
        else:
            services["llm"] = {
                "status": "unhealthy",
                "error": result.get("error", f"HTTP {result['status_code']}"),
            }
    except Exception as e:
        services["llm"] = {"status": "unhealthy", "error": str(e)}

    overall = "unhealthy" if any(
        s["status"] == "unhealthy" for s in services.values()
    ) else "healthy"

    if overall == "unhealthy":
        response.status_code = 503

    return {
        "status": overall,
        "services": services
    }
