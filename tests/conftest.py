"""tests"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """App fixture."""
    from stactools_uvx.app import app

    with TestClient(app) as client:
        yield client
