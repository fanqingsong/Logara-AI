from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


@patch("routes.search.QdrantVectorStore")
@patch("routes.search.embed_texts")
def test_semantic_search_filters_by_service_id(mock_embed_texts, mock_store_cls):
    mock_embed_texts.return_value = [[0.1] * 1024]

    mock_store = MagicMock()
    mock_store.semantic_search.return_value = [
        SimpleNamespace(
            id="point-1",
            score=0.98,
            payload={
                "service_id": "payments-api",
                "message": "database timeout",
            },
        )
    ]
    mock_store_cls.return_value = mock_store

    response = client.get(
        "/search",
        params={
            "query": "database timeout",
            "service_id": "payments-api",
            "limit": 5,
        },
    )

    assert response.status_code == 200

    data = response.json()
    assert data["service_id"] == "payments-api"
    assert len(data["results"]) == 1
    assert data["results"][0]["payload"]["service_id"] == "payments-api"

    kwargs = mock_store.semantic_search.call_args.kwargs
    assert kwargs["service_id"] == "payments-api"
    assert kwargs["limit"] == 5


def test_semantic_search_rejects_invalid_service_id():
    response = client.get(
        "/search",
        params={
            "query": "database timeout",
            "service_id": "bad service id",
        },
    )

    assert response.status_code == 400
