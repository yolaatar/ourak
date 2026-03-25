"""Tests for auth endpoints and JWT middleware."""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """TestClient with test env vars and in-memory DB."""
    with patch.dict(os.environ, {
        "APP_PASSWORD": "testpass123",
        "JWT_SECRET": "test-secret-key",
        "DATABASE_URL": "sqlite://",
    }):
        from backend.main import create_app
        app = create_app()
        yield TestClient(app)


# --- Auth ---


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_login_success(client):
    resp = client.post("/auth/login", json={"password": "testpass123"})
    assert resp.status_code == 200
    assert "session" in resp.cookies


def test_login_wrong_password(client):
    resp = client.post("/auth/login", json={"password": "wrong"})
    assert resp.status_code == 401


def test_logout(client):
    # Login first
    client.post("/auth/login", json={"password": "testpass123"})
    resp = client.get("/auth/logout")
    assert resp.status_code == 200
    # Cookie should be cleared (max_age=0)
    assert resp.cookies.get("session") is not None or "session" in resp.headers.get("set-cookie", "")


def test_protected_route_without_auth(client):
    resp = client.get("/topics")
    assert resp.status_code == 401


def test_protected_route_with_auth(client):
    # Login
    client.post("/auth/login", json={"password": "testpass123"})
    # Now access protected route
    resp = client.get("/topics")
    assert resp.status_code == 200
