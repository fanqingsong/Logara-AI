"""
Health-check service helpers.
"""

import httpx

from integrations.llm import llm_health_check
from integrations.qdrant import qdrant_client
from integrations.redis import redis_client


class HealthService:
    def check_services(self) -> dict:
        services = {}

        try:
            redis_client.ping()
            services["redis"] = {"status": "healthy"}
        except Exception as exc:
            services["redis"] = {"status": "unhealthy", "error": str(exc)}

        try:
            qdrant_client.get_collections()
            services["qdrant"] = {"status": "healthy"}
        except Exception as exc:
            services["qdrant"] = {"status": "unhealthy", "error": str(exc)}

        try:
            result = llm_health_check()
            if result.get("status_code", 503) < 500:
                services["llm"] = {"status": "healthy"}
            else:
                services["llm"] = {
                    "status": "unhealthy",
                    "error": result.get("error", f"HTTP {result['status_code']}"),
                }
        except httpx.HTTPError as exc:
            services["llm"] = {"status": "unhealthy", "error": str(exc)}
        except Exception as exc:
            services["llm"] = {"status": "unhealthy", "error": str(exc)}

        overall = (
            "unhealthy"
            if any(service["status"] == "unhealthy" for service in services.values())
            else "healthy"
        )

        return {
            "status": overall,
            "services": services,
        }
