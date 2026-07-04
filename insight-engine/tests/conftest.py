"""
Shared test fixtures and configuration for the insight-engine test suite.
"""
import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def mock_lazy_globals():
    """
    Pre-populate the Qdrant lazy singleton with a mock before each test so
    that get_qdrant_client() short-circuits without touching the network.
    """
    import services.search as search_module

    original_client = search_module._qdrant_client

    search_module._qdrant_client = MagicMock()

    yield

    # Restore originals so tests don't bleed state into each other
    search_module._qdrant_client = original_client
