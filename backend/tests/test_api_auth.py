"""The API itself must require the shared X-API-Key header (the
frontend's password screen alone doesn't protect the backend if it's
reachable directly -- see app/api/auth.py)."""

from fastapi.testclient import TestClient

from app.main import app


def test_request_without_api_key_is_rejected():
    with TestClient(app) as client:
        r = client.get("/clients")
        assert r.status_code == 401


def test_request_with_wrong_api_key_is_rejected():
    with TestClient(app) as client:
        r = client.get("/clients", headers={"X-API-Key": "wrong"})
        assert r.status_code == 401


def test_request_with_correct_api_key_succeeds():
    with TestClient(app) as client:
        r = client.get("/clients", headers={"X-API-Key": "311576250"})
        assert r.status_code == 200


def test_health_check_does_not_require_api_key():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
