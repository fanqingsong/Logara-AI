import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


pytestmark = pytest.mark.skipif(
    os.getenv("ENABLE_LIVE_SERVICE_TESTS") != "1",
    reason="Live service integration tests are disabled",
)


@pytest.mark.integration
@patch("services.health.llm_health_check", return_value={"status_code": 200})
def test_health_endpoint_with_live_redis_and_qdrant(_mock_llm):
    response = client.get("/health")

    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["services"]["redis"]["status"] == "healthy"
    assert payload["services"]["qdrant"]["status"] == "healthy"
    assert payload["services"]["llm"]["status"] == "healthy"
