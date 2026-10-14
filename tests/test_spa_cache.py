from fastapi.testclient import TestClient
from cortexa.web.app import app


def test_spa_entrypoints_do_not_cache_old_chat_code():
    # No lifespan: checking response headers must not start background DB jobs.
    client = TestClient(app)
    try:
        for path in ("/", "/chat"):
            response = client.get(path)
            assert response.status_code == 200
            assert "no-store" in response.headers.get("cache-control", "")
    finally:
        client.close()
